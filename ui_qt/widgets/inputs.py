"""
输入框组件
包含样式化的输入框、下拉框等
"""

from PyQt5 import QtWidgets, QtCore
from ui_qt.theme_styles import ThemeStyles


class StyledLineEdit(QtWidgets.QLineEdit):
    """样式化输入框"""

    def __init__(self, text: str, theme_styles: ThemeStyles, parent=None, readonly=False):
        super().__init__(text, parent)
        self.theme_styles = theme_styles
        self.readonly = readonly
        self._apply_style()

    def _apply_style(self):
        if self.readonly:
            self.setStyleSheet(f"""
                QLineEdit {{
                    background-color: {self.theme_styles.c.get('input_readonly_bg')};
                    color: {self.theme_styles.c.get('input_readonly_text')};
                    border: 1px solid {self.theme_styles.c.get('input_border')};
                    border-radius: 6px;
                    padding: 5px 10px;
                    font: 10pt "Microsoft YaHei UI";
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QLineEdit {{
                    background-color: {self.theme_styles.c.get('input_bg')};
                    color: {self.theme_styles.c.get('input_text')};
                    border: 1px solid {self.theme_styles.c.get('input_border')};
                    border-radius: 6px;
                    padding: 5px 10px;
                    font: 10pt "Microsoft YaHei UI";
                    selection-background-color: {self.theme_styles.c.get('accent')};
                }}
                QLineEdit:hover {{
                    background-color: {self.theme_styles.c.get('group_bg')};
                    border: 1px solid {self.theme_styles.c.get('label_muted')};
                }}
                QLineEdit:focus {{
                    background-color: {self.theme_styles.c.get('input_bg')};
                    border: 2px solid {self.theme_styles.c.get('accent')};
                    padding: 4px 9px;
                }}
            """)

    def update_theme(self, theme_styles: ThemeStyles):
        """更新主题样式"""
        self.theme_styles = theme_styles
        self._apply_style()


class ReadOnlyField(QtWidgets.QLineEdit):
    """只读字段"""

    def __init__(self, text: str, theme_styles: ThemeStyles, parent=None):
        super().__init__(text, parent)
        self.theme_styles = theme_styles
        self.setReadOnly(True)
        self._apply_style()

    def _apply_style(self):
        self.setStyleSheet(f"""
            QLineEdit {{
                background-color: {self.theme_styles.c.get('input_readonly_bg')};
                color: {self.theme_styles.c.get('input_readonly_text')};
                border: 1px solid {self.theme_styles.c.get('input_border')};
                border-radius: 6px;
                padding: 5px 10px;
                font: 10pt "Microsoft YaHei UI";
            }}
        """)

    def update_theme(self, theme_styles: ThemeStyles):
        """更新主题样式"""
        self.theme_styles = theme_styles
        self._apply_style()


class NoWheelComboBox(QtWidgets.QComboBox):
    """禁用滚轮的下拉框"""

    def __init__(self, theme_styles: ThemeStyles, parent=None):
        super().__init__(parent)
        self.theme_styles = theme_styles
        self._apply_style()

    def wheelEvent(self, event):
        """禁用鼠标滚轮切换"""
        event.ignore()

    def _apply_style(self):
        self.setStyleSheet(f"""
            QComboBox {{
                background-color: {self.theme_styles.c.get('input_bg')};
                color: {self.theme_styles.c.get('input_text')};
                border: 1px solid {self.theme_styles.c.get('input_border')};
                border-radius: 6px;
                padding: 5px 10px;
                font: 10pt "Microsoft YaHei UI";
            }}
            QComboBox::drop-down {{
                border: none;
                background-color: {self.theme_styles.c.get('input_bg')};
                width: 20px;
            }}
            QComboBox::down-arrow {{
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid {self.theme_styles.c.get('label_muted')};
                width: 0;
                height: 0;
                margin-right: 8px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {self.theme_styles.c.get('input_bg')};
                color: {self.theme_styles.c.get('input_text')};
                border: 1px solid {self.theme_styles.c.get('input_border')};
                selection-background-color: {self.theme_styles.c.get('input_border')};
                selection-color: #FFFFFF;
                font: 10pt "Microsoft YaHei UI";
                outline: none;
            }}
        """)

    def update_theme(self, theme_styles: ThemeStyles):
        """更新主题样式"""
        self.theme_styles = theme_styles
        self._apply_style()


class StyledComboBox(QtWidgets.QComboBox):
    """样式化的下拉框（默认允许滚轮）"""

    def __init__(self, theme_styles: ThemeStyles, parent=None):
        super().__init__(parent)
        self.theme_styles = theme_styles
        self._apply_style()

    def _apply_style(self):
        """应用基本样式（使用 NoWheelComboBox 样式）"""
        self.setStyleSheet(f"""
            QComboBox {{
                background-color: {self.theme_styles.c.get('input_bg')};
                color: {self.theme_styles.c.get('input_text')};
                border: 1px solid {self.theme_styles.c.get('input_border')};
                border-radius: 6px;
                padding: 5px 10px;
                font: 10pt "Microsoft YaHei UI";
            }}
            QComboBox::drop-down {{
                border: none;
                background-color: {self.theme_styles.c.get('input_bg')};
                width: 20px;
            }}
            QComboBox::down-arrow {{
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid {self.theme_styles.c.get('label_muted')};
                width: 0;
                height: 0;
                margin-right: 8px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {self.theme_styles.c.get('input_bg')};
                color: {self.theme_styles.c.get('input_text')};
                border: 1px solid {self.theme_styles.c.get('input_border')};
                selection-background-color: {self.theme_styles.c.get('input_border')};
                selection-color: #FFFFFF;
                font: 10pt "Microsoft YaHei UI";
                outline: none;
            }}
        """)

    def update_theme(self, theme_styles: ThemeStyles):
        """更新主题样式"""
        self.theme_styles = theme_styles
        self._apply_style()
