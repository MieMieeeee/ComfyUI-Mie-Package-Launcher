"""实时日志查看器:日志解析、进度折叠、文件 tail。"""
import re
import threading
from pathlib import Path
from typing import Callable, List, Tuple


_TIMESTAMP_RE = re.compile(
    r"^\[?(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:[.,]\d+)?)\]? (.*)$"
)


def parse_log_entry(line: str) -> Tuple[str, str]:
    """从一行日志里抽出 (timestamp, body)。

    Supports:
    - YYYY-MM-DD HH:MM:SS,fff body  (Python logging default)
    - [YYYY-MM-DD HH:MM:SS.fff] body  (ISO with brackets)

    Returns ("", line) when no match.
    """
    m = _TIMESTAMP_RE.match(line)
    if not m:
        return ("", line)
    return (m.group(1), m.group(2))


class LogTailer:
    """后台线程 tail 一个文件,新行通过回调 emit。

    设计目标:
    - 默认从文件末尾开始,只 emit 启动后新增的行
    - 行缓冲:不完整的行(没换行)要缓存到下次读到换行再 emit
    - 文件不存在时阻塞等待(ComfyUI 还没启动)
    - 文件被截断/轮转时重置读取位置
    - 回调在后台线程上跑;调用方负责把回调里的内容 post 到 Qt 主线程
    - stop() 幂等,同步 join 线程(最多 1s)
    """

    _POLL_INTERVAL = 0.05  # 50ms
    _PEEK_BYTES = 4096     # 轮转检测时读这么多字节找首行

    def __init__(
        self,
        path: Path,
        on_line: Callable[[str], None],
        start_from_beginning: bool = False,
    ) -> None:
        self._path = Path(path)
        self._on_line = on_line
        self._start_from_beginning = start_from_beginning
        self._stop_event = threading.Event()
        self._thread = None  # type: threading.Thread | None
        self._buffer = b""
        self._first_line = b""

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._buffer = b""
        self._first_line = b""
        self._thread = threading.Thread(
            target=self._run,
            name="LogTailer[" + self._path.name + "]",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=1.0)
            self._thread = None

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _read_first_line(self, f) -> bytes:
        """从当前位置 peek 首行字节(seek 到 0 后读)。"""
        try:
            f.seek(0)
            data = f.read(self._PEEK_BYTES)
        except OSError:
            return b""
        nl = data.find(b"\n")
        if nl >= 0:
            return data[:nl]
        return data

    def _run(self) -> None:
        path = self._path
        # 等待文件出现
        while not self._stop_event.is_set():
            if path.exists():
                break
            self._stop_event.wait(self._POLL_INTERVAL)
        if self._stop_event.is_set():
            return
        try:
            f = open(path, "rb")
        except OSError:
            return
        try:
            if self._start_from_beginning:
                f.seek(0)
                position = 0
            else:
                f.seek(0, 2)
                position = f.tell()
            self._buffer = b""
            self._first_line = self._read_first_line(f)
            while not self._stop_event.is_set():
                try:
                    size = path.stat().st_size
                except OSError:
                    size = position
                # 轮转检测:对比首行
                current_first = self._read_first_line(f)
                if current_first != self._first_line:
                    try:
                        f.seek(0)
                    except OSError:
                        return
                    position = 0
                    self._buffer = b""
                    self._first_line = current_first
                f.seek(position)
                chunk = f.read()
                if chunk:
                    position = f.tell()
                    self._buffer += chunk
                    while True:
                        idx = self._buffer.find(b"\n")
                        if idx < 0:
                            break
                        line_bytes = self._buffer[:idx]
                        if line_bytes.endswith(b"\r"):
                            line_bytes = line_bytes[:-1]
                        try:
                            line = line_bytes.decode("utf-8", errors="replace")
                        except Exception:
                            line = ""
                        self._on_line(line)
                        self._buffer = self._buffer[idx + 1:]
                else:
                    self._stop_event.wait(self._POLL_INTERVAL)
        finally:
            try:
                f.close()
            except Exception:
                pass

class ProgressCollapseFilter:
    """折叠 ComfyUI 日志中连续的 \r 进度行(典型来源:tqdm 进度条)。

    tqdm 写到 conhost 时用 \r 重写同一行;重定向到文件时,每个百分比都
    变成独立的一行(带 \r 字符)。直接 tail 这种文件会让 UI 滚动条
    长到几百行。折叠器把连续 \r 行合并成一个标记行,只保留最后一行
    原文,UI 显示为 "... N lines collapsed: <last>"。

    API 是流式的,每次 feed 一行,返回 emit 的行列表(0/1/2 行)。
    调用方应该把所有 emit 行原样追加到 UI 控件。
    """

    def __init__(self) -> None:
        self._cr_count: int = 0
        self._last_cr: str = ""

    def feed(self, line: str) -> List[str]:
        """输入一行,返回 emit 的行列表。"""
        if "\r" in line:
            self._cr_count += 1
            self._last_cr = line
            return []
        if self._cr_count > 0:
            count = self._cr_count
            last = self._last_cr
            self._cr_count = 0
            self._last_cr = ""
            return [f"... {count} lines collapsed: {last!r}", line]
        return [line]

    def flush(self) -> List[str]:
        """文件结束 / 停止 tail 时调用,返回剩余的折叠标记。"""
        if self._cr_count > 0:
            count = self._cr_count
            last = self._last_cr
            self._cr_count = 0
            self._last_cr = ""
            return [f"... {count} lines collapsed: {last!r}"]
        return []

try:
    from PyQt5 import QtCore, QtGui, QtWidgets
    from PyQt5.QtGui import QColor
    _HAS_QT = True
except Exception:
    _HAS_QT = False


if _HAS_QT:
    class _LineEmitter(QtCore.QObject):
        line_received = QtCore.pyqtSignal(str)


    class LogViewerPage(QtWidgets.QWidget):
        _LEVEL_COLORS_DARK = {
            "DEBUG": "#888888",
            "INFO": "#cccccc",
            "WARNING": "#f0c674",
            "ERROR": "#ff6b6b",
            "CRITICAL": "#ff6b6b",
        }
        _LEVEL_COLORS_LIGHT = {
            "DEBUG": "#666666",
            "INFO": "#333333",
            "WARNING": "#b07a00",
            "ERROR": "#cc0000",
            "CRITICAL": "#cc0000",
        }
        _TIMESTAMP_COLOR_DARK = "#666666"
        _TIMESTAMP_COLOR_LIGHT = "#888888"
        _LEVEL_RE = re.compile(r"\[(DEBUG|INFO|WARNING|ERROR|CRITICAL)\]")

        @classmethod
        def _detect_level(cls, body: str) -> str:
            """从 body 抽 [LEVEL] 标记;找不到默认 INFO。"""
            m = cls._LEVEL_RE.search(body)
            return m.group(1) if m else "INFO"

        @classmethod
        def _format_line_html(cls, line: str, is_dark: bool = True) -> str:
            """返回带颜色 HTML 片段;空行返回空串。"""
            if not line:
                return ""
            ts, body = parse_log_entry(line)
            safe_body = (
                body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            )
            safe_ts = (
                ts.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            ) if ts else ""
            level = cls._detect_level(body)
            palette = cls._LEVEL_COLORS_DARK if is_dark else cls._LEVEL_COLORS_LIGHT
            level_color = palette.get(level, palette["INFO"])
            ts_color = cls._TIMESTAMP_COLOR_DARK if is_dark else cls._TIMESTAMP_COLOR_LIGHT
            if ts:
                return (
                    f'<span style="color:{ts_color};">{safe_ts}</span> '
                    f'<span style="color:{level_color};">{safe_body}</span>'
                )
            return f'<span style="color:{level_color};">{safe_body}</span>'


        """实时 tail ComfyUI 日志的可滚动只读视图。

        组件:
        - QTextEdit:等宽字体,只读,自动滚到底
        - 控制条:折叠连续进度(checkbox)/暂停/清空/保存为...
        - 后台 LogTailer 线程通过 QTimer.singleShot 把行投回 UI 线程
        """

        DEFAULT_MAX_LINES = 5000

        def __init__(self, theme_manager=None, parent=None, max_lines=5000):
            super().__init__(parent)
            self.theme_manager = theme_manager
            self._max_lines = int(max_lines) if max_lines else self.DEFAULT_MAX_LINES
            self._tailer = None  # type: LogTailer | None
            self._emitter = _LineEmitter()
            self._filter = ProgressCollapseFilter()
            self._paused = False
            self._log_path = None  # type: Path | None
            self._setup_ui()

        def _setup_ui(self):
            layout = QtWidgets.QVBoxLayout(self)
            layout.setContentsMargins(15, 15, 15, 15)
            layout.setSpacing(8)

            # 标题
            title = QtWidgets.QLabel("ComfyUI 实时日志")
            title_font = title.font()
            title_font.setBold(True)
            title_font.setPointSize(13)
            title.setFont(title_font)
            layout.addWidget(title)

            # 控制条
            controls = QtWidgets.QHBoxLayout()
            self.collapse_checkbox = QtWidgets.QCheckBox("折叠连续进度")
            self.collapse_checkbox.setChecked(True)
            self.collapse_checkbox.toggled.connect(self._on_collapse_toggled)
            controls.addWidget(self.collapse_checkbox)

            self.wrap_checkbox = QtWidgets.QCheckBox("自动换行")
            self.wrap_checkbox.setChecked(False)  # 默认不换行,日志行可能很长
            self.wrap_checkbox.toggled.connect(self._on_wrap_toggled)
            controls.addWidget(self.wrap_checkbox)

            self.pause_btn = QtWidgets.QPushButton("暂停")
            self.pause_btn.setCheckable(True)
            self.pause_btn.toggled.connect(self._on_pause_toggled)
            controls.addWidget(self.pause_btn)

            self.clear_btn = QtWidgets.QPushButton("清空")
            self.clear_btn.clicked.connect(self._on_clear_clicked)
            controls.addWidget(self.clear_btn)

            self.save_btn = QtWidgets.QPushButton("保存为...")
            self.save_btn.clicked.connect(self._on_save_clicked)
            controls.addWidget(self.save_btn)

            controls.addStretch(1)
            self._path_label = QtWidgets.QLabel("(未选择日志)")
            self._path_label.setStyleSheet("color: #888;")
            controls.addWidget(self._path_label)
            layout.addLayout(controls)

            # 日志视图
            self.text_edit = QtWidgets.QTextBrowser()
            self.text_edit.setReadOnly(True)
            font = QtGui.QFont("Consolas, Courier New", 10)
            font.setStyleHint(QtGui.QFont.Monospace)
            self.text_edit.setFont(font)
            self.text_edit.setLineWrapMode(QtWidgets.QTextEdit.NoWrap)
            # 行数上限:Qt 在 block 数超过阈值时自动裁掉最早的 block,
            # 避免几 MB 日志把 QTextEdit 撑爆
            self.text_edit.document().setMaximumBlockCount(self._max_lines + 1)  # +1:Qt cap=N 实际只显示 N-1,留 1 块给光标
            layout.addWidget(self.text_edit)

        def set_log_path(self, path) -> None:
            self._log_path = Path(path)
            self._path_label.setText(str(self._log_path))

        def start_tailing(self, start_from_beginning: bool = False) -> None:
            if self._log_path is None:
                return
            if self._tailer is not None:
                return
            self._tailer = LogTailer(
                self._log_path,
                on_line=self._on_line_from_tailer,
                start_from_beginning=start_from_beginning,
            )
            self._emitter.line_received.connect(
                self._on_line_main, QtCore.Qt.QueuedConnection
            )
            self._tailer.start()

        def stop_tailing(self) -> None:
            try:
                self._emitter.line_received.disconnect(self._on_line_main)
            except Exception:
                pass
            if self._tailer is not None:
                self._tailer.stop()
                self._tailer = None
            for line in self._filter.flush():
                self._append_line(line)

        def _on_line_from_tailer(self, line: str) -> None:
            # tailer 线程:通过 signal 把行投到 UI 线程(QueuedConnection)
            self._emitter.line_received.emit(line)

        def _on_line_main(self, line: str) -> None:
            if self._paused:
                return
            if self.collapse_checkbox.isChecked():
                for out in self._filter.feed(line):
                    self._append_line(out)
            else:
                self._append_line(line)

        def _append_line(self, line: str) -> None:
            if not line:
                return
            is_dark = bool(self.theme_manager and self.theme_manager.is_dark)
            ts, body = parse_log_entry(line)
            level = self._detect_level(body)
            palette = self._LEVEL_COLORS_DARK if is_dark else self._LEVEL_COLORS_LIGHT
            level_color = QColor(palette.get(level, palette["INFO"]))
            ts_color = QColor(self._TIMESTAMP_COLOR_DARK if is_dark else self._TIMESTAMP_COLOR_LIGHT)
            cursor = self.text_edit.textCursor()
            cursor.movePosition(QtGui.QTextCursor.End)
            if ts:
                fmt = cursor.charFormat()
                fmt.setForeground(ts_color)
                cursor.setCharFormat(fmt)
                cursor.insertText(ts)
                cursor.insertText(" ")
            fmt = cursor.charFormat()
            fmt.setForeground(level_color)
            cursor.setCharFormat(fmt)
            cursor.insertText(body)
            cursor.insertText(chr(10))
            # 滚到底
            bar = self.text_edit.verticalScrollBar()
            if bar is not None:
                bar.setValue(bar.maximum())

        def _on_pause_toggled(self, checked: bool) -> None:
            self._paused = checked
            self.pause_btn.setText("继续" if checked else "暂停")

        def _on_clear_clicked(self) -> None:
            self.text_edit.clear()
            # 重置 filter 状态(避免之前积累的 \r 计数影响下一段)
            self._filter = ProgressCollapseFilter()

        def _on_collapse_toggled(self, checked: bool) -> None:
            # 切换折叠时重置 filter,避免陈旧 \r 计数
            self._filter = ProgressCollapseFilter()

        def _on_wrap_toggled(self, checked: bool) -> None:
            if checked:
                # WidgetWidth:按控件宽度换行(窄窗口也能看全)
                self.text_edit.setLineWrapMode(QtWidgets.QTextEdit.WidgetWidth)
            else:
                self.text_edit.setLineWrapMode(QtWidgets.QTextEdit.NoWrap)

        def _on_save_clicked(self) -> None:
            path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, "保存日志", "comfyui.log", "Log files (*.log);;All files (*)"
            )
            if not path:
                return
            try:
                Path(path).write_text(self.text_edit.toPlainText(), encoding="utf-8")
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "保存失败", str(e))