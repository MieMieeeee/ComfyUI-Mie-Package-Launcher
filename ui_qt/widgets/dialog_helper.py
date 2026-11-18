
from PyQt5 import QtWidgets, QtCore
from ui_qt.widgets.custom_confirm_dialog import CustomConfirmDialog
from ui_qt.widgets.cmcli_error_dialog import CmCliErrorDialog

class DialogHelper:
    """Helper class for showing custom styled dialogs"""
    
    @staticmethod
    def _get_theme_manager(parent):
        if parent is None:
            return None
        return getattr(parent, "theme_manager", None)

    @staticmethod
    def show_info(parent, title, content, min_width=None):
        """Show an information dialog with a single OK button"""
        dialog_kwargs = {
            "parent": parent,
            "title": title,
            "content": content,
            "buttons": [{"text": "确定", "role": "primary"}],
            "default_index": 0,
            "theme_manager": DialogHelper._get_theme_manager(parent),
        }
        if min_width is not None:
            dialog_kwargs["min_width"] = min_width
        dialog = CustomConfirmDialog(**dialog_kwargs)
        dialog.exec_()
        
    @staticmethod
    def show_warning(parent, title, content, min_width=None):
        """Show a warning dialog with a single OK button"""
        dialog_kwargs = {
            "parent": parent,
            "title": title,
            "content": content,
            "buttons": [{"text": "确定", "role": "primary"}],
            "default_index": 0,
            "theme_manager": DialogHelper._get_theme_manager(parent),
        }
        if min_width is not None:
            dialog_kwargs["min_width"] = min_width
        dialog = CustomConfirmDialog(**dialog_kwargs)
        dialog.exec_()
        
    @staticmethod
    def show_error(parent, title, content):
        """Show an error dialog with a single Close button"""
        dialog = CustomConfirmDialog(
            parent,
            title=title,
            content=content,
            buttons=[{"text": "关闭", "role": "destructive"}],
            default_index=0,
            theme_manager=DialogHelper._get_theme_manager(parent)
        )
        dialog.exec_()

    @staticmethod
    def show_error_with_detail(parent, title, content, detail=""):
        """Show an error dialog that also shows the raw tool output (cm-cli 等).

        detail 为空时退化成普通 show_error。detail 非空时弹 CmCliErrorDialog：
        正文 + 只读原始输出框 + 「复制详情」按钮（issue #111：失败原因原本
        只有一句「退出码 1」，用户/开发者都看不到真正报错）。
        """
        detail = (detail or "").strip()
        if not detail:
            DialogHelper.show_error(parent, title, content)
            return
        dialog = CmCliErrorDialog(
            parent,
            title=title,
            content=content,
            detail=detail,
            theme_manager=DialogHelper._get_theme_manager(parent)
        )
        dialog.exec_()

    @staticmethod
    def show_confirmation(parent, title, content, yes_text="是", no_text="否", destructive=False):
        """
        Show a confirmation dialog with Yes/No buttons
        Returns True if Yes is clicked, False otherwise
        """
        dialog = CustomConfirmDialog(
            parent,
            title=title,
            content=content,
            buttons=[
                {"text": no_text, "role": "normal"},
                {"text": yes_text, "role": "destructive" if destructive else "primary"}
            ],
            default_index=1,
            theme_manager=DialogHelper._get_theme_manager(parent)
        )
        return dialog.exec_() == QtWidgets.QDialog.Accepted and dialog.get_result() == 1
