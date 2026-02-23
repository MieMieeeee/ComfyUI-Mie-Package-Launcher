"""
表格组件
包含样式化的表格
"""

from PyQt5 import QtWidgets, QtGui
from ui_qt.theme_styles import ThemeStyles


class StyledTableWidget(QtWidgets.QTableWidget):
    """样式化的表格组件"""

    def __init__(self, theme_styles: ThemeStyles, parent=None):
        super().__init__(parent)
        self.theme_styles = theme_styles
        self._apply_style()
        self._setup_common_properties()

    def _apply_style(self):
        self.setStyleSheet(self.theme_styles.table_style())

    def _setup_common_properties(self):
        """设置通用表格属性"""
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.setShowGrid(False)
        self.setAlternatingRowColors(True)
        self.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)

    def update_theme(self, theme_styles: ThemeStyles):
        """更新主题样式"""
        self.theme_styles = theme_styles
        self._apply_style()

    def set_color_for_item(self, row: int, col: int, color: str):
        """设置特定单元格的颜色"""
        item = self.item(row, col)
        if item:
            item.setForeground(QtGui.QBrush(QtGui.QColor(color)))

    def set_font_for_item(self, row: int, col: int, bold: bool = False):
        """设置特定单元格的字体"""
        item = self.item(row, col)
        if item:
            font = item.font()
            font.setBold(bold)
            item.setFont(font)

    def add_data_row(self, data: list, commit_color: str = None):
        """添加一行数据"""
        row = self.rowCount()
        self.insertRow(row)

        for col, text in enumerate(data):
            item = QtWidgets.QTableWidgetItem(str(text))
            self.setItem(row, col, item)

        # 设置提交哈希列的特殊颜色（第一列）
        if len(data) > 0 and commit_color:
            self.set_color_for_item(row, 0, commit_color)
