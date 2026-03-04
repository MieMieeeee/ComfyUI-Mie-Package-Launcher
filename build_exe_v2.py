"""
ComfyUI启动器打包脚本 V2（Nuitka 版本）
使用 Nuitka 编译，体积更小、性能更好
"""

import os
import sys
import json
import time
import shutil
import subprocess


def get_project_dir():
    """获取项目根目录"""
    return os.path.dirname(os.path.abspath(__file__))


def find_python_exe():
    """查找虚拟环境中的 Python"""
    project_dir = get_project_dir()
    venv_python = os.path.join(project_dir, '.venv', 'Scripts', 'python.exe')
    if os.path.exists(venv_python):
        return venv_python
    return sys.executable


def update_build_parameters():
    """更新构建参数"""
    project_dir = get_project_dir()
    bp_path = os.path.join(project_dir, 'build_parameters.json')
    bp_path_launcher = os.path.join(project_dir, 'launcher', 'build_parameters.json')

    params = {}
    try:
        if os.path.exists(bp_path):
            with open(bp_path, 'r', encoding='utf-8') as f:
                params = json.load(f) or {}
    except:
        params = {}

    now = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
    ver = params.get('version', 'v1.0.7')
    params['version'] = ver
    params['suffix'] = f' · 构建于 {now}'
    params['mode'] = 'nuitka_release'
    params['built_at'] = now
    params['builder'] = '黎黎原上咩'

    try:
        with open(bp_path, 'w', encoding='utf-8') as f:
            json.dump(params, f, ensure_ascii=False, indent=2)
        os.makedirs(os.path.dirname(bp_path_launcher), exist_ok=True)
        with open(bp_path_launcher, 'w', encoding='utf-8') as f:
            json.dump(params, f, ensure_ascii=False, indent=2)
        print(f"[版本] 参数已写入: {bp_path}")
    except Exception as e:
        print(f"[版本] 写入忽略: {e}")

    return params


def build_nuitka():
    """使用 Nuitka 构建 standalone 版本"""
    print("=" * 60)
    print("ComfyUI启动器 Nuitka 构建脚本 V2")
    print("=" * 60)

    project_dir = get_project_dir()
    python_exe = find_python_exe()

    print(f"[环境] Python: {python_exe}")
    print(f"[环境] 项目目录: {project_dir}")

    # 更新版本参数
    params = update_build_parameters()
    print(f"[版本] {params.get('version', 'unknown')}")

    # 输出配置
    output_name = "ComfyUI启动器"
    dist_base = os.path.join(project_dir, "dist")
    dist_dir = os.path.join(dist_base, f"{output_name}.dist")
    exe_path = os.path.join(dist_dir, f"{output_name}.exe")

    # 如果已存在则删除旧的构建目录
    if os.path.exists(dist_dir):
        print(f"[清理] 删除旧目录: {dist_dir}")
        try:
            shutil.rmtree(dist_dir)
        except PermissionError:
            print(f"[警告] 目录被占用，无法删除。请先关闭正在运行的程序。")
            print(f"[警告] 将尝试覆盖构建...")
            # 尝试删除内部的文件
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
        '--windows-console-mode=disable',
        '--assume-yes-for-downloads',

        # 输出目录
        f'--output-dir={dist_base}',
        f'--output-filename={output_name}.exe',

        # 包含资源文件
        '--include-data-dir=assets=assets',
        '--include-data-file=build_parameters.json=build_parameters.json',

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

        # 图标
        '--windows-icon-from-ico=assets/rabbit.ico',

        # 公司/产品信息
        '--company-name=黎黎原上咩',
        '--product-name=ComfyUI启动器',
        '--file-description=ComfyUI Package Launcher',
        f'--file-version={params.get("version", "1.0.0").replace("v", "")}',
        f'--product-version={params.get("version", "1.0.0").replace("v", "")}',

        # 主脚本
        'comfyui_launcher_pyqt.py',
    ]

    print("\n[构建] 开始 Nuitka 编译...")

    try:
        result = subprocess.run(
            args,
            cwd=project_dir,
            env=os.environ.copy(),
        )

        if result.returncode != 0:
            print(f"\n❌ 构建失败，返回码: {result.returncode}")
            sys.exit(1)

        # 检查输出（Nuitka 实际输出目录基于脚本名）
        actual_dist_dir = os.path.join(dist_base, "comfyui_launcher_pyqt.dist")
        actual_exe = os.path.join(actual_dist_dir, f"{output_name}.exe")

        if os.path.exists(actual_exe):
            # 重命名目录为目标名称
            if os.path.exists(dist_dir):
                try:
                    shutil.rmtree(dist_dir)
                except PermissionError:
                    print(f"[警告] 无法删除旧目录，将直接使用 Nuitka 输出目录")
                    dist_dir = actual_dist_dir
                    exe_path = actual_exe
            if dist_dir != actual_dist_dir:
                os.rename(actual_dist_dir, dist_dir)
                exe_path = os.path.join(dist_dir, f"{output_name}.exe")

        if os.path.exists(exe_path):
            # 计算目录大小
            total_size = 0
            for root, dirs, files in os.walk(dist_dir):
                for f in files:
                    total_size += os.path.getsize(os.path.join(root, f))
            size_mb = total_size / (1024 * 1024)

            print("\n" + "=" * 60)
            print("✅ Nuitka 构建成功！")
            print("=" * 60)
            print(f"[输出] 目录: {dist_dir}")
            print(f"[输出] EXE: {exe_path}")
            print(f"[体积] 总计: {size_mb:.1f} MB")
            print(f"\n[下一步] 使用 Enigma Virtual Box 打包 {output_name}.dist 目录")
            print("=" * 60)
        else:
            print(f"\n❌ 未找到生成的 exe: {exe_path}")
            sys.exit(1)

    except Exception as e:
        print(f"\n❌ 构建异常: {e}")
        sys.exit(1)


if __name__ == "__main__":
    build_nuitka()
