"""find_pids_by_port_safe 的快路径顺序 + 短缓存回归。

2026-11-19（issue: 切页偶发卡一下才响应）：stall_probe 抓到主线程栈顶是
probe.find_pids_by_port_safe → subprocess.run（netstat）。排查发现三个问题：

1. **兜底顺序错了**：Windows 上非管理员进程调 psutil.net_connections 会抛
   AccessDenied → 旧代码接着走「逐进程 p.connections() 扫几千个进程」（最慢，
   几秒），最后才轮到 netstat（一次拿全表，几百 ms）。现在改成
   net_connections → **netstat** → 逐进程扫描。
2. **没有缓存**：一次状态查询里常要查同一端口好几次（收养 + 端口复核），
   等于把 netstat 跑成串。加了 3 秒短缓存。
3. **调用点在 UI 线程**：伴生服务页的 5 秒轮询定时器在主线程做端口探测 →
   每 5 秒把主线程堵一次（页面探测已移到后台线程，见 test_companion_page_poll.py）。
"""
import types

import pytest

import core.probe as probe


class _Conn:
    def __init__(self, status, port, pid):
        self.status = status
        self.laddr = types.SimpleNamespace(port=port)
        self.pid = pid


@pytest.fixture(autouse=True)
def _clear_cache():
    """端口→pid 缓存是模块级全局，测试之间必须隔离。"""
    probe.clear_port_pid_cache()
    yield
    probe.clear_port_pid_cache()


def _netstat_stub(text="", calls=None):
    def _run(cmd, **kwargs):
        if calls is not None:
            calls.append(cmd)
        return types.SimpleNamespace(returncode=0, stdout=text)
    return _run


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
    monkeypatch.setattr(probe, "run_hidden", _netstat_stub(calls=[]))
    assert probe.find_pids_by_port_safe("8188") == [4242]


def test_net_connections_empty_goes_to_netstat_before_process_iter(monkeypatch):
    """net_connections 空 → 先 netstat（一次拿全表），不是逐进程扫几千个。"""
    calls = []
    monkeypatch.setattr(probe, "psutil", types.SimpleNamespace(
        CONN_LISTEN="LISTEN",
        net_connections=lambda kind="inet": [],
        process_iter=lambda attrs=None: (_ for _ in ()).throw(
            AssertionError("netstat 有结果时不该走逐进程扫描")),
    ))
    monkeypatch.setattr(probe, "run_hidden", _netstat_stub(
        text="  TCP    0.0.0.0:8188    0.0.0.0:0    LISTENING    31337\n",
        calls=calls))
    assert probe.find_pids_by_port_safe("8188") == [31337]
    assert calls and calls[0][0] == "netstat"


def test_fast_path_failure_falls_back_to_netstat(monkeypatch):
    """net_connections 抛异常（平台不支持/缺权限）时静默回落，最终走 netstat。"""
    def boom(*a, **k):
        raise RuntimeError("net_connections unavailable")

    monkeypatch.setattr(probe, "psutil", types.SimpleNamespace(
        CONN_LISTEN="LISTEN",
        net_connections=boom,
    ))
    monkeypatch.setattr(probe, "run_hidden", _netstat_stub(
        text="  TCP    0.0.0.0:8188    0.0.0.0:0    LISTENING    31337\n"))
    assert probe.find_pids_by_port_safe("8188") == [31337]


def test_process_iter_is_last_resort(monkeypatch):
    """net_connections 与 netstat 都没结果 → 才逐进程扫（最慢，最后兜底）。"""
    class P:
        pid = 777
        def connections(self, kind="inet"):
            return [_Conn("LISTEN", 8188, 777)]

    monkeypatch.setattr(probe, "psutil", types.SimpleNamespace(
        CONN_LISTEN="LISTEN",
        net_connections=lambda kind="inet": [],
        process_iter=lambda attrs=None: iter([P()]),
    ))
    monkeypatch.setattr(probe, "run_hidden", _netstat_stub(text=""))
    assert probe.find_pids_by_port_safe("8188") == [777]


def test_port_result_is_cached(monkeypatch):
    """同端口短时间内的重复查询直接复用结果（别把 netstat 跑成串）。"""
    calls = []
    monkeypatch.setattr(probe, "psutil", types.SimpleNamespace(
        CONN_LISTEN="LISTEN",
        net_connections=lambda kind="inet": [],
        process_iter=lambda attrs=None: iter([]),
    ))
    monkeypatch.setattr(probe, "run_hidden", _netstat_stub(
        text="  TCP    0.0.0.0:8188    0.0.0.0:0    LISTENING    31337\n",
        calls=calls))
    assert probe.find_pids_by_port_safe("8188") == [31337]
    assert probe.find_pids_by_port_safe("8188") == [31337]
    assert probe.find_pids_by_port_safe("8188") == [31337]
    assert len(calls) == 1, "3 秒 TTL 内只该跑一次 netstat，实际 %d 次" % len(calls)


def test_cache_can_be_cleared(monkeypatch):
    calls = []
    monkeypatch.setattr(probe, "psutil", types.SimpleNamespace(
        CONN_LISTEN="LISTEN",
        net_connections=lambda kind="inet": [],
        process_iter=lambda attrs=None: iter([]),
    ))
    monkeypatch.setattr(probe, "run_hidden", _netstat_stub(
        text="  TCP    0.0.0.0:8188    0.0.0.0:0    LISTENING    31337\n",
        calls=calls))
    probe.find_pids_by_port_safe("8188")
    probe.clear_port_pid_cache()
    probe.find_pids_by_port_safe("8188")
    assert len(calls) == 2
