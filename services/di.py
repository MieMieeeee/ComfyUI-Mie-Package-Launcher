from pathlib import Path
from services.process_service import ProcessService
from services.version_service import VersionService
from services.config_service import ConfigService
from services.update_service import UpdateService
from services.git_service import GitService
from services.network_service import NetworkService
from services.runtime_service import RuntimeService
from services.announcement_service import AnnouncementService
from services.startup_service import StartupService
from services.model_path_service import ModelPathService


class ServiceContainer:
    def __init__(self, process: ProcessService, version: VersionService, config: ConfigService,
                 update: UpdateService, git: GitService, network: NetworkService, runtime: RuntimeService, announcement: AnnouncementService, startup: StartupService, model_path: ModelPathService):
        self.process = process
        self.version = version
        self.config = config
        self.update = update
        self.git = git
        self.network = network
        self.runtime = runtime
        self.announcement = announcement
        self.startup = startup
        self.model_path = model_path

    @classmethod
    def from_app(cls, app):
        try:
            cfg_file = Path(app.config_manager.config_file)
        except Exception:
            try:
                cfg_file = Path.cwd() / "launcher" / "config.json"
            except Exception:
                cfg_file = Path("launcher/config.json")
        return cls(
            process=ProcessService(app),
            version=VersionService(app),
            config=ConfigService(cfg_file, getattr(app, 'logger', None)),
            update=UpdateService(app),
            git=GitService(app),
            network=NetworkService(app),
            runtime=RuntimeService(app),
            announcement=AnnouncementService(app),
            startup=StartupService(app),
            model_path=ModelPathService(app),
        )
