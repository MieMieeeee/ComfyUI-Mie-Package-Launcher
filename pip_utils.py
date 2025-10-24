"""
pip 工具模块
提供 pip 可执行文件检测、包版本查询、安装和更新功能
"""

import subprocess
import logging
from pathlib import Path
from typing import Optional, Union, Dict, Any, List
from utils import run_hidden
import os


def compute_pip_executable(python_exec: Union[str, Path]) -> Path:
    """
    计算 pip 可执行文件路径
    
    Args:
        python_exec: Python 可执行文件路径
        
    Returns:
        pip 可执行文件路径
    """
    python_path = Path(python_exec).resolve()
    if os.name == 'nt':
        return python_path.parent.parent / 'Scripts' / 'pip.exe'
    else:
        # Try common venv layout; if missing, fallback to 'pip' on PATH via -m
        return python_path.parent.parent / 'bin' / 'pip'


def get_package_version(package_name: str, python_exec: Union[str, Path], logger: Optional[logging.Logger] = None, timeout: int = 10) -> Optional[str]:
    """
    获取已安装包的版本信息
    
    Args:
        package_name: 包名
        python_exec: Python 可执行文件路径
        logger: 日志记录器，可选
        timeout: 超时时间
        
    Returns:
        包版本字符串，如果未安装或查询失败则返回 None
    """
    if logger is None:
        logger = logging.getLogger(__name__)
        
    try:
        if logger:
            try:
                logger.info("操作pip: 仅查询 %s 版本（不会安装/更新；python -m pip）", package_name)
            except Exception:
                pass
        r = run_hidden([str(python_exec), "-m", "pip", "show", package_name], capture_output=True, text=True, timeout=timeout)
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                if line.startswith("Version:"):
                    ver = "v" + line.split(":")[1].strip()
                    return ver
            return None
        # Fallback to pip executable
        pip_exe = compute_pip_executable(python_exec)
        if pip_exe.exists():
            if logger:
                try:
                    logger.info("操作pip: 仅查询 %s 版本（不会安装/更新；pip.exe/pip）", package_name)
                except Exception:
                    pass
            r2 = run_hidden([str(pip_exe), "show", package_name], capture_output=True, text=True, timeout=timeout)
            if r2.returncode == 0:
                for line in r2.stdout.splitlines():
                    if line.startswith("Version:"):
                        ver = "v" + line.split(":")[1].strip()
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
    """
    安装或更新指定的包
    
    Args:
        package_name: 包名
        python_exec: Python 可执行文件路径
        index_url: PyPI 镜像 URL，可选
        upgrade: 是否升级到最新版本
        logger: 日志记录器，可选
        
    Returns:
        包含操作结果的字典，包含以下键：
        - success: 操作是否成功
        - updated: 是否发生了更新
        - up_to_date: 是否已是最新版本
        - version: 安装后的版本号
        - error: 错误信息（如果有）
    """
    if logger is None:
        logger = logging.getLogger(__name__)
        
    result = {
        "success": False,
        "updated": False,
        "up_to_date": False,
        "version": None,
        "error": None
    }
    
    try:
        pip_exe = compute_pip_executable(python_exec)
        
        # 构建命令
        if pip_exe.exists():
            cmd = [str(pip_exe), "install"]
        else:
            cmd = [str(python_exec), "-m", "pip", "install"]
            
        if upgrade:
            cmd.append("-U")
            
        cmd.append(package_name)
        
        if index_url:
            cmd.extend(["-i", index_url])
            
        logger.info(f"执行 pip 操作: {' '.join(cmd)}")
        
        # 执行安装/更新命令
        pip_result = run_hidden(cmd, capture_output=True, text=True)
        
        if pip_result.returncode == 0:
            result["success"] = True
            
            # 分析输出判断是否发生了更新
            stdout = getattr(pip_result, 'stdout', '') or ''
            result["updated"] = any(keyword in stdout for keyword in [
                "Successfully installed", 
                "Installing collected packages", 
                "Successfully upgraded"
            ])
            result["up_to_date"] = ("Requirement already satisfied" in stdout) and not result["updated"]
            
            # 获取安装后的版本号
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
    """
    批量安装或更新多个包
    
    Args:
        packages: 包名列表
        python_exec: Python 可执行文件路径
        index_url: PyPI 镜像 URL，可选
        upgrade: 是否升级到最新版本
        logger: 日志记录器，可选
        
    Returns:
        包含每个包操作结果的字典
    """
    if logger is None:
        logger = logging.getLogger(__name__)
        
    results = {}
    
    for package in packages:
        logger.info(f"开始处理包: {package}")
        results[package] = install_or_update_package(
            package, python_exec, index_url, upgrade, logger
        )
        
    return results