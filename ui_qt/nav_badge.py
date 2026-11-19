"""Nav 按钮文字/徽标的幂等更新。

为什么需要：启动器里有一批**高频信号**驱动的按钮更新 —— 最典型的是日志页
每读到一行新日志就 emit 一次 "有新日志"，主窗口据此给「实时日志」按钮加
"*" 前缀。原来每次都 `btn.setText(...)`，而 setText 会触发 QSS 重新计算 +
重绘。日志多的时候（ComfyUI 的 tqdm 每秒几十行）这是**持续的 UI 线程开销**，
表现为「点别的页面要卡一下才响应」—— 点击事件排在重绘队列后面。

这里统一收口成「文字没变就不动」：信号频率不变（行为语义不变），但重复的
setText 被去掉 —— 从"每行一次重绘"降到"状态变化时一次重绘"。

独立成模块而不是塞进 ui_qt/qt_app.py：qt_app 在部分环境 import 就会段错误
（PyQt5/sip ABI 问题），独立模块才能被单测直接引用。
"""

__all__ = ["set_nav_text"]


def set_nav_text(btn, text: str) -> bool:
    """幂等设置 nav 按钮文字。返回 True 表示文字真的变了（做了 setText）。

    - btn 为 None 或读取/设置抛异常 → 返回 False（绝不因装饰性更新把调用方带崩）
    - 文字与当前相同 → 不 setText（省掉 QSS 重算 + 重绘）
    """
    try:
        if btn is None:
            return False
        current = btn.text()
        if current == text:
            return False
        btn.setText(text)
        return True
    except Exception:
        return False
