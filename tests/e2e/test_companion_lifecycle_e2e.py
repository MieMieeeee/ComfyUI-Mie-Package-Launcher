"""e2e: CompanionServiceManager 真 spawn 生命周期 (假 runtime + 真进程/真端口/真身份匹配).

对应 webui 侧的 tests/e2e/test_webui_lifecycle_e2e.py 手法:
- 假 runtime 的命令用真 python 子进程, proxy/app 各监听一个真端口;
- 身份不 mock: proxy 的 -c 里含 comfy_api_proxy, app 的 -c 含 next 且 cwd=root,
  走 proctree 的 psutil 真匹配 (IdentityRule 的行为级验证).
"""
from __future__ import annotations

import socket
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.e2e


def _free_ports(n: int = 2) -> list:
    socks, ports = [], []
    for _ in range(n):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        socks.append(s)
        ports.append(s.getsockname()[1])
    for s in socks:
        s.close()
    return ports


@pytest.fixture()
def env(tmp_path):
    """假包根 + 假 app + 挂好 fake runtime 的 manager."""
    pkg = tmp_path / "pkg"
    root = pkg / "openjutsu"
    root.mkdir(parents=True)
    (root / "package.json").write_text("{}", encoding="utf-8")
    (root / "patch_proxy.py").write_text("# patch", encoding="utf-8")
    ports = _free_ports(2)
    cfg = {
        "environments": [{"id": "env_a", "comfyui_root": str(pkg), "python_path": "py"}],
        "active_env_id": "env_a",
        "services": {"openjutsu": {"proxy_port": ports[0], "app_port": ports[1]}},
    }
    app = SimpleNamespace(
        _cwd=str(tmp_path), config=cfg,
        logger=type("L", (), {"info": lambda *a, **kw: None,
                              "warning": lambda *a, **kw: None})(),
    )

    def _listener_cmd(token: str, port: int) -> list:
        # accept 循环: 只 listen 不 accept 的话, start 的就绪探测会把 backlog 占满,
        # status 的后续探测被拒 (假服务要像真服务一样处理连接)
        script = (f"x='{token}';import socket,time\n"
                  f"s=socket.socket();s.bind(('127.0.0.1',{port}));s.listen(4)\n"
                  f"while 1:\n c,_=s.accept();c.close()")
        return [sys.executable, "-c", script]

    fake_rt = SimpleNamespace(
        resolve_paths=lambda a, env_id=None: {
            "pkg_root": pkg, "root": root, "node_exe": pkg / "node/node.exe",
            "npm_cli": pkg / "node/npm.js", "py": sys.executable,
            "proxy_site": root / ".proxy-site", "env_id": "env_a"},
        check_deps=lambda p, **kw: {"ok": True, "missing": [], "available": ["node", "proxy", "next"]},
        # env 必须给真实环境 (空 env 下 Windows 子进程连 Winsock 都起不来, WinError 10106)
        build_step_cmd=lambda p: ([sys.executable, "-c", "print('build-ok')"],
                                  __import__("os").environ.copy(), str(root)),
        build_proxy_cmd=lambda p, port: (_listener_cmd("comfy_api_proxy", port),
                                         __import__("os").environ.copy(), str(root)),
        build_app_cmd=lambda p, app_port, proxy_port, comfy_port:
            (_listener_cmd("next", app_port), __import__("os").environ.copy(), str(root)),
        comfyui_port=lambda a: 8188,
        update=lambda a, p, on_progress=None: {"ok": True, "updated": True},
    )

    from core.companion.manager import CompanionServiceManager
    mgr = CompanionServiceManager(app, "openjutsu")
    patcher_rt = patch.object(type(mgr), "_runtime", return_value=fake_rt)
    patcher_core = patch.object(type(mgr), "_comfyui_running", return_value=True)
    patcher_rt.start()
    patcher_core.start()
    yield SimpleNamespace(mgr=mgr, app=app, ports=ports, root=root,
                          tmp_path=tmp_path)
    patcher_rt.stop()
    patcher_core.stop()
    mgr.stop()  # 兜底清理


def _listening(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except Exception:
        return False


def test_full_start_status_stop_lifecycle(env):
    m = env.mgr
    # start: build 步骤 + proxy/app 双 spawn, 阻塞到双端口就绪
    res = m.start(timeout=25)
    assert res["ok"] is True, res.get("error")
    assert res["exit_code"] == 0
    assert {e["role"] for e in res["pids"]} == {"proxy", "app"}
    assert res["ports"] == {"proxy": env.ports[0], "app": env.ports[1]}
    assert res["url"] == f"http://127.0.0.1:{env.ports[1]}"

    # pidstore 落盘 (v2, 双进程)
    raw = m._raw_store()
    assert raw is not None and raw["version"] == 2
    assert len(raw["processes"]) == 2

    # 日志: 三路输出合一, 带前缀
    log = Path(res["log_path"]).read_text(encoding="utf-8", errors="replace")
    assert "[build]" in log and "[proxy]" in log and "[app]" in log
    assert "build-ok" in log

    # status: running + ready (真身份匹配, 无 mock)
    s = m.status()
    assert s["running"] is True
    assert s["ready"] is True
    assert {e["role"] for e in s["pids"]} == {"proxy", "app"}

    # stop: 树杀 + 端口复核
    stop = m.stop()
    assert stop["ok"] is True
    assert stop["residual_ports"] == []
    assert not _listening(env.ports[0])
    assert not _listening(env.ports[1])
    assert m._raw_store() is None  # pidstore 清了
    assert m.is_running() is False


def test_start_already_running_short_circuits(env):
    m = env.mgr
    first = m.start(timeout=25)
    assert first["ok"] is True
    second = m.start(timeout=25)
    assert second["ok"] is True
    assert second["already_running"] is True
    assert second["exit_code"] == 0
    m.stop()


def test_stop_is_idempotent(env):
    m = env.mgr
    assert m.start(timeout=25)["ok"] is True
    assert m.stop()["ok"] is True
    again = m.stop()
    assert again["ok"] is True  # 未跑也返 ok


def test_start_no_wait_returns_without_ready(env):
    m = env.mgr
    res = m.start(timeout=25, no_wait=True)
    assert res["ok"] is True
    m.stop()
