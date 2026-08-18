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
# 发布产物里用的人类可读文件名（不再带时间戳，时间戳在父目录上）
EXE_NAME = "ComfyUI启动器.exe"
CLI_WRAPPER_NAME = "ComfyUI启动器-CLI.cmd"

# 发布子目录里要带的 launcher 操作文档（让 agent / 用户拿到 release 包就能读到 CLI 介绍）
RELEASE_DOC_FILES = [
    ("使用说明.md",     "使用说明.md"),
    ("AGENTS.md",       "AGENTS.md"),
    ("cli.md",     "cli.md"),
]


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




def find_python_exe():
    """查找虚拟环境中的 Python（项目根 .venv 优先）。从 build_exe_v2 迁过来。"""
    project_dir = get_project_dir()
    venv_python = os.path.join(project_dir, ".venv", "Scripts", "python.exe")
    if os.path.exists(venv_python):
        return venv_python
    return sys.executable


def update_build_parameters(is_test=False):
    """写构建参数到 build_parameters.json + launcher/build_parameters.json。从 build_exe_v2 迁过来。"""
    project_dir = get_project_dir()
    bp_path = os.path.join(project_dir, "build_parameters.json")
    bp_path_launcher = os.path.join(project_dir, "launcher", "build_parameters.json")

    params = {}
    try:
        if os.path.exists(bp_path):
            with open(bp_path, "r", encoding="utf-8") as f:
                params = json.load(f) or {}
    except:
        params = {}

    now = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    ver = params.get("version", "v1.0.7")
    params["version"] = ver
    params["suffix"] = f" - 构建于 {now}"
    params["mode"] = "nuitka_release"
    params["built_at"] = now
    params["builder"] = "黎黎原上咩"
    params["channel"] = "test" if is_test else "stable"

    try:
        with open(bp_path, "w", encoding="utf-8") as f:
            json.dump(params, f, ensure_ascii=False, indent=2)
        os.makedirs(os.path.dirname(bp_path_launcher), exist_ok=True)
        with open(bp_path_launcher, "w", encoding="utf-8") as f:
            json.dump(params, f, ensure_ascii=False, indent=2)
        print(f"[版本] 参数已写入: {bp_path}")
    except Exception as e:
        print(f"[版本] 写入忽略: {e}")

    return params
def step_nuitka_compile(is_test):
    """Step 1: Nuitka 编译（含构建参数 + dist 清理 + 编译后改名）。

    从 build_exe_v2.build_nuitka 内联过来；之前 build.py 跨文件 import 调用，
    现在 build.py 自包含，建 build_exe_v2.py / build_exe.py 可以下线。
    """
    project_dir = get_project_dir()
    python_exe = find_python_exe()

    print(f"[环境] Python: {python_exe}")
    print(f"[环境] 项目目录: {project_dir}")

    if is_test:
        print("[通道] 测试版本")
    else:
        print("[通道] 正式版本")

    params = update_build_parameters(is_test=is_test)
    print(f"[版本] {params.get('version', 'unknown')}")

    internal_name = INTERNAL_EXE_NAME
    if is_test:
        output_name = "ComfyUI启动器_test"
    else:
        output_name = "ComfyUI启动器"
    dist_base = os.path.join(project_dir, "dist")
    dist_dir = os.path.join(dist_base, f"{output_name}.dist")
    exe_path = os.path.join(dist_dir, f"{internal_name}.exe")

    # 如果已存在则删除旧的构建目录
    if os.path.exists(dist_dir):
        print(f"[清理] 删除旧目录: {dist_dir}")
        try:
            shutil.rmtree(dist_dir)
        except PermissionError:
            print(f"[警告] 目录被占用，无法删除。请先关闭正在运行的程序。")
            print(f"[警告] 将尝试覆盖构建...")
            try:
                for item in os.listdir(dist_dir):
                    item_path = os.path.join(dist_dir, item)
                    if os.path.isfile(item_path):
                        try:
                            os.remove(item_path)
                        except:
                            pass
            except:
                pass

    # Nuitka 参数
    args = [
        python_exe, '-m', 'nuitka',
        '--standalone',
        '--enable-plugin=pyqt5',
        '--windows-console-mode=attach',
        '--assume-yes-for-downloads',

        # 输出目录
        f'--output-dir={dist_base}',
        f'--output-filename={internal_name}.exe',

        # 包含资源文件
        '--include-data-dir=assets=assets',
        '--include-data-file=build_parameters.json=build_parameters.json',
        # cm_fast 包装器：运行时由启动器物化到真实磁盘（EVB 封包后虚拟文件对
        # 环境 python 不可见），再用环境 python 执行（见 services/plugin_service.py）
        '--include-data-file=services/_runner_scripts/cm_fast.py=cm_fast.py',

        # 排除不需要的 Qt 模块（减小体积）
        '--nofollow-import-to=PyQt5.QtQuick',
        '--nofollow-import-to=PyQt5.QtQml',
        '--nofollow-import-to=PyQt5.QtDesigner',
        '--nofollow-import-to=PyQt5.QtBluetooth',
        '--nofollow-import-to=PyQt5.QtLocation',
        '--nofollow-import-to=PyQt5.QtMultimedia',
        '--nofollow-import-to=PyQt5.QtMultimediaWidgets',
        '--nofollow-import-to=PyQt5.QtWebSockets',
        '--nofollow-import-to=PyQt5.QtSerialPort',
        '--nofollow-import-to=PyQt5.QtNfc',
        '--nofollow-import-to=PyQt5.QtSensors',
        '--nofollow-import-to=PyQt5.QtPositioning',
        '--nofollow-import-to=PyQt5.QtXmlPatterns',

        # 排除不需要的标准库
        '--nofollow-import-to=tkinter',
        '--nofollow-import-to=unittest',
        '--nofollow-import-to=test',
        '--nofollow-import-to=tests',

        # 包含必要的模块
        '--follow-import-to=core',
        '--follow-import-to=config',
        '--follow-import-to=utils',
        '--follow-import-to=ui',
        '--follow-import-to=ui_qt',
        '--follow-import-to=launcher',
        '--follow-import-to=services',
        '--follow-import-to=headless_app',

        # 图标
        '--windows-icon-from-ico=assets/rabbit.ico',

        # 公司/产品信息
        '--company-name=黎黎原上咩',
        '--product-name=ComfyUI启动器',
        '--file-description=ComfyUI Package Launcher',
        f'--file-version={params.get("version", "1.0.0").replace("v", "")}',
        f'--product-version={params.get("version", "1.0.0").replace("v", "")}',

        # 主脚本
        '__main__.py',
    ]

    print("\n[构建] 开始 Nuitka 编译...")

    try:
        result = subprocess.run(
            args,
            cwd=project_dir,
            env=os.environ.copy(),
        )

        if result.returncode != 0:
            print(f"\n[X] 构建失败，返回码: {result.returncode}")
            sys.exit(1)

        # 检查输出（Nuitka 实际输出目录基于脚本名）
        actual_dist_dir = os.path.join(dist_base, "__main__.dist")
        actual_exe = os.path.join(actual_dist_dir, f"{internal_name}.exe")

        if os.path.exists(actual_exe):
            if os.path.exists(dist_dir):
                try:
                    shutil.rmtree(dist_dir)
                except PermissionError:
                    print(f"[警告] 无法删除旧目录，将直接使用 Nuitka 输出目录")
                    dist_dir = actual_dist_dir
                    exe_path = actual_exe
            if dist_dir != actual_dist_dir:
                os.rename(actual_dist_dir, dist_dir)
                exe_path = os.path.join(dist_dir, f"{internal_name}.exe")

        if os.path.exists(exe_path):
            total_size = 0
            for root, dirs, files in os.walk(dist_dir):
                for f in files:
                    total_size += os.path.getsize(os.path.join(root, f))
            size_mb = total_size / (1024 * 1024)

            print("\n" + "=" * 60)
            print("[OK] Nuitka 构建成功！")
            print("=" * 60)
            print(f"[输出] 目录: {dist_dir}")
            print(f"[输出] EXE: {exe_path}")
            print(f"[体积] 总计: {size_mb:.1f} MB")
            print(f"\n[下一步] 使用 Enigma Virtual Box 打包 {output_name}.dist 目录")
            print(f"[提示] 内部 exe 已命名为 {internal_name}.exe，避免与外层同名冲突")
            print(f"[提示] Enigma 打包后的外层 exe 可以安全命名为 ComfyUI启动器.exe")
            print("=" * 60)
        else:
            print(f"\n[X] 未找到生成的 exe: {exe_path}")
            sys.exit(1)

    except Exception as e:
        print(f"\n[X] 构建异常: {e}")
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


def step_copy_cli_wrapper(dest_dir, project_dir):
    """把仓库根的 ComfyUI启动器-CLI.cmd 拷到 dest_dir。

    用于把 wrapper 同时放进：
    - dist_dir (Nuitka 输出目录，本地 dev tester 可以直接用)
    - release_subdir (最终 release 子目录)
    """
    src = os.path.join(project_dir, CLI_WRAPPER_NAME)
    if not os.path.exists(src):
        print(f"[警告] 找不到 wrapper 源: {src}（跳过）")
        return None
    dst = os.path.join(dest_dir, CLI_WRAPPER_NAME)
    shutil.copy2(src, dst)
    print(f"[wrapper] -> {dst}")
    return dst


def step_copy_release_docs(dest_dir, project_dir):
    """把 launcher 操作文档 (使用说明.md / AGENTS.md / cli.md) 拷到发布子目录。

    让 agent / 用户拿到 release 包后无需回仓库就能读到 CLI 介绍。
    缺失的源文件会跳过 + 警告，不让 build 失败。
    """
    copied = 0
    for src_rel, dst_rel in RELEASE_DOC_FILES:
        src = os.path.join(project_dir, src_rel)
        dst = os.path.join(dest_dir, dst_rel)
        if not os.path.exists(src):
            print(f"[docs] 跳过 (源不存在): {src}")
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        print(f"[docs] -> {dst}")
        copied += 1
    return copied


def generate_release_dirname(version, is_test):
    """生成 release 子目录名: ComfyUI启动器_v1.0.10_20260412_1033[_test]。

    内部文件用纯净名 (ComfyUI启动器.exe / ComfyUI启动器-CLI.cmd)，时间戳落在目录上。
    这样整合包发布后用户拿到 ComfyUI启动器.exe + ComfyUI启动器-CLI.cmd，
    wrapper 和 exe 永远配对，不会因为改名误用。
    """
    ver = version.lstrip('v') if version else '0.0.0'
    ts = time.strftime('%Y%m%d_%H%M', time.localtime())
    suffix = "_test" if is_test else ""
    return f"ComfyUI启动器_v{ver}_{ts}{suffix}"


def step_finalize_release(boxed_exe, version, is_test):
    """Step 3: 把 boxed_exe + wrapper 拷到 release/<带时间戳子目录>/

    最终结构：
        release/ComfyUI启动器_v1.0.10_20260412_1033/
            ComfyUI启动器.exe         <- 纯净名，不带时间戳
            ComfyUI启动器-CLI.cmd     <- 配套 wrapper
    """
    project_dir = get_project_dir()
    release_dir = os.path.join(project_dir, 'release')

    dirname = generate_release_dirname(version, is_test)
    sub_dir = os.path.join(release_dir, dirname)

    # 如果该路径已存在但类型不对（eg. 旧 build 留下的 .exe 单文件），挪开重建
    if os.path.exists(sub_dir) and not os.path.isdir(sub_dir):
        print(f"[清理] {sub_dir} 存在但不是目录，移动到 .bak")
        shutil.move(sub_dir, sub_dir + '.bak')
    os.makedirs(sub_dir, exist_ok=True)

    print(f"\n[3/3] 生成发布目录 {sub_dir}")

    # 1) ComfyUI启动器.exe （纯净名）
    exe_dest = os.path.join(sub_dir, EXE_NAME)
    shutil.copy2(boxed_exe, exe_dest)

    # 2) ComfyUI启动器-CLI.cmd （配套 wrapper）
    step_copy_cli_wrapper(sub_dir, project_dir)

    # 3) 操作文档（让 agent / 用户拿到 release 包就能读到 CLI 介绍）
    step_copy_release_docs(sub_dir, project_dir)

    return sub_dir


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

    # 3.5 让 dist_dir 也带上 wrapper（dev tester 直接在 dist 里也能跑 wrapper）
    if not args.evb_only:
        step_copy_cli_wrapper(dist_dir, project_dir)

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

    # 构建摘要。final_path 现在是目录，统计整个目录的总大小
    elapsed = time.time() - start_time
    total_bytes = sum(
        os.path.getsize(os.path.join(root, f))
        for root, _, files in os.walk(final_path)
        for f in files
    )
    size_mb = total_bytes / (1024 * 1024)

    print()
    print("=" * 60)
    print("  构建成功！")
    print("=" * 60)
    print(f"  版本:      {version}")
    print(f"  通道:      {channel}")
    print(f"  输出目录:  {os.path.relpath(final_path, project_dir)}")
    print(f"  目录大小:  {size_mb:.1f} MB")
    print(f"  耗时:      {format_duration(elapsed)}")
    print("=" * 60)


if __name__ == "__main__":
    main()