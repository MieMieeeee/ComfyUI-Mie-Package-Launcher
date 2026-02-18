from pathlib import Path
from utils.common import run_hidden


class GitService:
    def __init__(self, app):
        self.app = app

    def resolve_git(self):
        try:
            base = Path(self.app.config.get("paths", {}).get("comfyui_root") or ".").resolve()
        except Exception:
            base = Path(".").resolve()
        try:
            pkg_git = base / "tools" / "PortableGit" / "bin" / "git.exe"
            if pkg_git.exists():
                r_pkg = run_hidden([str(pkg_git), "--version"], capture_output=True, text=True, timeout=5)
                if r_pkg.returncode == 0:
                    self.app.git_path = str(pkg_git)
                    try:
                        self.app.logger.info(f"Git解析: 使用整合包Git path={self.app.git_path}")
                    except Exception:
                        pass
                    try:
                        self.apply_to_manager(self.app.git_path)
                    except Exception:
                        pass
                    return self.app.git_path, "使用整合包Git"
        except Exception:
            pass
        try:
            r_sys = run_hidden(["git", "--version"], capture_output=True, text=True, timeout=5)
            if r_sys.returncode == 0:
                self.app.git_path = "git"
                try:
                    self.app.logger.info("Git解析: 使用系统Git path=git")
                except Exception:
                    pass
                return self.app.git_path, "使用系统Git"
        except Exception:
            pass
        self.app.git_path = None
        try:
            self.app.logger.warning("Git解析: 未找到Git命令")
        except Exception:
            pass
        return None, "未找到Git命令"

    def apply_to_manager(self, git_path: str):
        try:
            if not git_path:
                return
            try:
                base = Path(self.app.config["paths"].get("comfyui_root", "")).resolve()
                comfy_root = (base / "ComfyUI").resolve()
            except Exception:
                comfy_root = None
            if not (comfy_root and comfy_root.exists()):
                return
            ini_path = comfy_root / "user" / "default" / "ComfyUI-Manager" / "config.ini"
            try:
                integrations = self.app.config.setdefault("integrations", {})
            except Exception:
                integrations = {}
                try:
                    self.app.config["integrations"] = integrations
                except Exception:
                    pass
            last_path = integrations.get("comfyui_manager_git_path")
            if last_path == git_path and ini_path.exists():
                return
            try:
                ini_path.parent.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
            try:
                content = ini_path.read_text(encoding="utf-8", errors="ignore") if ini_path.exists() else ""
            except Exception:
                content = ""
            lines = content.splitlines()
            updated = False
            new_lines = []
            for line in lines:
                if line.strip().lower().startswith("git_exe"):
                    new_lines.append(f"git_exe = {git_path}")
                    updated = True
                else:
                    new_lines.append(line)
            if not updated:
                new_lines.append(f"git_exe = {git_path}")
            try:
                ini_path.write_text("\n".join(new_lines) + ("\n" if new_lines else ""), encoding="utf-8")
            except Exception:
                with open(ini_path, "wb") as f:
                    f.write(("\n".join(new_lines) + ("\n" if new_lines else "")).encode("utf-8", errors="ignore"))
            try:
                integrations["comfyui_manager_git_set"] = True
                integrations["comfyui_manager_git_path"] = git_path
                try:
                    if getattr(self.app, 'services', None) and getattr(self.app.services, 'config', None):
                        self.app.services.config.save(self.app.config)
                    else:
                        self.app.config_manager.save_config(self.app.config)
                except Exception:
                    pass
            except Exception:
                pass
        except Exception:
            pass

    def fix_unsafe_repo(self, repo_path: str):
        try:
            if not repo_path:
                return
            # 尝试使用已解析的git，如果未解析则使用 "git"
            git_exe = getattr(self.app, 'git_path', None) or "git"
            
            # 检查 git status 看来判断是否遇到 dubious ownership
            # 使用 rev-parse --git-dir 可能更快，但 dubious ownership 通常在任何操作时都会触发
            r = run_hidden([git_exe, "status"], cwd=repo_path, capture_output=True, text=True, timeout=5)
            
            # 检查错误信息
            stderr = (r.stderr or "").lower()
            stdout = (r.stdout or "").lower()
            if "dubious ownership" in stderr or "dubious ownership" in stdout:
                try:
                    if getattr(self.app, 'logger', None):
                        self.app.logger.info(f"Git安全修复: 检测到所有权问题，尝试添加 safe.directory {repo_path}")
                except Exception:
                    pass
                
                # 规范化路径，git config 需要 forward slashes
                safe_path = str(Path(repo_path).resolve()).replace("\\", "/")
                
                # 执行修复
                run_hidden([git_exe, "config", "--global", "--add", "safe.directory", safe_path], timeout=5)
        except Exception:
            pass
