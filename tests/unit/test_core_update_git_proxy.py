"""内核更新的 git 代理注入单测（docs/core_update_git_proxy.md §8）。

背景：内核的 fetch/pull 以前硬直连仓库 origin，配了 gh-proxy 的用户「更新内核」必然
Recv failure。现在按 config.proxy_settings 给网络类 git 命令前置
``-c url.<前缀>.insteadOf=``。

不真跑 git —— mock run_hidden / Popen 验证 argv 形态。
"""
from unittest.mock import MagicMock, patch

from services.version_service import VersionService
from utils import net as NETUTILS


GH = "https://github.com/"
GITLAB = "https://gitlab.com/"
GH_PREFIX = "https://gh-proxy.com/https://github.com/"
GITLAB_PREFIX = "https://gh-proxy.com/https://gitlab.com/"

GH_PROXY_SETTINGS = {
    "git_proxy_mode": "gh-proxy",
    "git_proxy_url": "https://gh-proxy.com/",
}
NONE_SETTINGS = {"git_proxy_mode": "none", "git_proxy_url": ""}


def _svc(proxy_settings, git_path="git"):
    app = MagicMock()
    app.config = {"proxy_settings": proxy_settings}
    app.git_path = git_path
    svc = VersionService(app)
    return svc


# ---- utils.net.git_insteadof_args ----

def test_insteadof_args_gh_proxy_shape():
    """gh-proxy：github / gitlab 各一条，每条是单独一个 argv、不带引号。"""
    args = NETUTILS.git_insteadof_args(GH_PROXY_SETTINGS)
    assert args == [
        "-c", "url.{0}.insteadOf={1}".format(GH_PREFIX, GH),
        "-c", "url.{0}.insteadOf={1}".format(GITLAB_PREFIX, GITLAB),
    ]
    # 引号进 argv 会让 git 拼出坏地址（实测："https://gh-proxy.com/https://github.com/"Comfy-Org/...）
    assert not any('"' in a for a in args)


def test_insteadof_args_none_mode_returns_empty():
    assert NETUTILS.git_insteadof_args(NONE_SETTINGS) == []


def test_insteadof_args_custom_url_empty_returns_empty():
    """custom 模式但 URL 为空 → 不发 -c（否则 insteadOf 等于自己，永远不匹配）。"""
    assert NETUTILS.git_insteadof_args({"git_proxy_mode": "custom", "git_proxy_url": ""}) == []
    assert NETUTILS.git_insteadof_args({"git_proxy_mode": "custom", "git_proxy_url": "  "}) == []


def test_insteadof_args_unknown_mode_returns_empty():
    assert NETUTILS.git_insteadof_args({"git_proxy_mode": "ssr"}) == []


def test_insteadof_args_missing_settings_returns_empty():
    assert NETUTILS.git_insteadof_args(None) == []
    assert NETUTILS.git_insteadof_args({}) == []


def test_insteadof_args_custom_mode_uses_configured_url():
    """custom：前缀来自 git_proxy_url（去尾斜杠再补一个）。"""
    args = NETUTILS.git_insteadof_args(
        {"git_proxy_mode": "custom", "git_proxy_url": "https://my.mirror/"}
    )
    assert args[:2] == [
        "-c",
        "url.https://my.mirror/{0}.insteadOf={1}".format(GH, GH),
    ]


# ---- utils.net.git_cmd_needs_proxy ----

def test_needs_proxy_matches_network_subcommands():
    for sub in ("fetch", "pull", "ls-remote", "clone"):
        assert NETUTILS.git_cmd_needs_proxy(["git", sub]) is True
        assert NETUTILS.git_cmd_needs_proxy(["git", sub, "--prune"]) is True


def test_needs_proxy_skips_local_readonly_commands():
    """本地只读命令不加 -c（纯噪音）。"""
    for sub in ("rev-parse", "log", "describe", "status", "tag", "rev-list", "remote"):
        assert NETUTILS.git_cmd_needs_proxy(["git", sub, "HEAD"]) is False


def test_needs_proxy_matches_full_path_git_exe():
    """版本页传的是 git.exe 全路径，子命令在 cmd[1:] 一样要能命中。"""
    cmd = [r"C:\pkg\tools\PortableGit\bin\git.exe", "fetch", "--unshallow"]
    assert NETUTILS.git_cmd_needs_proxy(cmd) is True


# ---- VersionService._apply_git_path_and_proxy ----

def test_run_git_injects_proxy_args_for_fetch():
    svc = _svc(GH_PROXY_SETTINGS)
    out = svc._apply_git_path_and_proxy(["git", "fetch", "--prune"])
    assert out == ["git", "-c", "url.{0}.insteadOf={1}".format(GH_PREFIX, GH),
                   "-c", "url.{0}.insteadOf={1}".format(GITLAB_PREFIX, GITLAB),
                   "fetch", "--prune"]
    # -c 必须在可执行文件之后、子命令之前
    assert out.index("fetch") > out.index("-c")


def test_run_git_pull_paths_are_covered():
    """stable_only=False 路径的三条命令都要带 -c（用户日志失败的就是这几条）。"""
    svc = _svc(GH_PROXY_SETTINGS)
    for cmd in (["git", "fetch", "--prune"],
                ["git", "pull", "--ff-only"],
                ["git", "pull", "--rebase"]):
        out = svc._apply_git_path_and_proxy(list(cmd))
        assert "-c" in out, cmd
        # 原参数原样保留在尾部，只是前面多了 -c
        assert out[0] == "git"
        assert out[-len(cmd) + 1:] == cmd[1:], cmd


def test_run_git_no_args_when_proxy_disabled():
    svc = _svc(NONE_SETTINGS)
    assert svc._apply_git_path_and_proxy(["git", "fetch", "--prune"]) == [
        "git", "fetch", "--prune"
    ]


def test_run_git_no_args_for_readonly_commands():
    svc = _svc(GH_PROXY_SETTINGS)
    assert svc._apply_git_path_and_proxy(["git", "rev-parse", "HEAD"]) == [
        "git", "rev-parse", "HEAD"
    ]


def test_run_git_injects_when_cmd0_is_full_git_path():
    """version_page 形态：cmd[0] 是绝对路径，不靠 cmd[0]=='git' 也能注入。"""
    git_exe = r"C:\pkg\tools\PortableGit\bin\git.exe"
    svc = _svc(GH_PROXY_SETTINGS, git_path=git_exe)
    out = svc._apply_git_path_and_proxy([git_exe, "fetch", "--unshallow"])
    assert out[0] == git_exe
    assert "-c" in out
    assert out[-2:] == ["fetch", "--unshallow"]


def test_apply_does_not_mutate_input_list():
    """调用方（version_page）持有原 list；不复制的话 -c 会重复叠加（doc §8.7）。"""
    svc = _svc(GH_PROXY_SETTINGS)
    original = ["git", "fetch", "--prune"]
    snapshot = list(original)
    svc._apply_git_path_and_proxy(original)
    assert original == snapshot
    # 同一 list 再走一遍也不能叠加出两份 -c
    once = svc._apply_git_path_and_proxy(original)
    twice = svc._apply_git_path_and_proxy(once)
    assert twice.count("-c") == 4  # github + gitlab，各两次 = 两份参数


def test_apply_replaces_bare_git_with_git_path():
    svc = _svc(NONE_SETTINGS, git_path=r"C:\pkg\git.exe")
    assert svc._apply_git_path_and_proxy(["git", "rev-parse", "HEAD"])[0] == r"C:\pkg\git.exe"


# ---- 两个入口都要注入（_run_git_cancellable 不传 env，只能走 argv）----

def test_run_git_entrypoint_injects():
    svc = _svc(GH_PROXY_SETTINGS)
    with patch("services.version_service.run_hidden") as mh:
        mh.return_value = MagicMock(returncode=0, stdout="", stderr="")
        svc._run_git(["git", "fetch", "--prune"], capture_output=True, text=True,
                     timeout=10, cwd=".")
    cmd = mh.call_args[0][0]
    assert "-c" in cmd
    assert not any('"' in a for a in cmd)


def test_run_git_cancellable_entrypoint_injects():
    svc = _svc(GH_PROXY_SETTINGS)
    proc = MagicMock()
    proc.communicate.return_value = (b"", b"")
    proc.returncode = 0
    with patch("services.version_service.subprocess.Popen", return_value=proc) as mp:
        svc._run_git_cancellable(["git", "pull", "--ff-only"], timeout=10, cwd=".")
    cmd = mp.call_args[0][0]
    assert "-c" in cmd, "可取消路径靠 Popen argv 注入，不传 env"
    assert cmd[-2:] == ["pull", "--ff-only"]


def test_request_cancel_kills_recorded_popen():
    """超时分支靠 request_cancel() 杀掉 _run_git_cancellable 记下的那个 Popen。"""
    svc = _svc(NONE_SETTINGS)
    proc = MagicMock()
    proc.poll.return_value = None  # 还活着
    svc._current_process = proc
    svc.request_cancel()
    assert proc.terminate.called or proc.kill.called


def test_first_attempt_already_has_proxy():
    """不做「先直连失败再带代理重试」——第一次发出的 argv 就得带 -c。"""
    svc = _svc(GH_PROXY_SETTINGS)
    with patch("services.version_service.run_hidden") as mh:
        mh.return_value = MagicMock(returncode=1, stdout="", stderr="boom")
        svc._run_git(["git", "fetch", "--prune"], capture_output=True, text=True,
                     timeout=10, cwd=".")
    assert mh.call_count == 1
    assert "-c" in mh.call_args[0][0]


def test_broken_app_config_falls_back_to_no_proxy():
    """config 坏了不能连带把更新搞挂 —— 拿不到代理就按直连跑。"""
    app = MagicMock()
    type(app).config = property(lambda self: (_ for _ in ()).throw(RuntimeError("boom")))
    app.git_path = "git"
    svc = VersionService(app)
    assert svc._apply_git_path_and_proxy(["git", "fetch"]) == ["git", "fetch"]