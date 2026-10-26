import os
import threading
import time
import yaml
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List

from utils import path_probe
from utils.thread_util import wait_thread

class ModelPathService:
    # SD WebUI-style folder name aliases (from ComfyUI official a1111 example)
    # Maps ComfyUI key -> list of alternative folder names to probe
    SD_STYLE_ALIASES = {
        "checkpoints": ["Stable-diffusion"],
        "configs": ["Stable-diffusion"],
        "vae": ["VAE"],
        "loras": ["Lora", "LyCORIS"],
        "upscale_models": ["ESRGAN", "RealESRGAN", "SwinIR"],
        "controlnet": ["ControlNet"],
        "embeddings": ["embeddings"],
        "hypernetworks": ["hypernetworks"],
    }

    def __init__(self, app):
        self.app = app
        # 上一次 apply_libraries() 的结果：写成功了没有、哪些库因为对端不可达
        # 而沿用了旧配置。GUI 用它提示用户「这次没有真正刷新该库」。
        self.last_apply_report = {"ok": None, "skipped": []}
        # Standard folder mapping relative to the external base path (ordered)
        self.standard_map = [
            ("checkpoints", "models/checkpoints/"),
            ("text_encoders", "models/text_encoders/\nmodels/clip/"),
            ("clip_vision", "models/clip_vision/"),
            ("configs", "models/configs/"),
            ("controlnet", "models/controlnet/"),
            ("diffusion_models", "models/diffusion_models/\nmodels/unet/"),
            ("embeddings", "models/embeddings/"),
            ("loras", "models/loras/"),
            ("upscale_models", "models/upscale_models/"),
            ("vae", "models/vae/"),
            ("audio_encoders", "models/audio_encoders/"),
            ("model_patches", "models/model_patches/"),
        ]


    def _get_yaml_path(self) -> Path:
        # 多环境支持：读激活环境的 comfyui_root
        paths = self.app.get_active_paths() if hasattr(self.app, "get_active_paths") \
            else self.app.config.get("paths", {})
        base = Path(paths.get("comfyui_root") or ".").resolve()
        comfy_root = (base / "ComfyUI").resolve()
        return comfy_root / "extra_model_paths.yaml"

    # --- 有界磁盘访问 -------------------------------------------------
    #
    # 外置库可能指向局域网共享（\\NAS\models 或映射盘）。对端没开机时，
    # Windows 上每一次 exists()/iterdir() 都要等 SMB 重试超时（几十秒），
    # 而这些调用原先直接发生在 GUI 线程里 —— 表现为「切到模型库管理页
    # 整窗无响应」。下面三个助手把所有磁盘访问都变成有界的：对端不可达时
    # 立刻返回空/False，绝不把阻塞传导到 UI 线程。

    def _path_is_dir(self, path, force: bool = False) -> bool:
        """目录是否存在（有界）。"""
        try:
            return path_probe.isdir_bounded(str(path), force=force)
        except Exception:
            return False

    def _child_dirs(self, path, force: bool = False) -> List[str]:
        """子目录名列表（有界）。"""
        try:
            return path_probe.child_dirs_bounded(str(path), force=force)
        except Exception:
            return []

    def is_remote_path(self, base_path) -> bool:
        """该库是否落在网络路径上。"""
        try:
            return path_probe.is_remote_path(str(base_path or ""))
        except Exception:
            return False

    def is_reachable(self, base_path, force: bool = False) -> bool:
        """该库当前是否可访问。

        本地路径恒为 True；网络路径看对端主机是否在线（短 TCP 探测 + 缓存），
        以及这个共享刚才是否被判定为「连得上但用不了」（SMB 超时）。

        ``force=True`` 会绕过所有缓存重新探一次 —— 用户点了「刷新」或者刚把
        NAS 开机时用得上，否则得等缓存过期（30s）才知道它回来了。
        """
        if not base_path:
            return False
        try:
            if not self.is_remote_path(base_path):
                return True
            if force:
                path_probe.clear_unusable(str(base_path))
            if path_probe.is_unusable(str(base_path)):
                return False
            return path_probe.path_reachable(str(base_path), force=force)
        except Exception:
            return True

    def is_offline(self, base_path, force: bool = False) -> bool:
        """该库是否「网络路径且当前不可达」（对端没开机 / 共享掉了）。"""
        if not base_path:
            return False
        try:
            if not self.is_remote_path(base_path):
                return False
            return not self.is_reachable(base_path, force=force)
        except Exception:
            return False

    def _safe_resolve(self, path) -> str:
        """绝对化路径，网络路径不走 ``Path.resolve()``。

        Windows 上 ``Path.resolve()`` 会调 ``_getfinalpathname``，对 UNC 路径
        是真的去问网络 —— 对端关机时这一步就会卡住。``os.path.abspath`` 是纯
        字符串运算，不碰文件系统。
        """
        try:
            if self.is_remote_path(str(path)):
                return os.path.abspath(str(path))
            return str(Path(path).resolve())
        except Exception:
            return str(path)

    # 远端扫描的整体时限（秒）。超时按「扫不出来」处理。
    REMOTE_SCAN_TIMEOUT = 8.0
    # 一次 apply_libraries() 里所有远端库的总扫描预算（秒）。
    REMOTE_APPLY_BUDGET = 12.0

    def _bounded_scan(self, fn, timeout: float = None):
        """在守护线程里跑一次扫描，最多等 REMOTE_SCAN_TIMEOUT 秒。

        返回 fn 的结果；超时或抛异常时返回 None（调用方按「拿不到」处理）。
        """
        if timeout is None:
            timeout = self.REMOTE_SCAN_TIMEOUT
        box = {}

        def worker():
            try:
                box["value"] = fn()
            except Exception:
                box["value"] = None

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        # 不用 t.join()：join() 内部会调 threading.current_thread()，在 Qt
        # 线程池这类「非 threading 创建」的线程里调用会永久注册一个
        # _DummyThread，之后别人 enumerate()+join() 会炸（见 utils/thread_util.py）。
        wait_thread(t, timeout)
        return box.get("value", None)

    def _skeleton_block(self, lib: dict) -> dict:
        """扫描失败时能安全写下的最小块（只有 base_path）。"""
        block = {"base_path": lib.get("base_path", "")}
        if lib.get("is_default"):
            block["is_default"] = True
        return block

    def load_current_config(self) -> Dict[str, Any]:
        """
        Load connection configuration from extra_model_paths.yaml.
        We are specifically looking for our managed config (let's call it 'mie_launcher_external').
        Or if not found, try to parse the first entry.
        """
        yp = self._get_yaml_path()
        if not yp.exists():
            return {}

        try:
            with open(yp, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
                return data
        except Exception:
            return {}

    def get_external_path(self) -> str:
        # Prefer the multi-library data model: the default library's base_path.
        for lib in self.get_libraries():
            if lib.get("is_default"):
                return lib.get("base_path", "")
        # Legacy fallback: read whatever base_path the yaml currently exposes.
        data = self.load_current_config()
        # Prefer lowercase key first per ComfyUI docs
        cfg = data.get("comfyui", {})
        if not cfg:
            cfg = data.get("ComfyUI", {})
        if not cfg:
            cfg = data.get("mie_external", {})
            if not cfg:
                for k, v in data.items():
                    if isinstance(v, dict) and "base_path" in v:
                        return v["base_path"]
        return cfg.get("base_path", "")

    def _get_standard_mappings(self, base_path: str) -> List[tuple]:
        """
        Get standard mappings, prioritizing detected paths.
        1. Check if base_path/models/key exists -> models/key/
        2. Check if base_path/key exists -> key/
        3. Check SD WebUI-style aliases (e.g. Stable-diffusion, Lora, ESRGAN)
        4. Fallback: if base_path name is 'models' -> key/ else models/key/
        """
        if not base_path:
            return list(self.standard_map)

        try:
            base_dir = Path(base_path)
            base_is_models = base_dir.name.lower() == "models"
        except Exception:
            base_is_models = False
            base_dir = None

        adjusted_map = []

        def check_exists(path_obj):
            return self._path_is_dir(path_obj)

        # Cache actual directory names for case-sensitive alias matching.
        # 有界扫描：网络库对端没开机时这里直接返回空集，不会卡住调用方。
        base_exists = bool(base_dir) and self._path_is_dir(base_dir)
        actual_dir_names = None
        if base_exists:
            actual_dir_names = set(self._child_dirs(base_dir))

        for key, value in self.standard_map:
            new_lines = []
            for vline in value.split("\n"):
                clean_vline = vline.strip().rstrip("/")

                if base_exists:
                    # 1. Full standard path
                    p_full = base_dir / clean_vline
                    if check_exists(p_full):
                        new_lines.append(vline)
                        continue

                    # 2. SD WebUI-style aliases (check before short path to handle
                    #    case-insensitive filesystems where "controlnet" matches "ControlNet")
                    aliases = self.SD_STYLE_ALIASES.get(key, [])
                    found_alias = False
                    for alias in aliases:
                        if alias in actual_dir_names:
                            new_lines.append(alias + "/")
                            found_alias = True
                            break

                    if found_alias:
                        continue

                    # 3. Short path (strip models/ prefix)
                    if clean_vline.startswith("models/"):
                        short_vline = clean_vline[7:]
                    else:
                        short_vline = clean_vline
                    p_short = base_dir / short_vline
                    if check_exists(p_short):
                        new_lines.append(short_vline + "/")
                        continue

                    # 4. No real path matched. Skip emitting a phantom
                    #    `models/<key>/` line — the user might have a layout that
                    #    intentionally omits this category, and ComfyUI treats a
                    #    missing directory as silent (no warning UI to disambiguate).
                    pass
                else:
                    # base_path doesn't exist (cold start). Preserve the standard
                    # mapping so the user sees the framework; they can refresh once
                    # the directory is in place.
                    new_lines.append(vline)

            # Drop keys whose paths could not be resolved on disk so the yaml we
            # write reflects directories the launcher can actually point at.
            if not new_lines:
                continue
            adjusted_map.append((key, "\n".join(new_lines)))
        return adjusted_map

    def update_mapping(self, base_path: str) -> bool:
        import shutil

        if self.is_disabled():
            return False

        if not base_path.strip():
            return False
            
        # Resolve to the true base path
        base_path = self._resolve_base_path(base_path)

        # Backward compat: keep config.models.external_libraries[] in sync.
        # An existing release of the launcher only knew about a single base_path
        # via config; we mirror it into the new multi-library data model so
        # users on older configs see no observable change after upgrading.
        try:
            if self.find_library_by_base_path(base_path) is None:
                self.add_library(base_path)
        except Exception:
            pass

        # Post-migration routing: once external_libraries has any entry, switch
        # to the multi-library writer so the yaml stays in the new shape. The
        # cold-start path (no libraries yet) keeps the legacy single-key write
        # so the first migration pass can recognize and rename the key.
        if self.get_libraries():
            return self.apply_libraries()

        yp = self._get_yaml_path()

        # Backup existing file if it exists
        if yp.exists():
            try:
                bak_path = yp.with_suffix('.yaml.bak')
                shutil.copy2(yp, bak_path)
            except Exception as e:
                if hasattr(self.app, 'logger'):
                    self.app.logger.warning(f"Failed to backup yaml: {e}")

        # Build YAML manually to control order/format
        # Only one top-level key: comfyui
        lines = []
        lines.append("comfyui:")
        lines.append(f"  base_path: {base_path}")
        lines.append("  is_default: true")

        # Track paths already mapped (normalized)
        mapped_paths = set()

        standard_mappings = self._get_standard_mappings(base_path)
        for key, value in standard_mappings:
            if "\n" in value:
                lines.append(f"  {key}: |")
                for vline in value.split("\n"):
                    lines.append(f"    {vline}")
                    mapped_paths.add(vline.strip().rstrip("/"))
            else:
                lines.append(f"  {key}: {value}")
                mapped_paths.add(value.strip().rstrip("/"))

        # Discover additional subdirectories under external model root
        try:
            base_dir = Path(base_path)
            base_is_models = base_dir.name.lower() == "models"

            if self._path_is_dir(base_dir):
                extra_dirs = []
                for name in self._child_dirs(base_dir):
                    # If a child folder is named "models", map its subfolders instead
                    if name.lower() == "models":
                        for sub_name in self._child_dirs(base_dir / name):
                            rel_name = sub_name.replace("\\", "/")
                            mapped_value = f"models/{rel_name}/"
                            if mapped_value.rstrip("/") not in mapped_paths:
                                extra_dirs.append((rel_name, mapped_value))
                    else:
                        rel_path = name.replace("\\", "/")
                        if base_is_models:
                            mapped_value = f"{rel_path}/"
                        else:
                            mapped_value = f"models/{rel_path}/"

                        if mapped_value.rstrip("/") not in mapped_paths:
                            extra_dirs.append((rel_path, mapped_value))
                if extra_dirs:
                    lines.append("  # extra mapped folders")
                    for name, mapped_value in extra_dirs:
                        lines.append(f"  {name}: {mapped_value}")
        except Exception as e:
            if hasattr(self.app, 'logger'):
                self.app.logger.warning(f"Failed to scan external model dirs: {e}")

        try:
            with open(yp, 'w', encoding='utf-8') as f:
                f.write("\n".join(lines) + "\n")
            return True
        except Exception as e:
            if hasattr(self.app, 'logger'):
                self.app.logger.error(f"Failed to write model paths: {e}")
            return False

    def _collect_extra_mappings(self, base_path: str, mapped_paths: set) -> list[tuple]:
        extra_dirs = []
        standard_keys = {k for k, _ in self.standard_map}

        try:
            base_dir = Path(base_path)
            if not self._path_is_dir(base_dir):
                return extra_dirs
            for name in self._child_dirs(base_dir):
                # Skip if this folder name is already a standard key
                # (e.g. don't add 'checkpoints' again if it was handled by standard map)
                if name in standard_keys:
                    continue

                if name.lower() == "models":
                    models_dir = base_dir / name
                    for sub_name in self._child_dirs(models_dir):
                        if sub_name in standard_keys:
                            continue
                        rel_name = sub_name.replace("\\", "/")
                        mapped_value = f"models/{rel_name}/"
                        if mapped_value.rstrip("/") not in mapped_paths:
                            extra_dirs.append((rel_name, mapped_value))
                else:
                    rel_path = name.replace("\\", "/")
                    # Direct subfolder -> map directly
                    mapped_value = f"{rel_path}/"

                    if mapped_value.rstrip("/") not in mapped_paths:
                        extra_dirs.append((rel_path, mapped_value))
        except Exception as e:
            if hasattr(self.app, 'logger'):
                self.app.logger.warning(f"Failed to scan external model dirs: {e}")
        return extra_dirs


    def _resolve_base_path(self, base_path: str) -> str:
        """
        Smart resolution of the base path.
        If the user selects a parent folder (e.g., 'A') but the actual models are in 'A/B/models',
        we should automatically detect 'A/B' as the true base path.
        Logic:
        1. If base_path/models or base_path/checkpoints exists -> return base_path (it's already good)
        2. Iterate direct children of base_path:
           a. If child/models exists -> return child (e.g., found A/B/models -> return A/B)
           b. If child/checkpoints exists -> return child (e.g., found A/models/checkpoints -> return A/models)
        3. Return original base_path
        """
        if not base_path:
            return base_path
            
        try:
            p = Path(base_path)
            if not self._path_is_dir(p):
                return base_path

            # 1. Check direct
            if self._path_is_dir(p / "models"):
                return base_path
            if self._path_is_dir(p / "checkpoints"):
                return base_path

            # 1b. Check SD WebUI-style aliases
            all_aliases = set()
            for aliases in self.SD_STYLE_ALIASES.values():
                all_aliases.update(aliases)
            child_names = self._child_dirs(p)
            for name in child_names:
                if name in all_aliases:
                    return base_path

            # 2. Check children (depth 1)
            # Prioritize 'models' folder if found directly
            for name in child_names:
                child = p / name
                # If child is 'models', then base_path is actually correct (it contains 'models')
                # Wait, if p/models exists, we already caught it in step 1.
                # So here we are looking for A/B/models.

                if self._path_is_dir(child / "models"):
                    return self._safe_resolve(child)

                if self._path_is_dir(child / "checkpoints"):
                    # The child itself is likely the 'models' folder
                    return self._safe_resolve(child)

        except Exception:
            pass

        return base_path

    def get_mappings_for_base(self, base_path: str) -> List[tuple]:
        """某个库会映射出哪些目录。

        网络路径的整轮扫描有总时限：单次目录检查已经各自有界，但一个库要查
        几十个子目录，累加起来仍可能几十秒 —— 对端半死不活时尤其明显。
        超时就退回标准映射框架，绝不把调用方（GUI 线程）一起拖死。
        """
        if self.is_remote_path(base_path):
            result = self._bounded_scan(lambda: self._mappings_for_base(base_path))
            if result is None:
                return list(self.standard_map)
            return result
        return self._mappings_for_base(base_path)

    def _mappings_for_base(self, base_path: str) -> List[tuple]:
        # Resolve the path first to show what we would actually use
        resolved_path = self._resolve_base_path(base_path)

        mapped_paths = set()
        standard_mappings = self._get_standard_mappings(resolved_path)
        for _, value in standard_mappings:
            for vline in value.split("\n"):
                mapped_paths.add(vline.strip().rstrip("/"))
        if not resolved_path:
            return list(self.standard_map)
        extras = self._collect_extra_mappings(resolved_path, mapped_paths)
        return standard_mappings + extras

    def get_mappings(self) -> List[tuple]:
        return list(self.standard_map)

    # --- yaml round-trip (新增) ------------------------------------------

    LEGACY_TOP_KEYS = ("comfyui", "ComfyUI", "mie_external")
    TOP_KEY_PREFIX = "mie_launcher_"

    def load_yaml_data(self) -> dict:
        yp = self._get_yaml_path()
        if not yp.exists():
            return {}
        try:
            with open(yp, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _make_library_block(self, lib: dict) -> dict:
        """Compose the dict written under a single mie_launcher_<id> key."""
        block = {}
        block["base_path"] = lib["base_path"]
        if lib.get("is_default"):
            block["is_default"] = True
        std_mappings = self._get_standard_mappings(lib["base_path"])
        mapped_paths = set()
        for key, value in std_mappings:
            block[key] = value
            for vline in value.split("\n"):
                mapped_paths.add(vline.strip().rstrip("/"))
        try:
            extras = self._collect_extra_mappings(lib["base_path"], mapped_paths)
            for name, mapped_value in extras:
                block[name] = mapped_value
        except Exception:
            pass
        return block

    def apply_libraries(self, only_ids=None, force: bool = False) -> bool:
        """重写 extra_model_paths.yaml。

        ``only_ids`` 给定时，只重新生成这些库的块，其余库沿用 yaml 里已有的
        块（它们的配置没变，重扫一遍纯属浪费 —— 尤其网络库扫一次要好几秒）。
        ``force`` 会绕过可达性缓存重新探测（用户刚把 NAS 开机时点「刷新」用）。
        """
        if self.is_disabled():
            # Honor the legacy 'disable everything' opt-in: drop mie blocks,
            # but keep any non-managed entries the user had by hand.
            return self._write_yaml({})

        data = self.load_yaml_data()
        # Remember the blocks we are about to drop: a library whose NAS is
        # offline cannot be re-scanned, and regenerating its block from an
        # unreadable directory would silently drop its mappings (ComfyUI then
        # loads fewer models than the user configured — the exact failure mode
        # drift detection exists to prevent).
        previous_blocks = self._managed_blocks(data)

        # Strip any block the launcher previously wrote, legacy or not.
        to_drop = [k for k in list(data.keys()) if k.startswith(self.TOP_KEY_PREFIX)]
        to_drop += [k for k in list(data.keys()) if k in self.LEGACY_TOP_KEYS]
        for k in to_drop:
            data.pop(k, None)

        libs = [l for l in self.get_libraries() if l.get("enabled")]
        # Default block first; the rest preserve insertion order.
        libs.sort(key=lambda l: 0 if l.get("is_default") else 1)

        skipped = []
        deadline = time.monotonic() + self.REMOTE_APPLY_BUDGET
        for lib in libs:
            block_key = f"{self.TOP_KEY_PREFIX}{lib['id']}"
            base_path = lib.get("base_path", "")
            prev = previous_blocks.get(block_key)

            if only_ids is not None and lib.get("id") not in only_ids \
                    and isinstance(prev, dict):
                # 本次没动这个库，沿用 yaml 里已有的块（不用重扫共享）。
                data[block_key] = dict(prev)
                continue

            if self.is_offline(base_path, force=force):
                # 对端没开机：沿用上次写好的块，别把它降级成「只有 base_path」。
                skipped.append(lib)
                if isinstance(prev, dict):
                    data[block_key] = dict(prev)
                    continue
                data[block_key] = self._make_library_block(lib)
                continue

            if self.is_remote_path(base_path):
                # 在线但很慢的共享：整块扫描有总时限，超时就沿用旧块。
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    skipped.append(lib)
                    if isinstance(prev, dict):
                        data[block_key] = dict(prev)
                    else:
                        data[block_key] = self._skeleton_block(lib)
                    continue
                block = self._bounded_scan(
                    lambda: self._make_library_block(lib),
                    timeout=min(self.REMOTE_SCAN_TIMEOUT, remaining),
                )
                if block is None:
                    skipped.append(lib)
                    if isinstance(prev, dict):
                        data[block_key] = dict(prev)
                    else:
                        data[block_key] = self._skeleton_block(lib)
                    continue
                data[block_key] = block
                continue

            data[block_key] = self._make_library_block(lib)

        ok = self._write_yaml(data)
        self.last_apply_report = {"ok": ok, "skipped": skipped}
        if skipped:
            try:
                if hasattr(self.app, "logger"):
                    self.app.logger.warning(
                        "apply_libraries: %d 个外置库当前不可达（对端未开机？），"
                        "已保留原有 yaml 配置", len(skipped))
            except Exception:
                pass
        return ok

    # --- drift detection (yaml vs config) -------------------------------
    #
    # apply_libraries() is a full rewrite: it drops every mie_launcher_ block
    # and regenerates from external_libraries. So anything that edits the yaml
    # behind the launcher's back (整合包更新 / 手动编辑 / 别的工具) leaves the
    # file and config describing different model libraries, and ComfyUI then
    # silently loads fewer paths than the user configured. The GUI asks the
    # user whether to re-apply; the fingerprint below is what keeps us from
    # asking again for a drift the user already dismissed.

    # Keys under models. in config. Note these are *our* keys, not ComfyUI's.
    _DRIFT_KEY = "extra_paths_drift_notice"

    def _managed_blocks(self, data: dict) -> dict:
        """The subset of a loaded yaml that the launcher owns."""
        return {
            k: v for k, v in (data or {}).items()
            if k.startswith(self.TOP_KEY_PREFIX) and isinstance(v, dict)
        }

    def detect_drift(self) -> dict | None:
        """Return a drift report, or None when yaml agrees with config.

        Three ways they can disagree, all of which make ComfyUI load a
        different set of models than the user configured:

          missing  — an enabled library has no block in the yaml
          mismatch — the block exists but its base_path drifted
          orphan   — a block survives for a library that is gone or disabled

        A yaml with no managed blocks at all is *not* drift: that is the
        cold-start state (user never applied yet, or a fresh install), and
        `update_mapping` owns creating it. Remind-then-write on a fresh
        install would be noise, and a library that is simply unreachable
        (NAS offline) produces the same empty read, so we must not
        auto-create from a directory listing we could not read.
        """
        try:
            libs = [l for l in self.get_libraries() if l.get("enabled")]
            if not libs:
                return None
            blocks = self._managed_blocks(self.load_yaml_data())
            if not blocks:
                return None  # cold start / all libs unreachable — not drift

            missing, mismatch, orphan = [], [], []
            for lib in libs:
                key = f"{self.TOP_KEY_PREFIX}{lib['id']}"
                block = blocks.get(key)
                if block is None:
                    missing.append(lib)
                elif (block.get("base_path") or "") != (lib.get("base_path") or ""):
                    mismatch.append((lib, block.get("base_path")))
            known = {l.get("id") for l in libs}
            for key, block in blocks.items():
                if key[len(self.TOP_KEY_PREFIX):] not in known:
                    orphan.append((key, block.get("base_path")))

            if not (missing or mismatch or orphan):
                return None
            return {"missing": missing, "mismatch": mismatch, "orphan": orphan}
        except Exception:
            return None

    def _drift_fingerprint(self) -> str:
        """Digest of *what the user configured*, not of the drifted yaml.

        Deliberately excludes the yaml side: a drift the user declined still
        has the same config, so the fingerprint is stable across restarts and
        the prompt stays dismissed until the library set itself changes
        (added / removed / re-pointed / toggled) — at which point the digest
        moves and we ask again.
        """
        try:
            parts = []
            for lib in self.get_libraries():
                parts.append("|".join(str(x) for x in (
                    lib.get("id", ""),
                    lib.get("base_path", ""),
                    "on" if lib.get("enabled") else "off",
                    "def" if lib.get("is_default") else "-",
                )))
            parts.sort()
            return hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()
        except Exception:
            return ""

    def get_drift_notice_state(self) -> dict | None:
        """The dismissed-drift record, or None when nothing is on record."""
        try:
            rec = self.app.config.get("models", {}).get(self._DRIFT_KEY)
            if isinstance(rec, dict) and rec.get("fingerprint"):
                return rec
            return None
        except Exception:
            return None

    def should_prompt_for_drift(self) -> bool:
        """True when drift exists and we have not already asked about *this* one."""
        try:
            if self.is_disabled():
                return False
            if not self.detect_drift():
                return False
            rec = self.get_drift_notice_state()
            if rec and rec.get("fingerprint") == self._drift_fingerprint():
                return False
            return True
        except Exception:
            return False

    def mark_drift_acknowledged(self, applied: bool) -> None:
        """Record that the user answered the prompt for the current library set.

        Both answers are recorded: applying fixes it, and declining is a
        deliberate choice (e.g. they want ComfyUI to keep running on the
        built-in library only) that must not re-prompt on every launch. The
        record is keyed by fingerprint, so changing the library set re-arms it.
        """
        try:
            models = self._ensure_models_section()
            models[self._DRIFT_KEY] = {
                "fingerprint": self._drift_fingerprint(),
                "applied": bool(applied),
                "at": int(datetime.now().timestamp()),
            }
            svcs = getattr(self.app, "services", None)
            cfg_svc = getattr(svcs, "config", None) if svcs else None
            if cfg_svc and hasattr(cfg_svc, "save"):
                cfg_svc.save(self.app.config)
        except Exception:
            pass

    def clear_drift_notice(self) -> None:
        """Drop the record once the yaml and config agree again."""
        try:
            models = self.app.config.get("models", {})
            if self._DRIFT_KEY not in models:
                return
            models.pop(self._DRIFT_KEY, None)
            svcs = getattr(self.app, "services", None)
            cfg_svc = getattr(svcs, "config", None) if svcs else None
            if cfg_svc and hasattr(cfg_svc, "save"):
                cfg_svc.save(self.app.config)
        except Exception:
            pass

    def _write_yaml(self, data: dict) -> bool:
        import shutil
        yp = self._get_yaml_path()
        # Backup once per write if the file existed before.
        if yp.exists():
            try:
                shutil.copy2(yp, yp.with_suffix(".yaml.bak"))
            except Exception as e:
                if hasattr(self.app, "logger"):
                    self.app.logger.warning(f"Failed to backup yaml: {e}")
        try:
            yp.parent.mkdir(parents=True, exist_ok=True)
            with open(yp, "w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False,
                               default_flow_style=False, width=4096)
            return True
        except Exception as e:
            if hasattr(self.app, "logger"):
                self.app.logger.error(f"Failed to write yaml: {e}")
            return False

    def is_disabled(self) -> bool:
        """Whole-feature disable: legacy flag OR every library is disabled."""
        models = self.app.config.get("models", {})
        if bool(models.get("disable_external", False)):
            return True
        libs = self.get_libraries()
        if libs and not any(l.get("enabled") for l in libs):
            return True
        return False

    @staticmethod
    def _derive_lib_name(base_path: str) -> str:
        """Best-effort library display name from a base path."""
        try:
            return Path(base_path).name or "library"
        except Exception:
            return "library"

    @staticmethod
    def _library_id_for(base_path: str) -> str:
        """Stable 8-char id derived from the absolute resolved path."""
        try:
            if path_probe.is_remote_path(str(base_path)):
                # 网络路径不做 Path.resolve()（会真的去问网络，对端关机即卡死）
                resolved = os.path.abspath(str(base_path))
            else:
                resolved = str(Path(base_path).resolve())
        except Exception:
            resolved = base_path
        digest = hashlib.sha1(resolved.encode("utf-8")).hexdigest()
        return digest[:8]

    def get_libraries(self) -> list:
        libs = self.app.config.get("models", {}).get("external_libraries")
        if isinstance(libs, list):
            return libs
        return []

    def get_apply_report(self) -> dict:
        """上一次 apply_libraries() 的报告（ok / skipped 库列表）。"""
        return getattr(self, "last_apply_report", {"ok": None, "skipped": []}) or {
            "ok": None, "skipped": []
        }

    def library_status(self, base_path, force: bool = False) -> dict:
        """一个库的可达性状态，供 GUI 显示「离线」标记。"""
        base_path = base_path or ""
        remote = self.is_remote_path(base_path)
        reachable = self.is_reachable(base_path, force=force) if base_path else False
        return {
            "base_path": base_path,
            "remote": remote,
            "reachable": reachable,
            "offline": bool(remote and not reachable),
        }

    def _ensure_models_section(self) -> dict:
        return self.app.config.setdefault("models", {})

    def add_library(self, base_path: str, name=None) -> dict:
        if not base_path or not base_path.strip():
            raise ValueError("base_path is required")

        libs = self.get_libraries()
        new_id = self._library_id_for(base_path)
        for lib in libs:
            if lib.get("id") == new_id:
                return lib

        if name is None:
            name = Path(base_path).name or "library"

        is_default = len(libs) == 0

        lib = {
            "id": new_id,
            "name": name,
            "base_path": base_path,
            "enabled": True,
            "is_default": is_default,
        }
        libs.append(lib)
        self._ensure_models_section()["external_libraries"] = libs
        return lib

    def _find_library_index(self, library_id: str) -> int:
        libs = self.get_libraries()
        for i, lib in enumerate(libs):
            if lib.get("id") == library_id:
                return i
        return -1

    def remove_library(self, library_id: str) -> bool:
        idx = self._find_library_index(library_id)
        if idx < 0:
            return False
        libs = self.get_libraries()
        removed = libs.pop(idx)
        if removed.get("is_default") and libs:
            libs[0]["is_default"] = True
        self._ensure_models_section()["external_libraries"] = libs
        return True

    def set_default_library(self, library_id: str) -> bool:
        idx = self._find_library_index(library_id)
        if idx < 0:
            return False
        libs = self.get_libraries()
        for lib in libs:
            lib["is_default"] = (lib.get("id") == library_id)
        self._ensure_models_section()["external_libraries"] = libs
        return True

    def enable_library(self, library_id: str, enabled: bool = True) -> bool:
        idx = self._find_library_index(library_id)
        if idx < 0:
            return False
        libs = self.get_libraries()
        libs[idx]["enabled"] = bool(enabled)
        self._ensure_models_section()["external_libraries"] = libs
        return True

    def update_library(self, library_id: str, **fields) -> bool:
        idx = self._find_library_index(library_id)
        if idx < 0:
            return False
        libs = self.get_libraries()
        lib = libs[idx]
        for k, v in fields.items():
            if k == "id":
                continue
            lib[k] = v
        self._ensure_models_section()["external_libraries"] = libs
        return True

    def find_library_by_base_path(self, base_path: str):
        target = self._library_id_for(base_path)
        for lib in self.get_libraries():
            if lib.get("id") == target:
                return lib

    def migrate_legacy_yaml(self) -> dict:
        """
        One-shot upgrade entry point. Idempotent.

        Adopts legacy single-base yaml keys (comfyui: / ComfyUI: / mie_external:)
        into external_libraries[]. Also "rehydrates" external_libraries[] from
        any pre-existing mie_launcher_<id>: blocks, which covers users whose
        yaml was migrated by a previous launcher build but whose config records
        never made it to disk (so get_libraries() returns [] even though the
        yaml already declares a block).

        Returns { migrated: bool, adopted: int, rehydrated: int }.
        """
        if self.get_libraries():
            return {"migrated": False, "adopted": 0, "rehydrated": 0}

        data = self.load_yaml_data()
        if not data:
            return {"migrated": False, "adopted": 0, "rehydrated": 0}

        adopted_count = 0
        rewritten_yaml = False

        # Step 1: adopt a legacy single-base yaml key, if any.
        legacy_key = None
        for k in ("comfyui", "ComfyUI", "mie_external"):
            if k in data and isinstance(data[k], dict) and data[k].get("base_path"):
                legacy_key = k
                break

        if legacy_key is not None:
            legacy_block = data[legacy_key]
            base_path = legacy_block["base_path"]
            lib = self.add_library(base_path)

            new_block_key = f"{self.TOP_KEY_PREFIX}{lib['id']}"
            new_block = dict(legacy_block)
            new_block["base_path"] = base_path
            data.pop(legacy_key, None)
            data[new_block_key] = new_block

            # Back the pre-migration yaml up so users can roll back.
            try:
                import shutil
                yp = self._get_yaml_path()
                if yp.exists():
                    shutil.copy2(yp, yp.with_suffix(".yaml.user_bak"))
            except Exception:
                pass

            rewritten_yaml = True
            adopted_count = 1

        # Step 2: rehydrate from existing mie_launcher_<id>: blocks. Each block
        # represents a library whose config record got lost somewhere along the
        # way (older build, manual migration, restored backup, etc.).
        rehydrated_count = 0
        for k in list(data.keys()):
            if not k.startswith(self.TOP_KEY_PREFIX):
                continue
            block = data[k]
            if not isinstance(block, dict):
                continue
            base_path = block.get("base_path")
            if not base_path:
                continue
            block_id = k[len(self.TOP_KEY_PREFIX):]
            # Skip if external_libraries already has this id (idempotent).
            if any(l.get("id") == block_id for l in self.get_libraries()):
                continue
            lib = self.add_library(base_path)
            # align id with the yaml block so apply_libraries picks the same key.
            lib["id"] = block_id
            lib["name"] = block.get("name") or self._derive_lib_name(base_path)
            lib["enabled"] = True
            lib["is_default"] = bool(block.get("is_default"))
            rehydrated_count += 1

        if adopted_count or rehydrated_count:
            if rewritten_yaml:
                self._write_yaml(data)
            # Persist external_libraries so the next cold start finds the records.
            try:
                svcs = getattr(self.app, "services", None)
                cfg_svc = getattr(svcs, "config", None) if svcs else None
                if cfg_svc and hasattr(cfg_svc, "save"):
                    cfg_svc.save(self.app.config)
            except Exception:
                pass
            return {"migrated": bool(adopted_count), "adopted": adopted_count, "rehydrated": rehydrated_count}

        return {"migrated": False, "adopted": 0, "rehydrated": 0}
        return None
        return lib
