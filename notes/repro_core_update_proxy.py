"""复现「内核更新一直失败」：跑真实 VersionService.upgrade_latest() 的三场景对照。

背景见 docs/core_update_git_proxy.md。本机 github.com 直连是通的，所以用 insteadOf
精确模拟用户那个「直连被重置」的网络：

  A  origin 直连 github.com，启动器不挂代理   -> 本机现状（直连可达 -> 成功）
  B  github.com 被打死，启动器不挂代理       -> 复刻用户报错（unable to access ...）
  C  github.com 被 insteadOf 改写到 gh-proxy -> 证明代理注入即为修复方向

用法：
    mkdir -p F:/tmp/cu_repro && cd F:/tmp/cu_repro
    git clone --depth 1 https://github.com/Comfy-Org/ComfyUI ComfyUI
    python notes/repro_core_update_proxy.py [整合包根目录]   # 默认 F:/tmp/cu_repro
"""
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

LAUNCHER_ROOT = Path(__file__).resolve().parent.parent
WORK = Path(sys.argv[1] if len(sys.argv) > 1 else r"F:\tmp\cu_repro")
REPO = WORK / "ComfyUI"
DIRECT = "https://github.com/Comfy-Org/ComfyUI"

sys.path.insert(0, str(LAUNCHER_ROOT))
from services.version_service import VersionService  # noqa: E402

# 把 github.com 改写到打死端口，模拟「连接被重置」
DEAD_DIRECT_CFG = '[url "http://127.0.0.1:1/"]\n\tinsteadOf = https://github.com/\n'
# 启动器在 proxy_mode=gh-proxy 时应注入的规则（与 plugin_service._git_proxy_config_path 同构）
PROXY_CFG = (
    "; launcher-managed git proxy (auto-generated, do not edit)\n"
    '[url "https://gh-proxy.com/https://github.com/"]\n\tinsteadOf = https://github.com/\n'
    '[url "https://gh-proxy.com/https://gitlab.com/"]\n\tinsteadOf = https://gitlab.com/\n'
)


class FakeApp:
    """鸭子类型，只实现 VersionService 用到的几个入口。"""

    def __init__(self, root):
        self.config = {}
        self.logger = logging.getLogger("repro")
        self.git_path = None
        self._root = root

    def get_active_paths(self):
        return {"comfyui_root": str(self._root)}


def scenario(name, gitconfig):
    print(f"\n=== {name} ===")
    subprocess.run(["git", "remote", "set-url", "origin", DIRECT],
                   cwd=REPO, check=True, capture_output=True)
    backup = os.environ.get("GIT_CONFIG_GLOBAL")
    cfg_path = WORK / "gitconfig.test"
    if gitconfig is None:
        os.environ.pop("GIT_CONFIG_GLOBAL", None)
    else:
        cfg_path.write_text(gitconfig, encoding="utf-8")
        os.environ["GIT_CONFIG_GLOBAL"] = str(cfg_path)
    try:
        eff = subprocess.run(["git", "remote", "get-url", "origin"], cwd=REPO,
                             capture_output=True, text=True).stdout.strip()
        print(f"    git actually contacts: {eff}")
        svc = VersionService(FakeApp(WORK))
        svc.reset_cancel()
        t0 = time.time()
        res = svc.upgrade_latest(stable_only=False)
        print(f"    elapsed: {time.time() - t0:.1f}s")
        print(f"    result: {res}")
        return res
    finally:
        if backup is None:
            os.environ.pop("GIT_CONFIG_GLOBAL", None)
        else:
            os.environ["GIT_CONFIG_GLOBAL"] = backup
        cfg_path.unlink(missing_ok=True)


if __name__ == "__main__":
    if not (REPO / ".git").exists():
        sys.exit(f"缺少 {REPO}，请先在该目录 git clone --depth 1 "
                 f"https://github.com/Comfy-Org/ComfyUI ComfyUI")

    logging.basicConfig(level=logging.INFO, format="    log| %(message)s",
                        stream=sys.stdout)
    logging.getLogger("comfyui_launcher").setLevel(logging.WARNING)

    a = scenario("A: 直连 github.com（本机现状）", None)
    b = scenario("B: 直连被打死，启动器不挂代理（复刻用户失败）", DEAD_DIRECT_CFG)
    c = scenario("C: insteadOf 改写到 gh-proxy（修复方向）", PROXY_CFG)

    print("\n--- summary ---")
    print(f"A 直连可达 : updated={a.get('updated')} err={a.get('error')}")
    print(f"B 直连被墙 : updated={b.get('updated')} err={b.get('error')}")
    print(f"C 走代理   : updated={c.get('updated')} err={c.get('error')}")