from pathlib import Path
from urllib.parse import urlparse

# PyPI mirror URLs. These are well-known, stable endpoints that mirror the
# official Python Package Index. They are used both for writing pip.ini and
# for explicit ``pip install -i <url>`` invocations from the launcher.
PYPI_ALIYUN_URL = 'https://mirrors.aliyun.com/pypi/simple/'
PYPI_TSINGHUA_URL = 'https://pypi.tuna.tsinghua.edu.cn/simple/'
PYPI_HUAWEICLOUD_URL = 'https://repo.huaweicloud.com/repository/pypi/simple/'

HF_MIRROR_URL_DEFAULT = 'https://hf-mirror.com'
GITHUB_PROXY_DEFAULT_URL = 'https://gh-proxy.com/'


# Mode values used by the launcher UI / config. Keep these in sync with
# ``ui_qt/pages/launch/environment_section.py`` and the combo box options.
PYPI_MODE_NONE = 'none'
PYPI_MODE_ALIYUN = 'aliyun'
PYPI_MODE_TSINGHUA = 'tsinghua'
PYPI_MODE_HUAWEICLOUD = 'huaweicloud'
PYPI_MODE_CUSTOM = 'custom'


# Single source of truth for ``mode -> index URL`` resolution. Unknown modes
# and ``none`` / ``custom`` return ``None`` so callers can decide what to do
# (e.g. fall back to pypi.org or to a user-supplied URL).
def get_pypi_index_url_for_mode(mode: str) -> str | None:
    mode = (mode or '').strip()
    if mode == PYPI_MODE_ALIYUN:
        return PYPI_ALIYUN_URL
    if mode == PYPI_MODE_TSINGHUA:
        return PYPI_TSINGHUA_URL
    if mode == PYPI_MODE_HUAWEICLOUD:
        return PYPI_HUAWEICLOUD_URL
    return None


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
    try:
        py_path = Path(python_exec_path).resolve()
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

        # Built-in mirror modes (aliyun / tsinghua / huaweicloud) carry their
        # own URL and trusted host. Everything else (``custom`` etc.) falls
        # back to whatever the caller supplied in ``index_url``.
        idx_url = get_pypi_index_url_for_mode(mode)
        trusted_host = ''
        if idx_url:
            try:
                parsed = urlparse(idx_url)
                trusted_host = parsed.hostname or ''
            except Exception:
                trusted_host = ''
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
                logger.exception("更新 pip.ini 过程出现异常")
            except Exception:
                pass

def apply_pip_proxy_settings(python_exec: str, pypi_proxy_mode: str, pypi_proxy_url: str, pip_proxy_url: str, logger=None):
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
