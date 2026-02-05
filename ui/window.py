import os
import time
import tkinter as tk  # 建议显式导入以使用类型提示或常量
from ui import assets_helper as ASSETS
from ui import theme as THEME
from ui.constants import COLORS

def setup_window(app):
    try:
        # 1. 基础设置
        app.root.title("ComfyUI启动器 - 黎黎原上咩")
        
        # 2. 窗口尺寸与位置计算 (核心修改部分)
        screen_width = app.root.winfo_screenwidth()
        screen_height = app.root.winfo_screenheight()

        # 设定目标宽度：默认1250，但不能超过屏幕宽度的90%
        target_width = min(1250, int(screen_width * 0.95))
        
        # 设定目标高度：默认1020，但不能超过屏幕高度的85% (留出任务栏和标题栏空间)
        # 原逻辑减去60太极限，建议留出至少100-150px的余量，或者使用比例
        target_height = min(1020, int(screen_height * 0.88))
        
        # 计算居中位置 (x, y)
        pos_x = (screen_width - target_width) // 2
        pos_y = (screen_height - target_height) // 2
        
        # 防止 y 轴过高 (有些用户喜欢偏上一点，避免太靠下被遮挡)
        pos_y = max(0, pos_y - 20) 

        # 应用尺寸和位置: 格式 "WxH+X+Y"
        app.root.geometry(f"{target_width}x{target_height}+{pos_x}+{pos_y}")
        app.root.minsize(1100, 700)

        # 3. Windows 任务栏图标分组 ID
        if os.name == 'nt':
            try:
                import ctypes
                # 这一步是为了让任务栏图标独立显示，不与python默认图标混淆
                myappid = 'comfyui.launcher.lili.1.0' 
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
            except Exception:
                pass # 非关键功能失败可以忽略

        # 4. 图标与主题设置
        # 这里的 try-except 可以保留，防止因为资源文件缺失导致崩溃
        try:
            ASSETS.apply_window_icons(app.root, getattr(app, 'logger', None))
        except Exception as e:
            if getattr(app, 'logger', None):
                app.logger.warning(f"应用图标失败: {e}")

        # 初始化样式
        app.style = THEME.create_style(logger=getattr(app, 'logger', None))
        if app.style:
            THEME.apply_theme(app.style, logger=getattr(app, 'logger', None))
            # 隐藏 Notebook 的 Tab 栏（如果需要的话）
            try:
                app.style.layout('Hidden.TNotebook.Tab', [])
            except:
                pass

        # 设置背景色
        bg_color = COLORS.get("BG", "#FFFFFF")
        app.root.configure(bg=bg_color)
        
        # 字体与样式配置
        THEME.configure_default_font(app.root, logger=getattr(app, 'logger', None))
        THEME.configure_styles(app.style, COLORS, logger=getattr(app, 'logger', None))

        # 5. 窗口调整监听 (Debounce 逻辑)
        # 将复杂的嵌套 try-except 简化
        def _on_cfg(event):
            # 过滤掉非 root 窗口的事件（组件内部的 resize 也会触发 configure，但这通常不需要处理）
            if event.widget != app.root:
                return
            
            w, h = event.width, event.height
            
            # 检查是否有变化
            last = getattr(app, '_last_size', None)
            if last != (w, h):
                app._last_size = (w, h)
                app._last_resize_ts = time.perf_counter()
                app._is_resizing = True
                
                # 取消之前的 timer
                tid = getattr(app, '_resizing_reset_timer', None)
                if tid:
                    app.root.after_cancel(tid)
                
                # 设置新的 timer (120ms 后重置状态)
                app._resizing_reset_timer = app.root.after(120, lambda: setattr(app, '_is_resizing', False))

        app.root.bind("<Configure>", _on_cfg)

    except Exception as e:
        # 捕获 setup_window 自身的致命错误
        try:
            if getattr(app, 'logger', None):
                app.logger.exception(f"setup_window 阶段发生严重异常: {e}")
            else:
                print(f"Error in setup_window: {e}")
        except:
            pass