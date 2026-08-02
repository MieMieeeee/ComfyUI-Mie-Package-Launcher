"""实时日志查看器:日志解析、进度折叠、文件 tail。"""
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

# Python logging-style level marker ([INFO] / [ERROR] / ...). Multi-\r 行 first
# segment matching this is treated as a log prefix (node status line / import
# time line) and preserved. Subsequent \r segments (tqdm progress frames) only
# update the progress part -- matches ComfyUI frontend console behavior.
# tqdm progress frames also contain "[elapsed<remaining, rate]" so a naive
# "in [" heuristic would mis-classify them; matching the actual level names avoids that.
_LOG_LEVEL_MARKER_RE = re.compile(r"\[(INFO|DEBUG|WARN|WARNING|ERROR|CRITICAL|FATAL)\]")

# ComfyUI node ID line like "#335 [PrimitiveFloat]: 0.00s - vram 0b".
_NODE_ID_RE = re.compile(r"^#\d+(\.\d+)?(\.\w+)?\s+\[")



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
        self._first_line = b""
        _diag_logger.info(
            "LogTailer.__init__ path=%s start_from_beginning=%s",
            self._path, start_from_beginning,
        )

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
                    emitted_cr = self._emit_complete_carriage_returns(path)
                    if emitted_cr:
                        # _emit_complete_carriage_returns stopped at the LAST \r before \n.
                        # Remaining buffer (before \n) is either:
                        #   (a) tqdm-style progress frame (contains "%|") — emit as \r
                        #       segment so downstream active-progress logic updates the live
                        #       progress bar;
                        #   (b) arbitrary text after the last \r (e.g. "done" right after
                        #       "Loading: 40%\r") — leave for the main \n loop.
                        idx = self._buffer.find(b"\n")
                        if idx >= 0:
                            line_bytes = self._buffer[:idx]
                            if b"%|" in line_bytes:
                                if line_bytes.endswith(b"\r"):
                                    line_bytes = line_bytes[:-1]
                                if line_bytes:
                                    line = line_bytes.decode("utf-8", errors="replace") + "\r"
                                    if _should_log_emit("LogTailer.emit"):
                                        _diag_logger.info("LogTailer.emit path=%s line=%r", path, line[:200])
                                    self._on_line(line)
                                self._buffer = self._buffer[idx + 1:]
                    while True:
                        idx = self._buffer.find(b"\n")
                        if idx < 0:
                            break
                        line_bytes = self._buffer[:idx]
                        if line_bytes.endswith(b"\r"):
                            line_bytes = line_bytes[:-1]
                        # tqdm 重定向到文件时，整段进度压在一条物理行里，
                        # 用 \r 分隔每次刷新，只在迭代末尾写 \n。
                        # 如果不在这里按 \r 切段，LogTailer 会把整段积压在 buffer 等 \n，
                        # 而任务可能跑几分钟才出 \n，期间用户看不到任何进度。
                        # 切段后每段单独 emit（\r 标记保留给 Filter 识别），
                        # Filter 再按新值/速率限决定是否实时显出。
                        if b"\r" in line_bytes:
                            for seg in line_bytes.split(b"\r"):
                                if not seg:
                                    # 连续 \r 之间的空段（tqdm 写新值前先 \r 把光标归位），
                                    # 直接丢弃
                                    continue
                                try:
                                    line = seg.decode("utf-8", errors="replace") + "\r"
                                except Exception:
                                    line = "\r"
                                if _should_log_emit("LogTailer.emit"):
                                    _diag_logger.info("LogTailer.emit path=%s line=%r", path, line[:200])
                                self._on_line(line)
                        else:
                            try:
                                line = line_bytes.decode("utf-8", errors="replace")
                            except Exception:
                                line = ""
                            if line:
                                if _should_log_emit("LogTailer.emit"):
                                    _diag_logger.info("LogTailer.emit path=%s line=%r", path, line[:200])
                                self._on_line(line)
                        self._buffer = self._buffer[idx + 1:]
                else:
                    self._stop_event.wait(self._POLL_INTERVAL)
        finally:
            try:
                f.close()
            except Exception:
                pass

    def _emit_complete_carriage_returns(self, path) -> bool:
        """立即发出以回车结束的刷新，尾部半行继续等待后续字节。

        Returns True if any \r 段 was emitted. When True, the remaining buffer before \n
        is the LAST \r 段 of a multi-\r 行 — caller should emit it as a \r segment
        rather than letting the main \n loop treat it as a normal line, otherwise the same
        content shows up twice in the viewer.
        """
        emitted_any = False
        while True:
            idx = self._buffer.find(b"\r")
            newline_idx = self._buffer.find(b"\n")
            if idx < 0 or (newline_idx >= 0 and newline_idx <= idx + 1):
                return emitted_any
            segment = self._buffer[:idx]
            self._buffer = self._buffer[idx + 1:]
            if not segment:
                continue
            line = segment.decode("utf-8", errors="replace") + "\r"
            if _should_log_emit("LogTailer.emit"):
                _diag_logger.info("LogTailer.emit path=%s line=%r", path, line[:200])
            self._on_line(line)
            emitted_any = True

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


class ProgressCollapseFilter:
    """折叠 ComfyUI 日志中含 \r 的进度刷新(典型来源:tqdm 进度条)。

    tqdm 在 conhost 里用 \r 重写同一行做进度动画;重定向到文件时,这些
    \r 刷新都被保留下来,有两种物理形态:

    1. **多行形态**:每个百分比占一行(行尾的 \r 被 LogTailer 剥掉),
       连续 N 行都是进度刷新。
    2. **单行多刷新形态**(bug 场景):整段进度被压在了一个物理行里,
       81 个百分比之间全是 \r,只有最后一个 \n 才换行。一行就有 80 个 \r。

    旧实现把整段折叠、留到下一个普通行才 emit 一个 "... N lines collapsed: <last>"
    标记行 —— 但任务跑几分钟期间用户看不到任何进度,体验非常糟。
    新实现改成「实时刷出」:

    - 每次 feed 看到新值(与上次 live emit 的 segment 不同)且距上次 live emit
      >= _LIVE_INTERVAL 秒,emit 一条 "[progress] <segment>" —— 让用户看到进度在动
    - 同值重复 feed(典型场景:tqdm 在两个采样步骤之间重绘同一帧)不重复 emit
    - 普通行到达时,先吐一条 "... N updates: <last>" 总结(标记这一段进度累计多少帧),
      再吐本行,并清空状态 —— 下一次进度可以从 0 开始重新累计
    - flush() 在 tail 结束时收尾:有累积就吐一条总结

    速率限(_LIVE_INTERVAL)存在的意义:tqdm 一次写盘会把整段多帧压在一条物理行里,
    LogTailer 切 \r 段后可能在毫秒级内连续 emit 几十条 "[progress]",速率限让 burst
    情况只露第一帧,其余静默累计到 summary(避免 UI 闪屏)。tqdm 真实跨步刷新间隔
    通常几百毫秒到几秒,远大于速率限,所以正常 sampling 期间每帧新值都能看到。

    API 是流式的,每次 feed 一行(已去掉末尾换行),返回 emit 的行列表。
    调用方把所有 emit 行原样追加到 UI 控件。
    """

    # live emit 之间的最小时间间隔(秒)。tqdm 默认 mininterval 在非 tty 下
    # 通常 >= 0.5s,这里取 0.3s 是为了 burst 场景下 millisecond 级连续 feed
    # 也只 emit 一帧;真实跨步刷新不会受影响。
    _LIVE_INTERVAL = 0.3

    def __init__(self) -> None:
        self._refresh_count: int = 0          # 累计的进度刷新次数(\r 个数)
        self._last_refresh: str = ""          # 最后一次刷新的文本(已剥多余 \r)
        self._last_live_segment: str = ""     # 上次 live emit 的 segment(同值不重复 emit)
        self._last_live_emit_ts: float = 0.0  # 上次 live emit 的 monotonic 时间

    @staticmethod
    def _last_segment(line: str) -> str:
        """从含 \r 的行里取出最后一段(最后一次刷新的文本)。

        "a\rb\rc" -> "c"; "a\rb\r" -> "a"(末尾空段忽略,回到上一个非空)。
        全空段时返回空串。
        """
        # 按 \r 切,从后往前找第一个非空段
        for seg in reversed(line.split("\r")):
            if seg:
                return seg
        return ""

    def feed(self, line: str) -> List[str]:
        """输入一行,返回 emit 的行列表。"""
        if "\r" not in line:
            # 普通行:如果之前在折叠进度,先吐一个总结标记行,再吐本行,并清状态
            if self._refresh_count > 0:
                count = self._refresh_count
                last = self._last_refresh
                self._refresh_count = 0
                self._last_refresh = ""
                self._last_live_segment = ""
                self._last_live_emit_ts = 0.0
                return [self._summary(count, last), line]
            return [line]
        # 含 \r 的进度行:累计刷新次数,只记最后一次刷新文本
        # 一行里多个 \r 算多次刷新(\r 个数 = 段数 - 1)
        n_refresh_in_line = line.count("\r")
        self._refresh_count += n_refresh_in_line
        last_seg = self._last_segment(line)
        if last_seg:
            self._last_refresh = last_seg
        # 新值(与上次 live emit 的 segment 不同)且距上次 emit 够久 -> 实时 emit
        # 同值重复 / 距上次 emit 太近(< _LIVE_INTERVAL)则静默累计,不刷屏
        if last_seg and last_seg != self._last_live_segment:
            import time as _time
            now = _time.monotonic()
            if now - self._last_live_emit_ts >= self._LIVE_INTERVAL:
                self._last_live_segment = last_seg
                self._last_live_emit_ts = now
                return [self._live_marker(self._refresh_count, last_seg)]
        return []

    def flush(self) -> List[str]:
        """文件结束 / 停止 tail 时调用,返回剩余的折叠总结。"""
        if self._refresh_count > 0:
            count = self._refresh_count
            last = self._last_refresh
            self._refresh_count = 0
            self._last_refresh = ""
            self._last_live_segment = ""
            self._last_live_emit_ts = 0.0
            return [self._summary(count, last)]
        return []

    @classmethod
    def _summary(cls, count: int, last: str) -> str:
        """生成折叠总结行(在普通行前或 flush 时 emit)。

        措辞从 "lines collapsed" 改成 "updates":现在每帧新值都会 live emit,
        这里的 N 表示「这一段进度里累计了多少帧」,而不是"被折叠掉的数量"。

        last 是最后一次刷新的原文(如 "tracking: 100%|████| 81/81")。
        不用 repr()——repr 会把整串(含 unicode 块字符)包成乱码;
        直接拼原文,UI 能正确渲染,保存为纯文本也干净。
        """
        if last:
            return f"... {count} updates: {last}"
        return f"... {count} updates"

    @classmethod
    def _live_marker(cls, count: int, last: str) -> str:
        """实时进度标记行(每帧新值各 emit 一条,带 [progress] 前缀便于识别)。

        count 是当前累计刷新次数(包含本次),方便用户看出进度跳了多少帧。
        """
        if last:
            return f"[progress #{count}] {last}"
        return f"[progress #{count}]"


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
            self._filter = ProgressCollapseFilter()
            self._paused = False
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
            self._active_progress = ""
            # Multi-\r 行 first segment matching log-prefix pattern is preserved.
            # Subsequent \r segments (tqdm progress frames) only update the progress
            # part. Matches ComfyUI frontend console behavior.
            self._active_progress_prefix = ""
            # Was the previous line a \r segment? Used to detect "new multi-\r line first segment".
            self._last_segment_was_cr = False
            self._setup_ui()

        # 最近历史日志的行数上限(用户首次切到日志页时回填这么多行)。
        # 太大→首次进入卡;太小→看不到上下文。500 行覆盖一次完整启动序列。
        RECENT_HISTORY_LINES = 500
        # 批量渲染 flush 间隔。tailer 每 50ms 读一次,这里也 50ms 攒一批,
        # 让实时跟随的延迟感 < 100ms 且不逐行卡。
        _BATCH_INTERVAL_MS = 50

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
            """
            if self._log_path is None:
                return
            try:
                lines = read_tail_lines(self._log_path, self.RECENT_HISTORY_LINES)
            except Exception:
                return
            for line in lines:
                # 历史行也是从原始文件读出来的, 会含 ANSI SGR 代码
                # (例如 Python logging 输出的 \x1b[1m\x1b[31m[ERROR]\x1b[0m) -> QTextBrowser 里\x1b不可见
                # 会留下 [1m[31m[0m 这种“残乙”。走 filter 之前先剥 ANSI,与实时行一致。
                clean = strip_ansi(line)
                # 走折叠过滤器(与实时行一致),结果入批量缓冲
                if self.collapse_checkbox.isChecked():
                    for out in self._filter.feed(clean):
                        self._enqueue_batch(out)
                else:
                    self._enqueue_batch(clean)
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
            self.collapse_checkbox = QtWidgets.QCheckBox("折叠连续进度")
            self.collapse_checkbox.setChecked(True)
            self.collapse_checkbox.toggled.connect(self._on_collapse_toggled)
            controls.addWidget(self.collapse_checkbox)

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
            if self._active_progress:
                self._finalize_active_progress()
            flushed = self._filter.flush()
            for line in flushed:
                self._append_line(line)
            self.logger.info(
                "stop_tailing path=%s receivers_before=%d tailer_alive_before=%s flushed_lines=%d",
                self._log_path, receivers_before, tailer_alive, len(flushed),
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
                return
            if self.collapse_checkbox.isChecked() and "\r" in line:
                # Virtual terminal: \r overwrites current active line.
                # First segment of a multi-\r line is preserved as prefix if it looks
                # like a log line (level marker or ComfyUI node ID).
                progress = ProgressCollapseFilter._last_segment(line)
                if progress:
                    is_first_cr = not self._last_segment_was_cr
                    self._set_active_progress(progress, is_first_cr=is_first_cr)
                self._last_segment_was_cr = True
                return
            # Normal line: reset state, finalize old active progress, run filter.
            self._last_segment_was_cr = False
            if self._active_progress or self._active_progress_prefix:
                self._finalize_active_progress()
            if self.collapse_checkbox.isChecked():
                for out in self._filter.feed(line):
                    self._append_line(out)
            else:
                self._append_line(line)

        def _set_active_progress(self, line: str, *, is_first_cr: bool = False) -> None:
            """Update active progress line.

            is_first_cr=True means this is the first segment of a new multi-\r line.
            Detect whether it is a log prefix (level marker or ComfyUI node ID) and
            preserve it, or treat it as a normal progress frame.
            """
            clean = strip_ansi(line)
            if is_first_cr:
                if _LOG_LEVEL_MARKER_RE.search(clean) or _NODE_ID_RE.match(clean):
                    self._active_progress_prefix = clean
                    self._active_progress = ""
                else:
                    self._active_progress_prefix = ""
                    self._active_progress = clean
            else:
                self._active_progress = clean
            self._enqueue_batch(None)

        def _finalize_active_progress(self) -> None:
            self._flush_batch()
            cursor = self.text_edit.textCursor()
            cursor.movePosition(QtGui.QTextCursor.End)
            cursor.insertBlock()
            self._active_progress = ""
            self._active_progress_prefix = ""

        def _append_line(self, line: str) -> None:
            """处理一行日志:剥 ANSI、记录未读、入批量缓冲(不直接写 QTextEdit)。

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
            """普通行入缓冲；None 表示只触发活动进度刷新。"""
            if line is not None:
                self._batch_buffer.append(line)
            if self._batch_timer is None:
                self._batch_timer = QtCore.QTimer(self)
                self._batch_timer.setSingleShot(True)
                self._batch_timer.timeout.connect(self._flush_batch)
            if not self._batch_timer.isActive():
                self._batch_timer.start(self._BATCH_INTERVAL_MS)

        def _flush_batch(self) -> None:
            """把缓冲里的行一次性 append 到 QTextEdit(一次 insertText,一次滚动)。

            批量化是关键:把 N 次 insertText(每次触发富文本布局重算)合并成 1 次,
            实时跟随(行流)和历史回填(几百行)都只做 O(1) 次 DOM 写入。
            """
            if not self._batch_buffer and not self._active_progress and not self._active_progress_prefix:
                return
            batch_size = len(self._batch_buffer)
            text = "\n".join(self._batch_buffer)
            self._batch_buffer.clear()
            if _should_log_emit("flush_batch"):
                self.logger.info("flush_batch size=%d first_line=%r", batch_size, text.splitlines()[0][:120] if text else "")
            # moveCursor + insertText 一次写整批;document 的 maximumBlockCount 自动裁老的
            cursor = self.text_edit.textCursor()
            cursor.movePosition(QtGui.QTextCursor.End)
            if self._active_progress or self._active_progress_prefix:
                cursor.select(QtGui.QTextCursor.BlockUnderCursor)
                cursor.removeSelectedText()
                if text:
                    cursor.insertText(text + "\n")
                # Combine prefix (log line) with progress (tqdm frame) so they show
                # on the same visual line, matching ComfyUI web console behavior.
                full_active = self._active_progress_prefix + self._active_progress
                cursor.insertText(full_active)
            elif text:
                cursor.insertText(text + "\n")
            # 滚到底(整批一次)
            bar = self.text_edit.verticalScrollBar()
            if bar is not None:
                bar.setValue(bar.maximum())


        def _on_pause_toggled(self, checked: bool) -> None:
            self._paused = checked
            self.pause_btn.setText("继续" if checked else "暂停")

        def _on_clear_clicked(self) -> None:
            self.text_edit.clear()
            self._active_progress = ""
            # 重置 filter 状态(避免之前积累的 \r 计数影响下一段)
            self._filter = ProgressCollapseFilter()

        def _on_collapse_toggled(self, checked: bool) -> None:
            if self._active_progress or self._active_progress_prefix:
                self._finalize_active_progress()
            # Reset filter and prefix state
            self._filter = ProgressCollapseFilter()
            self._last_segment_was_cr = False

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