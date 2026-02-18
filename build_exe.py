"""
ComfyUI启动器打包脚本
使用PyInstaller将启动器打包成独立的exe文件
"""

import PyInstaller.__main__
import os
import shutil
import json
import time

def build_simple_test():
    """构建简化测试exe文件"""
    print("开始构建简化测试exe文件...")
    
    # 获取当前目录
    current_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 构建参数
    args = [
        '--name=测试启动器',
        '--onefile',
        '--console',
        '--debug=all',
        'test_simple.py'
    ]
    
    try:
        # 运行PyInstaller
        PyInstaller.__main__.run(args)
        
        # 检查是否成功生成exe文件
        exe_path = os.path.join(current_dir, '..', 'dist', '测试启动器.exe')
        if os.path.exists(exe_path):
            print(f"\n简化测试exe打包完成!")
            print(f"exe文件位置: {exe_path}")
            print("\n✅ 简化测试打包成功!")
        else:
            print("❌ 简化测试打包失败: 未找到生成的exe文件")
            
    except Exception as e:
        print(f"❌ 简化测试打包失败: {e}")

def build_exe():
    """构建exe文件"""
    print("开始构建exe文件...")
    
    # 获取当前目录
    current_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 构建参数
    args = [
        '--name=ComfyUI启动器',
        '--onefile',
        '--windowed',
        '--add-data=assets/about_me.png;assets',
        '--add-data=assets/comfyui.png;assets',
        '--add-data=assets/rabbit.png;assets',
        '--add-data=assets/rabbit.ico;assets',
        '--add-data=build_parameters.json;.',
        '--hidden-import=threading',
        '--hidden-import=json',
        '--hidden-import=pathlib',
        '--hidden-import=subprocess',
        '--hidden-import=webbrowser',
        '--hidden-import=tempfile',
        '--hidden-import=atexit',
        '--hidden-import=PyQt5',
        '--hidden-import=PyQt5.QtWidgets',
        '--hidden-import=PyQt5.QtCore',
        '--hidden-import=PyQt5.QtGui',
        # 新结构的显式隐藏导入，确保打包准确包含子模块
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
        'comfyui_launcher_pyqt.py'
    ]
    
    # 检查图标文件是否存在
    # 如果设置了环境变量 SKIP_ICON=1，则跳过图标嵌入（用于规避异常）
    if os.environ.get('SKIP_ICON') == '1':
        pass
    else:
        # 选择有效的 ico 文件作为图标（校验 ICO 头部以避免 PyInstaller 读取错误）
        def _valid_ico(path: str) -> bool:
            try:
                if not os.path.exists(path):
                    return False
                if os.path.getsize(path) <= 0:
                    return False
                with open(path, 'rb') as f:
                    header = f.read(4)
                    # ICO: 00 00 01 00 或 CUR: 00 00 02 00
                    return header in (b'\x00\x00\x01\x00', b'\x00\x00\x02\x00')
            except Exception:
                return False

        candidates = [
            os.path.join(current_dir, 'assets', 'rabbit.ico'),
            os.path.join(current_dir, 'rabbit.ico'),
        ]
        for ico in candidates:
            if _valid_ico(ico):
                args.insert(-1, f'--icon={ico}')
                break
    
    try:
        bp_path = os.path.join(current_dir, 'build_parameters.json')
        bp_path_launcher = os.path.join(current_dir, 'launcher', 'build_parameters.json')
        params = {}
        try:
            if os.path.exists(bp_path):
                with open(bp_path, 'r', encoding='utf-8') as f:
                    params = json.load(f) or {}
        except Exception:
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
            try:
                os.makedirs(os.path.dirname(bp_path_launcher), exist_ok=True)
                with open(bp_path_launcher, 'w', encoding='utf-8') as f:
                    json.dump(params, f, ensure_ascii=False, indent=2)
                print(f"版本参数写入: {bp_path} 以及 {bp_path_launcher}")
            except Exception:
                print(f"版本参数写入: {bp_path}（launcher 目录写入失败，忽略）")
        except Exception:
            pass
        # 运行PyInstaller
        PyInstaller.__main__.run(args)
        
        # 检查是否成功生成exe文件
        exe_path = os.path.join(current_dir, 'dist', 'ComfyUI启动器.exe')
        if os.path.exists(exe_path):
            # 复制到项目根目录
            root_exe_path = os.path.join(current_dir, 'ComfyUI启动器.exe')
            shutil.copy2(exe_path, root_exe_path)
            
            print(f"\n打包完成!")
            print(f"exe文件位置: {exe_path}")
            print(f"已复制到项目根目录: {root_exe_path}")
            print("\n✅ 打包成功!")
            print("现在可以使用 ComfyUI启动器.exe 来启动ComfyUI了")
        else:
            print("❌ 打包失败: 未找到生成的exe文件")
            
    except Exception as e:
        print(f"❌ 打包失败: {e}")
        return False
    
    return True

if __name__ == "__main__":
    import sys
    
    # 检查命令行参数
    if len(sys.argv) > 1:
        choice = sys.argv[1]
    else:
        # 默认构建完整版启动器
        choice = "1"
    
    print(f"构建选择: {'完整版启动器' if choice == '1' else '简化测试版'}")
    
    if choice == "2":
        build_simple_test()
    else:
        build_exe()
        
    print("构建完成!")
