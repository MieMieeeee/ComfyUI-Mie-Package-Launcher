"""
ComfyUI启动器打包脚本
使用PyInstaller将启动器打包成独立的exe文件
"""

import PyInstaller.__main__
import os
import shutil

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
        '--hidden-import=tkinter',
        '--hidden-import=tkinter.ttk',
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
        '--windowed',  # 改回窗口模式
        '--add-data=version_manager.py;.',
        '--add-data=about_me.png;.',
        '--hidden-import=threading',
        '--hidden-import=json',
        '--hidden-import=pathlib',
        '--hidden-import=subprocess',
        '--hidden-import=webbrowser',
        '--hidden-import=tempfile',
        '--hidden-import=atexit',
        '--hidden-import=tkinter',
        '--hidden-import=tkinter.ttk',
        '--hidden-import=tkinter.messagebox',
        '--hidden-import=tkinter.filedialog',
        '--exclude-module=fcntl',
        '--exclude-module=posix',
        '--exclude-module=pwd',
        '--exclude-module=grp',
        '--exclude-module=_posixsubprocess',
        'comfyui_launcher_enhanced.py'
    ]
    
    # 检查图标文件是否存在
    icon_path = os.path.join(current_dir, 'icon.ico')
    if os.path.exists(icon_path):
        args.insert(-1, f'--icon={icon_path}')
    
    try:
        # 运行PyInstaller
        PyInstaller.__main__.run(args)
        
        # 检查是否成功生成exe文件
        exe_path = os.path.join(current_dir, 'dist', 'ComfyUI启动器.exe')
        if os.path.exists(exe_path):
            # 复制到项目根目录
            root_exe_path = os.path.join(current_dir, '..', 'ComfyUI启动器.exe')
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