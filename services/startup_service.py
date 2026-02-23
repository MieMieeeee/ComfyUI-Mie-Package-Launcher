from concurrent.futures import ThreadPoolExecutor


class StartupService:
    def __init__(self, app):
        self.app = app

    def start_all(self):
        try:
            from core.version_service import refresh_version_info
            refresh_version_info(self.app, scope="all")
        except Exception:
            pass

    def start_announcements_only(self):
        try:
            ex = ThreadPoolExecutor(max_workers=1)
        except Exception:
            ex = None
        def _announcement_task():
            try:
                if getattr(self.app, 'services', None) and getattr(self.app.services, 'announcement', None):
                    self.app.services.announcement.show_if_available()
            except Exception:
                pass
        if ex:
            try:
                ex.submit(_announcement_task)
            except Exception:
                pass
        else:
            try:
                import threading
                threading.Thread(target=_announcement_task, daemon=True).start()
            except Exception:
                pass
