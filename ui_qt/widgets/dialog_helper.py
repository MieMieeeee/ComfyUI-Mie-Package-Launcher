
from PyQt5 import QtWidgets, QtCore
from ui_qt.widgets.custom_confirm_dialog import CustomConfirmDialog

class DialogHelper:
    """Helper class for showing custom styled dialogs"""
    
    @staticmethod
    def _get_theme_manager(parent):
        if parent is None:
            return None
        return getattr(parent, "theme_manager", None)

    @staticmethod
    def show_info(parent, title, content):
        """Show an information dialog with a single OK button"""
        dialog = CustomConfirmDialog(
            parent,
            title=title,
            content=content,
            buttons=[{"text": "确定", "role": "primary"}],
            default_index=0,
            theme_manager=DialogHelper._get_theme_manager(parent)
        )
        dialog.exec_()
        
    @staticmethod
    def show_warning(parent, title, content):
        """Show a warning dialog with a single OK button"""
        dialog = CustomConfirmDialog(
            parent,
            title=title,
            content=content,
            buttons=[{"text": "确定", "role": "primary"}],
            default_index=0,
            theme_manager=DialogHelper._get_theme_manager(parent)
        )
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
