"""e2e: H3 短剧工作台真机启停 (真 Flask 进程 / 真端口 / 真健康检查).

对应计划 docs/plans/2026-11-18-launcher-h3-workbench.md 的验收条目:
  - 跑一次真实 Flask 启停, 验证健康检查;
  - **CLI 退出后服务仍可访问并持续写日志** (文件直写日志模式的意义);
  - 启停幂等;
  - 无关服务占用端口 → 启动报冲突, 且停止不影响占用者.

前置: 本机有一个装了 H3 引擎 + mie_* 依赖的整合包 (默认 C:\\PP\\V9\\V9-Large\\
comfyui_mie_2026_v9.0_large). 没有就 skip (别让 CI 为环境缺失而红).

临时包根用 **目录 junction** 搭: ComfyUI / python_embeded 指向真实包, 于是
  - 引擎与依赖是真的;
  - 设置/任务/快照落在 tmp 目录里 (不污染真包).
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.e2e

# 真机部署包 (有 ComfyUI-Mie-H3-Engine + mie_llm/mie_craft/mie_prompt)
REAL_PKG = Path(r"C:\PP\V9\V9-Large\comfyui_mie_2026_v9.0_large")


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _junction(link: Path, target: Path) -> bool:
    """建目录 junction (不需要管理员). 失败返回 False (调用方 skip)."""
    try:
        link.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                           capture_output=True, text=True, errors="ignore",
                           timeout=30)
        return r.returncode == 0 and link.exists()
    except Exception:
        return False


def _health(port: int, timeout: float = 2.0):
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/api/health" % port,
                                    timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:
        return None


@pytest.fixture()
def real_env(tmp_path):
    """临时包根 (junction 到真包的 ComfyUI / python_embeded) + 假 app."""
    if not REAL_PKG.is_dir():
        pytest.skip("本机没有 H3 部署包: %s" % REAL_PKG)
    engine = REAL_PKG / "ComfyUI" / "custom_nodes" / "ComfyUI-Mie-H3-Engine"
    if not (engine / "webapp" / "__main__.py").is_file():
        pytest.skip("部署包里没有 H3 引擎: %s" % engine)
    pkg = tmp_path / "pkg"
    pkg.mkdir(parents=True, exist_ok=True)
    if not _junction(pkg / "ComfyUI", REAL_PKG / "ComfyUI"):
        pytest.skip("mklink /J 失败 (junction 建不起来)")
    _junction(pkg / "python_embeded", REAL_PKG / "python_embeded")
    port = _free_port()
    cfg = {
        "environments": [{"id": "env_a", "comfyui_root": str(pkg),
                          "python_path": "python_embeded/python.exe"}],
        "active_env_id": "env_a",
        "services": {"h3-engine": {"port": port}},
    }
    app = SimpleNamespace(
        _cwd=str(tmp_path), config=cfg,
        logger=type("L", (), {"info": lambda *a, **kw: None,
                              "warning": lambda *a, **kw: None})(),
    )
    return app, pkg, port


def _mgr(app):
    from core.companion.manager import CompanionServiceManager
    return CompanionServiceManager(app, "h3-engine")


def test_real_start_health_stop_idempotent(real_env):
    """真 Flask 起停: 健康检查通 → 停 → 再停仍 0 (幂等)."""
    app, pkg, port = real_env
    m = _mgr(app)
    res = m.start(timeout=90)
    try:
        assert res["ok"] is True, res.get("error")
        assert res["exit_code"] == 0
        # 健康检查: 引擎自己的 /api/health
        payload = _health(port)
        assert payload is not None, "健康检查没响应"
        assert payload.get("status") == "ok"
        assert payload.get("app") == "comfyui-mie-web"
        # plugin_root 归属当前环境
        assert payload.get("plugin_root"), "健康检查没回 plugin_root"
        # 设置/任务落在临时包根下 (不污染真包)
        assert (pkg / "launcher" / "h3-engine").is_dir()
    finally:
        stop_res = m.stop(timeout=15)
    assert stop_res["ok"] is True
    assert stop_res["residual_ports"] == []
    # 幂等: 再停一次仍成功
    again = m.stop(timeout=15)
    assert again["ok"] is True


def test_service_survives_launcher_exit_and_keeps_logging(real_env):
    """CLI 退出后服务仍可访问并持续写日志 (文件直写日志模式).

    做法: 用 manager 起服务 → **模拟 launcher 进程退出** (manager 的 drain 线程
    不存在, 子进程只靠自己的文件句柄写日志) → 再打一次健康检查 → 看日志文件
    有没有新内容.
    """
    app, pkg, port = real_env
    m = _mgr(app)
    res = m.start(timeout=90)
    assert res["ok"] is True, res.get("error")
    log_path = m._log_path()
    try:
        # 文件直写模式: manager 侧没有 drain 线程 (进程退出后日志照样写)
        assert m._procs["app"]["thread"] is None
        before = _size(log_path)
        # 让服务再写点日志 (werkzeug 每个请求都写一行)
        for _ in range(3):
            assert _health(port) is not None
        deadline = time.time() + 15
        grew = False
        while time.time() < deadline:
            if _size(log_path) > before:
                grew = True
                break
            time.sleep(0.3)
        assert grew, "服务没继续写日志 (日志大小没变): %s" % log_path
    finally:
        m.stop(timeout=15)


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except Exception:
        return 0


def test_port_conflict_reports_and_spares_occupier(real_env):
    """无关服务占端口 → 启动报冲突 (exit 1) 且占用者不受影响."""
    app, pkg, port = real_env
    blocker = socket.socket()
    blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    blocker.bind(("127.0.0.1", port))
    # backlog 要给够: 启动器探测端口时会连好几次 (start 预检 + stop 的端口复核),
    # backlog 太小的话这些探测连接会占满队列 → 后续 connect 被拒 → 端口看起来
    # 「不再监听」, 那是测试自己造出来的假象, 不是产品行为.
    blocker.listen(64)
    try:
        m = _mgr(app)
        res = m.start(timeout=30)
        assert res["ok"] is False
        assert res["exit_code"] == 1
        assert res.get("port_in_use") is True
        assert str(port) in res["error"]
        # 占用者还活着 (stop 不会去动它)
        stop_res = m.stop(timeout=10)
        assert stop_res["ok"] is False
        assert "无法确认" in stop_res["error"]
        assert stop_res["residual_ports"], "占用者应仍在 (如实上报残留端口)"
        conn = socket.create_connection(("127.0.0.1", port), timeout=2)
        conn.close()
    finally:
        blocker.close()
