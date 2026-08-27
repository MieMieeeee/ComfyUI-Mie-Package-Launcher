import gzip
import zlib
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

def describe_git_proxy(app_config) -> str:
    """For UI display: one-line Chinese label for the git proxy mode that
    ``pull_webui`` / ``clone_webui`` will actually use given current
    ``config["proxy_settings"]``. Pull banner uses this so the user knows
    whether the command goes through gh-proxy.com / 直连 / 自定义代理.

    Format:
      mode=none         -> "直连 github.com"
      mode=gh-proxy     -> "通过 <url>" (URL derived from proxy_settings or
                            GITHUB_PROXY_DEFAULT_URL)
      mode=custom       -> "通过自定义代理 <url>"
      mode=other         -> "通过 <mode>" (raw fallback so we never lose info)
    """
    try:
        ps = (app_config or {}).get("proxy_settings", {}) if isinstance(app_config, dict) else {}
    except Exception:
        ps = {}
    try:
        mode = (ps.get("git_proxy_mode") or "none").strip() if ps else "none"
    except Exception:
        mode = "none"
    if mode == "none":
        return "直连 github.com"
    if mode == "gh-proxy":
        try:
            url = (ps.get("git_proxy_url") or "").strip() or GITHUB_PROXY_DEFAULT_URL
        except Exception:
            url = GITHUB_PROXY_DEFAULT_URL
        url = url.rstrip("/")
        return "通过 " + url
    if mode == "custom":
        try:
            url = (ps.get("git_proxy_url") or "").strip()
        except Exception:
            url = ""
        return "通过自定义代理 " + url
    return "通过 " + mode

def describe_webui_proxy_for_mirror(mirror, app_config) -> str:
    """Mirror-aware one-line label for the webui pull/clone task title.

    pull_webui / clone_webui only apply gh-proxy when the URL contains
    "github.com" (per 9b6f4d2). For Gitee, the configured proxy
    mode is irrelevant -- Gitee is direct. So we must NOT say
    "通过 gh-proxy" when the user picked Gitee, even if they have
    a gh-proxy config in place.

    Format:
      mirror=gitee  -> Gitee（直连）
      mirror=github + mode=none -> GitHub（直连）
      mirror=github + mode=gh-proxy -> GitHub（通过 <url>）
      mirror=github + mode=custom -> GitHub（通过自定义代理 <url>）
    """
    m = (mirror or "").strip().lower()
    if m != "github":
        # Gitee / 自定义 走直连, proxy 配置被忽略.
        # Empty mirror 默认 Gitee (跟 WEBUI_DEFAULT_MIRROR 一致).
        label = "Gitee" if m in ("", "gitee") else m
        return label + "（直连）"
    # github -- proxy 真的生效, 复用 describe_git_proxy 描述.
    proxy = describe_git_proxy(app_config)
    return "GitHub（" + proxy + "）"



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


def resolve_pypi_index_url(app) -> str | None:
    """从 app 的 pypi proxy 配置解析 pypi index URL.

    统一 webui install / setup / GUI 三处的解析逻辑:
    - aliyun / tsinghua / huaweicloud -> 对应内置 URL
    - custom -> 读 app.pypi_proxy_url.get() (去首尾空格, 空则回退内置)
    - none / 未知 / 缺属性 / .get() 抛异常 -> None

    app.pypi_proxy_mode / pypi_proxy_url 是 tk Variable (有 .get()), 本函数对
    属性缺失和 .get() 抛异常都做防御, 安全回退到 None.
    """
    try:
        v = getattr(app, 'pypi_proxy_mode', None)
        mode = (v.get() or 'none').strip() if v else 'none'
    except Exception:
        mode = 'none'
    idx_url = get_pypi_index_url_for_mode(mode)
    if mode == PYPI_MODE_CUSTOM:
        try:
            uv = getattr(app, 'pypi_proxy_url', None)
            if uv:
                u = (uv.get() or '').strip()
                if u:
                    idx_url = u
        except Exception:
            pass
    return idx_url


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


# GitHub 代理模式常量, 跟 launcher config.proxy_settings.git_proxy_mode 对齐.
GITHUB_PROXY_MODE_NONE = "none"
GITHUB_PROXY_MODE_GH_PROXY = "gh-proxy"
GITHUB_PROXY_MODE_CUSTOM = "custom"

# 默认 gh-proxy 域名 (services/version_service.py 里 hardcode 的是同样这个).
GITHUB_GH_PROXY_BASE = "https://gh-proxy.com/"


def apply_git_proxy_to_url(base: str, proxy_settings: dict | None) -> str:
    """根据 config.proxy_settings 给 GitHub URL 加代理前缀.

    - git_proxy_mode == "gh-proxy"  ->  https://gh-proxy.com/<base>
    - git_proxy_mode == "custom"    ->  <git_proxy_url>/<base>
    - 其他 (none / 缺失)            ->  原样返回 base

    idempotent: base 已经以代理前缀开头, 原样返回 (避免双重 prefix 触发 403).

    实际场景: 用户之前用 gh-proxy clone 过 webui, .git/config 里 remote.origin.url
    已经是 https://gh-proxy.com/https://github.com/...; pull_webui 用
    `git remote get-url origin` 读到 raw=已代理 URL, 再 apply 会变成
    https://gh-proxy.com/https://gh-proxy.com/... gh-proxy 返 403.

    跟 services/version_service.py:_apply_proxy_to_path 行为一致, 抽到这里供
    webui clone / 未来一般 git 链接复用, 避免散落 magic.
    """
    base = (base or "").strip()
    if not base:
        return base
    try:
        cfg = proxy_settings or {}
        mode = (cfg.get("git_proxy_mode") or "none").strip()
        url = (cfg.get("git_proxy_url") or "").strip()
        # idempotent: 已带 proxy 前缀就原样返回
        if mode == GITHUB_PROXY_MODE_GH_PROXY:
            if base.lower().startswith(GITHUB_GH_PROXY_BASE.lower()):
                return base
            return GITHUB_GH_PROXY_BASE + base
        if mode == GITHUB_PROXY_MODE_CUSTOM and url:
            if not url.endswith("/"):
                url += "/"
            if base.lower().startswith(url.lower()):
                return base
            return url + base
    except Exception:
        pass
    return base


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


def read_response_raw(resp) -> bytes:
    """读取 urllib response 的原始 bytes，自动处理 gzip / deflate Content-Encoding。

    Python 的 urllib 不像 requests 那样自动解 Content-Encoding（issue 11），
    CDN 强制返 gzip 时 json.loads(resp.read()) 会因 zlib header 失败而崩。
    本函数集中处理：调用方传 ``urllib.response.addinfourl`` 实例进来，
    拿到解压后的 bytes 用于后续 JSON 解析。

    Args:
        resp: 有 ``headers`` dict 和 ``read() -> bytes`` 方法的对象
             （urllib response / MagicMock 都可）。

    Returns:
        解压后的原始 bytes（Content-Encoding 不是 gzip/deflate 时原样返回）。
    """
    raw = resp.read()
    encoding = (resp.headers.get("Content-Encoding") or "").strip().lower()
    if not encoding:
        return raw
    if encoding == "gzip":
        return gzip.decompress(raw)
    if encoding == "deflate":
        # 一些老旧 CDN 把 deflate 直接发 zlib 流（无 header），
        # 另一些用 raw deflate（无 zlib header，wbits=-MAX_WBITS）。
        # 两种都 try，失败回退 raw。
        try:
            return zlib.decompress(raw)
        except zlib.error:
            try:
                return zlib.decompress(raw, -zlib.MAX_WBITS)
            except zlib.error:
                return raw
    # brotli / identity / 其它未实现：原样返回，让上层 JSON 解析自己处理
    return raw
