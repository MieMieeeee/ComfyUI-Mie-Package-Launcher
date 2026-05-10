"""
ComfyUI启动器 Release 发布脚本
配合 GitHub CLI (gh) 使用

用法:
  python release.py                                    # 交互式选择 release 目录中的 exe 上传
  python release.py --version v1.0.10                  # 指定版本号创建 release
  python release.py --file "release/xxx.exe"           # 指定文件上传
  python release.py --title "v1.0.10"                 # 指定标题
  python release.py --notes "更新内容..."             # 指定发布说明
  python release.py --latest                          # 同时标记为 latest
  python release.py --list                            # 仅列出 release 目录中的 exe 文件
  python release.py --view                            # 查看当前所有 release
"""

import os
import sys
import time
import argparse
import glob
import subprocess

GH_REPO = "MieMieeeee/ComfyUI-Mie-Package-Launcher"


def parse_args():
    parser = argparse.ArgumentParser(description='ComfyUI启动器 Release 发布脚本')
    parser.add_argument('--version', type=str, default=None,
                        help='版本号 (如 v1.0.10)，从 release 目录文件名中提取')
    parser.add_argument('--file', type=str, default=None,
                        help='指定要上传的 exe 文件路径')
    parser.add_argument('--title', type=str, default=None,
                        help='Release 标题')
    parser.add_argument('--notes', '--note', type=str, default=None,
                        help='Release 更新说明')
    parser.add_argument('--notes-file', type=str, default=None,
                        help='从文件读取发布说明')
    parser.add_argument('--latest', action='store_true',
                        help='同时标记为 Latest')
    parser.add_argument('--list', '-l', action='store_true',
                        help='仅列出 release 目录中的 exe 文件')
    parser.add_argument('--view', '-v', action='store_true',
                        help='查看当前所有 release')
    parser.add_argument('--delete', type=str, default=None,
                        help='删除指定版本的 release')
    parser.add_argument('--repo', type=str, default=GH_REPO,
                        help=f'GitHub 仓库 (默认: {GH_REPO})')
    return parser.parse_args()


def get_project_dir():
    return os.path.dirname(os.path.abspath(__file__))


def list_exe_files():
    """列出 release 目录中的所有 exe 文件"""
    project_dir = get_project_dir()
    release_dir = os.path.join(project_dir, 'release')
    pattern = os.path.join(release_dir, '*.exe')
    files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
    return files


def extract_version_from_filename(filename):
    """从文件名中提取版本号，如 ComfyUI启动器_v1.0.10_20260510_1502.exe -> v1.0.10"""
    basename = os.path.basename(filename)
    if '_v' in basename:
        try:
            part = basename.split('_v')[1]
            ver = part.split('_')[0]
            return f"v{ver}"
        except Exception:
            pass
    return None


def format_exe_list(files):
    lines = []
    for i, f in enumerate(files, 1):
        size_mb = os.path.getsize(f) / (1024 * 1024)
        mtime = time.strftime('%Y-%m-%d %H:%M', time.localtime(os.path.getmtime(f)))
        ver = extract_version_from_filename(f) or 'unknown'
        lines.append(f"  [{i}] {os.path.basename(f)}")
        lines.append(f"      版本: {ver}  大小: {size_mb:.1f} MB  修改: {mtime}")
    return '\n'.join(lines)


def pick_exe_interactive(files):
    """交互式选择 exe 文件"""
    if not files:
        print("[错误] release 目录中没有找到 exe 文件")
        print("[提示] 请先运行 python build.py 构建")
        sys.exit(1)

    print("\n=== 选择要发布的 exe 文件 ===")
    print(format_exe_list(files))
    print()

    while True:
        try:
            choice = input("请输入编号 (直接回车选 [1]): ").strip()
            if not choice:
                return files[0]
            idx = int(choice)
            if 1 <= idx <= len(files):
                return files[idx - 1]
            print(f"[错误] 请输入 1-{len(files)} 之间的数字")
        except ValueError:
            print("[错误] 请输入有效数字")


def run_gh(args_list, check=True):
    """运行 gh 命令"""
    try:
        result = subprocess.run(
            args_list,
            capture_output=True,
            encoding='utf-8',
            errors='replace',
        )
    except Exception as e:
        if check:
            print(f"[错误] gh {' '.join(args_list)}")
            print(f"[异常] {e}")
            sys.exit(1)
        return None
    if check and result.returncode != 0:
        print(f"[错误] gh {' '.join(args_list)}")
        print(result.stderr or "")
        sys.exit(1)
    return result


def do_list(args):
    files = list_exe_files()
    if not files:
        print("[提示] release 目录中没有找到 exe 文件")
    else:
        print(format_exe_list(files))
    return files


def do_view(args):
    print(f"\n=== Releases: {args.repo} ===")
    result = run_gh(['gh', 'release', 'list', '--repo', args.repo])
    if result and result.stdout and result.stdout.strip():
        print(result.stdout)
    else:
        print("  (暂无 release)")


def do_delete(args):
    if not args.version:
        print("[错误] --delete 需要指定 --version")
        sys.exit(1)
    tag = args.version if args.version.startswith('v') else f"v{args.version}"
    print(f"[删除] 确认删除 release {tag}? (Ctrl+C 取消)")
    try:
        input()
    except KeyboardInterrupt:
        print(" 已取消")
        return
    run_gh(['gh', 'release', 'delete', tag, '--repo', args.repo, '--yes'])


def do_upload(args):
    # 1. 确定要上传的文件
    if args.file:
        exe_path = os.path.abspath(args.file)
        if not os.path.exists(exe_path):
            print(f"[错误] 文件不存在: {exe_path}")
            sys.exit(1)
    else:
        files = list_exe_files()
        exe_path = pick_exe_interactive(files)

    exe_name = os.path.basename(exe_path)
    size_mb = os.path.getsize(exe_path) / (1024 * 1024)

    # 2. 确定版本号
    version = args.version
    if not version:
        version = extract_version_from_filename(exe_path)
    if not version:
        version = input("请输入版本号 (如 v1.0.10): ").strip()
    if not version.startswith('v'):
        version = f"v{version}"

    # 3. 确定标题
    title = args.title or version

    # 4. 确定发布说明
    notes = None
    if args.notes_file:
        try:
            with open(args.notes_file, 'r', encoding='utf-8') as f:
                notes = f.read()
        except Exception as e:
            print(f"[错误] 读取发布说明文件失败: {e}")
            sys.exit(1)
    elif args.notes:
        notes = args.notes

    if not notes:
        notes_editor = os.environ.get('EDITOR')
        if not notes_editor:
            notes_editor = 'notepad' if sys.platform == 'win32' else 'nano'
        print(f"\n[发布说明] 编辑器: {notes_editor}")
        print(f"[提示] 按 Enter 继续打开编辑器编辑发布说明...")
        print(f"[提示] 或输入发布说明内容 (支持多行，单独输入一行只含 --- 结束):")
        print()
        lines = []
        while True:
            try:
                line = input()
                if line.strip() == '---':
                    break
                lines.append(line)
            except EOFError:
                break
        if lines:
            notes = '\n'.join(lines)
        else:
            notes = f"Release {version}"

    # 5. 检查 release 是否已存在
    existing = run_gh(['gh', 'release', 'view', version, '--repo', args.repo], check=False)
    if existing is not None and existing.returncode == 0:
        print(f"[提示] Release {version} 已存在，将上传文件到现有 release")
        upload_only = True
    else:
        upload_only = False

    # 6. 创建或更新 release
    if upload_only:
        print(f"\n[上传] {exe_name} ({size_mb:.1f} MB) -> {version}")
    else:
        print(f"\n[创建] Release: {title}")
        print(f"[文件] {exe_name} ({size_mb:.1f} MB)")
        gh_args = [
            'gh', 'release', 'create', version,
            '--title', title,
            '--notes', notes,
            '--repo', args.repo,
        ]
        if args.latest:
            gh_args.append('--latest')
        run_gh(gh_args)

    # 7. 上传文件
    run_gh([
        'gh', 'release', 'upload', version, exe_path,
        '--repo', args.repo,
        '--clobber',
    ])

    # 8. 确认
    print(f"\n[完成] https://github.com/{args.repo}/releases/tag/{version}")


def main():
    args = parse_args()
    project_dir = get_project_dir()

    if args.list:
        do_list(args)
    elif args.view:
        do_view(args)
    elif args.delete:
        do_delete(args)
    else:
        do_upload(args)


if __name__ == "__main__":
    main()
