"""
启动器自动更新服务
"""

from pathlib import Path
from urllib.request import urlopen, Request
import concurrent.futures
import json
import hashlib
import sys
import os


class _UpdateSources(dict):
    """支持 `in` 操作符检查值的字典"""

    def __contains__(self, key):
        return super().__contains__(key) or key in self.values()


class LauncherUpdateService:
    """启动器自动更新服务"""

    # 通道常量
    CHANNEL_STABLE = "stable"
    CHANNEL_TEST = "test"

    # 更新源 - 双通道
    UPDATE_SOURCES = _UpdateSources(
        {
            CHANNEL_STABLE: "https://gitee.com/MieMieeeee/comfyui-mie-resources/raw/master/launcher/updates/index.json",
            CHANNEL_TEST: "https://gitee.com/MieMieeeee/comfyui-mie-resources/raw/master/launcher/updates/test/index.json",
        }
    )

    def __init__(self, app):
        self.app = app
        self._last_update_info = None
        self._compiled_channel = None  # Channel from build_parameters.json

    def _log(self, level: str, msg: str, *args):
        """安全日志"""
        logger = getattr(self.app, "logger", None)
        if logger:
            try:
                fn = getattr(logger, level, logger.info)
                fn(msg, *args)
            except Exception:
                pass

    def _get_update_dir(self) -> Path:
        """获取更新目录"""
        try:
            base = Path.cwd() / "launcher" / "update"
        except Exception:
            base = Path("launcher/update")
        try:
            base.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        return base

    def _get_pending_flag(self) -> Path:
        """获取待更新标记文件"""
        return self._get_update_dir() / "pending_update.flag"

    def get_current_channel(self) -> str:
        """获取当前更新通道，优先使用编译时指定的通道"""
        # 如果已经从 build_parameters.json 读取过，直接返回
        if self._compiled_channel:
            return self._compiled_channel

        # 否则从 config 读取（向后兼容）
        try:
            cfg = getattr(self.app, "config", None) or {}
            if not isinstance(cfg, dict):
                cfg = {}
            launcher_cfg = cfg.get("launcher_update", {})
            if not isinstance(launcher_cfg, dict):
                return self.CHANNEL_STABLE
            return launcher_cfg.get("channel", self.CHANNEL_STABLE)
        except Exception:
            return self.CHANNEL_STABLE

    def set_channel(self, channel: str):
        """设置更新通道

        注意：在编译后的 exe 中，build_parameters.json 的 channel 会通过
        _compiled_channel 优先生效。此方法主要用于开发/调试场景。
        """
        if channel not in (self.CHANNEL_STABLE, self.CHANNEL_TEST):
            channel = self.CHANNEL_STABLE
        self._compiled_channel = channel
        try:
            cfg = self.app.config or {}
            if "launcher_update" not in cfg:
                cfg["launcher_update"] = {}
            cfg["launcher_update"]["channel"] = channel
        except Exception:
            pass

    def get_stable_channel_url(self) -> str:
        return self.UPDATE_SOURCES[self.CHANNEL_STABLE]

    def get_test_channel_url(self) -> str:
        return self.UPDATE_SOURCES[self.CHANNEL_TEST]

    def get_update_url(self) -> str:
        """获取当前通道的更新 URL"""
        if self.get_current_channel() == self.CHANNEL_TEST:
            return self.get_test_channel_url()
        return self.get_stable_channel_url()

    def _get_bat_script(self) -> Path:
        """获取更新批处理脚本"""
        return self._get_update_dir() / "apply_update.bat"

    def get_current_version(self) -> str:
        """获取当前版本"""
        try:
            candidates = []
            try:
                candidates.append(
                    Path(getattr(sys, "_MEIPASS", "")) / "build_parameters.json"
                )
            except Exception:
                pass
            try:
                candidates.append(
                    Path(sys.executable).resolve().parent / "build_parameters.json"
                )
            except Exception:
                pass
            try:
                candidates.append(Path.cwd() / "build_parameters.json")
                candidates.append(Path.cwd() / "launcher" / "build_parameters.json")
            except Exception:
                pass

            for p in candidates:
                try:
                    if p.exists():
                        with open(p, "r", encoding="utf-8") as f:
                            params = json.load(f) or {}
                        ver = str(params.get("version") or "").strip()
                        if ver:
                            channel = params.get("channel", self.CHANNEL_STABLE)
                            self._compiled_channel = channel
                            return ver
                except Exception:
                    pass
        except Exception:
            pass
        return "v0.0.0"

    @staticmethod
    def calculate_sha256(file_path: str) -> str:
        """计算文件的 SHA256 哈希"""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()

    @staticmethod
    def read_version_from_file(file_path: str) -> str:
        """从 build_parameters.json 读取版本号"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                params = json.load(f)
                return params.get("version", "")
        except Exception:
            return ""

    def _fetch_update_payload(self, url: str, headers: dict):
        self._log("debug", "launcher_update: checking %s", url)
        req = Request(url, headers=headers)
        with urlopen(req, timeout=5) as resp:
            raw = resp.read()
            return json.loads(raw.decode("utf-8", errors="ignore"))

    def _build_update_info(
        self, data: dict, current_version: str, latest_version: str
    ) -> dict:
        return {
            "has_update": True,
            "current": current_version,
            "latest": latest_version,
            "release_date": data.get("release_date", ""),
            "download_url": data.get("download_url", ""),
            "backup_urls": data.get("backup_urls", []),
            "file_size": data.get("file_size", 0),
            "sha256": data.get("sha256", ""),
            "changelog": data.get("changelog", ""),
            "min_version": data.get("min_version", ""),
            "prerelease": data.get("prerelease", False),
        }

    def _version_tuple(self, s: str) -> tuple:
        """版本字符串转元组，prerelease 版本在比较时小于正式版本"""
        try:
            v = (s or "").strip().lower()
            if v.startswith("v"):
                v = v[1:]

            prerelease_offset = 0
            prerelease_patterns = [
                ("-alpha.", -3),
                ("-alpha", -3),
                ("-a.", -3),
                ("-a", -3),
                ("-beta.", -2),
                ("-beta", -2),
                ("-b.", -2),
                ("-b", -2),
                ("-rc.", -1),
                ("-rc", -1),
                ("-pre.", -1),
                ("-pre", -1),
            ]
            for pattern, offset in prerelease_patterns:
                idx = v.find(pattern)
                if idx != -1:
                    prefix = v[:idx]
                    last_char = prefix[-1] if prefix else ""
                    valid_boundary = last_char in (
                        "0",
                        "1",
                        "2",
                        "3",
                        "4",
                        "5",
                        "6",
                        "7",
                        "8",
                        "9",
                        ".",
                    )
                    if valid_boundary:
                        v = prefix
                        prerelease_offset = offset
                        break

            parts = v.split(".")
            nums = []
            for p in parts:
                try:
                    nums.append(int("".join(ch for ch in p if ch.isdigit())))
                except Exception:
                    nums.append(0)

            while len(nums) < 3:
                nums.append(0)

            if prerelease_offset != 0:
                nums[2] = nums[2] + prerelease_offset

            return tuple(nums[:3])
        except Exception:
            return (0, 0, 0)

    def check_update(self) -> dict:
        """
        检查是否有新版本
        返回: 更新信息字典，或 None（无更新/检查失败）
        """
        from urllib.error import HTTPError, URLError

        headers = {"User-Agent": "ComfyUI-Launcher", "Accept": "application/json"}
        current_version = self.get_current_version()
        current_tuple = self._version_tuple(current_version)

        last_error_type = None

        url = self.get_update_url()
        try:
            data = self._fetch_update_payload(url, headers)
            if data is None:
                return None

            latest_version = str(data.get("latest_version") or "").strip()
            if not latest_version:
                self._log("info", "launcher_update: no version info in response")
                return {
                    "has_update": False,
                    "current": current_version,
                    "latest": current_version,
                    "reason": "not_configured",
                }

            latest_tuple = self._version_tuple(latest_version)

            if latest_tuple <= current_tuple:
                self._log(
                    "info",
                    "launcher_update: already latest current=%s latest=%s",
                    current_version,
                    latest_version,
                )
                return {
                    "has_update": False,
                    "current": current_version,
                    "latest": latest_version,
                }

            info = self._build_update_info(data, current_version, latest_version)

            self._last_update_info = info
            self._log("info", "launcher_update: found new version %s", latest_version)
            return info

        except HTTPError as e:
            if e.code == 404:
                self._log(
                    "info", "launcher_update: update index not found (404) from %s", url
                )
                return {
                    "has_update": False,
                    "current": current_version,
                    "latest": current_version,
                    "reason": "not_configured",
                }
            self._log("warning", "launcher_update: HTTP error %d from %s", e.code, url)
            return None
        except URLError as e:
            self._log(
                "warning", "launcher_update: network error from %s: %s", url, e.reason
            )
            return None
        except Exception as e:
            self._log("warning", "launcher_update: check failed from %s: %s", url, e)
            return None

    def has_pending_update(self) -> bool:
        """检查是否有待处理的更新"""
        return self._get_pending_flag().exists()

    def download_update(self, url: str, on_progress=None, expected_sha256: str = "") -> str:
        """
        下载更新文件（带总超时和 SHA256 校验）
        返回: 下载文件路径，或 None（失败）
        """
        update_dir = self._get_update_dir()
        target_file = update_dir / "launcher_new.exe"

        def _do_download():
            """内部下载函数，在 ThreadPoolExecutor 中运行以支持总超时。"""
            self._log("info", "launcher_update: downloading from %s", url)
            req = Request(url, headers={"User-Agent": "ComfyUI-Launcher"})
            with urlopen(req, timeout=30) as resp:
                total_size = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                chunk_size = 8192

                with open(target_file, "wb") as f:
                    while True:
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if on_progress and total_size > 0:
                            try:
                                on_progress(downloaded, total_size)
                            except Exception:
                                pass

            self._log("info", "launcher_update: download complete, size=%d", downloaded)

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_do_download)
                future.result(timeout=120)  # 120 秒总超时

            # SHA256 校验
            if expected_sha256:
                actual_hash = self.calculate_sha256(str(target_file))
                if actual_hash != expected_sha256:
                    self._log(
                        "error",
                        "launcher_update: SHA256 mismatch (expected=%s, got=%s)",
                        expected_sha256[:16],
                        actual_hash[:16],
                    )
                    try:
                        target_file.unlink()
                    except Exception:
                        pass
                    return None
                self._log("info", "launcher_update: SHA256 verified OK")

            return str(target_file)

        except concurrent.futures.TimeoutError:
            self._log("error", "launcher_update: download timed out (120s)")
            try:
                if target_file.exists():
                    target_file.unlink()
            except Exception:
                pass
            return None

        except Exception as e:
            self._log("error", "launcher_update: download failed: %s", e)
            # 清理失败的下载
            try:
                if target_file.exists():
                    target_file.unlink()
            except Exception:
                pass
            return None

    def prepare_update(self, downloaded_file: str) -> bool:
        """
        准备更新：创建批处理脚本和标记文件
        """
        try:
            update_dir = self._get_update_dir()
            bat_path = self._get_bat_script()
            flag_path = self._get_pending_flag()

            # 获取当前 exe 路径
            current_exe = Path(sys.executable).resolve()
            new_exe = Path(downloaded_file).resolve()

            # 创建批处理脚本
            bat_content = f'''@echo off
chcp 65001 > nul
echo 正在更新启动器，请稍候...
timeout /t 3 > nul

copy /y "{new_exe}" "{current_exe}"
if errorlevel 1 (
    timeout /t 3 > nul
    copy /y "{new_exe}" "{current_exe}"
    if errorlevel 1 (
        echo 更新失败：无法覆盖启动器文件
        if exist "{new_exe}" del /f /q "{new_exe}"
        del "{flag_path}"
        timeout /t 5 > nul
        start "" "{current_exe}"
        exit /b 1
    )
)

if exist "{new_exe}" del /f /q "{new_exe}"
del "{flag_path}"
echo 更新完成！
timeout /t 2 > nul
start "" "{current_exe}"
exit
'''
            bat_path.write_text(bat_content, encoding="utf-8")

            # 创建标记文件
            flag_path.write_text(
                json.dumps(
                    {
                        "new_version": self._last_update_info.get("latest", "")
                        if self._last_update_info
                        else "",
                        "prepared_at": str(Path.cwd()),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            self._log("info", "launcher_update: prepared, bat=%s", bat_path)
            return True

        except Exception as e:
            self._log("error", "launcher_update: prepare failed: %s", e)
            return False

    def apply_pending_update(self) -> bool:
        """
        启动时应用待处理的更新
        返回: True 表示应该退出并执行更新
        """
        if not self.has_pending_update():
            # 没有待处理更新，但有残留文件则清理
            self._cleanup_orphaned_files()
            return False

        bat_path = self._get_bat_script()
        if not bat_path.exists():
            # bat 丢失，清理所有残留
            self._log("warning", "launcher_update: bat script missing, cleaning up")
            self.clear_pending_update()
            return False

        try:
            self._log("info", "launcher_update: applying pending update")
            # 使用 subprocess 启动批处理脚本
            import subprocess

            subprocess.Popen(
                f'cmd /c "{bat_path}"',
                shell=True,
                cwd=str(bat_path.parent),
                creationflags=subprocess.DETACHED_PROCESS
                | subprocess.CREATE_NEW_PROCESS_GROUP,
            )
            return True
        except Exception as e:
            self._log("error", "launcher_update: apply failed: %s", e)
            self.clear_pending_update()
            return False

    def _cleanup_orphaned_files(self):
        """清理没有 flag 的残留 launcher_new.exe。"""
        try:
            new_exe = self._get_update_dir() / "launcher_new.exe"
            if new_exe.exists():
                self._log("info", "launcher_update: cleaning up orphaned download")
                new_exe.unlink()
        except Exception:
            pass

    def clear_pending_update(self):
        """清除待处理的更新"""
        try:
            flag = self._get_pending_flag()
            if flag.exists():
                flag.unlink()
        except Exception:
            pass
        try:
            bat = self._get_bat_script()
            if bat.exists():
                bat.unlink()
        except Exception:
            pass
        try:
            new_exe = self._get_update_dir() / "launcher_new.exe"
            if new_exe.exists():
                new_exe.unlink()
        except Exception:
            pass
