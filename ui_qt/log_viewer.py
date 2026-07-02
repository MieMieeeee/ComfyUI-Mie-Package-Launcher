"""实时日志查看器:日志解析与进度折叠工具。"""
from typing import List


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