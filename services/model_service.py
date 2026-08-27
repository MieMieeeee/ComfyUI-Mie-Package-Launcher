"""ModelService：manifest model item 的路径解析 + 文件校验（**只验证，不下载**）。

命名提示：与已有的 ``services/model_path_service.py``（管外置库 CRUD / yaml 映射）区分。
本 service 只管 manifest 里 model item 的三件事：

1. ``resolve_dest(library_id, category, filename)`` —— 算 model 该落到哪个绝对路径
2. ``verify_manual(item)`` —— 校验用户手动下载的文件是否就位
3. ``open_link(url)`` —— ``webbrowser.open`` 打开下载链接

**不引入 huggingface_hub / modelscope / requests** —— model 永远是用户手动下载，
启动器只给链接列表 + 校验文件存在（plan §0 / §3.1.2）。

关键设计（plan §2.2.3 / §3.1.2）：

- ``library_id="default"``（magic string）→ 映射到 ``external_libraries`` 里
  ``is_default=True`` 的那条的 ``base_path``；8 位 hex id → 精确匹配；``null`` → 等同 default
- ``category`` 落到类目子目录。标准类目以 ``ModelPathService.standard_map`` 的 key 为准
  （12 个：checkpoints/text_encoders/clip_vision/configs/controlnet/diffusion_models/
  embeddings/loras/upscale_models/vae/audio_encoders/model_patches）。非标准 → 警告但不阻断
  （新模型类型早期是 plugin 自管，硬拒会挡住合法用例）
- ``verify_manual`` **不返 ``size_mismatch``** —— ``size_hint`` 仅 UI 展示用，不参与校验
  （避免 fp16/fp32/EXL2 变体字节数不同误报）。只返 ``ok`` / ``missing`` / ``checksum_mismatch``
- ``open_link`` 接受 http/https（网盘短链经常是 HTTP，plan §6.4）
"""
from __future__ import annotations

import hashlib
import webbrowser
from pathlib import Path
from typing import Any


# verify_manual 的返回状态（plan §3.1.2，无 size_mismatch）
VERIFY_OK = "ok"
VERIFY_MISSING = "missing"
VERIFY_CHECKSUM_MISMATCH = "checksum_mismatch"


def _compute_sha256(path: Path) -> str:
    """分块计算文件 sha256（8KB chunk，复用 launcher_update_service 的惯用法）。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


class ModelService:
    """manifest model item 的路径解析 + 文件校验。不下载，只 verify。"""

    def __init__(self, app):
        self.app = app

    # ------------------------------------------------------------------
    # resolve_dest
    # ------------------------------------------------------------------

    def _get_model_path_service(self):
        """拿 ModelPathService 实例（复用其 standard_map / get_libraries / get_external_path）。

        app.services.model_path 是 DI 注入点（见 services/interfaces.py IModelPathService）；
        GUI app 上有，headless / 单测里可能没有 —— 调用方负责 mock。
        """
        return self.app.services.model_path

    def _standard_category_keys(self) -> set[str]:
        """标准类目集 = ModelPathService.standard_map 的 key。"""
        try:
            mps = self._get_model_path_service()
            return {k for k, _ in mps.standard_map}
        except Exception:
            # 兜底：ModelPathService 不可用时用 plan §2.2.3 列的 12 个
            return {
                "checkpoints", "text_encoders", "clip_vision", "configs", "controlnet",
                "diffusion_models", "embeddings", "loras", "upscale_models", "vae",
                "audio_encoders", "model_patches",
            }

    def resolve_dest(self, library_id: str | None, category: str, filename: str) -> Path:
        """算 model 该落到哪个绝对路径。

        Args:
            library_id: ``"default"`` / ``None`` → default 库；8 位 hex id → 精确匹配
            category: 类目名（标准或非标准都行，非标准会调 ``on_nonstandard_category`` 回调）
            filename: 文件名（必填，由 manifest 校验保证非空）

        Returns:
            目标绝对路径（``<base_path>/<category>/<filename>``）。
            **不创建目录**（目录创建在 verify 阶段或 apply 阶段按需 mkdir）。

        Raises:
            ValueError: library_id 找不到对应的外置库
        """
        base_path = self._resolve_library_base(library_id)
        return Path(base_path) / category / filename

    def _resolve_library_base(self, library_id: str | None) -> str:
        """把 library_id 解析成外置库的 base_path。"""
        if library_id in (None, "", "default"):
            # magic string / null → default 库
            try:
                mps = self._get_model_path_service()
                base = mps.get_external_path()
                if base:
                    return base
            except Exception:
                pass
            raise ValueError("找不到 default 外置模型库（external_libraries 里无 is_default=True 的条目）")
        # 8 位 hex id → 精确匹配
        try:
            mps = self._get_model_path_service()
            for lib in mps.get_libraries():
                if lib.get("id") == library_id:
                    base = lib.get("base_path", "")
                    if base:
                        return base
            raise ValueError(f"找不到 library_id={library_id!r} 的外置模型库")
        except ValueError:
            raise
        except Exception as e:
            raise ValueError(f"解析 library_id={library_id!r} 失败: {e}") from e

    def is_standard_category(self, category: str) -> bool:
        """category 是否在标准类目集内（非标准 → UI/CLI 给警告但不阻断）。"""
        return category in self._standard_category_keys()

    # ------------------------------------------------------------------
    # verify_manual
    # ------------------------------------------------------------------

    def verify_manual(
        self,
        item: dict,
        *,
        alt_path: str | Path | None = None,
    ) -> dict[str, Any]:
        """校验用户手动下载的文件是否就位。

        Args:
            item: manifest 的 model item dict（含 ``dest`` / 可选 ``checksum`` / 可选 ``skip_if_exists``）
            alt_path: 用户通过「浏览...」按钮指向的非 manifest 路径（plan §5.6）。
                给了就用它做 verify；不给则用 ``resolve_dest`` 算 manifest 指定路径。

        Returns:
            ``{"status": "ok|missing|checksum_mismatch", "path": str, "at_alt_path": bool}``

            - ``status=ok``：文件存在 + sha256 匹配（若 manifest 带了 checksum）
            - ``status=missing``：文件不存在
            - ``status=checksum_mismatch``：文件存在但 sha256 不符
            - ``at_alt_path``：True 表示文件在 alt_path 而非 manifest 指定路径
              （PackageUpdateService 据此把 item 标 ``ok_at_alt_path``，plan §3.1.1）

        **不返 ``size_mismatch``** —— ``size_hint`` 仅 UI 展示，不参与校验（plan §2.2.3）。
        """
        dest = item.get("dest", {})
        filename = dest.get("filename", "")
        manifest_path = self.resolve_dest(dest.get("library_id"), dest.get("category", ""), filename)

        if alt_path is not None:
            target = Path(alt_path)
            at_alt = True
        else:
            target = manifest_path
            at_alt = False

        if not target.exists():
            return {"status": VERIFY_MISSING, "path": str(target), "at_alt_path": at_alt}

        # sha256 校验（manifest 带了才严格校验，否则只看文件存在）
        checksum = item.get("checksum")
        if isinstance(checksum, dict) and checksum.get("value"):
            expected = str(checksum["value"]).strip().lower()
            actual = _compute_sha256(target)
            if actual != expected:
                return {"status": VERIFY_CHECKSUM_MISMATCH, "path": str(target),
                        "at_alt_path": at_alt, "expected": expected, "actual": actual}

        return {"status": VERIFY_OK, "path": str(target), "at_alt_path": at_alt}

    # ------------------------------------------------------------------
    # open_link
    # ------------------------------------------------------------------

    # open_link 白名单：http/https。其它协议（file:/javascript:/ms-windows-store: 等）一律拦截，
    # 否则 webbrowser.open 可能唤起系统 shell 或执行 script（issue 7）。
    _SAFE_SCHEMES = ("http://", "https://")

    def open_link(self, url: str) -> bool:
        """``webbrowser.open(url)``，接受 http/https。

        HTTPS-only 规则仅适用于 **manifest 源 URL**（load_source 那一层，plan §6.4）；
        model ``links[].url`` 因网盘短链经常是 HTTP，必须放行（plan §3.1.2 / §6.4）。
        UI 调本方法前若 url 是 http，按 plan §6.4 给「非 HTTPS」徽章提示，但本方法正常打开。

        安全护栏（issue 7）：白名单 http/https；file:/javascript:/ms-windows-store: 等
        一律拦截，避免 webbrowser.open 唤起系统 shell / 执行 script。

        Returns:
            True 表示 webbrowser 返回成功（不保证浏览器真打开了）
        """
        if not url:
            return False
        if not url.startswith(self._SAFE_SCHEMES):
            try:
                import logging
                logging.getLogger(__name__).error(
                    "open_link blocked unsafe url: %r", url[:80]
                )
            except Exception:
                pass
            return False
        try:
            return bool(webbrowser.open(url))
        except Exception:
            return False
