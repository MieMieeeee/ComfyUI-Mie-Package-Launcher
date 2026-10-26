"""find_pids_by_port_safe 快路径（psutil.net_connections）回归。

旧实现逐进程 p.connections()，上千进程要好几秒且跑在 UI 线程
（toggle_comfyui 启动前检测），表现为点「一键启动」后按钮卡住。
新实现优先 psutil.net_connections 一次拿全系统连接表，仅在不可用时
才回落逐进程扫描 / netstat。
"""
import types

import core.probe as probe


class _Conn:
    def __init__(self, status, port, pid):
        self.status = status
        self.laddr = types.SimpleNamespace(port=port)
        self.pid = pid


def test_fast_path_returns_listen_pids(monkeypatch):
    def fake_net_connections(kind="inet"):
        return [
            _Conn("LISTEN", 8188, 4242),
            _Conn("ESTABLISHED", 8188, 999),  # 非 LISTEN：不收
            _Conn("LISTEN", 9999, 555),       # 其他端口：不收
            _Conn("LISTEN", 8188, 0),         # pid<=0：不收
        ]

    def boom(*a, **k):
        raise AssertionError("快路径命中时不应走逐进程兜底")

    monkeypatch.setattr(probe, "psutil", types.SimpleNamespace(
        CONN_LISTEN="LISTEN",
        net_connections=fake_net_connections,
        process_iter=boom,
    ))
    assert probe.find_pids_by_port_safe("8188") == [4242]


def test_falls_back_to_process_iter_when_net_connections_empty(monkeypatch):
    class P:
        pid = 777
        def connections(self, kind="inet"):
            return [_Conn("LISTEN", 8188, 777)]

    monkeypatch.setattr(probe, "psutil", types.SimpleNamespace(
        CONN_LISTEN="LISTEN",
        net_connections=lambda kind="inet": [],
        process_iter=lambda attrs=None: iter([P()]),
    ))
    assert probe.find_pids_by_port_safe("8188") == [777]


def test_fast_path_failure_falls_back_to_netstat(monkeypatch):
    """net_connections 抛异常（平台不支持/缺权限）时静默回落，最终走 netstat。"""
    def boom(*a, **k):
        raise RuntimeError("net_connections unavailable")

    monkeypatch.setattr(probe, "psutil", types.SimpleNamespace(
        CONN_LISTEN="LISTEN",
        net_connections=boom,
    ))
    # netstat 兜底：伪造 run_hidden 输出
    monkeypatch.setattr(probe, "run_hidden", lambda *a, **k: types.SimpleNamespace(
        returncode=0,
        stdout="  TCP    0.0.0.0:8188    0.0.0.0:0    LISTENING    31337\n",
    ))
    assert probe.find_pids_by_port_safe("8188") == [31337]
