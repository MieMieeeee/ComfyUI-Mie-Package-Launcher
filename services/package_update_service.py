"""PackageUpdateService：整合包更新编排（plan §3.1.1）。

职责：加载 manifest → 校验 → 与当前 env diff → 协调 4 类 item 执行 → 记录 report。

四类 item：
- ``core`` → VersionService.checkout_ref（exact/min/channel/commit）
- ``plugin`` → PluginService（install/uninstall/enable/disable/update），返回值经
  :mod:`core.plugin_normalize` 归一化（三套契约）
- ``model`` → ModelService.verify_manual（只校验，不下载；用户手动下完点「我已下载」）
- ``dependency`` → utils.pip.install_or_update_package（单包，走 FROZEN_PKGS 黑名单）

关键设计（plan v3.3）：

- **env 不匹配前置检测**（§6.5.3）：apply 启动前调 ``_env_matches``，不匹配弹窗（GUI）/
  拒绝（CLI 无 --auto-yes）→ 直接 exit 9 短路，不进 item 循环（因此没有
  ``env_mismatch_rejected`` reason）
- **status 枚举**：ok / ok_at_alt_path / skipped / not_applicable / failed /
  manual_required / pending / in_progress
- **exit 5 触发**：仅 ``failed`` 触发（ok_at_alt_path/not_applicable/manual_required 不算失败）
- **结构化 reason**：skipped/not_applicable/ok_at_alt_path 带枚举值（agent 可 grep）
- **plugin 归一化**：经 plugin_normalize 处理三套契约 + 两个陷阱（do_update 字段不可靠 /
  force 成功路径 detail 进 log 不进 error）
- **FROZEN_PKGS**：dependency item 默认 skip_frozen=true，torch/numpy 等标 skipped + reason=frozen_pkg

本 service 是**同步阻塞方法**（plan §6.5 线程模型）：apply() 串行跑完所有 item 才返回。
GUI 必须丢工作线程跑（PackageApplyWorker），CLI 直接主线程调。
"""
from __future__ import annotations

import os
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable
from urllib.error import URLError

from core.package_manifest import (
    ManifestValidationError,
    ParsedManifest,
    load_manifest_from_text,
    parse_manifest,
    parse_version,
    verify_sha256,
)
from core.plugin_normalize import normalize_plugin_result
from services.dependency_policy import filter_frozen


# status 枚举（plan §3.1.1）
STATUS_OK = "ok"
STATUS_OK_AT_ALT_PATH = "ok_at_alt_path"
STATUS_SKIPPED = "skipped"
STATUS_NOT_APPLICABLE = "not_applicable"
STATUS_FAILED = "failed"
STATUS_MANUAL_REQUIRED = "manual_required"
STATUS_PENDING = "pending"
STATUS_IN_PROGRESS = "in_progress"

# reason 枚举（plan §3.1.1）
REASON_USER_SKIPPED = "user_skipped"
REASON_UP_TO_DATE = "up_to_date"
REASON_FROZEN_PKG = "frozen_pkg"
REASON_MIN_VERSION_REACHED = "min_version_reached"
REASON_FILE_EXISTS = "file_exists"
REASON_NOT_GIT_FOR_FORCE = "not_git_for_force"
REASON_NO_VERSION_GE_REF = "no_version_ge_ref"
REASON_VERIFIED_AT_ALT_PATH = "verified_at_alt_path"


class PackageUpdateService:
    """整合包更新编排服务。"""

    def __init__(self, app):
        self.app = app
        self._cancelled = False
        self._last_report: dict | None = None

    # ------------------------------------------------------------------
    # 子 service 访问（DI 注入点，单测可 mock）
    # ------------------------------------------------------------------

    def _version_service(self):
        return self.app.services.version

    def _plugin_service(self):
        return self.app.services.plugins

    def _model_service(self):
        # ModelService 不在 DI 接口里，按需构造（或从 app.services.model 拿）
        ms = getattr(self.app.services, "model", None)
        # MagicMock 的 getattr 永远返非 None，所以用类型检查区分「真 ModelService」vs「mock 占位」
        if ms is not None and hasattr(ms, "verify_manual") and hasattr(ms, "resolve_dest"):
            return ms
        from services.model_service import ModelService
        ms = ModelService(self.app)
        try:
            self.app.services.model = ms
        except Exception:
            pass
        return ms

    def _update_service(self):
        return self.app.services.update

    def _active_env(self) -> dict:
        """当前激活环境的 paths（comfyui_root / python_path）。"""
        if hasattr(self.app, "get_active_paths"):
            return self.app.get_active_paths()
        return self.app.config.get("paths", {})

    def _config_value(self, key: str, default=None):
        """读 package_update 段的配置（带兜底）。"""
        pu = self.app.config.get("package_update", {}) if isinstance(self.app.config, dict) else {}
        return pu.get(key, default)

    # ------------------------------------------------------------------
    # load_source（本地文件 / HTTPS URL / 粘贴文本）
    # ------------------------------------------------------------------

    def load_source(self, source: str) -> tuple[dict, str]:
        """从本地文件路径或 HTTPS URL 加载 manifest dict。

        Args:
            source: 本地文件路径 或 https:// URL（http:// 拒绝，plan §6.4）

        Returns:
            ``(manifest_dict, resolved_path)`` —— resolved_path 是实际读到的文件路径
            （URL 拉取会落 cache）

        Raises:
            ValueError: 文件不存在 / URL 不可达 / JSON 解析失败 / manifest URL 是 HTTP
        """
        if not source or not isinstance(source, str):
            raise ValueError("source 为空")
        source = source.strip()
        if source.startswith(("http://", "https://")):
            return self._load_from_url(source)
        # 本地文件
        p = Path(source)
        if not p.exists():
            raise ValueError(f"文件不存在: {source}")
        try:
            text = p.read_text(encoding="utf-8-sig")
        except Exception as e:
            raise ValueError(f"读取文件失败: {e}") from e
        manifest = load_manifest_from_text(text)
        return manifest, str(p.resolve())

    def _load_from_url(self, url: str) -> tuple[dict, str]:
        """从 HTTPS URL 拉 manifest（http:// 拒绝，落 cache）。"""
        if url.startswith("http://"):
            raise ValueError("manifest URL 必须 HTTPS（http:// 已拒绝，plan §6.4）")
        cache_dir = self._config_value("cache_dir", "launcher/manifests/cache/")
        # cache 文件名：url hash + fetched 时间
        import hashlib as _h
        url_hash = _h.sha256(url.encode("utf-8")).hexdigest()[:16]
        fetched = time.strftime("%Y%m%dT%H%M%S")
        cache_path = Path(cache_dir) / f"{url_hash}_{fetched}.json"
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        # 拉取（默认严格 TLS，plan §6.4）
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ComfyUI-Launcher"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
        except URLError as e:
            raise ValueError(f"URL 拉取失败: {e}") from e
        except Exception as e:
            raise ValueError(f"URL 拉取失败: {e}") from e
        text = data.decode("utf-8-sig", errors="replace")
        try:
            cache_path.write_text(text, encoding="utf-8")
        except Exception:
            pass  # cache 写失败不影响功能
        manifest = load_manifest_from_text(text)
        return manifest, str(cache_path)

    # ------------------------------------------------------------------
    # validate
    # ------------------------------------------------------------------

    def validate(self, manifest: dict) -> tuple[bool, str | None]:
        """校验 schema + sha256。

        Returns:
            (ok, error) —— ok=False 时 error 是人读描述
        """
        try:
            parse_manifest(manifest)
        except ManifestValidationError as e:
            return False, str(e)
        # sha256 校验（可选字段，没填视为通过）
        sha_ok, actual = verify_sha256(manifest)
        if not sha_ok:
            declared = manifest.get("sha256", "")
            return False, (f"sha256 校验失败: 声明 {declared} 与实算 {actual} 不符")
        return True, None

    # ------------------------------------------------------------------
    # diff_against_current（plan §3.1.1 satisfied 判定表）
    # ------------------------------------------------------------------

    def diff_against_current(self, manifest: dict) -> dict:
        """与当前 env 对照，返回哪些 item 已满足 / 哪些要跑。

        判定依据 plan §3.1.1 satisfied 表。plugin update 永远 satisfied=false（diff 阶段不联网），
        但 diff_basis 字段标记这是「by design」。
        """
        try:
            parsed = parse_manifest(manifest)
        except ManifestValidationError as e:
            return {"error": str(e)}
        already: list[str] = []
        to_apply: list[str] = []
        manual_required: list[str] = []
        diff_basis: dict[str, str] = {}
        for item in parsed.items:
            sat = self._is_satisfied(item)
            if sat is True:
                already.append(item.id)
            elif sat is False:
                to_apply.append(item.id)
                if item.kind == "plugin" and item.raw.get("action") == "update":
                    diff_basis[item.id] = "plugin_update_skips_satisfied_check_by_design"
            else:  # None = manual_required（model 项无法自动判）
                manual_required.append(item.id)
        return {
            "items_already_satisfied": already,
            "items_to_apply": to_apply,
            "items_manual_required": manual_required,
            "diff_basis": diff_basis,
        }

    def _is_satisfied(self, item) -> bool | None:
        """判 item 是否已满足。返回 True/False，None 表示无法自动判（manual_required）。"""
        kind = item.kind
        raw = item.raw
        if kind == "core":
            return self._core_satisfied(raw)
        if kind == "plugin":
            return self._plugin_satisfied(raw)
        if kind == "model":
            return self._model_satisfied(raw)
        if kind == "dependency":
            return self._dependency_satisfied(raw)
        return False

    def _core_satisfied(self, raw: dict) -> bool:
        """core satisfied 判定（plan §3.1.1 表）。"""
        sel = raw.get("selection", {})
        mode = sel.get("mode")
        ref = sel.get("ref", "")
        try:
            current = self._version_service().get_current_kernel_version()
        except Exception:
            return False
        if not current:
            return False
        if mode == "exact":
            return (current.get("tag") or "") == ref
        if mode == "commit":
            return (current.get("commit") or "") == ref
        if mode == "min":
            cur_tag = current.get("tag") or ""
            if not cur_tag:
                return False
            return parse_version(cur_tag) >= parse_version(ref)
        if mode == "channel":
            if ref == "stable":
                # 当前是最新 stable → satisfied（粗判：有 tag 即视为在 stable 轨道）
                return bool(current.get("tag"))
            # master：无法可靠判（需联网比对 origin/master），保守返 False
            return False
        return False

    def _plugin_satisfied(self, raw: dict) -> bool:
        """plugin satisfied 判定。update 永远返 False（diff 阶段不联网）。"""
        action = raw.get("action")
        if action == "update":
            return False  # plan §3.1.1：永远判 satisfied=false
        spec = raw.get("spec", "")
        # 用 plugin_service.list_installed 判 dir 是否存在
        try:
            installed = self._plugin_service().list_installed()
            names = {p.get("name") or p.get("dir") for p in installed}
            dir_name = spec.split("@")[0].split("/")[-1].replace(".git", "")
            exists = dir_name in names
        except Exception:
            exists = False
        if action == "install":
            return exists
        if action == "uninstall":
            return not exists
        # enable/disable 需要看 disabled 标记（插件目录是否被 rename 成 .disabled）
        try:
            target = spec.split("@")[0]
            return exists  # 粗判：存在即 satisfied（enable/disable 细判留给 apply）
        except Exception:
            return False

    def _model_satisfied(self, raw: dict) -> bool | None:
        """model satisfied 判定。文件存在 + checksum 匹配 → True；否则 False。

        返回 bool（不返 None，因为文件存在性可自动判）。manual_required 是「用户没勾」，
        在 apply 阶段据 manual_decisions 判，不是 diff 阶段。
        """
        try:
            r = self._model_service().verify_manual(raw)
            return r["status"] == "ok"
        except Exception:
            return False

    def _dependency_satisfied(self, raw: dict) -> bool:
        """dependency satisfied 判定：pip show 版本满足 spec。"""
        pkgs = raw.get("packages", [])
        if not pkgs:
            return False
        try:
            py = self._active_env().get("python_path", "python_embeded/python.exe")
            comfy_root = self._active_env().get("comfyui_root", ".")
            from utils import pip as PIPUTILS
            from utils import paths as PATHS
            py_exec = PATHS.resolve_python_exec(comfy_root, py)
            for pkg in pkgs:
                spec = pkg.get("spec", "")
                name = spec.split("=")[0].split(">")[0].split("<")[0].split("!")[0].split("[")[0].strip()
                if not name:
                    continue
                ver = PIPUTILS.get_package_version(name, py_exec)
                if not ver:
                    return False
                # 粗判：spec 带 == 时精确比；其它保守返 False（让 apply 跑）
                if "==" in spec:
                    want = spec.split("==")[1].strip()
                    if ver.strip() != want:
                        return False
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # apply（plan §6.5.3 env 前置检测 + 4 类 item 循环）
    # ------------------------------------------------------------------

    def apply(
        self,
        manifest: dict,
        item_ids: list[str] | None = None,
        manual_decisions: dict | None = None,
        on_item: Callable[[str, str, dict], None] | None = None,
        auto_yes: bool = False,
        confirm_env_mismatch: Callable[[dict], bool] | None = None,
    ) -> dict:
        """应用 manifest。

        流程（plan §6.5.3）：
        1. env 不匹配前置检测 → 不匹配且未确认 → 返 exit_hint=9 的空 report
        2. 逐 item 串行执行（core/plugin/model/dependency 各走各的）
        3. 失败不中断后续（除非 cancelled），汇总成 report

        Args:
            manifest: manifest dict
            item_ids: 只跑指定 item_id（None = 全部）
            manual_decisions: ``{item_id: "yes"|"skip"}``（model 项用户勾选）
            on_item: 每项状态变更回调 ``(item_id, status, payload)``
            auto_yes: 跳过 env-mismatch 弹窗（CLI --auto-yes / 脚本）
            confirm_env_mismatch: GUI 弹窗回调（返 True=继续）；CLI 传 None

        Returns:
            report dict（plan §3.1.1 schema + exit_hint 字段供调用方判退出码）
        """
        self._cancelled = False
        manual_decisions = manual_decisions or {}
        run_id = time.strftime("%Y%m%dT%H-%M-%S") + "-" + uuid.uuid4().hex[:6]
        started = time.strftime("%Y-%m-%dT%H:%M:%S")
        env_id = self._current_env_id()

        # 1. env 不匹配前置检测（§6.5.3）
        target = manifest.get("package_target", {})
        if target and not self._env_matches(target):
            if not (auto_yes or (confirm_env_mismatch and confirm_env_mismatch(manifest))):
                report = self._build_env_reject_report(manifest, run_id, started, env_id)
                self._last_report = report
                return report

        # 2. 解析 + 按 item_ids 过滤
        try:
            parsed = parse_manifest(manifest)
        except ManifestValidationError as e:
            report = {
                "manifest_id": manifest.get("id", "?"), "run_id": run_id,
                "started_at": started, "env_id": env_id,
                "items": [], "summary": self._empty_summary(),
                "exit_hint": 10, "error": str(e),
            }
            self._last_report = report
            return report

        items_to_run = parsed.items
        if item_ids is not None:
            id_set = set(item_ids)
            items_to_run = [it for it in parsed.items if it.id in id_set]

        report_items: list[dict] = []
        # 先把被过滤掉的 item 标 pending
        if item_ids is not None:
            for it in parsed.items:
                if it.id not in id_set:
                    report_items.append(self._mk_item_report(it, STATUS_PENDING))

        # 3. 逐项执行
        for item in items_to_run:
            if self._cancelled:
                report_items.append(self._mk_item_report(item, STATUS_PENDING, error="cancelled"))
                continue
            decision = manual_decisions.get(item.id)
            if decision == "skip":
                r = self._mk_item_report(item, STATUS_SKIPPED, reason=REASON_USER_SKIPPED)
                report_items.append(r)
                self._notify(on_item, item.id, r)
                continue
            r = self._execute_item(item, decision, on_item)
            report_items.append(r)

        finished = time.strftime("%Y-%m-%dT%H:%M:%S")
        summary = self._summarize(report_items)
        exit_hint = self._exit_hint(summary)
        report = {
            "manifest_id": parsed.id, "run_id": run_id,
            "started_at": started, "finished_at": finished, "env_id": env_id,
            "items": report_items, "summary": summary, "exit_hint": exit_hint,
        }
        self._last_report = report
        return report

    def _execute_item(self, item, decision: str | None, on_item) -> dict:
        """执行单个 item，按 kind 分派。"""
        self._notify(on_item, item.id, self._mk_item_report(item, STATUS_IN_PROGRESS))
        try:
            if item.kind == "core":
                return self._exec_core(item, on_item)
            if item.kind == "plugin":
                return self._exec_plugin(item, on_item)
            if item.kind == "model":
                return self._exec_model(item, decision, on_item)
            if item.kind == "dependency":
                return self._exec_dependency(item, on_item)
        except Exception as e:
            r = self._mk_item_report(item, STATUS_FAILED, error=str(e))
            self._notify(on_item, item.id, r)
            return r
        r = self._mk_item_report(item, STATUS_FAILED, error=f"unknown kind: {item.kind}")
        self._notify(on_item, item.id, r)
        return r

    def _exec_core(self, item, on_item) -> dict:
        sel = item.raw.get("selection", {})
        mode = sel.get("mode")
        ref = sel.get("ref", "")
        res = self._version_service().checkout_ref(mode, ref)
        # skipped 情况（min 无候选）
        if res.get("skipped"):
            reason = res.get("reason", REASON_NO_VERSION_GE_REF)
            r = self._mk_item_report(item, STATUS_SKIPPED, reason=reason,
                                     error=res.get("error"), after=res)
            self._notify(on_item, item.id, r)
            return r
        if res.get("error"):
            r = self._mk_item_report(item, STATUS_FAILED, error=res.get("error"), after=res)
            self._notify(on_item, item.id, r)
            return r
        r = self._mk_item_report(item, STATUS_OK, after=res)
        self._notify(on_item, item.id, r)
        return r

    def _exec_plugin(self, item, on_item) -> dict:
        raw = item.raw
        action = raw.get("action")
        spec = raw.get("spec")
        force = bool(raw.get("force"))
        svc = self._plugin_service()
        # 调对应方法
        if action == "install":
            res = svc.install(spec)
        elif action == "uninstall":
            res = svc.uninstall(spec)
        elif action == "enable":
            res = svc.enable(spec)
        elif action == "disable":
            res = svc.disable(spec)
        elif action == "update":
            if force and spec:
                res = svc.force_update_selected([spec.split("@")[0]])
            elif spec:
                res = svc.update_selected([spec])
            else:
                res = svc.update_all()
        else:
            r = self._mk_item_report(item, STATUS_FAILED, error=f"unknown action: {action}")
            self._notify(on_item, item.id, r)
            return r
        # 归一化（三套契约）
        norm = normalize_plugin_result(res, action=action, force=force,
                                       spec=spec.split("@")[0] if spec else None)
        if norm.get("not_applicable"):
            r = self._mk_item_report(item, STATUS_NOT_APPLICABLE, reason=norm.get("reason"),
                                     error=norm.get("error"), log=norm.get("log"))
        elif norm.get("ok"):
            r = self._mk_item_report(item, STATUS_OK, log=norm.get("log"), error=norm.get("error"))
        else:
            r = self._mk_item_report(item, STATUS_FAILED, error=norm.get("error"), log=norm.get("log"))
        self._notify(on_item, item.id, r)
        return r

    def _exec_model(self, item, decision: str | None, on_item) -> dict:
        raw = item.raw
        if decision != "yes":
            # model 项用户没勾「我已下载」→ manual_required
            r = self._mk_item_report(item, STATUS_MANUAL_REQUIRED)
            self._notify(on_item, item.id, r)
            return r
        # skip_if_exists 命中 → skipped
        if raw.get("skip_if_exists"):
            try:
                check = self._model_service().verify_manual(raw)
                if check["status"] == "ok":
                    r = self._mk_item_report(item, STATUS_SKIPPED, reason=REASON_FILE_EXISTS,
                                             after={"path": check["path"]})
                    self._notify(on_item, item.id, r)
                    return r
            except Exception:
                pass
        # verify（用户称已下载）
        try:
            alt = raw.get("_alt_path")  # GUI 浏览按钮临时注入
            v = self._model_service().verify_manual(raw, alt_path=alt)
        except Exception as e:
            r = self._mk_item_report(item, STATUS_FAILED, error=str(e))
            self._notify(on_item, item.id, r)
            return r
        if v["status"] == "ok":
            if v.get("at_alt_path"):
                r = self._mk_item_report(item, STATUS_OK_AT_ALT_PATH,
                                         reason=REASON_VERIFIED_AT_ALT_PATH,
                                         after={"path": v["path"]})
            else:
                r = self._mk_item_report(item, STATUS_OK, after={"path": v["path"]})
        elif v["status"] == "missing":
            r = self._mk_item_report(item, STATUS_MANUAL_REQUIRED,
                                     error="文件未就位")
        else:  # checksum_mismatch
            r = self._mk_item_report(item, STATUS_FAILED,
                                     error=f"sha256 不符: 期望 {v.get('expected')} 实算 {v.get('actual')}")
        self._notify(on_item, item.id, r)
        return r

    def _exec_dependency(self, item, on_item) -> dict:
        raw = item.raw
        pkgs = raw.get("packages", [])
        skip_frozen = raw.get("skip_frozen", True)
        specs = [p.get("spec", "") for p in pkgs if p.get("spec")]
        # FROZEN_PKGS 过滤
        allowed, frozen = filter_frozen(specs) if skip_frozen else (specs, [])
        if frozen and not allowed:
            # 全部被冻结 → 整项 skipped
            r = self._mk_item_report(item, STATUS_SKIPPED, reason=REASON_FROZEN_PKG,
                                     log=f"冻结包: {frozen}")
            self._notify(on_item, item.id, r)
            return r
        # 逐包装
        from utils import pip as PIPUTILS
        from utils import paths as PATHS
        paths = self._active_env()
        py_exec = PATHS.resolve_python_exec(paths.get("comfyui_root", "."),
                                            paths.get("python_path", "python_embeded/python.exe"))
        idx_override = raw.get("index_url_override")
        idx = self._resolve_dep_index_url(idx_override)
        installed = []
        errors = []
        for p in pkgs:
            spec = p.get("spec", "")
            name = spec.split("=")[0].split(">")[0].split("<")[0].split("!")[0].split("[")[0].strip()
            if skip_frozen and name.lower() in {"torch", "torchvision", "torchaudio", "triton", "xformers", "numpy"}:
                continue  # 冻结包跳过
            try:
                res = PIPUTILS.install_or_update_package(
                    spec, py_exec, index_url=idx, upgrade=True,
                    logger=getattr(self.app, "logger", None),
                    force_reinstall=bool(p.get("force_reinstall")),
                )
                if res.get("success"):
                    installed.append({"spec": spec, "version": res.get("version")})
                else:
                    errors.append(f"{spec}: {res.get('error', 'unknown')}")
            except Exception as e:
                errors.append(f"{spec}: {e}")
        if errors:
            r = self._mk_item_report(item, STATUS_FAILED,
                                     error="; ".join(errors),
                                     after={"installed": installed, "frozen": frozen})
        else:
            r = self._mk_item_report(item, STATUS_OK,
                                     after={"installed": installed, "frozen": frozen})
        self._notify(on_item, item.id, r)
        return r

    # ------------------------------------------------------------------
    # env 不匹配检测（plan §6.5.3）
    # ------------------------------------------------------------------

    def _env_matches(self, target: dict) -> bool:
        """粗略判 manifest 的 package_target.channel 与当前 env 是否匹配。

        channel 缺失 → 视为匹配（向后兼容老 manifest）。
        用 env name / comfyui_root 路径里的版本标识粗判（如含 'V9' / 'v9'）。
        """
        channel = str(target.get("channel", "")).strip().lower()
        if not channel:
            return True
        try:
            env = self._active_env()
            env_name = str(self._current_env_name()).lower()
            root = str(env.get("comfyui_root", "")).lower()
            needle = channel.replace("v", "")  # "v9" → "9"
            return needle in env_name or channel in env_name or channel in root or needle in root
        except Exception:
            return True  # 判不了 → 放行（不阻断）

    def _current_env_id(self) -> str:
        try:
            return str(self.app.config.get("active_env_id", ""))
        except Exception:
            return ""

    def _current_env_name(self) -> str:
        try:
            envs = self.app.config.get("environments", [])
            aid = self.app.config.get("active_env_id", "")
            for e in envs:
                if e.get("id") == aid:
                    return e.get("name", "")
        except Exception:
            pass
        return ""

    def _build_env_reject_report(self, manifest, run_id, started, env_id) -> dict:
        finished = time.strftime("%Y-%m-%dT%H:%M:%S")
        return {
            "manifest_id": manifest.get("id", "?"), "run_id": run_id,
            "started_at": started, "finished_at": finished, "env_id": env_id,
            "items": [], "summary": self._empty_summary(),
            "exit_hint": 9, "error": "env 不匹配且用户拒绝继续",
        }

    # ------------------------------------------------------------------
    # report 辅助
    # ------------------------------------------------------------------

    def _mk_item_report(self, item, status, reason=None, error=None, log=None,
                        before=None, after=None) -> dict:
        return {
            "id": item.id, "kind": item.kind, "title": item.title,
            "status": status, "reason": reason, "error": error, "log": log,
            "before": before or {}, "after": after or {},
        }

    def _notify(self, on_item, item_id, report_item):
        if on_item:
            try:
                on_item(item_id, report_item["status"], report_item)
            except Exception:
                pass

    def _empty_summary(self) -> dict:
        return {"total": 0, "ok": 0, "ok_at_alt_path": 0, "skipped": 0,
                "not_applicable": 0, "failed": 0, "manual_required": 0}

    def _summarize(self, items: list[dict]) -> dict:
        s = {"total": len(items), "ok": 0, "ok_at_alt_path": 0, "skipped": 0,
             "not_applicable": 0, "failed": 0, "manual_required": 0}
        for it in items:
            st = it.get("status")
            if st in s and st != "total":
                s[st] += 1
        return s

    def _exit_hint(self, summary: dict) -> int:
        """据 summary 算 exit hint（plan §4.3：仅 failed 触发 5）。"""
        if summary.get("failed", 0) > 0:
            return 5
        return 0

    def _resolve_dep_index_url(self, override) -> str | None:
        """dependency item 的 index_url 解析。"""
        if override == "none":
            return None
        if isinstance(override, str) and override.strip():
            return override.strip()
        # 走 config 的 pypi_proxy_mode
        try:
            return self._update_service()._resolve_index_url()
        except Exception:
            return None

    # ------------------------------------------------------------------
    # cancel / build_report
    # ------------------------------------------------------------------

    def cancel(self):
        """请求取消（安全停；当前 item 跑完才生效）。"""
        self._cancelled = True

    def build_report(self) -> dict | None:
        """返回最近一次 apply 的 report（供 GUI 历史记录 / 持久化用）。"""
        return self._last_report
