"""实时日志查看器:VirtualTerminal (VT100 行模型) + 文件 tail。"""
import logging
import os
import platform
import re
import subprocess
import threading
from pathlib import Path
from typing import Callable, List, Tuple


_TIMESTAMP_RE = re.compile(
    r"^\[?(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:[.,]\d+)?)\]? (.*)$"
)

# 诊断日志：挂到 launcher 子 logger，同 handler、同 launcher.log。
# 默认 INFO 级别不输出，需 DEBUG：创建 launcher/is_debug 文件，或置环境变量 COMFYUI_LAUNCHER_DEBUG=1。
# 输出包含源码位置、文件路径、信号连接计数、tailer 状态、line 预览，
# 用于下次复现 env 切换 3x 重复时排查。默认 INFO 输出到 launcher.log，修复后清理。
_diag_logger = logging.getLogger("comfyui_launcher.log_viewer")

# 高频点防爆采样。原则:
# - 前 5 次调用都 log（保证初始 bug 能被记下）
# - 之后每 100 次 log 1 次（保持可观测量，防爆诊断日志填满 launcher.log）
_EMIT_LOG_INTERVAL = 100
_EMIT_LOG_INITIAL = 5
_emit_counters = {}


def _should_log_emit(key: str) -> bool:
    """防爆采样判定。调用方法:_should_log_emit("LogTailer.emit")。
    
    为防止一个点的限流状态泄露给另一个点（例如初始 5 次中某个中途被 swallow），
    并且高频点在 burst 下可能反复调过判定函数反而被重置计数器,
    采用计数器（字典）状态以保证跨调用不丢。
    """
    n = _emit_counters.get(key, 0) + 1
    _emit_counters[key] = n
    return n <= _EMIT_LOG_INITIAL or n % _EMIT_LOG_INTERVAL == 0


# TODO(diag): env 切换 3x 重复 bug 修复后清理。全部诊断日志位于：
#  - _diag_logger / _diag_logger.info/debug 调用
#  - _EMIT_LOG_INITIAL / _EMIT_LOG_INTERVAL 参数
#  - _emit_counters / _should_log_emit 函数
#  - 各 LogTailer / LogViewerPage 方法中的 .info() 调用
# 修复后删除本 TODO 及上述全部代码。






# ANSI SGR 颜色码 → CSS 颜色(对应 8 色 + 亮色变体)。
# ComfyUI / tqdm 重定向到文件时会保留 ESC[...m 序列(如 \x1b[32m 绿色)。
# 解析后转成 <span style="color:..."> 片段,QTextBrowser 渲染时上色。
_ANSI_PALETTE = {
    30: "#000000", 31: "#cc0000", 32: "#4e9a06", 33: "#c4a000",
    34: "#3465a4", 35: "#75507b", 36: "#06989a", 37: "#d3d7cf",
    90: "#555753", 91: "#ef2929", 92: "#8ae234", 93: "#fce94f",
    94: "#729fcf", 95: "#ad7fa8", 96: "#34e2e2", 97: "#eeeeec",
}
# 匹配 ANSI/VT100 转义序列(CSI): \x1b[ ... <字母>
# 含 SGR 颜色码、光标移动、清屏等;非 SGR 的统一剥离掉(它们在重定向文件里
# 没意义,留着只会让日志变成乱码)。
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

# 只剥掉非 SGR 的 CSI(光标移动/清屏: 末字母不是 m 的)。SGR(m 结尾)单独处理,
# 因为要按颜色码上色。
_NON_SGR_CSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-ln-z]")
# SGR 序列(以 m 结尾)
_SGR_RE = re.compile(r"\x1b\[([0-9;]*)m")

def ansi_to_html(text: str, default_color: str = "") -> str:
    """把带 ANSI SGR 颜色码的文本转成带 <span style=color:...> 的 HTML 片段。

    - 非 SGR 的 ANSI 转义序列(光标移动/清屏等)直接剥离
    - HTML 转义先做(避免 < > & 被当标签)
    - 嵌套 span 用闭合/重开实现;ANSI reset (\\x1b[0m) 关掉当前 span
    """
    # 先 HTML 转义,再处理 ANSI(否则 ANSI 处理里插入的 < 会被转义)
    safe = (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
    # 1) 剥掉所有非 SGR 的 CSI(光标移动/清屏等)
    safe = _NON_SGR_CSI_RE.sub("", safe)

    out = []
    open_span = False
    pos = 0
    for m in _SGR_RE.finditer(safe):
        # m 之前的纯文本
        out.append(safe[pos:m.start()])
        pos = m.end()
        codes = m.group(1)
        # 解析 SGR 参数
        parts = [c for c in codes.split(";") if c] if codes else []
        # 关掉旧 span
        if open_span:
            out.append("</span>")
            open_span = False
        # 0 或空 = reset;其它非颜色码(bold=1 等)也按 reset 处理(简单起见)
        color = None
        if parts and parts != ["0"]:
            for p in parts:
                try:
                    code = int(p)
                except ValueError:
                    continue
                if code == 0:
                    color = None
                    break
                if code in _ANSI_PALETTE:
                    color = _ANSI_PALETTE[code]
                    break
        if color is not None:
            out.append(f'<span style="color:{color};">')
            open_span = True
    # 末尾剩余文本
    out.append(safe[pos:])
    if open_span:
        out.append("</span>")
    return "".join(out)


def strip_ansi(text: str) -> str:
    """剥掉所有 ANSI 转义序列(给纯文本路径用,如 level 检测)。"""
    return _ANSI_ESCAPE_RE.sub("", text)


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

    @staticmethod
    def _open_shared(path):
        """以共享只读模式打开文件,允许其它进程 rename/write/delete 同名文件。

        Windows 上默认 open("rb") 的 share mode 不含 FILE_SHARE_DELETE,
        会阻止 ComfyUI-Manager 的日志轮转(rename comfyui.log → comfyui.prev.log)
        报 PermissionError [WinError 32]。用 CreateFile 指定全套 share flags
        解决。其它平台直接 open。
        """
        if os.name != "nt":
            return open(path, "rb")
        import ctypes
        from ctypes import wintypes
        # FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE = 0x7
        # OPEN_EXISTING = 3, GENERIC_READ = 0x80000000
        # FILE_ATTRIBUTE_NORMAL = 0x80
        k32 = ctypes.windll.kernel32
        CreateFileW = k32.CreateFileW
        CreateFileW.restype = wintypes.HANDLE
        CreateFileW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
            ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
        ]
        handle = CreateFileW(str(path), 0x80000000, 0x7, None, 3, 0x80, None)
        if handle == -1 or handle == ctypes.c_void_p(-1).value:
            raise OSError(f"CreateFileW failed for {path}")
        # 把 Windows HANDLE 转成 C fd,再包成 Python file object
        import msvcrt
        fd = msvcrt.open_osfhandle(handle, 0)  # 0 = O_RDONLY
        return os.fdopen(fd, "rb")

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
        _diag_logger.info(
            "LogTailer.__init__ path=%s start_from_beginning=%s",
            self._path, start_from_beginning,
        )

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._buffer = b""
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

    def _run(self) -> None:
        path = self._path
        _diag_logger.info("LogTailer._run thread_start path=%s", path)
        # 等待文件出现
        while not self._stop_event.is_set():
            if path.exists():
                break
            self._stop_event.wait(self._POLL_INTERVAL)
        if self._stop_event.is_set():
            return
        try:
            f = self._open_shared(path)
        except OSError:
            _diag_logger.info("LogTailer._run open_failed path=%s", path)
            return
        try:
            if self._start_from_beginning:
                f.seek(0)
                position = 0
            else:
                f.seek(0, 2)
                position = f.tell()
            self._buffer = b""
            # 记录打开时的文件实体标识(inode),用于轮转检测
            opened_key = self._file_key(path)
            _diag_logger.info(
                "LogTailer._run opened path=%s position=%d start_from_beginning=%s",
                path, position, self._start_from_beginning,
            )
            while not self._stop_event.is_set():
                # 轮转检测:对比当前路径下文件的标识与打开时的标识
                # - file_key 变化(st_dev+st_ino):文件被重命名后新建
                #   (ComfyUI-Manager 的轮转:comfyui.log → comfyui.prev.log + 新建)
                # - position > 当前文件 size:同一个文件被 truncate(open("w") 清空重写),
                #   旧的读取位置已经超出新文件末尾,继续读只会读到空/错位的内容
                # 任一情况都要重新 open 文件(或 seek 回 0),否则旧 fd 还指向被重命名的
                # 旧文件,永远读不到新内容。注意:正常 append(size 增长)不算轮转。
                current_key = self._file_key(path)
                current_size = self._file_size(path)
                rotated = False
                if current_key and opened_key and current_key != opened_key:
                    rotated = True
                elif current_size is not None and position > current_size:
                    rotated = True
                if rotated:
                    _diag_logger.info(
                        "LogTailer._run rotated_detected path=%s old_key=%s new_key=%s old_pos=%d new_size=%s",
                        path, opened_key, current_key, position, current_size,
                    )
                    try:
                        f.close()
                    except Exception:
                        pass
                    try:
                        f = self._open_shared(path)
                    except OSError:
                        return
                    position = 0
                    self._buffer = b""
                    opened_key = self._file_key(path)
                    # 立即 fallthrough 读新文件内容
                f.seek(position)
                chunk = f.read()
                if chunk:
                    position = f.tell()
                    self._buffer += chunk
                    # 按 \r 或 \n 任一边界 emit"段"(保留边界字符)。
                    # 这是贴近 xterm 的逐块喂法:消费方(VirtualTerminal)按边界字符
                    # 解释覆盖(\r)/换行(\n)语义。
                    #
                    # 为什么不只按 \n 切:tqdm 重定向到文件时,一次采样可能写几十个
                    # \r 帧但只有最后一个 \n。若只按 \n 切,LogTailer 会把整段进度积压
                    # 在 buffer 里直到任务结束,用户几分钟看不到任何进度。按 \r 也切,
                    # 每个 \r 帧到达就 emit,VirtualTerminal 把它覆盖成最新帧作 active_line,
                    # 用户实时看到进度条在动。
                    #
                    # 边界字符保留在段里:VirtualTerminal 需要看到 \r 才知道"回行首覆盖",
                    # 看到 \n 才知道"finalize 当前行"。
                    while True:
                        cr_idx = self._buffer.find(b"\r")
                        nl_idx = self._buffer.find(b"\n")
                        # 取更早出现的边界
                        if cr_idx < 0 and nl_idx < 0:
                            break  # buffer 里没有完整段,等下次读
                        if cr_idx < 0:
                            boundary, sep = nl_idx, b"\n"
                        elif nl_idx < 0:
                            boundary, sep = cr_idx, b"\r"
                        elif cr_idx <= nl_idx:
                            boundary, sep = cr_idx, b"\r"
                        else:
                            boundary, sep = nl_idx, b"\n"
                        # 段 = 边界字符之前的内容 + 边界字符本身
                        seg_bytes = self._buffer[:boundary] + sep
                        self._buffer = self._buffer[boundary + 1:]
                        seg = seg_bytes.decode("utf-8", errors="replace")
                        if _should_log_emit("LogTailer.emit"):
                            _diag_logger.info("LogTailer.emit path=%s seg=%r", path, seg[:200])
                        self._on_line(seg)
                else:
                    self._stop_event.wait(self._POLL_INTERVAL)
        finally:
            try:
                f.close()
            except Exception:
                pass

    @staticmethod
    def _file_key(path) -> tuple:
        """文件实体标识 (st_dev, st_ino)。

        用于检测「同名文件被替换」(重命名 + 新建同名)。
        - Unix: 重命名 + 新建后 inode 变化 → key 变化 → 触发重 open
        - Windows: 文件被替换后 st_ino 通常也会变化(ntfs/generational),
          即使部分 fs 返回 0,组合 st_dev 仍有区分度
        不含 mtime/size:正常追加也会改这两个,不能用来判断轮转。
        路径不存在 / stat 失败返回 ()。
        """
        try:
            st = path.stat()
            return (st.st_dev, st.st_ino)
        except OSError:
            return ()

    @staticmethod
    def _file_size(path):
        try:
            return path.stat().st_size
        except OSError:
            return None


def read_tail_lines(path, n: int) -> List[str]:
    """读文件最后 n 行(已剥 \r、UTF-8 解码)。文件不存在/为空返回 []。

    用 deque(maxlen=n) 从头扫,只保留最后 n 行——对大文件(数万行)也是线性单遍,
    不会把整个文件读进内存。供 LogViewerPage 首次进入时按需加载最近历史用。
    """
    from collections import deque
    p = Path(path)
    if not p.exists():
        return []
    buf = deque(maxlen=n)
    with LogTailer._open_shared(p) as f:
        chunk = b""
        while True:
            data = f.read(65536)
            if not data:
                break
            chunk += data
            while True:
                idx = chunk.find(b"\n")
                if idx < 0:
                    break
                line_bytes = chunk[:idx]
                if line_bytes.endswith(b"\r"):
                    line_bytes = line_bytes[:-1]
                buf.append(line_bytes.decode("utf-8", errors="replace"))
                chunk = chunk[idx + 1:]
    return list(buf)


class VirtualTerminal:
    """极简 VT100 行模型:解释 \\r / \\n 控制字符,模拟终端"当前行"语义。

    这是日志页"和 ComfyUI 前端 xterm.js console 表现一致"的核心。tqdm 重定向
    到文件时,每个进度帧之间用 \\r 分隔(回车 = 光标回行首),只有最后一个帧
    之后才写 \\n(换行)。xterm.js 直接吃原始字节流,\\r 自然覆盖当前行;
    我们用同样语义:维护一个"当前行"字符串,\\r 后续字符覆盖写,\\n 才 finalize。

    只实现 tqdm/ComfyUI 日志用到的子集(\\r 回行首覆盖、\\n 换行),
    不处理光标上下左右移动、alternate screen、ESC[K 清屏等——日志里没有。

    纯覆盖语义(不做行尾 pad):\\r 后直接清空当前行重建。tqdm 进度帧单调变长,
    实测不会残留旧字符尾部;与 ComfyUI 前端 xterm 行为一致。

    线程安全:无状态共享,实例仅供单消费方使用(LogViewerPage / webui_page 各自一个)。
    """

    def __init__(self) -> None:
        self._current: str = ""              # 当前行(已解释覆盖语义后的最终内容)
        self._carriage_returned: bool = False  # 上一个是 \r,后续字符从行首覆盖写

    def feed(self, text: str) -> List[str]:
        """喂一段字符流,返回这段期间因 \\n 而 finalize 的行列表(不含当前活动行)。

        消费方调 active_line 属性拿当前活动行单独渲染(它还没被 \\n 收尾)。

        \\r\\n 序列安全:Windows 风格 \\r\\n 里 \\r 先标记 carriage_returned,
        \\n 紧跟其后 finalize 当前行 —— \\n 不走"覆盖写"分支,不会误清空内容。
        """
        finalized: List[str] = []
        for ch in text:
            if ch == "\n":
                finalized.append(self._current)
                self._current = ""
                self._carriage_returned = False
            elif ch == "\r":
                self._carriage_returned = True
            else:
                if self._carriage_returned:
                    # 纯覆盖:回行首后新内容替换整行
                    self._current = ""
                    self._carriage_returned = False
                self._current += ch
        return finalized

    @property
    def active_line(self) -> str:
        """当前活动行(还没被 \\n 收尾的部分)。消费方实时渲染它。"""
        return self._current

    def reset(self) -> None:
        """清空状态(清屏 / 切环境 / 关闭折叠时调)。"""
        self._current = ""
        self._carriage_returned = False


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
        # 实时日志收到新内容时发此信号(level=DEBUG/INFO/WARNING/ERROR/CRITICAL),
        # 主窗口据此在 nav 按钮上亮一个红点 badge,提示用户有未读日志。
        # 仅当用户当前不在「日志页」时才需要提示。
        new_logs_received = QtCore.pyqtSignal(str)

        # 新日志通知在主窗口的 nav 按钮上显示一个简单的 "*" 前缀(无级别区分),
        # 历史上按 [LEVEL] 区分 绿/黄/红 灯的逻辑已移除 —— 用户反馈太花式,
        # 只要知道"有未读"就够。这里只 emit 一个 sentinel 字符串("__new__"),
        # QtApp._refresh_logs_nav 收到非 __viewed__/__cleared__ 就会加星号。



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
            # VirtualTerminal 解释 \r/\n 覆盖语义(替代旧的 prefix/progress 双缓冲
            # 折中方案)。这是"和 ComfyUI 前端 xterm 一致"的核心:tqdm 进度帧被
            # \r 覆盖成最终帧,节点状态行不再被错误粘连。
            self._vt = VirtualTerminal()
            self._paused = False
            # 暂停期间累积的 tailer 段(不丢弃)。继续后一次性 feed 给 VirtualTerminal,
            # 让暂停期间的新行补显示到末尾 —— 类似 ComfyUI 前端 xterm 的暂停语义
            # (画面冻结,但日志不丢)。tailer 线程不受暂停影响,继续读文件 emit。
            # 有 cap(_PAUSED_PENDING_CAP)防 OOM:用户暂停几小时 + 高频日志时,
            # 超出 cap 后丢弃最旧的段(保留最近的,符合"看到最新"的预期)。
            self._pending_while_paused = []  # type: List[str]
            self._log_path = None  # type: Path | None
            # 诊断 logger（同 launcher 同名子 logger，同 handler，写入 launcher.log）
            self.logger = _diag_logger
            # 自用户上次「看到」日志页后是否有新内容;页面可见时为 False。
            # 配合 new_logs_received 信号,主窗口在 nav 按钮亮红点提示。
            self._unread_since_view = False
            # 历史日志按需加载:启动时 tailer 只从末尾跟随新行(start_from_beginning=False),
            # 用户首次切到本页时才读最近 N 行填充。避免启动时把数万行历史灌进主线程冻死 UI。
            self._history_loaded = False
            # 批量渲染:行先进缓冲,定时器(50ms)批量 append 到 QTextEdit,
            # 避免逐行 insertText 触发富文本 O(n²) 布局重算。
            self._batch_buffer = []  # type: List[str]
            self._batch_timer = None  # type: QtCore.QTimer | None
            # 标记当前 QTextEdit 末尾是否有一个"活动行"(VirtualTerminal 的 active_line)。
            # _flush_batch 据此决定:先删旧活动行,再插新 batch,最后插新活动行。
            self._has_active_line = False
            self._setup_ui()

        # 最近历史日志的行数上限(用户首次切到日志页时回填这么多行)。
        # 太大→首次进入卡;太小→看不到上下文。500 行覆盖一次完整启动序列。
        RECENT_HISTORY_LINES = 500
        # 批量渲染 flush 间隔。tailer 每 50ms 读一次,这里也 50ms 攒一批,
        # 让实时跟随的延迟感 < 100ms 且不逐行卡。
        _BATCH_INTERVAL_MS = 50
        # 暂停期间累积段的 cap。防 OOM:用户暂停几小时 + 高频 tqdm 日志时,
        # 一段是一个 \r/\n 边界单元(一个进度帧算一段),50000 段约等于
        # 几小时重度采样。超出后丢最旧的(保留最近内容,符合"看到最新"预期)。
        _PAUSED_PENDING_CAP = 50000

        def showEvent(self, event):
            """页面切到前台:清未读标记("*") + 首次进入时按需加载最近历史。"""
            try:
                self._unread_since_view = False
                self.new_logs_received.emit("__viewed__")
            except Exception:
                pass
            # 首次切到本页才加载历史(之后靠 tailer 跟随,不重复读)
            if not self._history_loaded:
                self._history_loaded = True
                self.logger.info("showEvent history_load path=%s", self._log_path)
                try:
                    self._load_recent_history()
                except Exception:
                    pass
            super().showEvent(event)

        def _load_recent_history(self):
            """读日志文件最后 N 行,批量填进视图(用户首次进入日志页时调)。

            在调用线程(主线程)同步读文件末尾——只读 N 行,毫秒级,不阻塞。
            用批量 append(走 _enqueue_batch → 定时器 flush),一次写完。

            read_tail_lines 已经按 \n 切行、剥掉行尾 \r,所以历史行都是
            "已固化的完整行",直接进 batch buffer,不走 VirtualTerminal
            (实时 tailer 那边才需要解释 \r 覆盖语义)。
            """
            if self._log_path is None:
                return
            try:
                lines = read_tail_lines(self._log_path, self.RECENT_HISTORY_LINES)
            except Exception:
                return
            for line in lines:
                # 历史行含 ANSI SGR 代码(如 \x1b[32m[INFO]\x1b[0m),QTextBrowser 里
                # \x1b 不可见会留残渣。剥 ANSI 后入缓冲,与实时行一致。
                self._enqueue_batch(strip_ansi(line))
            self._flush_batch()  # 历史一次性 flush,不等定时器

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
            # 注:"折叠连续进度" checkbox 已移除 —— VirtualTerminal 的 \r 覆盖语义
            # 天然把 tqdm 多帧进度折叠成最终帧,不再需要手动的折叠开关/Filter。

            self.wrap_checkbox = QtWidgets.QCheckBox("自动换行")
            self.wrap_checkbox.setChecked(True)  # 默认换行,窄窗口也能看全
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

            # 在文件管理器里打开并选中日志文件。实时日志只显示最近内容,
            # 用户想看完整历史/翻旧日志时直接打开原文件最方便。
            self.open_in_explorer_btn = QtWidgets.QPushButton("📁 打开日志文件")
            self.open_in_explorer_btn.clicked.connect(self._on_open_in_explorer)
            controls.addWidget(self.open_in_explorer_btn)

            self.notify_checkbox = QtWidgets.QCheckBox("新日志提醒")
            # 默认开启:有新日志且不在日志页时,nav 按钮亮带颜色的提示。
            # 取消勾选则完全不发未读提示(适合常驻后台、不想被打扰)。
            self.notify_checkbox.setChecked(True)
            self.notify_checkbox.toggled.connect(self._on_notify_toggled)
            controls.addWidget(self.notify_checkbox)

            controls.addStretch(1)
            self._path_label = QtWidgets.QLabel("(未选择日志)")
            self._path_label.setStyleSheet("color: #888;")
            controls.addWidget(self._path_label)
            layout.addLayout(controls)

            # 日志视图
            self.text_edit = QtWidgets.QTextBrowser()
            self.text_edit.setObjectName("LogViewEdit")  # 供全局 QSS 按 objectName 设主题色
            self.text_edit.setReadOnly(True)
            # 选一个系统实际可用的等宽字体。不用 setFamilies fallback list 也不用 setStyleHint(Monospace)，
            # 避免 Qt 枚举系统无法处理的旧位图字体（Fixedsys/Modern/MS Sans Serif 等）触发
            # DirectWrite 负载失败 "CreateFontFaceFromHDC() failed" 警告。选字体顺序:
            # 1) 首选我们面向多平台的偏好 (只选系统实际装的)→ 避免 fallback 枚举中心 fallback chain 里众多无法处理的旧字体;
            # 2) 都不装的话退到系统默认(避免重新触发枚举)。
            try:
                from PyQt5 import QtGui as _QtGui
                _families = set(_QtGui.QFontDatabase().families())
            except Exception:
                _families = set()
            _picked = next(
                (f for f in ("Consolas", "Cascadia Mono", "Courier New", "Menlo",
                              "DejaVu Sans Mono", "Courier")
                 if f in _families),
                "",
            )
            if _picked:
                font = _QtGui.QFont(_picked)
            else:
                # 系统默认字体(不加任何 hint)→避免枚举无法处理的旧字体。
                font = _QtGui.QFont()
            font.setPointSize(10)
            self.text_edit.setFont(font)
            self.text_edit.setLineWrapMode(QtWidgets.QTextEdit.WidgetWidth)
            # 行数上限:Qt 在 block 数超过阈值时自动裁掉最早的 block,
            # 避免几 MB 日志把 QTextEdit 撑爆
            self.text_edit.document().setMaximumBlockCount(self._max_lines + 1)  # +1:Qt cap=N 实际只显示 N-1,留 1 块给光标
            # 纯文本模式(移除了逐行着色)后,text_edit 的背景/前景必须显式设主题色——
            # 否则 QTextBrowser 走 Qt 默认 palette(白底黑字),与深色主题格格不入。
            self._apply_text_edit_theme()
            layout.addWidget(self.text_edit)

        def _apply_text_edit_theme(self):
            """据当前主题设日志视图的背景/前景色(随主题切换调)。

            纯文本模式下文字没有逐行 charFormat,必须靠 stylesheet 保证对比度。
            用 input_bg(深色 rgba(0,0,0,0.3) / 浅色 #FFFFFF)做背景,
            input_text(深色 #E5E7EB / 浅色 #0F172A)做文字色,和输入框视觉一致。
            """
            try:
                tm = self.theme_manager
                colors = tm.colors if tm else None
                bg = (colors.get("input_bg") if colors else None) or "rgba(0,0,0,0.3)"
                fg = (colors.get("input_text") if colors else None) or "#E5E7EB"
                border = (colors.get("input_border") if colors else None) or "#4B5563"
                self.text_edit.setStyleSheet(
                    f"QTextBrowser {{ background-color: {bg}; color: {fg};"
                    f" border: 1px solid {border}; border-radius: 6px; padding: 6px; }}"
                )
            except Exception:
                pass

        def update_theme(self, _theme_styles=None):
            """主题切换回调(qt_app._apply_theme 对 _new_pages 每页调)。

            重新读 theme_manager.colors 刷日志视图背景/前景色。
            """
            self._apply_text_edit_theme()

        def set_log_path(self, path) -> None:
            self._log_path = Path(path)
            self._path_label.setText(str(self._log_path))

        def start_tailing(self, start_from_beginning: bool = False) -> None:
            if self._log_path is None:
                self.logger.info("start_tailing skipped: no log_path")
                return
            if self._tailer is not None:
                self.logger.info(
                    "start_tailing skipped: tailer_alive path=%s", self._log_path,
                )
                return
            self._tailer = LogTailer(
                self._log_path,
                on_line=self._on_line_from_tailer,
                start_from_beginning=start_from_beginning,
            )
            # 每次启动都用全新的 emitter,与 tailer 生命周期严格 1:1。
            # 旧 emitter(连同它上面任何残留的 signal 连接)随引用替换被 GC,
            # 不再依赖 disconnect() 精确断开——pyqtSignal.disconnect(bound_method)
            # 在某些 PyQt5 版本/打包环境下会静默失败(实测用户机器:receivers_after
            # 不降),导致切环境后 line_received 上累积多个指向 _on_line_main 的
            # 连接,每行日志被触发多次(用户实测重复 2 次)。
            self._emitter = _LineEmitter()
            # UniqueConnection 作双保险:即使同一 emitter 上也不会重复挂同一 slot.
            # 但它在测试/某些 PyQt5 环境下偶发抛 TypeError('connection is not unique')
            # (Qt 跨实例信号槽注册冲突), 失败时回退普通连接, 不让整个 start_tailing 挂掉.
            try:
                self._emitter.line_received.connect(
                    self._on_line_main,
                    QtCore.Qt.QueuedConnection | QtCore.Qt.UniqueConnection,
                )
            except TypeError:
                self._emitter.line_received.connect(
                    self._on_line_main,
                    QtCore.Qt.QueuedConnection,
                )
            self._tailer.start()
            self.logger.info(
                "start_tailing path=%s start_from_beginning=%s receivers=%d",
                self._log_path, start_from_beginning,
                self._emitter.receivers(self._emitter.line_received),
            )

        def stop_tailing(self) -> None:
            receivers_before = -1
            if self._emitter is not None:
                try:
                    receivers_before = self._emitter.receivers(self._emitter.line_received)
                except Exception:
                    pass
            tailer_alive = (
                self._tailer.is_alive() if self._tailer is not None else None
            )
            if self._tailer is not None:
                self._tailer.stop()
                self._tailer = None
            # 丢弃旧 emitter:它上面残留的 signal 连接随之失效(下次 start 会建全新的)。
            # 不再调 disconnect——bound method disconnect 在部分环境静默失败(见 start_tailing 注释)。
            self._emitter = None
            # 收尾:把 VirtualTerminal 里残留的 active_line(还没被 \n 终结的半行)
            # flush 成一条完整行,避免进度条卡在末尾不被固化。
            self._finalize_active_line()
            self.logger.info(
                "stop_tailing path=%s receivers_before=%d tailer_alive_before=%s",
                self._log_path, receivers_before, tailer_alive,
            )

        def _on_line_from_tailer(self, line: str) -> None:
            # tailer 线程:通过 signal 把行投到 UI 线程(QueuedConnection)
            if _should_log_emit("tailer_cb_recv"):
                self.logger.info("tailer_cb_recv line=%r", line[:200])
            # stop_tailing 会把 _emitter 置空;tailer 线程在 stop() join 之前可能
            # 还有尾包回调到达这里,直接丢弃即可(stop 后的新行本就不该再显示)。
            emitter = self._emitter
            if emitter is None:
                return
            emitter.line_received.emit(line)

        def _on_line_main(self, line: str) -> None:
            if _should_log_emit("main_recv"):
                self.logger.info("main_recv line=%r", line[:200])
            if self._paused:
                # 暂停时不丢弃:tailer 线程还在读文件,把段累积起来,
                # 继续后一次性补 feed,避免暂停期间日志丢失。
                self._pending_while_paused.append(line)
                # 防 OOM cap:超限丢最旧的(保留最近内容)。重度采样下 50000 段
                # 约几小时,够覆盖正常使用;极端长暂停也不会把内存撑爆。
                if len(self._pending_while_paused) > self._PAUSED_PENDING_CAP:
                    del self._pending_while_paused[:len(self._pending_while_paused) - self._PAUSED_PENDING_CAP]
                return
            # 喂给 VirtualTerminal 解释 \r/\n 覆盖语义。
            # finalized 是因 \n 而"完成"的行(已固化,进 batch buffer);
            # active_line 是当前还在"活动中"的行(tqdm 进度条),单独渲染。
            finalized = self._vt.feed(line)
            for fl in finalized:
                if fl:  # 跳过真正空字符串(\n\n 产生的空段); 保留含空白的合法行
                    self._append_line(fl)
            # 即使没有 finalized 行,active_line 可能变了(进度帧刷新)→ 触发 batch flush 重绘
            self._enqueue_batch(None)

        def _finalize_active_line(self) -> None:
            """收尾活动行:把 VirtualTerminal 里残留的 active_line flush 成完整行。

            在 stop_tailing / 清屏时调,避免 tqdm 进度条永远卡在末尾不被固化。
            """
            active = self._vt.active_line
            if not active:
                return
            self._vt.reset()
            self._append_line(active)

        def _append_line(self, line: str) -> None:
            """处理一行已固化的日志:剥 ANSI、记录未读、入批量缓冲(不直接写 QTextEdit)。

            纯文本模式(移除了颜色标识):剥掉 ANSI 转义码后原文进缓冲,
            由 _flush_batch 定时器批量 append。不再逐行 insertText + charFormat
            着色——那是 O(n²) 的富文本布局,数万行历史会冻死 UI。
            不再做日志级别(level)解析 —— nav 按钮只关心"有没有新",不再按级别配色。
            """
            if not line:
                return
            # 页面不可见 + 用户开启「新日志提醒」时,标记未读并通知主窗口加 "*" 前缀。
            # 关闭提醒则完全不发信号,nav 按钮保持原文字。
            if not self.isVisible() and self.notify_checkbox.isChecked():
                try:
                    if not self._unread_since_view:
                        self._unread_since_view = True
                    self.new_logs_received.emit("__new__")
                except Exception:
                    pass
            # 剥 ANSI 后入缓冲(纯文本,不着色)
            clean = strip_ansi(line)
            self._enqueue_batch(clean)

        def _enqueue_batch(self, line) -> None:
            """普通行入缓冲；None 表示只触发活动行刷新(active_line 可能变了)。"""
            if line is not None:
                self._batch_buffer.append(line)
            if self._batch_timer is None:
                self._batch_timer = QtCore.QTimer(self)
                self._batch_timer.setSingleShot(True)
                self._batch_timer.timeout.connect(self._flush_batch)
            if not self._batch_timer.isActive():
                self._batch_timer.start(self._BATCH_INTERVAL_MS)

        def _flush_batch(self) -> None:
            """把缓冲里的行 + 当活动行一次性写入 QTextEdit(尽量少的 DOM 写入)。

            批量化是关键:把 N 次 insertText(每次触发富文本布局重算)合并,
            实时跟随(行流)和历史回填(几百行)都只做 O(1) 次 DOM 写入。

            活动行(active_line = VirtualTerminal 当前的 \r 覆盖结果,如 tqdm 进度条)
            渲染策略:它必须是 QTextEdit 末尾独立的一块,下次 flush 时先删掉再覆盖写,
            这样 \r 的"覆盖当前行"语义在 QTextEdit 里成立。
            """
            active = strip_ansi(self._vt.active_line)
            if not self._batch_buffer and not active and not self._has_active_line:
                return
            batch_size = len(self._batch_buffer)
            text = "\n".join(self._batch_buffer)
            self._batch_buffer.clear()
            if _should_log_emit("flush_batch"):
                self.logger.info("flush_batch size=%d first_line=%r active=%r",
                                 batch_size, text.splitlines()[0][:120] if text else "", active[:80])
            cursor = self.text_edit.textCursor()
            cursor.movePosition(QtGui.QTextCursor.End)
            # 如果末尾有上一轮残留的活动行块,先清空块内文本(\r 覆盖语义:整行重写)。
            # 关键:用 StartOfBlock + EndOfBlock(KeepAnchor) 选中块内文本(不含块分隔符),
            # 不能用 BlockUnderCursor —— 后者会连带删掉块分隔符 (\u2029),导致删完后
            # 光标粘在前一块末尾,后续 insertText 把新内容拼到前一行(换行丢失,
            # 表现为 "#104 [...]b100%|..." 粘连 bug)。
            if self._has_active_line:
                cursor.movePosition(QtGui.QTextCursor.StartOfBlock)
                cursor.movePosition(QtGui.QTextCursor.EndOfBlock, QtGui.QTextCursor.KeepAnchor)
                cursor.removeSelectedText()
                self._has_active_line = False
            # 插入本批已固化的行(每行末尾带 \n)
            if text:
                cursor.insertText(text + "\n")
            # 插入新的活动行(末尾不带 \n,下次 flush 会先删它再覆盖)
            if active:
                cursor.insertText(active)
                self._has_active_line = True
            # 滚到底(整批一次)
            bar = self.text_edit.verticalScrollBar()
            if bar is not None:
                bar.setValue(bar.maximum())


        def _on_pause_toggled(self, checked: bool) -> None:
            self._paused = checked
            self.pause_btn.setText("继续" if checked else "暂停")
            if not checked and self._pending_while_paused:
                # 继续时:把暂停期间累积的段一次性补 feed 给 VirtualTerminal,
                # 让暂停期间的新行正确显示到末尾(\r/\n 覆盖语义保持一致)。
                pending = self._pending_while_paused
                self._pending_while_paused = []
                for line in pending:
                    finalized = self._vt.feed(line)
                    for fl in finalized:
                        if fl:  # 与 _on_line_main 一致,跳过空字符串
                            self._append_line(fl)
                # 触发一次 flush 渲染(含最终 active_line)
                self._enqueue_batch(None)

        def _on_clear_clicked(self) -> None:
            self.text_edit.clear()
            # 重置 VirtualTerminal 状态(清掉残留的活动行/覆盖标志)
            self._vt.reset()
            self._has_active_line = False
            self._batch_buffer.clear()
            # 清空暂停期间累积的段(用户主动清空,不要在继续时补显示)
            self._pending_while_paused.clear()

        def _on_wrap_toggled(self, checked: bool) -> None:
            if checked:
                # WidgetWidth:按控件宽度换行(窄窗口也能看全)
                self.text_edit.setLineWrapMode(QtWidgets.QTextEdit.WidgetWidth)
            else:
                self.text_edit.setLineWrapMode(QtWidgets.QTextEdit.NoWrap)

        def _on_notify_toggled(self, checked: bool) -> None:
            # 关闭提醒时,顺手清掉当前已经亮起的未读标记,
            # 否则 nav 按钮会一直顶着 🟢/🟡/🔴 直到用户下次切进日志页。
            if not checked:
                try:
                    self._unread_since_view = False
                    self.new_logs_received.emit("__cleared__")
                except Exception:
                    pass

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

        def _on_open_in_explorer(self) -> None:
            """在系统文件管理器里打开并选中当前日志文件。

            实时日志只显示最近内容(启动后新行 + 首次进入读的最近 500 行),
            想看完整历史/翻旧日志时直接打开原文件最方便。用 explorer /select
            在文件管理器里选中文件(而不是用关联程序打开)。
            """
            if self._log_path is None:
                QtWidgets.QMessageBox.information(self, "提示", "未选择日志文件。")
                return
            path = Path(self._log_path)
            if not path.exists():
                QtWidgets.QMessageBox.information(self, "提示", f"日志文件尚未生成:\n{path}")
                return
            try:
                if platform.system() == "Windows":
                    # /select,<path> 在资源管理器里打开父目录并选中该文件
                    subprocess.Popen(["explorer", "/select,", str(path)])
                elif platform.system() == "Darwin":
                    # macOS: 在 Finder 里揭示文件
                    subprocess.Popen(["open", "-R", str(path)])
                else:
                    # Linux: 打开所在目录(无通用「选中」命令)
                    subprocess.Popen(["xdg-open", str(path.parent)])
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "打开失败", str(e))