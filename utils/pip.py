"""
pip 工具模块
提供 pip 可执行文件检测、包版本查询、安装和更新功能
"""

import logging
from pathlib import Path, PurePosixPath
from typing import Optional, Union, Dict, Any, Iterable, List
from utils.common import run_hidden
import os
import sys


def compute_pip_executable(python_exec: Union[str, Path]) -> Path:
    if os.name == "nt":
        python_path = Path(python_exec).resolve()
        return python_path.parent.parent / "Scripts" / "pip.exe"

    if sys.platform == "win32":
        python_path = PurePosixPath(str(python_exec))
        return python_path.parent.parent / "bin" / "pip"

    python_path = Path(python_exec).resolve()
    return python_path.parent.parent / "bin" / "pip"


def get_package_version(
    package_name: str,
    python_exec: Union[str, Path],
    logger: Optional[logging.Logger] = None,
    timeout: int = 10,
) -> Optional[str]:
    if logger is None:
        logger = logging.getLogger(__name__)
    # pip show 不接受 specifier（如 transformers>=4.50.3），会返回 rc=1。
    # 调用方传入的可能是从 requirements.txt 读出的 spec，
    # 这里先裁到包名再走 pip show，避免被当作包名查。
    pkg_name, _ver = _split_name_version(package_name or "")
    try:
        python_path = Path(python_exec).resolve()
        if not python_path.exists():
            try:
                logger.info(
                    "操作pip: 跳过查询 %s，Python 未找到: %s",
                    package_name,
                    str(python_path),
                )
            except Exception:
                pass
            return None
        if logger:
            try:
                logger.info("操作pip: 仅查询 %s 版本（python -m pip）", package_name)
            except Exception:
                pass
        # 下面的 pip show 实际使用裁后的 pkg_name，但日志仍然输出原 spec
        # 以便人能看出为什么查这个包。
        r = run_hidden(
            [str(python_path), "-m", "pip", "show", pkg_name],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                if line.startswith("Version:"):
                    ver = line.split(":", 1)[1].strip()
                    return ver
            return None
        pip_exe = compute_pip_executable(python_path)
        if pip_exe.exists():
            if logger:
                try:
                    logger.info("操作pip: 仅查询 %s 版本（pip.exe/pip）", package_name)
                except Exception:
                    pass
            r2 = run_hidden(
                [str(pip_exe), "show", pkg_name],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if r2.returncode == 0:
                for line in r2.stdout.splitlines():
                    if line.startswith("Version:"):
                        ver = line.split(":", 1)[1].strip()
                        return ver
                return None
        return None
    except Exception:
        return None


def install_or_update_package(
    package_name: str,
    python_exec: Union[str, Path],
    index_url: Optional[str] = None,
    upgrade: bool = True,
    logger: Optional[logging.Logger] = None,
    on_progress=None,
) -> Dict[str, Any]:
    """Install or upgrade a single package, optionally streaming pip progress.

    ``on_progress`` follows the ``(text, percent)`` convention where ``text``
    is a human-readable status line and ``percent`` is an optional 0-100
    value (``None`` means indeterminate). When provided, the install runs
    via the streaming helper so pip's per-byte progress reaches the caller.
    """
    if logger is None:
        logger = logging.getLogger(__name__)
    # 保持原有字段不变，新增 error_code 作为规范化错误码（双写迁移）
    result: Dict[str, Any] = {
        "success": False,
        "updated": False,
        "up_to_date": False,
        "version": None,
        "error": None,
        "error_code": None,
    }
    try:
        python_path = Path(python_exec).resolve()
        pip_exe = compute_pip_executable(python_path)
        if pip_exe.exists():
            cmd = [str(pip_exe), "install"]
        else:
            cmd = [str(python_path), "-m", "pip", "install"]
        if upgrade:
            cmd.append("-U")
        cmd.append(package_name)
        if index_url:
            cmd.extend(["-i", index_url])
        logger.info(f"执行 pip 操作: {' '.join(cmd)}")
        if on_progress is not None:
            pip_result = _run_pip_streaming(cmd, logger, on_progress)
        else:
            pip_result = run_hidden(cmd, capture_output=True, text=True)
        if pip_result.returncode == 0:
            result["success"] = True
            stdout = getattr(pip_result, "stdout", "") or ""
            result["updated"] = any(
                keyword in stdout
                for keyword in [
                    "Successfully installed",
                    "Installing collected packages",
                    "Successfully upgraded",
                ]
            )
            result["up_to_date"] = (
                "Requirement already satisfied" in stdout
            ) and not result["updated"]
            result["version"] = get_package_version(package_name, python_exec, logger)
            logger.info(
                f"pip 操作完成: {package_name}, 更新={result['updated']}, 已满足={result['up_to_date']}"
            )
        else:
            stderr = getattr(pip_result, "stderr", "") or ""
            result["error"] = f"pip 命令执行失败: {stderr}"
            # 规范化错误码：命令返回非零但未抛异常
            if "Could not find a version" in stderr:
                result["error_code"] = "VERSION_NOT_FOUND"
            else:
                result["error_code"] = "PIP_COMMAND_FAILED"
            logger.error(result["error"])
    except Exception as e:
        result["error"] = f"pip 操作异常: {str(e)}"
        # 规范化错误码：运行时异常
        result["error_code"] = "PIP_OPERATION_EXCEPTION"
        logger.error(result["error"])
    return result


def batch_install_packages(
    packages: List[str],
    python_exec: Union[str, Path],
    index_url: Optional[str] = None,
    upgrade: bool = True,
    logger: Optional[logging.Logger] = None,
) -> Dict[str, Dict[str, Any]]:
    if logger is None:
        logger = logging.getLogger(__name__)
    results = {}
    for package in packages:
        logger.info(f"开始处理包: {package}")
        results[package] = install_or_update_package(
            package, python_exec, index_url, upgrade, logger
        )
    return results


def _run_pip_streaming(cmd, logger, on_progress):
    """Run pip with streaming stdout/stderr, reporting progress via on_progress.

    pip 的进度和阶段信息会同时写到 stdout 和 stderr：下载阶段基本
    走 stdout，但安装阶段的关键消息（"Installing collected packages"、
    "Uninstalling"、"Installing"、"Successfully installed"、
    "Running setup.py install for" 等）大多走 stderr。原来只解析
    stdout 会导致进入安装阶段后 UI 卡在最后一条 Downloading 消息，
    看起来像死锁。

    现在把两个流共用一个行解析器；它们会并发地写"当前包"到同一个
    pkg_state，用轻量锁保护；on_progress 自身经 ui_post 投递到 UI
    线程，可以从任意线程调用。
    """
    import re as _re
    import subprocess
    import threading
    import time

    si = None
    cf = 0
    if os.name == "nt":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        cf = subprocess.CREATE_NO_WINDOW

    if logger:
        logger.info("执行 pip requirements 安装（流式）: %s", " ".join(map(str, cmd)))

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        startupinfo=si,
        creationflags=cf,
    )

    # 两个线程（主线程读 stdout，后台线程读 stderr）会同时改"当前包"，
    # 用锁保护。on_progress 的最终接收者是 UI 线程，不需要再保护。
    pkg_lock = threading.Lock()
    pkg_state = {"pkg": None}
    # 最近一次解析出真实行的时间。心跳线程据此判断要不要覆盖 UI。
    last_event_lock = threading.Lock()
    last_event_at = {"t": time.monotonic()}

    def _set_pkg(name):
        with pkg_lock:
            pkg_state["pkg"] = name

    def _get_pkg():
        with pkg_lock:
            return pkg_state["pkg"]

    def _mark_event():
        with last_event_lock:
            last_event_at["t"] = time.monotonic()

    def _handle_line(raw):
        """把一行 pip 输出翻译成 UI 进度消息。stdout 和 stderr 共用。"""
        try:
            if raw.startswith("Collecting "):
                token = raw[len("Collecting "):].split()[0]
                name = _re.split(r"[><=!]", token)[0].split("[")[0]
                _set_pkg(name)
                on_progress(f"正在收集依赖: {name}")
                return

            if raw.startswith("Downloading "):
                sm = _re.search(r"\(([^)]+)\)", raw)
                size = sm.group(1).strip() if sm else ""
                if not _get_pkg():
                    url = raw.split("Downloading ", 1)[1].split("(")[0].strip()
                    _set_pkg(url.split("/")[-1].split("-")[0])
                p = _get_pkg()
                on_progress(f"正在下载 {p} ({size})" if size else f"正在下载 {p}")
                return

            if raw.startswith("Installing collected packages"):
                tail = raw.split(":", 1)[-1].strip() if ":" in raw else ""
                on_progress(
                    "正在安装依赖包" + (f": {tail}" if tail else "")
                )
                return

            if raw.startswith("Attempting uninstall:"):
                m = _re.search(r"Attempting uninstall:\s*(\S+)", raw)
                if m:
                    _set_pkg(m.group(1))
                    on_progress(f"正在清理旧版: {m.group(1)}")
                return

            if raw.startswith("Uninstalling "):
                # "Uninstalling comfyui-foo-1.2.3:" — pkg 是 "-<数字>" 之前的部分
                m = _re.search(r"Uninstalling\s+([A-Za-z0-9_.\-]+)-\d", raw)
                if m:
                    _set_pkg(m.group(1))
                    on_progress(f"正在卸载: {m.group(1)}")
                return

            if raw.startswith("Installing ") and not raw.startswith(
                "Installing collected"
            ):
                # "Installing comfyui-foo-1.2.3" — pkg 名是 "-<数字>" 之前的部分
                m = _re.search(
                    r"Installing\s+([A-Za-z0-9_.\-]+)-\d", raw
                )
                if m:
                    _set_pkg(m.group(1))
                    on_progress(f"正在安装: {m.group(1)}")
                return

            if raw.startswith("Successfully installed "):
                tail = raw[len("Successfully installed "):].strip()
                on_progress(f"已安装: {tail}")
                return

            if raw.startswith("Successfully uninstalled "):
                tail = raw[len("Successfully uninstalled "):].strip()
                on_progress(f"已卸载: {tail}")
                return

            if raw.startswith("Running setup.py install for "):
                # "Running setup.py install for legacy-pkg: started"
                m = _re.search(
                    r"Running setup\.py install for\s+(\S+)", raw
                )
                if m:
                    name = m.group(1).rstrip(":")
                    on_progress(
                        f"正在编译: {name}（首次安装需要编译，请稍候）"
                    )
                return

            if raw.startswith("Found existing installation:"):
                # "Found existing installation: bar 1.0" 或 "bar-1.0"
                m = _re.search(
                    r"Found existing installation:\s+([A-Za-z0-9_.\-]+?)(?:[\s-]\d|$)",
                    raw,
                )
                if m:
                    _set_pkg(m.group(1))
                return

            # pip progress bar: "11.1/22.2 MB" or "2.2M/22.2M"
            pm = _re.search(
                r"([\d.]+)\s*/\s*([\d.]+)\s*([kKmMgG][bB]?)\b", raw
            )
            if pm and _get_pkg():
                cur, tot, unit = pm.group(1), pm.group(2), pm.group(3)
                on_progress(
                    f"正在下载 {_get_pkg()}  {cur} {unit} / {tot} {unit}"
                )
        except Exception:
            # 解析异常不能拖垮后台线程
            pass
        else:
            # 没抛异常就算一次"真实事件"，告诉心跳线程：刚有活干。
            _mark_event()

    def _drain(stream, line_sink, byte_sink):
        """按行把 stream 抽干：line_sink 收解码后的行（stdout 用），
        byte_sink 收原始字节（stderr 用，保持 CompletedProcess.stderr
        原始内容）；每解析出一行就调一次 _handle_line 推 UI。"""
        buf = b""
        try:
            while True:
                chunk = stream.read(512)
                if not chunk:
                    break
                if byte_sink is not None:
                    byte_sink.append(chunk)
                buf += chunk
                while True:
                    cr = buf.find(b"\r")
                    lf = buf.find(b"\n")
                    if cr < 0 and lf < 0:
                        break
                    pos = min(p for p in (cr, lf) if p >= 0)
                    raw = buf[:pos].decode("utf-8", errors="ignore").strip()
                    buf = buf[pos + 1:]
                    if raw:
                        line_sink.append(raw)
                        _handle_line(raw)
        except Exception:
            pass
        if buf:
            raw = buf.decode("utf-8", errors="ignore").strip()
            if raw:
                line_sink.append(raw)
                _handle_line(raw)

    stderr_parts = []
    stderr_thread = threading.Thread(
        target=_drain,
        args=(proc.stderr, [], stderr_parts),
        daemon=True,
    )
    stderr_thread.start()

    # 心跳线程：pip 在解析依赖/排队下载阶段可能 5~30s 都不打任何 stdout/stderr，
    # 不打任何东西 UI 就一直卡在"开始安装…"。每 5s 看一下距上次"真实行"
    # 多久了，超过 5s 就推一条"正在解析/下载中…（已等待 Ns）"覆盖 UI，
    # 让用户知道 pip 还在跑。pip 一打新行就由 on_progress 立刻覆盖。
    heartbeat_start = time.monotonic()
    heartbeat_stop = threading.Event()

    def _heartbeat():
        while not heartbeat_stop.is_set():
            # 5s 检查一次；用 Event.wait 让 stop 立刻响应
            if heartbeat_stop.wait(5.0):
                break
            with last_event_lock:
                since_last = time.monotonic() - last_event_at["t"]
            # 5s 内有真实行 → 不打扰 pip 的进度显示
            if since_last < 5.0:
                continue
            elapsed = int(time.monotonic() - heartbeat_start)
            try:
                on_progress(
                    f"正在解析依赖/下载中…（已等待 {elapsed}s，"
                    f"如长时间停留请检查网络）"
                )
            except Exception:
                # on_progress 自身出问题不能拖垮后台线程
                pass

    heartbeat_thread = threading.Thread(target=_heartbeat, daemon=True)
    heartbeat_thread.start()

    stdout_lines = []
    try:
        _drain(proc.stdout, stdout_lines, None)
    finally:
        # 退出前一定要停心跳，否则它会一直打 on_progress
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=2)

    proc.wait()
    stderr_thread.join(timeout=5)
    stderr_out = b"".join(stderr_parts).decode("utf-8", errors="ignore")

    if logger:
        logger.info("pip 流式安装完成: rc=%d", proc.returncode)

    return subprocess.CompletedProcess(
        args=cmd,
        returncode=proc.returncode,
        stdout="\n".join(stdout_lines),
        stderr=stderr_out,
    )


import re as _re_missing

_MISSING_PKG_RE = _re_missing.compile(
    r"Could not find a version that satisfies the requirement\s+"
    r"([A-Za-z0-9_.\-]+\s*[><=!~]+\s*[A-Za-z0-9_.+\-]+)"
)


def _parse_missing_packages(stderr):
    """Extract package specs that pip could not find a version for."""
    if not stderr:
        return []
    seen = set()
    out = []
    for line in stderr.splitlines():
        m = _MISSING_PKG_RE.search(line)
        if not m:
            continue
        spec = m.group(1).strip()
        if spec in seen:
            continue
        seen.add(spec)
        out.append(spec)
    return out


def _filter_requirements(req_path, missing):
    """Write a filtered requirements file with missing-package lines commented out."""
    if not missing:
        return req_path
    try:
        text = req_path.read_text(encoding="utf-8")
    except Exception:
        return req_path
    out_lines = []
    matched = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            out_lines.append(line)
            continue
        is_missing = False
        for spec in missing:
            if spec in line:
                is_missing = True
                matched = True
                break
        out_lines.append(("# " + line) if is_missing else line)
    if not matched:
        return req_path
    filtered = req_path.with_suffix(req_path.suffix + ".filtered")
    try:
        filtered.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    except Exception:
        return req_path
    return filtered

def _parse_requirements_file(req_path) -> List[str]:
    """Extract package specs from a pip requirements file.

    Skips empty lines, comments (lines starting with ``#`` and inline ``#``),
    command-line options (``-r``, ``-e``, ``--index-url`` and friends), and
    strips environment markers (``pkg ; python_version < "3.10"``). The
    remaining non-empty lines are returned as package specs that can be fed
    directly to ``pip install <spec>``.
    """
    try:
        text = Path(req_path).read_text(encoding="utf-8")
    except Exception:
        return []
    specs: List[str] = []
    for raw in text.splitlines():
        # strip inline comments
        line = raw.split("#", 1)[0].strip() if "#" in raw else raw.strip()
        if not line:
            continue
        # skip pip options and -r / -e includes
        if line.startswith("-"):
            continue
        # strip environment markers
        if ";" in line:
            line = line.split(";", 1)[0].strip()
        if line:
            specs.append(line)
    return specs


def _split_name_version(spec: str):
    """Pull ``(name, version)`` out of a requirement spec.

    For ``comfyui-frontend-package==1.45.15`` returns
    ``("comfyui-frontend-package", "1.45.15")``; for ``torch>=2.0`` returns
    ``("torch", ">=2.0")``; for ``requests`` returns ``("requests", "")``.
    """
    import re as _re_split

    m = _re_split.match(
        r"^\s*([A-Za-z0-9_.\-]+)\s*([><=!~].*)?\s*$",
        spec,
    )
    if not m:
        return spec, ""
    return m.group(1), (m.group(2) or "").strip()


def _retry_install_remaining(
    req_path,
    missing,
    original_cmd,
    logger,
    on_progress=None,
):
    """Skip the packages that pip could not find and install the rest.

    Independent of ``install_requirements_file`` so callers (and tests) can
    exercise the partial-retry path on its own. Returns a dict with the
    same shape as ``install_requirements_file``'s result, plus a
    ``partial`` flag.

    The caller is responsible for unlinking the temporary filtered
    requirements file (this function returns the path so the caller can
    clean up after merging the result).
    """
    if logger is None:
        logger = logging.getLogger(__name__)
    out = {
        "success": False,
        "partial": False,
        "updated": False,
        "up_to_date": False,
        "error": None,
        "error_code": None,
        "installed": [],
        "satisfied": [],
        "missing": list(missing),
        "filtered_path": None,
    }
    try:
        filtered_path = _filter_requirements(req_path, set(missing))
    except Exception as e:
        logger.error("\u8fc7\u6ee4 requirements \u5931\u8d25: %s", e)
        out["error"] = f"\u8fc7\u6ee4 requirements \u5931\u8d25: {e}"
        out["error_code"] = "PIP_FILTER_FAILED"
        return out
    if filtered_path == req_path:
        out["filtered_path"] = None
        return out
    out["filtered_path"] = filtered_path
    retry_cmd = list(original_cmd)
    for i, c in enumerate(retry_cmd):
        if c == str(req_path):
            retry_cmd[i] = str(filtered_path)
            break
    logger.info(
        "\u8df3\u8fc7\u955c\u50cf\u5c1a\u672a\u540c\u6b65\u7684\u5305\uff0c\u5b89\u88c5\u5176\u4f59\u4f9d\u8d56: %s",
        ", ".join(missing),
    )
    if on_progress:
        retry_result = _run_pip_streaming(retry_cmd, logger, on_progress)
    else:
        retry_result = run_hidden(retry_cmd, capture_output=True, text=True)
    if retry_result.returncode == 0:
        out["success"] = True
        out["partial"] = True
        out["updated"] = True
        out["up_to_date"] = False
        retry_stdout = getattr(retry_result, "stdout", "") or ""
        try:
            import re as _re_retry
            for line in retry_stdout.splitlines():
                if "Successfully installed" in line:
                    tail = line.split("Successfully installed", 1)[1].strip()
                    for t in tail.split():
                        m = _re_retry.match(
                            r"^([A-Za-z0-9_.\-]+)-([0-9][A-Za-z0-9_.+\-]*)$",
                            t,
                        )
                        if m:
                            out["installed"].append(f"{m.group(1)}-{m.group(2)}")
                        else:
                            out["installed"].append(t)
                elif "Requirement already satisfied" in line:
                    m = _re_retry.search(
                        r"Requirement already satisfied:\s*"
                        r"([A-Za-z0-9_.\-]+).*?"
                        r"\(.*?version\s+([A-Za-z0-9_.+\-]+)",
                        line,
                    )
                    if m:
                        out["satisfied"].append(
                            f"{m.group(1)}-{m.group(2)}"
                        )
        except Exception:
            pass
        logger.info(
            "\u90e8\u5206\u4f9d\u8d56\u5b8c\u6210\u5b89\u88c5\uff08\u8df3\u8fc7\u7684\u5305: %s\uff09",
            ", ".join(missing),
        )
    else:
        retry_stderr = getattr(retry_result, "stderr", "") or ""
        out["error"] = (
            f"\u8df3\u8fc7\u672a\u540c\u6b65\u5305\u540e\u91cd\u8bd5\u4ecd\u5931\u8d25: {retry_stderr[:200]}"
        )
        out["error_code"] = "PIP_REQUIREMENTS_COMMAND_FAILED"
        logger.error(out["error"])
    return out



def install_requirements_file(
    requirements_file: Union[str, Path],
    python_exec: Union[str, Path],
    index_url: Optional[str] = None,
    upgrade: bool = False,
    logger: Optional[logging.Logger] = None,
    on_progress=None,
    ignore_pkgs: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Install each package in the requirements file individually.

    ``pip install -r requirements.txt`` bails out on the first error, so
    one missing or conflicting package stops the rest from being installed.
    We instead parse the file and run ``pip install <spec>`` for each
    package, then aggregate the per-package results. One failure does not
    block the others.

    ``ignore_pkgs`` is an optional iterable of package names (case-insensitive)
    that should be left untouched — e.g. ``{"torch", "numpy"}``.  Frozen
    specs are not pip-installed and do not appear in installed/satisfied/
    missing/failed.  They are returned in ``frozen`` as a list of
    ``{name, spec}`` dicts so the caller can surface them.

    Returns a result dict with the same top-level shape as before plus a
    ``failed`` list of ``{spec, reason, stderr}`` for non-mirror errors::

        {
            "success": bool,            # all non-frozen packages installed ok
            "partial": bool,            # at least one non-frozen installed
            "updated": bool,            # at least one was actually new
            "up_to_date": bool,         # everything was already satisfied
            "error": str | None,
            "error_code": str | None,
            "installed": ["name-version", ...],
            "satisfied": ["name-version", ...],
            "missing": ["pkg==1.0", ...],          # 镜像未同步
            "failed": [{"spec": ..., "reason": ..., "stderr": ...}, ...],
            "frozen": [{"name": ..., "spec": ...}, ...],  # 黑名单跳过
        }
    """
    if logger is None:
        logger = logging.getLogger(__name__)
    result: Dict[str, Any] = {
        "success": False,
        "partial": False,
        "updated": False,
        "up_to_date": False,
        "error": None,
        "error_code": None,
        "installed": [],
        "satisfied": [],
        "missing": [],
        "failed": [],
        "frozen": [],
    }
    frozen_names: set = set()
    if ignore_pkgs:
        for n in ignore_pkgs:
            try:
                frozen_names.add(str(n).strip().lower())
            except Exception:
                pass
    try:
        req_path = Path(requirements_file).resolve()
        if not req_path.exists():
            result["error"] = f"requirements 文件不存在: {str(req_path)}"
            result["error_code"] = "REQUIREMENTS_FILE_NOT_FOUND"
            logger.error(result["error"])
            return result

        specs = _parse_requirements_file(req_path)
        if not specs:
            result["up_to_date"] = True
            result["success"] = True
            return result

        # 黑名单过滤：需要升级的 specs 与 frozen 名单交集为空时才进入主循环
        active_specs: List[str] = []
        for spec in specs:
            name, _ver = _split_name_version(spec)
            if name and name.strip().lower() in frozen_names:
                result["frozen"].append({"name": name, "spec": spec})
                continue
            active_specs.append(spec)
        skipped = len(specs) - len(active_specs)
        if skipped:
            try:
                logger.info(
                    "跳过黑名单依赖 %d 项：%s",
                    skipped,
                    ", ".join(item["name"] for item in result["frozen"]),
                )
            except Exception:
                pass

        if not active_specs:
            # 全部都在黑名单里，认为“已最新”，不报错
            result["up_to_date"] = True
            result["success"] = True
            return result

        logger.info(
            "开始逐个安装 requirements: %s（共 %d 项，跳过 %d 项）",
            req_path.name,
            len(active_specs),
            skipped,
        )

        any_new_install = False
        total = len(active_specs)
        for idx, spec in enumerate(active_specs, start=1):
            name, _ver = _split_name_version(spec)
            # 每个包都给调用方报上“正在更新 idx/total: spec”作为背景状态，
            # 让进度对话框能看到当前是哪个包、剩什么。
            overall_pct = int(idx / total * 100) if total else 100

            def _pkg_progress(text, percent=None, _spec=spec, _idx=idx, _total=total, _pct=overall_pct):
                if on_progress is None:
                    return
                # 底层 pip 会输出“正在下载 X/Y MB”类的子状态（tail）。
                # 之前用“双空格拼接 + 30 字符截断”，会把长 pkg 名（如
                # comfyui-workflow-templates-media-other）隐藏到省略号里。
                # 现在改为：tail 换行、不裁断。对应弹窗 setWordWrap(True)
                # 会自动水平叠加；多行不够也会自动绕到下一行。
                head = f"正在更新依赖 {_idx}/{_total}：{_spec}"
                if text:
                    status = f"{head}\n{text}"
                else:
                    status = head
                on_progress(status, _pct)

            # 无版本要求的 spec（如 scipy）：本地已安装就直接记入 satisfied，
            # 不再走 pip install -U。这能省掉一次 pip 解析 / 下载 / 构建开销。
            # 有版本锁定（==X.Y.Z）的 spec 仍按原逻辑走，避免覆盖用户预期。
            if not _ver:
                try:
                    current_ver = get_package_version(name, python_exec, logger)
                except Exception:
                    current_ver = None
                if current_ver:
                    _pkg_progress(f"已安装 {current_ver}，跳过安装")
                    result["satisfied"].append(f"{name}-{current_ver}")
                    try:
                        logger.info(
                            "跳过无版本要求的依赖 %s（本地已安装 %s）",
                            name,
                            current_ver,
                        )
                    except Exception:
                        pass
                    continue
                # 本地没有该包，下面继续走正常安装流程

            # 每进入一个包，先报一次“开始安装”，确保进度不会卡在某个包里
            _pkg_progress("开始安装…")

            try:
                pkg_result = install_or_update_package(
                    spec,
                    python_exec,
                    index_url=index_url,
                    upgrade=upgrade,
                    logger=logger,
                    on_progress=_pkg_progress,
                )
            except Exception as e:
                logger.error("安装 %s 时异常: %s", spec, e)
                # 封装异常为 install_or_update_package 的返回结果，
                # 让后面的错误分支统一处理，不会遗漏进度事件
                _pkg_progress(f"安装异常: {e}")
                pkg_result = {
                    "success": False,
                    "updated": False,
                    "up_to_date": False,
                    "version": None,
                    "error": f"pip 操作异常: {e}",
                    "error_code": "PIP_OPERATION_EXCEPTION",
                }

            if pkg_result.get("success"):
                version = pkg_result.get("version") or ""
                label = f"{name}-{version}" if version else name
                if pkg_result.get("up_to_date"):
                    result["satisfied"].append(label)
                else:
                    result["installed"].append(label)
                    any_new_install = True
                continue

            err_code = pkg_result.get("error_code")
            stderr = pkg_result.get("error") or ""
            if err_code == "VERSION_NOT_FOUND":
                # 镜像未同步
                result["missing"].append(spec)
            else:
                # 其他错误（网络、权限、冲突...）
                short = stderr.strip().replace("\r", " ").replace("\n", " ")
                if len(short) > 200:
                    short = short[:200] + "…"
                result["failed"].append(
                    {
                        "spec": spec,
                        "reason": short or "未知错误",
                        "stderr": stderr,
                    }
                )

        # 汇总状态
        total_failed = len(result["missing"]) + len(result["failed"])
        if total_failed == 0:
            result["success"] = True
            result["up_to_date"] = not any_new_install
            result["updated"] = any_new_install
        else:
            # 至少部分成功
            if result["installed"] or result["satisfied"]:
                result["partial"] = True
                result["success"] = True
                result["updated"] = any_new_install
                if result["missing"] and not result["failed"]:
                    result["error_code"] = "VERSION_NOT_FOUND"
                elif result["failed"] and not result["missing"]:
                    result["error_code"] = "PIP_PARTIAL_FAILURE"
                else:
                    result["error_code"] = "PIP_PARTIAL_FAILURE"
            else:
                result["success"] = False
                if result["missing"]:
                    result["error_code"] = "VERSION_NOT_FOUND"
                    result["error"] = (
                        f"{len(result['missing'])} 个包未找到版本"
                    )
                else:
                    result["error_code"] = "PIP_REQUIREMENTS_COMMAND_FAILED"
                    result["error"] = (
                        f"{len(result['failed'])} 个包安装失败"
                    )
        logger.info(
            "requirements 安装汇总 %s: 安装 %d / 满足 %d / 失败 %d",
            req_path.name,
            len(result["installed"]),
            len(result["satisfied"]),
            total_failed,
        )
    except Exception as e:
        result["error"] = f"pip requirements 操作异常: {str(e)}"
        result["error_code"] = "PIP_REQUIREMENTS_OPERATION_EXCEPTION"
        logger.error(result["error"])
    return result
