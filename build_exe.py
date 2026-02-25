"""
ComfyUI启动器打包脚本（PyQt5 + Enigma 专用优化版）
"""

import PyInstaller.__main__
import os
import glob
import shutil
import json
import time
import site   # 新增：用于自动查找 PyQt5 路径

def find_venv_python_dll():
    """自动查找 .venv / venv 中的 Python DLL (python3.dll 或 python312.dll)"""
    project_dir = os.path.dirname(os.path.abspath(__file__))
    
    possible_venv_dirs = [
        os.path.join(project_dir, '.venv'),
        os.path.join(project_dir, 'venv'),
        os.path.join(project_dir, 'env'),
    ]
    
    for venv_dir in possible_venv_dirs:
        if not os.path.exists(venv_dir):
            continue
        
        # venv 激活后 python.exe 在 Scripts\python.exe
        python_exe = os.path.join(venv_dir, 'Scripts', 'python.exe')
        if not os.path.exists(python_exe):
            continue
        
        # venv 的 python.exe 是链接到系统 Python 的，所以找 python.exe 的真实路径
        try:
            real_python_exe = os.readlink(python_exe) if os.path.islink(python_exe) else python_exe
            python_root = os.path.dirname(real_python_exe)
        except:
            # 如果不是 symlink，直接用 Scripts 上级
            python_root = os.path.dirname(os.path.dirname(python_exe))
        
        # 常见 DLL 位置：python_root 下或 python_root\DLLs
        possible_dll_patterns = [
            os.path.join(python_root, 'python3*.dll'),          # python3.dll
            os.path.join(python_root, 'DLLs', 'python3*.dll'),
            os.path.join(python_root, '..', 'python3*.dll'),    # 有时在上级
        ]
        
        for pattern in possible_dll_patterns:
            dll_files = glob.glob(pattern)
            if dll_files:
                return dll_files[0]  # 返回第一个找到的
        
        # 备选：从 site-packages 向上找（但很少见）
        for base in site.getsitepackages():
            dll = os.path.join(base, '..', '..', 'python3.dll')
            if os.path.exists(dll):
                return dll
    
    # 如果 venv 没找到，直接用当前解释器路径（fallback）
    current_python_root = os.path.dirname(sys.executable)
    fallback_dll = os.path.join(current_python_root, 'python3.dll')
    if os.path.exists(fallback_dll):
        return fallback_dll
    
    return None

def find_pyqt5_plugins():
    """自动查找 PyQt5 plugins 目录（确保 qwindows.dll 被正确收集）"""
    for base in site.getsitepackages() + [site.getusersitepackages()]:
        for variant in ['PyQt5/Qt/plugins', 'PyQt5/Qt5/plugins', 'PyQt5/plugins']:
            p = os.path.join(base, variant)
            if os.path.exists(os.path.join(p, 'platforms', 'qwindows.dll')):
                return p
    return None


def build_exe():
    """构建完整版 onedir（供 Enigma 封装）"""
    print("开始构建 ComfyUI启动器（onedir 模式）...")
    
    current_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 自动查找 PyQt5 plugins（关键修复）
    pyqt_plugins_path = find_pyqt5_plugins()
    if pyqt_plugins_path:
        print(f"[PyQt5] 自动检测到 plugins 路径: {pyqt_plugins_path}")

    # ★ 新增：查找并准备添加 python3.dll
    python_dll_path = find_venv_python_dll()
    if python_dll_path:
        print(f"[DLL Fix] 找到 python DLL: {python_dll_path}")
    else:
        print("[DLL Fix] 未找到 python3.dll / python312.dll，请手动检查 Python 安装目录！")
    
    args = [
        '--name=ComfyUI启动器',
        '--onedir',
        '--windowed',
        '--noconfirm',        # 自动覆盖不询问
        '--clean',
        '--noupx',            # 必须！防止 UPX 破坏 Qt DLL
        '--add-data=assets/about_me.png;assets',
        '--add-data=assets/comfyui.png;assets',
        '--add-data=assets/rabbit.png;assets',
        '--add-data=assets/rabbit.ico;assets',
        '--add-data=build_parameters.json;.',
        
        # PyQt5 加强收集
        '--hidden-import=PyQt5',
        '--hidden-import=PyQt5.QtWidgets',
        '--hidden-import=PyQt5.QtCore',
        '--hidden-import=PyQt5.QtGui',
        '--hidden-import=PyQt5.sip',
        '--hidden-import=PyQt5.Qt',
        '--hidden-import=PyQt5.Qt5',   # 部分安装有这个
        
        # 你的其他 hidden-import
        '--hidden-import=core.process_manager',
        '--hidden-import=config.manager',
        '--hidden-import=utils.logging',
        '--hidden-import=utils.paths',
        '--hidden-import=utils.net',
        '--hidden-import=utils.pip',
        '--hidden-import=utils.common',
        '--hidden-import=ui.assets_helper',
        '--hidden-import=ui_qt.qt_app',
        
        '--exclude-module=fcntl',
        '--exclude-module=posix',
        '--exclude-module=pwd',
        '--exclude-module=grp',
        '--exclude-module=_posixsubprocess',
    ]

    # 动态添加 PyQt5 plugins
    if pyqt_plugins_path:
        args.append(f'--add-data={pyqt_plugins_path};PyQt5/Qt/plugins')
    
    # ★ 新增：动态添加 python DLL 到 _internal
    if python_dll_path:
        args.append(f'--add-binary={python_dll_path};_internal')

    args.append('comfyui_launcher_pyqt.py')
    
    # 图标处理（保持原逻辑）
    if os.environ.get('SKIP_ICON') != '1':
        def _valid_ico(path: str) -> bool:
            try:
                if not os.path.exists(path) or os.path.getsize(path) <= 0:
                    return False
                with open(path, 'rb') as f:
                    header = f.read(4)
                    return header in (b'\x00\x00\x01\x00', b'\x00\x00\x02\x00')
            except:
                return False

        candidates = [
            os.path.join(current_dir, 'assets', 'rabbit.ico'),
            os.path.join(current_dir, 'rabbit.ico'),
        ]
        for ico in candidates:
            if _valid_ico(ico):
                args.insert(-1, f'--icon={ico}')
                break
    
    # 版本信息写入（保持原逻辑）
    bp_path = os.path.join(current_dir, 'build_parameters.json')
    bp_path_launcher = os.path.join(current_dir, 'launcher', 'build_parameters.json')
    params = {}
    try:
        if os.path.exists(bp_path):
            with open(bp_path, 'r', encoding='utf-8') as f:
                params = json.load(f) or {}
    except:
        params = {}
    
    now = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
    ver = params.get('version', 'v1.0.2')
    params['version'] = ver
    params['suffix'] = f' · 构建 {now}'
    params['mode'] = 'release'
    params['built_at'] = now
    
    try:
        with open(bp_path, 'w', encoding='utf-8') as f:
            json.dump(params, f, ensure_ascii=False, indent=2)
        os.makedirs(os.path.dirname(bp_path_launcher), exist_ok=True)
        with open(bp_path_launcher, 'w', encoding='utf-8') as f:
            json.dump(params, f, ensure_ascii=False, indent=2)
        print(f"版本参数已写入: {bp_path} 和 launcher 目录")
    except Exception as e:
        print(f"版本写入忽略: {e}")
    
    # 执行打包
    try:
        print("PyInstaller args:", args)  # 调试：打印参数看是否加了 DLL
        PyInstaller.__main__.run(args)
        
        # onedir 正确路径
        exe_path = os.path.join(current_dir, 'dist', 'ComfyUI启动器', 'ComfyUI启动器.exe')
        
        if os.path.exists(exe_path):
            print(f"\n✅ 打包成功！")
            print(f"onedir 目录: {os.path.join(current_dir, 'dist', 'ComfyUI启动器')}")
            print(f"主 exe: {exe_path}")
            print("\n下一步：用 Enigma Virtual Box 封装整个 dist\\ComfyUI启动器 文件夹")
        else:
            print("❌ 未找到生成的 exe 文件")
            
    except Exception as e:
        print(f"❌ 打包失败: {e}")
        return False
    
    return True

if __name__ == "__main__":
    import sys
    choice = sys.argv[1] if len(sys.argv) > 1 else "1"
    
    print(f"构建模式: {'完整版' if choice == '1' else '简化测试版'}")
    
    if choice == "2":
        build_simple_test()
    else:
        build_exe()
        
    print("构建流程结束！")