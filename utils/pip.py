"""
pip 工具模块
提供 pip 可执行文件检测、包版本查询、安装和更新功能
"""

import logging
from pathlib import Path
from typing import Optional, Union, Dict, Any, List
from utils.common import run_hidden
import os


def compute_pip_executable(python_exec: Union[str, Path]) -> Path:
    python_path = Path(python_exec).resolve()
    if os.name == 'nt':
        return python_path.parent.parent / 'Scripts' / 'pip.exe'
    else:
        return python_path.parent.parent / 'bin' / 'pip'


def get_package_version(package_name: str, python_exec: Union[str, Path], logger: Optional[logging.Logger] = None, timeout: int = 10) -> Optional[str]:
    if logger is None:
        logger = logging.getLogger(__name__)
    try:
        python_path = Path(python_exec).resolve()
        if not python_path.exists():
            try:
                logger.info("操作pip: 跳过查询 %s，Python 未找到: %s", package_name, str(python_path))
            except Exception:
                pass
            return None
        if logger:
            try:
                logger.info("操作pip: 仅查询 %s 版本（python -m pip）", package_name)
            except Exception:
                pass
        r = run_hidden([str(python_path), "-m", "pip", "show", package_name], capture_output=True, text=True, timeout=timeout)
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
            r2 = run_hidden([str(pip_exe), "show", package_name], capture_output=True, text=True, timeout=timeout)
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
    logger: Optional[logging.Logger] = None
) -> Dict[str, Any]:
    if logger is None:
        logger = logging.getLogger(__name__)
    result = {"success": False, "updated": False, "up_to_date": False, "version": None, "error": None}
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
            stdout = getattr(pip_result, 'stdout', '') or ''
            result["updated"] = any(keyword in stdout for keyword in [
                "Successfully installed",
                "Installing collected packages",
                "Successfully upgraded"
            ])
            result["up_to_date"] = ("Requirement already satisfied" in stdout) and not result["updated"]
            result["version"] = get_package_version(package_name, python_exec, logger)
            logger.info(f"pip 操作完成: {package_name}, 更新={result['updated']}, 最新={result['up_to_date']}")
        else:
            stderr = getattr(pip_result, 'stderr', '') or ''
            result["error"] = f"pip 命令执行失败: {stderr}"
            logger.error(result["error"])
    except Exception as e:
        result["error"] = f"pip 操作异常: {str(e)}"
        logger.error(result["error"])
    return result


def batch_install_packages(
    packages: List[str],
    python_exec: Union[str, Path],
    index_url: Optional[str] = None,
    upgrade: bool = True,
    logger: Optional[logging.Logger] = None
) -> Dict[str, Dict[str, Any]]:
    if logger is None:
        logger = logging.getLogger(__name__)
    results = {}
    for package in packages:
        logger.info(f"开始处理包: {package}")
        results[package] = install_or_update_package(package, python_exec, index_url, upgrade, logger)
    return results


def install_requirements_file(
    requirements_file: Union[str, Path],
    python_exec: Union[str, Path],
    index_url: Optional[str] = None,
    upgrade: bool = False,
    logger: Optional[logging.Logger] = None
) -> Dict[str, Any]:
    if logger is None:
        logger = logging.getLogger(__name__)
    result = {"success": False, "updated": False, "up_to_date": False, "error": None, "installed": [], "satisfied": []}
    try:
        req_path = Path(requirements_file).resolve()
        python_path = Path(python_exec).resolve()
        if not req_path.exists():
            result["error"] = f"requirements 文件不存在: {str(req_path)}"
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
        pip_result = run_hidden(cmd, capture_output=True, text=True)
        if pip_result.returncode == 0:
            result["success"] = True
            stdout = getattr(pip_result, 'stdout', '') or ''
            try:
                import re as _re
                for line in stdout.splitlines():
                    if "Successfully installed" in line:
                        tail = line.split("Successfully installed", 1)[1].strip()
                        toks = tail.split()
                        for t in toks:
                            m = _re.match(r"^([A-Za-z0-9_.\-]+)-([0-9][A-Za-z0-9_.+\-]*)$", t)
                            if m:
                                name = m.group(1)
                                ver = m.group(2)
                                result["installed"].append(f"{name}-{ver}")
                            else:
                                result["installed"].append(t)
                    elif "Requirement already satisfied" in line:
                        m = _re.search(r"Requirement already satisfied:\s*([A-Za-z0-9_.\-]+).*?\(.*?version\s+([A-Za-z0-9_.+\-]+)\)", line)
                        if m:
                            result["satisfied"].append(f"{m.group(1)}-{m.group(2)}")
                        else:
                            m2 = _re.search(r"Requirement already satisfied:\s*([A-Za-z0-9_.\-]+)", line)
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
            result["updated"] = ("Installing collected packages" in stdout) or ("Successfully installed" in stdout) or ("Successfully upgraded" in stdout)
            result["up_to_date"] = ("Requirement already satisfied" in stdout) and not result["updated"]
            logger.info(f"requirements 安装完成: {req_path.name}, 更新={result['updated']}, 最新={result['up_to_date']}")
        else:
            stderr = getattr(pip_result, 'stderr', '') or ''
            result["error"] = f"pip requirements 执行失败: {stderr}"
            logger.error(result["error"])
    except Exception as e:
        result["error"] = f"pip requirements 操作异常: {str(e)}"
        logger.error(result["error"])
    return result
