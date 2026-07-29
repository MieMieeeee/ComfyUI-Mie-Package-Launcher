"""
ComfyUI启动器 Release 发布脚本
配合 GitHub CLI (gh) 使用

支持新的 release 子目录格式（推荐，build.py 默认产物）：
  release/ComfyUI启动器_v<ver>_<YYYYMMDD_HHMM>[_test]/
    ComfyUI启动器.exe
    ComfyUI启动器-CLI.cmd
    使用说明.md / AGENTS.md / cli.md

也兼容旧的散落 .exe 格式（迁移前残留）。

约定:
- gh / git 命令失败抛 ReleaseError，main() 统一 exit 1
- subdir 名字带 _test 后缀 → gh release create 加 --prerelease
- 上传失败重跑：检测 release 已存在时走 upload-only 分支，可安全重试
- git tag 默认创建本地 tag，--push-tag 才会 push 到 origin
"""

import os
import sys
import time
import argparse
import glob
import subprocess
import re
import zipfile

GH_REPO = "MieMieeeee/ComfyUI-Mie-Package-Launcher"

# subdir 名字模板：ComfyUI启动器_v1.2.3_20260726_1410[_test]
SUBDIR_VERSION_RE = re.compile(r"_v(\d+(?:\.\d+)*)_\d{8}_\d{4}(?:_test)?$")


class ReleaseError(Exception):
    """gh / git / 参数错误。main() 统一捕获并 exit 1。"""


def parse_args():
    p = argparse.ArgumentParser(
        description="ComfyUI启动器 Release 发布脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--version", type=str, default=None,
                   help="版本号 (如 v1.0.15)；缺省从 subdir 名字抽")
    p.add_argument("--file", type=str, default=None,
                   help="指定 exe 文件路径 / release subdir 路径")
    p.add_argument("--title", type=str, default=None,
                   help="Release 标题（默认 = 版本号）")
    p.add_argument("--notes", "--note", type=str, default=None,
                   help="Release 更新说明（内联字符串）")
    p.add_argument("--notes-file", type=str, default=None,
                   help="从文件读取发布说明")
    p.add_argument("--latest", action="store_true",
                   help="创建 release 时标记为 Latest")
    p.add_argument("--list", "-l", action="store_true",
                   help="列出 release/ 下的所有产物")
    p.add_argument("--view", "-v", action="store_true",
                   help="查看 GitHub 上的所有 release")
    p.add_argument("--delete", type=str, default=None,
                   help="删除指定版本的 release（值即版本号）")
    p.add_argument("--no-tag", dest="no_tag", action="store_true",
                   help="不要创建本地 git tag")
    p.add_argument("--push-tag", dest="push_tag", action="store_true",
                   help="创建本地 git tag 后 push 到 origin")
    p.add_argument("--repo", type=str, default=GH_REPO,
                   help=f"GitHub 仓库 (默认: {GH_REPO})")
    return p.parse_args()


def get_project_dir():
    return os.path.dirname(os.path.abspath(__file__))


# ---------- 产物扫描 ----------

def find_release_subdirs():
    """返回 release/ 下所有 ComfyUI启动器_v* 子目录，按 mtime 降序"""
    release_dir = os.path.join(get_project_dir(), "release")
    if not os.path.isdir(release_dir):
        return []
    out = []
    for name in os.listdir(release_dir):
        full = os.path.join(release_dir, name)
        if os.path.isdir(full) and name.startswith("ComfyUI启动器_v"):
            out.append(full)
    out.sort(key=os.path.getmtime, reverse=True)
    return out


def find_legacy_exe_files():
    """返回 release/ 下散落的 .exe（旧格式遗留）。"""
    release_dir = os.path.join(get_project_dir(), "release")
    if not os.path.isdir(release_dir):
        return []
    return sorted(
        glob.glob(os.path.join(release_dir, "*.exe")),
        key=os.path.getmtime, reverse=True,
    )


def extract_version_from_subdir(subdir_path):
    """从 "ComfyUI启动器_v1.0.14_20260726_1410[_test]" 抠 "v1.0.14" """
    m = SUBDIR_VERSION_RE.search(os.path.basename(subdir_path))
    return f"v{m.group(1)}" if m else None


def extract_version_from_legacy_filename(filename):
    """从 "ComfyUI启动器_v1.0.14_20260725_1253.exe" 抠 "v1.0.14" """
    basename = os.path.basename(filename)
    if "_v" in basename:
        try:
            part = basename.split("_v")[1]
            ver = part.split("_")[0]
            return f"v{ver}"
        except Exception:
            pass
    return None


def is_test_path(path):
    name = os.path.basename(path)
    return name.endswith("_test") or "_test." in name


def find_exe_in_subdir(subdir):
    """从 subdir 找 .exe；优先 ComfyUI启动器.exe / ComfyUI启动器_test.exe，兜底扫目录"""
    for cand in ("ComfyUI启动器.exe", "ComfyUI启动器_test.exe"):
        full = os.path.join(subdir, cand)
        if os.path.isfile(full):
            return full
    try:
        for name in os.listdir(subdir):
            if name.endswith(".exe"):
                return os.path.join(subdir, name)
    except Exception:
        pass
    return None


def collect_candidates():
    """扫描所有候选产物。
    返回 [(label, path, version, is_test, mtime, kind)] 按 mtime 降序，
    其中 kind: 'subdir' (新格式，会打成 zip 上传) 或 'legacy_exe' (单文件上传)
    """
    items = []

    for d in find_release_subdirs():
        items.append((
            os.path.basename(d),
            d,
            extract_version_from_subdir(d),
            is_test_path(d),
            os.path.getmtime(d),
            "subdir",
        ))

    for f in find_legacy_exe_files():
        items.append((
            os.path.basename(f),
            f,
            extract_version_from_legacy_filename(f),
            is_test_path(f),
            os.path.getmtime(f),
            "legacy_exe",
        ))
    items.sort(key=lambda x: x[4], reverse=True)
    return items


# ---------- 交互选择 ----------

def _fmt_size(n):
    return f"{n / (1024 * 1024):.1f} MB"


def _fmt_mtime(t):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(t))


def _fmt_ver(ver):
    return ver if ver else "unknown"


def pick_candidate_interactive(items):
    """列出所有候选，让用户选。返回 (path, version, is_test, kind)。
    kind: 'subdir' 选完会打 zip 上传；'legacy_exe' 直接传单文件
    """
    if not items:
        print("[错误] release/ 目录里没有可用产物。请先跑 `python build.py` 或 `python build.py --test`。")
        sys.exit(1)

    print("\n=== Release 产物候选（按修改时间倒序）===")
    for i, (label, path, ver, is_test, mtime, kind) in enumerate(items, 1):
        if kind == "subdir":
            try:
                size = sum(
                    os.path.getsize(os.path.join(root, f))
                    for root, _, files in os.walk(path)
                    for f in files
                )
            except OSError:
                size = 0
            kind_tag = "  [subdir→zip]"
        else:
            try:
                size = os.path.getsize(path)
            except OSError:
                size = 0
            kind_tag = "  [legacy exe]"
        test_tag = "  [test]" if is_test else ""
        print(f"  [{i}] {label}{kind_tag}{test_tag}")
        print(f"      版本: {_fmt_ver(ver)}  大小: {_fmt_size(size)}  修改: {_fmt_mtime(mtime)}")
    print()

    while True:
        try:
            choice = input("请输入编号 (直接回车选 [1]): ").strip()
        except EOFError:
            choice = "1"
        if not choice:
            idx = 0
            break
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(items):
                break
        except ValueError:
            pass
        print(f"[错误] 请输入 1-{len(items)} 之间的数字")

    _, path, ver, is_test, _, kind = items[idx]
    return path, ver, is_test, kind


# ---------- 路径解析 ----------

def resolve_exe(args):
    """根据 args.file / 默认策略解析 (path, version, is_test, kind)。
    kind: 'subdir' -> 打 zip 上传；'legacy_exe' -> 直接传单文件
    """
    if args.file:
        path = os.path.abspath(args.file)
        if not os.path.exists(path):
            raise ReleaseError(f"--file 路径不存在: {path}")
        if os.path.isdir(path):
            ver = extract_version_from_subdir(path) or args.version
            return path, ver, is_test_path(path), "subdir"
        ver = extract_version_from_legacy_filename(path) or args.version
        return path, ver, is_test_path(path), "legacy_exe"

    items = collect_candidates()
    subdir_items = [it for it in items if it[5] == "subdir"]
    if len(subdir_items) == 1:
        label, path, ver, is_test, _, _ = subdir_items[0]
        print(f"[默认] {label} (最新 subdir)")
        return path, ver, is_test, "subdir"
    return pick_candidate_interactive(items)


# ---------- 发布说明 ----------

def resolve_notes(args):
    """根据 --notes / --notes-file / 交互输入解析发布说明；可能返回 None（用默认）。"""
    if args.notes_file:
        try:
            with open(args.notes_file, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            raise ReleaseError(f"读取 --notes-file 失败: {e}")
    if args.notes:
        return args.notes
    print("\n[发布说明] 留空直接回车 = 默认 `Release <version>`")
    print("[提示] 多行输入：单独输入 `---` 结束；Ctrl+Z / Ctrl+D 结束输入")
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == "---":
            break
        lines.append(line)
    return "\n".join(lines) if lines else None


# ---------- gh / git 封装 ----------

def _run(cmd, check=True):
    """subprocess.run 统一封装：失败抛 ReleaseError（保留 stderr 信息）"""
    try:
        result = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")
    except FileNotFoundError:
        if check:
            raise ReleaseError(f"找不到命令: {cmd[0]}")
        return None
    except Exception as e:
        if check:
            raise ReleaseError(f"{cmd[0]} 执行异常: {e}")
        return None
    if check and result.returncode != 0:
        msg = (result.stderr or result.stdout or "").strip() or "(no output)"
        raise ReleaseError(f"{cmd[0]} 失败 (exit {result.returncode}): {msg}\n命令: {" ".join(cmd)}")
    return result


def run_gh(cmd, check=True):
    return _run(cmd, check=check)


def run_git(cmd, check=True):
    return _run(cmd, check=check)


# ---------- git tag ----------

def create_git_tag(version):
    """本地创建 git tag（已存在则跳过）"""
    existing = run_git(["git", "tag", "-l", version], check=False)
    if existing and version in (existing.stdout or ""):
        print(f"[tag] 本地 git tag 已存在，跳过: {version}")
        return
    run_git(["git", "tag", version])
    print(f"[tag] 本地 git tag 创建: {version}")


def push_git_tag(version):
    run_git(["git", "push", "origin", version])
    print(f"[tag] 已 push: origin/{version}")


# ---------- zip 打包 ----------

def create_release_zip(subdir_path):
    """把 subdir 打成 zip。zip 文件放在 release/ 根下，与 subdir 同名（+.zip）。
    zip 内的路径保留 subdir 名：解压后得到同名子目录。
    返回 (zip_path, file_count)。
    """
    subdir_name = os.path.basename(subdir_path)
    release_root = os.path.dirname(subdir_path)
    zip_path = os.path.join(release_root, subdir_name + ".zip")

    if os.path.exists(zip_path):
        os.remove(zip_path)

    file_count = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for root, _dirs, files in os.walk(subdir_path):
            for file in files:
                full = os.path.join(root, file)
                arc = os.path.relpath(full, release_root)
                zf.write(full, arc)
                file_count += 1
    return zip_path, file_count


# ---------- 子命令 ----------

def do_list(args):
    items = collect_candidates()
    if not items:
        print("[提示] release/ 目录里没有产物。请先跑 `python build.py`。")
        return
    subdir_items = [it for it in items if it[5] == "subdir"]
    legacy_items = [it for it in items if it[5] == "legacy_exe"]

    if subdir_items:
        print("\n=== Release 子目录（推荐，上传时打 zip） ===")
        for label, path, ver, is_test, mtime, _ in subdir_items:
            try:
                size = sum(
                    os.path.getsize(os.path.join(root, f))
                    for root, _, files in os.walk(path)
                    for f in files
                )
            except OSError:
                size = 0
            test_tag = "  [test]" if is_test else ""
            print(f"  {label}{test_tag}")
            print(f"      版本: {_fmt_ver(ver)}  原始: {_fmt_size(size)}  修改: {_fmt_mtime(mtime)}")
    if legacy_items:
        print("\n=== 散落的 .exe（旧格式，迁移前残留） ===")
        for label, exe, ver, is_test, mtime, _ in legacy_items:
            try:
                size = os.path.getsize(exe)
            except OSError:
                size = 0
            test_tag = "  [test]" if is_test else ""
            print(f"  {label}{test_tag}")
            print(f"      版本: {_fmt_ver(ver)}  大小: {_fmt_size(size)}  修改: {_fmt_mtime(mtime)}")


def do_view(args):
    print(f"\n=== Releases: {args.repo} ===")
    result = run_gh(["gh", "release", "list", "--repo", args.repo], check=False)
    if result and result.returncode == 0 and (result.stdout or "").strip():
        print(result.stdout)
    else:
        print("  (暂无 release 或 gh 未认证)")


def do_delete(args):
    if not args.delete:
        raise ReleaseError("--delete 需要一个版本号作为参数值")
    tag = args.delete if args.delete.startswith("v") else f"v{args.delete}"
    print(f"[删除] 确认删除 release {tag}? (Ctrl+C 取消)")
    try:
        input()
    except KeyboardInterrupt:
        print(" 已取消")
        return
    run_gh(["gh", "release", "delete", tag, "--repo", args.repo, "--yes"])
    print(f"[完成] 删除 release {tag}")


def do_upload(args):
    path, version, is_test, kind = resolve_exe(args)
    if not version:
        raise ReleaseError("无法确定版本号。请用 --version 显式指定。")
    if not version.startswith("v"):
        version = f"v{version}"

    title = args.title or version
    notes = resolve_notes(args) or f"Release {version}"

    # 准备要上传的资产
    # subdir -> 打 zip 上传；legacy_exe -> 直接传单文件（向后兼容）
    if kind == "subdir":
        print(f"[打包] {path}")
        zip_path, file_count = create_release_zip(path)
        upload_path = zip_path
        asset_name = os.path.basename(zip_path)
        size_mb = os.path.getsize(zip_path) / (1024 * 1024)
        print(f"[打包] {file_count} 个文件 -> {asset_name} ({size_mb:.1f} MB)")
    else:
        upload_path = path
        asset_name = os.path.basename(path)
        size_mb = os.path.getsize(path) / (1024 * 1024)
        print(f"[资产] {asset_name} ({size_mb:.1f} MB)  legacy_exe")

    # 检查 release 是否已存在
    existing = run_gh(["gh", "release", "view", version, "--repo", args.repo], check=False)
    upload_only = bool(existing and existing.returncode == 0)

    if upload_only:
        print(f"\n[上传] {asset_name} ({size_mb:.1f} MB) -> {version} (release 已存在，走 upload-only)")
    else:
        print(f"\n[创建] Release: {title}")
        print(f"[文件] {asset_name} ({size_mb:.1f} MB)  {"test" if is_test else "stable"}")
        gh_args = [
            "gh", "release", "create", version,
            "--title", title,
            "--notes", notes,
            "--repo", args.repo,
        ]
        if args.latest:
            gh_args.append("--latest")
        if is_test:
            gh_args.append("--prerelease")
        run_gh(gh_args)

    run_gh([
        "gh", "release", "upload", version, upload_path,
        "--repo", args.repo,
        "--clobber",
    ])
    print(f"\n[完成] https://github.com/{args.repo}/releases/tag/{version}")
    print(f"[资产] https://github.com/{args.repo}/releases/download/{version}/{asset_name}")

    # git tag 步骤（不影响 release 上传）
    if not args.no_tag:
        try:
            create_git_tag(version)
            if args.push_tag:
                push_git_tag(version)
        except ReleaseError as e:
            print(f"[warning] git tag 步骤失败（release 已上传，不影响）: {e}", file=sys.stderr)


def main():
    args = parse_args()
    try:
        if args.list:
            do_list(args)
        elif args.view:
            do_view(args)
        elif args.delete:
            do_delete(args)
        else:
            do_upload(args)
    except ReleaseError as e:
        print(f"[ReleaseError] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

