"""cm_fast — cm-cli 补丁包装器（由启动器物化到真实磁盘后用环境 python 执行）。

绕过 ComfyUI-Manager cm-cli 在 Windows 上的性能坑：每次调用同步等缓存刷新
（实测 ~5.5 分钟），而服务端网页版从不等待。根因两个：

1. ``manager_util.is_file_created_within_one_day`` 用 ``os.path.getctime()``——
   Windows 上是文件**创建**时间；NTFS 隧道效应使「删除后 15 秒内同名重建」
   继承旧 ctime，导致 registry 缓存文件的 ctime 永远冻结在首次创建日，
   缓存永远被判「过期」。
2. ``cm-cli.py`` 的 ``set_channel_mode`` 硬编码 ``reload(dont_wait=False)``：
   缓存过期即同步全量拉取 CNR（api.comfy.org ~250 页、每页间 sleep 0.5s）。
   Manager 核心的 ``reload()`` 默认其实是 ``dont_wait=True``（缓存文件存在
   就直接用旧数据），网页版正是靠这个默认值。

补丁（只改本进程内存，不动 ComfyUI-Manager 文件）：

- patch 1: ``is_file_created_within_one_day`` 改用 mtime。
  语义差异（相对原实现）：ctime→mtime。缓存文件被重写后 ctime 不变、
  mtime 更新；用 mtime 反映「最近被刷新过」，符合「有新鲜缓存就别联网
  刷新」的目标。覆盖 manager_core.get_data_by_mode 的调用点
  （load_nightly 路径，无 dont_wait 保护）。
- patch 2: ``UnifiedManager.reload`` 强制 dont_wait=True：缓存文件存在即用
  旧数据，永不阻塞等待网络刷新（与网页版行为一致）。覆盖
  cnr_utils.get_cnr_data 的过期分支。

用法（参数与 cm-cli 完全一致，输出行也一致）：

    python cm_fast.py <cm-cli 子命令> [参数...]

退出码：cm-cli 原生退出码；额外约定 **exit 3** = install 非 URL 目标但
CNR registry 缓存文件缺失（外层启动器收到 3 应转原生 cm-cli 兜底，
付一次慢速全量把缓存建起来，之后恢复秒级）。
"""
import glob
import os
import runpy
import sys

CM_FAST_EXIT_CACHE_MISSING = 3


def _install_patches(manager_dir: str) -> None:
    """打两个 monkey-patch。必须在 runpy cm-cli 之前完成（cm-cli 复用
    sys.modules 里已打补丁的模块）。"""
    sys.path.insert(0, manager_dir)
    sys.path.insert(0, os.path.join(manager_dir, "glob"))

    import manager_util

    def _within_one_day_by_mtime(file_path):
        # 语义差异：ctime→mtime（见模块 docstring patch 1）。getctime 在
        # Windows 上是创建时间且被 NTFS 隧道冻结；mtime 随重写更新。
        try:
            import datetime
            return (datetime.datetime.now().timestamp()
                    - os.path.getmtime(file_path) <= 86400)
        except OSError:
            return False

    manager_util.is_file_created_within_one_day = _within_one_day_by_mtime

    # import manager_core 会触发模块级初始化（user dir / cache_dir 解析），
    # 依赖 sys.path 里已有 ComfyUI 根（调用方负责）。
    import manager_core

    _orig_reload = manager_core.UnifiedManager.reload

    async def _reload_dont_wait(self, cache_mode, dont_wait=True):
        # cm-cli 硬编码 dont_wait=False；这里丢弃调用方传值，强制 True。
        return await _orig_reload(self, cache_mode, True)

    manager_core.UnifiedManager.reload = _reload_dont_wait


def _install_target_needs_cnr_cache() -> bool:
    """install 命令且带非 URL 目标时才需要 CNR registry 缓存。

    uninstall/disable/enable/update 走 tracking 文件/git url，URL 安装走
    gitclone，均不依赖 CNR 缓存文件——这些情况永不 exit 3。
    """
    try:
        idx = sys.argv.index("install", 1)
    except ValueError:
        return False
    rest = sys.argv[idx + 1:]
    if not rest:
        return False
    has_url = any(t.lower().startswith(("http://", "https://")) for t in rest)
    return not has_url


def main() -> None:
    comfy_path = os.environ.get("COMFYUI_PATH")
    if not comfy_path:
        print("[cm_fast] ERROR: COMFYUI_PATH not set", file=sys.stderr)
        sys.exit(1)
    manager_dir = os.environ.get("CM_FAST_MANAGER_DIR") or os.path.join(
        comfy_path, "custom_nodes", "ComfyUI-Manager")
    cm_cli = os.path.join(manager_dir, "cm-cli.py")
    if not os.path.isfile(cm_cli):
        print(f"[cm_fast] ERROR: cm-cli.py not found: {cm_cli}", file=sys.stderr)
        sys.exit(1)

    # manager_core 通过 import folder_paths 找 user 目录 → 需要先放行 ComfyUI 根
    sys.path.append(comfy_path)
    _install_patches(manager_dir)

    if _install_target_needs_cnr_cache():
        import manager_util
        if not glob.glob(os.path.join(manager_util.cache_dir, "*_nodes.json")):
            print("[cm_fast] CNR registry cache missing; "
                  "caller should fall back to stock cm-cli")
            sys.exit(CM_FAST_EXIT_CACHE_MISSING)

    # runpy 不重排 argv：把 argv[0] 换成 cm-cli 本尊，其余原样透传
    sys.argv = [cm_cli] + sys.argv[1:]
    runpy.run_path(cm_cli, run_name="__main__")


if __name__ == "__main__":
    main()
