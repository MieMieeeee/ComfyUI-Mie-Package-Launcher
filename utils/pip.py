"""
pip 工具模块
提供 pip 可执行文件检测、包版本查询、安装和更新功能
"""

import logging
from pathlib import Path, PurePosixPath
from typing import Optional, Union, Dict, Any, List
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
        r = run_hidden(
            [str(python_path), "-m", "pip", "show", package_name],
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
                [str(pip_exe), "show", package_name],
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
) -> Dict[str, Any]:
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
                f"pip 操作完成: {package_name}, 更新={result['updated']}, 最新={result['up_to_date']}"
            )
        else:
            stderr = getattr(pip_result, "stderr", "") or ""
            result["error"] = f"pip 命令执行失败: {stderr}"
            # 规范化错误码：命令返回非零但未抛异常
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
    """Run pip with streaming stdout, reporting download progress via on_progress.

    Reads stdout treating both \\r and \\n as line delimiters, so pip's
    progress-bar updates are captured in real time.  Returns a
    CompletedProcess with full stdout/stderr for downstream parsing.
    """
    import re as _re
    import subprocess
    import threading

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

    # Drain stderr in background to avoid pipe deadlock
    stderr_parts = []

    def _drain():
        try:
            while True:
                c = proc.stderr.read(8192)
                if not c:
                    break
                stderr_parts.append(c)
        except Exception:
            pass

    stderr_thread = threading.Thread(target=_drain, daemon=True)
    stderr_thread.start()

    stdout_lines = []
    buf = b""
    pkg = None

    while True:
        chunk = proc.stdout.read(512)
        if not chunk:
            break
        buf += chunk
        # Process complete lines (delimited by \r or \n)
        while True:
            cr = buf.find(b"\r")
            lf = buf.find(b"\n")
            if cr < 0 and lf < 0:
                break
            pos = min(p for p in (cr, lf) if p >= 0)
            raw = buf[:pos].decode("utf-8", errors="ignore").strip()
            buf = buf[pos + 1 :]
            if not raw:
                continue
            stdout_lines.append(raw)
            try:
                if raw.startswith("Collecting "):
                    token = raw[len("Collecting ") :].split()[0]
                    pkg = _re.split(r"[><=!]", token)[0].split("[")[0]
                    on_progress(f"正在收集依赖: {pkg}")
                elif raw.startswith("Downloading "):
                    sm = _re.search(r"\(([^)]+)\)", raw)
                    size = sm.group(1).strip() if sm else ""
                    if not pkg:
                        url = raw.split("Downloading ", 1)[1].split("(")[0].strip()
                        pkg = url.split("/")[-1].split("-")[0]
                    on_progress(
                        f"正在下载 {pkg} ({size})" if size else f"正在下载 {pkg}"
                    )
                elif "Installing collected packages" in raw:
                    on_progress("正在安装依赖包...")
                else:
                    # pip progress bar: "11.1/22.2 MB" or "2.2M/22.2M"
                    pm = _re.search(
                        r"([\d.]+)\s*/\s*([\d.]+)\s*([kKmMgG][bB]?)\b", raw
                    )
                    if pm and pkg:
                        cur, tot, unit = pm.group(1), pm.group(2), pm.group(3)
                        on_progress(f"正在下载 {pkg}  {cur} {unit} / {tot} {unit}")
            except Exception:
                pass

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

def install_requirements_file(
    requirements_file: Union[str, Path],
    python_exec: Union[str, Path],
    index_url: Optional[str] = None,
    upgrade: bool = False,
    logger: Optional[logging.Logger] = None,
    on_progress=None,
) -> Dict[str, Any]:
    if logger is None:
        logger = logging.getLogger(__name__)
    # 保持原有字段不变，新增 error_code 作为规范化错误码（双写迁移）
    result: Dict[str, Any] = {
        "success": False,
        "updated": False,
        "up_to_date": False,
        "error": None,
        "error_code": None,
        "installed": [],
        "satisfied": [],
    }
    try:
        req_path = Path(requirements_file).resolve()
        python_path = Path(python_exec).resolve()
        if not req_path.exists():
            result["error"] = f"requirements 文件不存在: {str(req_path)}"
            result["error_code"] = "REQUIREMENTS_FILE_NOT_FOUND"
            logger.error(result["error"])
            return result
        pip_exe = compute_pip_executable(python_path)
        if pip_exe.exists():
            cmd = [str(pip_exe), "install"]
        else:
            cmd = [str(python_path), "-m", "pip", "install"]
        cmd.extend(["-r", str(req_path)])
        if index_url:
            cmd.extend(["-i", index_url])
        logger.info(f"执行 pip requirements 安装: {' '.join(cmd)}")
        if on_progress:
            pip_result = _run_pip_streaming(cmd, logger, on_progress)
        else:
            pip_result = run_hidden(cmd, capture_output=True, text=True)
        if pip_result.returncode == 0:
            result["success"] = True
            stdout = getattr(pip_result, "stdout", "") or ""
            try:
                import re as _re

                for line in stdout.splitlines():
                    if "Successfully installed" in line:
                        tail = line.split("Successfully installed", 1)[1].strip()
                        toks = tail.split()
                        for t in toks:
                            m = _re.match(
                                r"^([A-Za-z0-9_.\-]+)-([0-9][A-Za-z0-9_.+\-]*)$", t
                            )
                            if m:
                                name = m.group(1)
                                ver = m.group(2)
                                result["installed"].append(f"{name}-{ver}")
                            else:
                                result["installed"].append(t)
                    elif "Requirement already satisfied" in line:
                        m = _re.search(
                            r"Requirement already satisfied:\s*([A-Za-z0-9_.\-]+).*?\(.*?version\s+([A-Za-z0-9_.+\-]+)\)",
                            line,
                        )
                        if m:
                            result["satisfied"].append(f"{m.group(1)}-{m.group(2)}")
                        else:
                            m2 = _re.search(
                                r"Requirement already satisfied:\s*([A-Za-z0-9_.\-]+)",
                                line,
                            )
                            if m2:
                                result["satisfied"].append(m2.group(1))
                if result["installed"]:
                    for item in result["installed"]:
                        try:
                            logger.info(f"依赖变更: 安装/更新 {item}")
                        except Exception:
                            pass
                if result["satisfied"]:
                    try:
                        logger.info(f"依赖满足: {', '.join(result['satisfied'])}")
                    except Exception:
                        pass
            except Exception:
                pass
            result["updated"] = (
                ("Installing collected packages" in stdout)
                or ("Successfully installed" in stdout)
                or ("Successfully upgraded" in stdout)
            )
            result["up_to_date"] = (
                "Requirement already satisfied" in stdout
            ) and not result["updated"]
            logger.info(
                f"requirements 安装完成: {req_path.name}, 更新={result['updated']}, 最新={result['up_to_date']}"
            )
        else:
            stderr = getattr(pip_result, "stderr", "") or ""
            result["error"] = f"pip requirements 执行失败: {stderr}"
            result["error_code"] = "PIP_REQUIREMENTS_COMMAND_FAILED"
            missing = _parse_missing_packages(stderr)
            if missing:
                # 包名称或版本在当前镜像上尚未同步
                result["error_code"] = "VERSION_NOT_FOUND"
                result["missing"] = list(missing)
                logger.warning(
                    "pip 未找到版本: %s",
                    ", ".join(missing),
                )
                try:
                    filtered_path = _filter_requirements(req_path, set(missing))
                except Exception as e:
                    logger.error("过滤 requirements 失败: %s", e)
                    filtered_path = req_path
                if filtered_path != req_path:
                    retry_cmd = list(cmd)
                    for i, c in enumerate(retry_cmd):
                        if c == str(req_path):
                            retry_cmd[i] = str(filtered_path)
                            break
                    logger.info("跳过镜像尚未同步的包，安装其余依赖: %s", ", ".join(missing))
                    if on_progress:
                        retry_result = _run_pip_streaming(retry_cmd, logger, on_progress)
                    else:
                        retry_result = run_hidden(retry_cmd, capture_output=True, text=True)
                    if retry_result.returncode == 0:
                        result["success"] = True
                        result["partial"] = True
                        result["updated"] = True
                        result["up_to_date"] = False
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
                                            result["installed"].append(f"{m.group(1)}-{m.group(2)}")
                                        else:
                                            result["installed"].append(t)
                                elif "Requirement already satisfied" in line:
                                    m = _re_retry.search(
                                        r"Requirement already satisfied:\s*([A-Za-z0-9_.\-]+).*?\(.*?version\s+([A-Za-z0-9_.+\-]+)",
                                        line,
                                    )
                                    if m:
                                        result["satisfied"].append(f"{m.group(1)}-{m.group(2)}")
                        except Exception:
                            pass
                        logger.info("部分依赖完成安装")
                    else:
                        retry_stderr = getattr(retry_result, "stderr", "") or ""
                        logger.error("跳过未同步包后重试仍失败: %s", retry_stderr[:200])
                    try:
                        filtered_path.unlink()
                    except Exception:
                        pass
            logger.error(result["error"])
    except Exception as e:
        result["error"] = f"pip requirements 操作异常: {str(e)}"
        result["error_code"] = "PIP_REQUIREMENTS_OPERATION_EXCEPTION"
        logger.error(result["error"])
    return result
