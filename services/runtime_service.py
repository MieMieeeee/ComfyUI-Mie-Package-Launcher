from pathlib import Path


class RuntimeService:
    def __init__(self, app):
        self.app = app

    def pre_start_up(self):
        pass
        # try:
        #     py_path = None
        #     try:
        #         py_path = Path(self.app.config["paths"].get("python_path", self.app.python_exec)).resolve()
        #     except Exception:
        #         py_path = Path(self.app.python_exec).resolve()
        #     site_packages = None
        #     try:
        #         if self.app and hasattr(self.app, 'python_exec') and Path(self.app.python_exec).suffix.lower() == '.exe':
        #             site_packages = py_path.parent.parent / "Lib" / "site-packages"
        #         else:
        #             import sysconfig
        #             p = sysconfig.get_paths().get("purelib") or sysconfig.get_paths().get("platlib") or ""
        #             if p:
        #                 site_packages = Path(p).resolve()
        #     except Exception:
        #         site_packages = None
        #     if not site_packages:
        #         return
        #     target = site_packages / "comfyui_workflow_templates" / "templates"
        #     try:
        #         target.mkdir(parents=True, exist_ok=True)
        #     except Exception:
        #         pass
        # except Exception:
        #     pass