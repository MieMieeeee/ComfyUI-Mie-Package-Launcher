from pathlib import Path
from urllib.parse import urlparse

# Defaults used across the launcher
PYPI_ALIYUN_URL = 'https://mirrors.aliyun.com/pypi/simple/'
HF_MIRROR_URL_DEFAULT = 'https://hf-mirror.com'
GITHUB_PROXY_DEFAULT_URL = 'https://gh-proxy.com/'


def ensure_trailing_slash(url: str) -> str:
    u = (url or '').strip()
    if not u:
        return ''
    return u if u.endswith('/') else (u + '/')


def build_github_endpoint(base_url: str) -> str:
    base = ensure_trailing_slash(base_url)
    if not base:
        return ''
    return f"{base}https://github.com"


def update_pip_ini(python_exec_path: str, mode: str, index_url: str, pip_proxy: str, logger=None):
    """Write pip.ini based on proxy mode.

    - mode == 'none': remove index-url/trusted-host/proxy (delete file if empty)
    - mode == 'aliyun': use Aliyun mirror with trusted-host
    - mode == 'custom': use provided index_url and derived trusted-host
    """
    try:
        py_path = Path(python_exec_path).resolve()
        # pip.ini resides next to embedded python.exe
        py_root = py_path.parent if py_path.exists() else Path('python_embeded')
        pip_ini = py_root / 'pip.ini'

        if (mode or 'none') == 'none':
            if pip_ini.exists():
                try:
                    content = pip_ini.read_text(encoding='utf-8', errors='ignore')
                    lines = [ln for ln in content.splitlines() if ln.strip()]
                    filtered = []
                    for ln in lines:
                        low = ln.strip().lower()
                        if low.startswith('index-url') or low.startswith('trusted-host') or low.startswith('proxy'):
                            continue
                        filtered.append(ln)
                    non_comment = [ln for ln in filtered if ln.strip() and not ln.strip().startswith('#')]
                    if not non_comment or (len(non_comment) == 1 and non_comment[0].strip().lower() == '[global]'):
                        pip_ini.unlink(missing_ok=True)
                    else:
                        pip_ini.write_text('\n'.join(filtered) + '\n', encoding='utf-8')
                except Exception:
                    try:
                        pip_ini.unlink(missing_ok=True)
                    except Exception:
                        pass
            return

        if mode == 'aliyun':
            idx_url = PYPI_ALIYUN_URL
            trusted_host = 'mirrors.aliyun.com'
        else:
            idx_url = (index_url or '').strip()
            try:
                parsed = urlparse(idx_url)
                trusted_host = parsed.hostname or ''
            except Exception:
                trusted_host = ''

        if not idx_url:
            return

        lines = ['[global]', f'index-url = {idx_url}']
        if trusted_host:
            lines.append(f'trusted-host = {trusted_host}')
        if pip_proxy:
            lines.append(f'proxy = {pip_proxy}')

        try:
            pip_ini.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        try:
            pip_ini.write_text('\n'.join(lines) + '\n', encoding='utf-8')
            if logger:
                try:
                    logger.info("已更新 pip.ini: mode=%s url=%s host=%s proxy=%s", mode, idx_url, trusted_host, pip_proxy or '-')
                except Exception:
                    pass
        except Exception:
            if logger:
                try:
                    logger.warning("写入 pip.ini 失败: %s", str(pip_ini))
                except Exception:
                    pass
    except Exception:
        if logger:
            try:
                logger.exception("应用 PyPI 代理到 pip.ini 时出错")
            except Exception:
                pass


def apply_pip_proxy_settings(python_exec: str, pypi_proxy_mode: str, pypi_proxy_url: str, pip_proxy_url: str, logger=None):
    """根据当前 PyPI 代理设置更新 python_embeded/pip.ini。
    
    Args:
        python_exec: Python 可执行文件路径
        pypi_proxy_mode: 代理模式 ('none', 'aliyun', 'custom')
        pypi_proxy_url: 自定义 PyPI 镜像 URL
        pip_proxy_url: pip 代理 URL
        logger: 日志记录器
    """
    try:
        mode = (pypi_proxy_mode or 'none').strip()
        url = (pypi_proxy_url or '').strip()
        pip_proxy = (pip_proxy_url or '').strip()
        
        update_pip_ini(python_exec, mode, url, pip_proxy, logger)
    except Exception:
        if logger:
            try:
                logger.exception("应用 PyPI 代理到 pip.ini 时出错")
            except Exception:
                pass