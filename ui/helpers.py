from __future__ import annotations
from typing import Any

# UI 辅助函数：路径文本截断与宽度测算

def truncate_middle(text: str, max_chars: int) -> str:
    try:
        if max_chars <= 0:
            return ""
        if len(text) <= max_chars:
            return text
        if max_chars <= 3:
            return text[:max_chars]
        keep = max_chars - 1  # 预留一个位置给省略号“…”
        head = keep // 2
        tail = keep - head
        return text[:head] + "…" + text[-tail:]
    except Exception:
        return text


def compute_elided_path_text(app: Any) -> str:
    """根据可用宽度将路径文本进行中间截断，避免顶栏按钮被挤出。
    读取 app 的相关控件与字体信息，返回适合显示的截断文本。
    """
    try:
        full = getattr(app, "_path_full_text", None) or (
            app.path_value_var.get() if hasattr(app, "path_value_var") else ""
        )
        # 计算可用于显示路径的像素宽度：顶栏总宽度 - 标题宽度 - 按钮宽度 - 余量
        top_w = app._path_top_bar.winfo_width() if hasattr(app, "_path_top_bar") else 0
        title_w = app.path_label_title.winfo_width() if hasattr(app, "path_label_title") else 0
        btn_w = app.reset_root_btn.winfo_width() if hasattr(app, "reset_root_btn") else 0
        # 预留边距与间距（标题右侧8px，按钮左侧12px等），综合设置为 40px
        available_px = max(60, top_w - title_w - btn_w - 40)
        # 根据字体估算最大字符数（使用“M”作宽度参考）
        font_obj = getattr(app, "_path_label_font", None)
        if font_obj:
            try:
                m_w = max(7, int(font_obj.measure("M")))
            except Exception:
                m_w = 9
        else:
            m_w = 9
        max_chars = max(10, available_px // m_w)
        return truncate_middle(full, max_chars)
    except Exception:
        return full if 'full' in locals() else ""