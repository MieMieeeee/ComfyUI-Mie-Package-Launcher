"""
ComfyUI启动器 一键构建脚本
整合 Nuitka 编译 + Enigma Virtual Box 封包

用法:
  python build.py                     # 使用当前版本构建
  python build.py --version v1.0.10   # 设置版本号并构建
  python build.py --test              # 测试通道
  python build.py --evb-only          # 跳过 Nuitka，仅封包
"""

import os
import sys
import json
import time
import shutil
import subprocess
import argparse

# Enigma Virtual Box 安装路径搜索列表
ENIGMA_SEARCH_PATHS = [
    r"C:\Program Files (x86)\Enigma Virtual Box\enigmavbconsole.exe",
    r"C:\Program Files\Enigma Virtual Box\enigmavbconsole.exe",
    r"D:\Program Files (x86)\Enigma Virtual Box\enigmavbconsole.exe",
    r"D:\Program Files\Enigma Virtual Box\enigmavbconsole.exe",
    r"E:\Program Files (x86)\Enigma Virtual Box\enigmavbconsole.exe",
    r"E:\Program Files\Enigma Virtual Box\enigmavbconsole.exe",
    r"F:\Program Files (x86)\Enigma Virtual Box\enigmavbconsole.exe",
    r"F:\Program Files\Enigma Virtual Box\enigmavbconsole.exe",
]

INTERNAL_EXE_NAME = "ComfyUI_Launcher_Internal"
BOXED_EXE_NAME = "ComfyUI_Launcher_Internal_boxed.exe"


def parse_args():
    parser = argparse.ArgumentParser(description='ComfyUI启动器 一键构建脚本')
    parser.add_argument('--version', type=str, default=None,
                        help='设置版本号 (如 v1.0.10)，不指定则使用当前版本')
    parser.add_argument('--test', action='store_true',
                        help='构建测试通道版本')
    parser.add_argument('--evb-only', action='store_true',
                        help='跳过 Nuitka 编译，仅执行 Enigma 打包')
    parser.add_argument('--enigma-path', type=str, default=None,
                        help='指定 enigmavbconsole.exe 路径')
    return parser.parse_args()


def get_project_dir():
    return os.path.dirname(os.path.abspath(__file__))


def find_enigma_console(custom_path=None):
    """查找 enigmavbconsole.exe"""
    if custom_path and os.path.isfile(custom_path):
        return custom_path

    for path in ENIGMA_SEARCH_PATHS:
        if os.path.isfile(path):
            return path

    found = shutil.which('enigmavbconsole')
    if found:
        return found

    print("[错误] 未找到 enigmavbconsole.exe")
    print("[提示] 请使用 --enigma-path 参数指定路径")
    print("[提示] 或安装 Enigma Virtual Box: https://enigmaprotector.com/")
    sys.exit(1)


def bump_version(version_str):
    """更新 build_parameters.json 中的版本号"""
    project_dir = get_project_dir()
    bp_path = os.path.join(project_dir, 'build_parameters.json')
    bp_path_launcher = os.path.join(project_dir, 'launcher', 'build_parameters.json')

    params = {}
    try:
        if os.path.exists(bp_path):
            with open(bp_path, 'r', encoding='utf-8') as f:
                params = json.load(f) or {}
    except Exception:
        params = {}

    old_version = params.get('version', 'unknown')
    params['version'] = version_str

    with open(bp_path, 'w', encoding='utf-8') as f:
        json.dump(params, f, ensure_ascii=False, indent=2)

    try:
        os.makedirs(os.path.dirname(bp_path_launcher), exist_ok=True)
        with open(bp_path_launcher, 'w', encoding='utf-8') as f:
            json.dump(params, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    print(f"[版本] {old_version} -> {version_str}")


def read_build_parameters():
    """读取 build_parameters.json"""
    project_dir = get_project_dir()
    bp_path = os.path.join(project_dir, 'build_parameters.json')
    try:
        with open(bp_path, 'r', encoding='utf-8') as f:
            return json.load(f) or {}
    except Exception:
        return {}


def get_dist_dir(is_test):
    """获取 dist 输出目录"""
    project_dir = get_project_dir()
    name = "ComfyUI启动器_test" if is_test else "ComfyUI启动器"
    return os.path.join(project_dir, "dist", f"{name}.dist")


def step_nuitka_compile(is_test):
    """Step 1: Nuitka 编译"""
    from build_exe_v2 import build_nuitka

    print(f"\n[1/3] Nuitka 编译...")
    build_nuitka(is_test=is_test)

    dist_dir = get_dist_dir(is_test)
    exe_path = os.path.join(dist_dir, f"{INTERNAL_EXE_NAME}.exe")

    if not os.path.exists(exe_path):
        print(f"[错误] Nuitka 编译后未找到 exe: {exe_path}")
        sys.exit(1)

    return dist_dir


def step_enigma_package(dist_dir, is_test, enigma_exe):
    """Step 2: Enigma Virtual Box 打包"""
    project_dir = get_project_dir()
    evb_path = os.path.join(project_dir, 'EnigmaVirtualBox', 'launcher.evb')

    if not os.path.exists(evb_path):
        print(f"[错误] 未找到 EVB 项目文件: {evb_path}")
        sys.exit(1)

    # 测试通道需要替换 EVB 中的路径
    actual_evb = evb_path
    if is_test:
        # 动态生成测试版 EVB：替换 dist 目录路径
        stable_dist = r'ComfyUI启动器.dist'
        test_dist = r'ComfyUI启动器_test.dist'

        evb_content = open(evb_path, 'r', encoding='utf-8', errors='ignore').read()
        test_evb_content = evb_content.replace(stable_dist, test_dist)

        test_evb_path = os.path.join(project_dir, 'EnigmaVirtualBox', 'launcher_test.evb')
        with open(test_evb_path, 'w', encoding='utf-8', errors='ignore') as f:
            f.write(test_evb_content)
        actual_evb = test_evb_path
        print(f"[封包] 使用测试版 EVB: launcher_test.evb")

    print(f"\n[2/3] Enigma 打包...")
    print(f"[封包] {enigma_exe}")
    print(f"[封包] {actual_evb}")

    result = subprocess.run(
        [enigma_exe, actual_evb],
        cwd=project_dir,
    )

    if result.returncode != 0:
        print(f"[错误] Enigma 打包失败，返回码: {result.returncode}")
        sys.exit(1)

    boxed_exe = os.path.join(dist_dir, BOXED_EXE_NAME)
    if not os.path.exists(boxed_exe):
        print(f"[错误] 打包后未找到输出文件: {boxed_exe}")
        sys.exit(1)

    boxed_size = os.path.getsize(boxed_exe) / (1024 * 1024)
    print(f"[封包] 完成: {boxed_exe} ({boxed_size:.1f} MB)")

    return boxed_exe


def generate_release_filename(version, is_test):
    """生成发布文件名: ComfyUI启动器_v1.0.10_20260412_1033.exe"""
    ver = version.lstrip('v') if version else '0.0.0'
    ts = time.strftime('%Y%m%d_%H%M', time.localtime())
    suffix = "_test" if is_test else ""
    return f"ComfyUI启动器_v{ver}_{ts}{suffix}.exe"


def step_finalize_release(boxed_exe, version, is_test):
    """Step 3: 复制到 release/ 目录并重命名"""
    project_dir = get_project_dir()
    release_dir = os.path.join(project_dir, 'release')
    os.makedirs(release_dir, exist_ok=True)

    filename = generate_release_filename(version, is_test)
    dest = os.path.join(release_dir, filename)

    print(f"\n[3/3] 生成发布文件...")
    shutil.copy2(boxed_exe, dest)

    size_mb = os.path.getsize(dest) / (1024 * 1024)
    print(f"[输出] {dest}")
    print(f"[大小] {size_mb:.1f} MB")

    return dest


def format_duration(seconds):
    """格式化耗时"""
    if seconds < 60:
        return f"{seconds:.0f} 秒"
    m, s = divmod(int(seconds), 60)
    return f"{m} 分 {s} 秒"


def main():
    start_time = time.time()
    args = parse_args()
    project_dir = get_project_dir()

    # 读取当前版本
    params = read_build_parameters()
    version = params.get('version', 'unknown')
    channel = 'test' if args.test else 'stable'
    mode = 'Enigma 封包' if args.evb_only else 'Nuitka + Enigma'

    print("=" * 60)
    print("  ComfyUI启动器 一键构建")
    print("=" * 60)
    print(f"  版本:     {version}")
    print(f"  通道:     {channel}")
    print(f"  模式:     {mode}")
    print("=" * 60)

    # 1. 版本更新
    if args.version:
        bump_version(args.version)
        version = args.version

    # 2. Nuitka 编译
    if not args.evb_only:
        dist_dir = step_nuitka_compile(args.test)
    else:
        dist_dir = get_dist_dir(args.test)
        if not os.path.exists(dist_dir):
            print(f"[错误] dist 目录不存在: {dist_dir}")
            print("[提示] 请先运行一次完整构建，或去掉 --evb-only 参数")
            sys.exit(1)
        print(f"\n[跳过] Nuitka 编译 (--evb-only)")

    # evb-only 模式下同步版本号到 dist 目录的 build_parameters.json
    if args.evb_only and args.version:
        dist_bp = os.path.join(dist_dir, 'build_parameters.json')
        try:
            with open(dist_bp, 'r', encoding='utf-8') as f:
                dist_params = json.load(f) or {}
            dist_params['version'] = args.version
            with open(dist_bp, 'w', encoding='utf-8') as f:
                json.dump(dist_params, f, ensure_ascii=False, indent=2)
            print(f"[版本] dist/build_parameters.json 已同步为 {args.version}")
        except Exception as e:
            print(f"[警告] 同步 dist 版本号失败: {e}")

    # 3. Enigma 打包
    enigma_exe = find_enigma_console(args.enigma_path)
    boxed_exe = step_enigma_package(dist_dir, args.test, enigma_exe)

    # 4. 生成发布文件
    # 从 dist 目录中的 build_parameters.json 读取最终版本（Nuitka 会写入时间戳）
    dist_bp = os.path.join(dist_dir, 'build_parameters.json')
    if os.path.exists(dist_bp):
        try:
            with open(dist_bp, 'r', encoding='utf-8') as f:
                final_params = json.load(f) or {}
            version = final_params.get('version', version)
        except Exception:
            pass

    final_path = step_finalize_release(boxed_exe, version, args.test)

    # 构建摘要
    elapsed = time.time() - start_time
    size_mb = os.path.getsize(final_path) / (1024 * 1024)

    print()
    print("=" * 60)
    print("  构建成功！")
    print("=" * 60)
    print(f"  版本:      {version}")
    print(f"  通道:      {channel}")
    print(f"  输出文件:  {os.path.relpath(final_path, project_dir)}")
    print(f"  文件大小:  {size_mb:.1f} MB")
    print(f"  耗时:      {format_duration(elapsed)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
