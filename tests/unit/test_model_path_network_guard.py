"""外置模型库指向局域网共享、且那台机器暂时不可访问时的行为。

背景：外置库常配成 ``\\\\NAS\\models``。对端没开机时，Windows 上每一次
``exists()`` / ``iterdir()`` 都要等 SMB 重试超时（几十秒），而这些调用原先
直接发生在 GUI 线程里 —— 表现为「切到模型库管理页整窗无响应」。

这里钉住三件事：

1. 不可达的网络库不会拖住调用方（有界探测 + 缓存）；
2. 不可达时**不会**把 yaml 里已有的映射抹掉（抹掉 = ComfyUI 静默少加载
   模型，正是漂移检测要防的那种失败）；
3. 页面把扫描放到后台线程，并在界面上明确标出「该库当前离线」。
"""

import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

yaml = pytest.importorskip("yaml")

UNC = "\\\\" + "no-such-nas-host-xyz123" + "\\models"


def _lib(lib_id, base_path, enabled=True, is_default=True):
    return {
        "id": lib_id,
        "name": f"lib_{lib_id}",
        "base_path": base_path,
        "enabled": enabled,
        "is_default": is_default,
    }


def _make_service(tmp_path, libs):
    from services.model_path_service import ModelPathService

    app = MagicMock()
    app.logger = MagicMock()
    app.config = {
        "paths": {"comfyui_root": str(tmp_path)},
        "models": {"external_libraries": list(libs)},
    }
    service = ModelPathService(app)
    service._get_yaml_path = lambda: Path(tmp_path) / "extra_model_paths.yaml"
    return service


def _write_yaml(service, data):
    yp = service._get_yaml_path()
    yp.parent.mkdir(parents=True, exist_ok=True)
    yp.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return yp


def _read_yaml(service):
    yp = service._get_yaml_path()
    if not yp.exists():
        return {}
    return yaml.safe_load(yp.read_text(encoding="utf-8")) or {}


@pytest.fixture(autouse=True)
def _clean_probe_cache():
    from utils import path_probe

    path_probe.clear_cache()
    yield
    path_probe.clear_cache()


def _wait_for_ui(app, predicate, timeout=8.0):
    """轮询等待条件成立（不依赖嵌套事件循环，见用例里的说明）。"""
    deadline = time.time() + timeout
    while True:
        if predicate():
            return True
        if time.time() > deadline:
            return False
        try:
            app.processEvents()
        except Exception:
            pass
        time.sleep(0.01)


class TestPathProbeBasics:
    def test_unc_path_is_remote(self):
        from utils import path_probe

        assert path_probe.is_remote_path(UNC)
        assert path_probe.is_unc_path(UNC)
        assert path_probe.host_of(UNC) == "no-such-nas-host-xyz123"

    def test_local_path_is_not_remote(self, tmp_path):
        from utils import path_probe

        assert not path_probe.is_remote_path(str(tmp_path))
        assert path_probe.host_of(str(tmp_path)) == ""

    def test_local_path_checks_are_cheap_and_correct(self, tmp_path):
        from utils import path_probe

        target = tmp_path / "models"
        target.mkdir()
        assert path_probe.isdir_bounded(str(target))
        assert not path_probe.isdir_bounded(str(tmp_path / "nope"))
        assert path_probe.child_dirs_bounded(str(target)) == []


class TestOfflineLibraryDoesNotBlock:
    def test_unreachable_library_returns_standard_map_quickly(self, tmp_path, monkeypatch):
        from utils import path_probe

        monkeypatch.setattr(path_probe, "path_reachable",
                            lambda path, force=False: False)
        svc = _make_service(tmp_path, [_lib("a", UNC)])

        t0 = time.monotonic()
        mappings = svc.get_mappings_for_base(UNC)
        elapsed = time.monotonic() - t0

        assert elapsed < 1.0, f"不可达的库不能拖住调用方，实测 {elapsed:.2f}s"
        assert len(mappings) == len(svc.standard_map)

    def test_repeated_calls_are_served_from_cache(self, tmp_path, monkeypatch):
        from utils import path_probe

        probes = []

        def fake_tcp_probe(host, timeout=1.2):
            probes.append(host)
            return False

        monkeypatch.setattr(path_probe, "_tcp_probe", fake_tcp_probe)
        svc = _make_service(tmp_path, [_lib("a", UNC)])

        svc.get_mappings_for_base(UNC)
        svc.get_mappings_for_base(UNC)
        svc.get_mappings_for_base(UNC)
        assert len(probes) <= 1, \
            f"对端探测应该被缓存，实际探测了 {len(probes)} 次"

    def test_offline_library_is_reported_as_offline(self, tmp_path, monkeypatch):
        from utils import path_probe

        monkeypatch.setattr(path_probe, "path_reachable",
                            lambda path, force=False: False)
        svc = _make_service(tmp_path, [_lib("a", UNC)])

        status = svc.library_status(UNC)
        assert status["remote"] is True
        assert status["offline"] is True
        assert svc.is_offline(UNC) is True

    def test_local_library_is_never_offline(self, tmp_path):
        svc = _make_service(tmp_path, [_lib("a", str(tmp_path))])
        assert svc.is_offline(str(tmp_path)) is False
        assert svc.library_status(str(tmp_path))["offline"] is False


class TestApplyKeepsOfflineLibraryConfig:
    def test_existing_block_is_preserved_when_library_is_offline(self, tmp_path, monkeypatch):
        from utils import path_probe

        monkeypatch.setattr(path_probe, "path_reachable",
                            lambda path, force=False: False)
        svc = _make_service(tmp_path, [_lib("a", UNC)])
        _write_yaml(svc, {
            "mie_launcher_a": {
                "base_path": UNC,
                "is_default": True,
                "checkpoints": "models/checkpoints/",
                "my_extra": "models/my_extra/",
            }
        })

        assert svc.apply_libraries() is True

        data = _read_yaml(svc)
        block = data.get("mie_launcher_a")
        assert block is not None, "离线库的块不能被整个删掉"
        assert block.get("checkpoints") == "models/checkpoints/", \
            "离线时必须沿用原映射，否则 ComfyUI 会静默少加载模型"
        assert block.get("my_extra") == "models/my_extra/"

    def test_apply_report_lists_the_skipped_library(self, tmp_path, monkeypatch):
        from utils import path_probe

        monkeypatch.setattr(path_probe, "path_reachable",
                            lambda path, force=False: False)
        svc = _make_service(tmp_path, [_lib("a", UNC)])

        svc.apply_libraries()
        report = svc.get_apply_report()
        assert [l["id"] for l in report["skipped"]] == ["a"]

    def test_online_library_block_is_regenerated(self, tmp_path, monkeypatch):
        from utils import path_probe

        monkeypatch.setattr(path_probe, "path_reachable",
                            lambda path, force=False: True)
        monkeypatch.setattr(path_probe, "isdir_bounded",
                            lambda path, timeout=1.5, force=False: False)
        monkeypatch.setattr(path_probe, "child_dirs_bounded",
                            lambda path, timeout=1.5, force=False: [])
        svc = _make_service(tmp_path, [_lib("a", UNC)])
        _write_yaml(svc, {
            "mie_launcher_a": {"base_path": UNC, "stale_key": "models/stale/"}
        })

        svc.apply_libraries()

        block = _read_yaml(svc).get("mie_launcher_a")
        assert block is not None
        assert "stale_key" not in block, "在线的库要重新生成块，不能沿用旧的"

    def test_only_ids_leaves_other_blocks_untouched(self, tmp_path, monkeypatch):
        from utils import path_probe

        monkeypatch.setattr(path_probe, "path_reachable",
                            lambda path, force=False: True)
        monkeypatch.setattr(path_probe, "isdir_bounded",
                            lambda path, timeout=1.5, force=False: False)
        monkeypatch.setattr(path_probe, "child_dirs_bounded",
                            lambda path, timeout=1.5, force=False: [])
        svc = _make_service(tmp_path, [_lib("a", UNC, is_default=True),
                                       _lib("b", UNC + "2", is_default=False)])
        _write_yaml(svc, {
            "mie_launcher_a": {"base_path": UNC, "checkpoints": "models/checkpoints/"},
            "mie_launcher_b": {"base_path": UNC + "2", "loras": "models/loras/"},
        })

        svc.apply_libraries(only_ids=["a"])

        data = _read_yaml(svc)
        assert data["mie_launcher_b"].get("loras") == "models/loras/", \
            "没动过的库要沿用旧块，不必重扫共享"


class TestModelsPageStaysResponsive:
    def test_remote_library_is_probed_off_thread_and_marked_offline(self, qtbot, qapp,
                                                                    tmp_path, monkeypatch):
        pytest.importorskip("PyQt5")
        from utils import path_probe

        monkeypatch.setattr(path_probe, "path_reachable",
                            lambda path, force=False: False)
        monkeypatch.setattr(path_probe, "isdir_bounded",
                            lambda path, timeout=1.5, force=False: False)
        monkeypatch.setattr(path_probe, "child_dirs_bounded",
                            lambda path, timeout=1.5, force=False: [])

        from services.model_path_service import ModelPathService
        from ui_qt.pages.models_page import ModelsPage
        from ui_qt.theme_manager import ThemeManager

        theme = ThemeManager(dark=True)
        app = MagicMock()
        app.config = {"paths": {"comfyui_root": str(tmp_path)}, "models": {}}
        services = MagicMock()
        services.config = MagicMock()
        services.model_path = ModelPathService(app)
        app.services = services
        services.model_path.add_library(UNC, name="NAS")

        t0 = time.monotonic()
        page = ModelsPage(app=app, theme_manager=theme)
        qtbot.addWidget(page)
        build_time = time.monotonic() - t0
        assert build_time < 2.0, \
            f"构造页面不能被网络库拖住，实测 {build_time:.2f}s"

        # 后台探测完成后应标出「离线」。
        # 这里用 processEvents 轮询而不是 qtbot.waitUntil：会话里别的用例
        # （test_format_update_summary）会调 QApplication.quit()，那会永久
        # 置上线程的 quitNow 标志，之后所有嵌套事件循环（waitUntil 的实现）
        # 都会立刻返回，排队投递的信号也就永远等不到。
        assert _wait_for_ui(qapp, lambda: "无法访问" in page.net_status_label.text()), \
            f"离线提示没出现，当前文案: {page.net_status_label.text()!r}"
        assert "离线" in page.library_list.item(0).text()

    def test_local_library_still_fills_the_table_synchronously(self, qtbot, tmp_path):
        pytest.importorskip("PyQt5")
        from services.model_path_service import ModelPathService
        from ui_qt.pages.models_page import ModelsPage
        from ui_qt.theme_manager import ThemeManager

        theme = ThemeManager(dark=True)
        app = MagicMock()
        app.config = {"paths": {"comfyui_root": str(tmp_path)}, "models": {}}
        services = MagicMock()
        services.config = MagicMock()
        services.model_path = ModelPathService(app)
        app.services = services

        lib_dir = tmp_path / "Lib"
        (lib_dir / "checkpoints").mkdir(parents=True)
        services.model_path.add_library(str(lib_dir), name="Lib")

        page = ModelsPage(app=app, theme_manager=theme)
        qtbot.addWidget(page)
        page.refresh_from_config()
        assert page.mapping_table.rowCount() >= 1
