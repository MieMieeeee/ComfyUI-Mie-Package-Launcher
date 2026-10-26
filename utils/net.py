import gzip
import os
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


# git 需要改写 URL 的上游 host（与 plugin_service._GIT_PROXY_ORIG_PREFIXES 同集合）
_GIT_PROXY_ORIG_PREFIXES = (
    'https://github.com/',
    'https://gitlab.com/',
)

# 走代理的 git 子命令。只有这些会真的访问网络, 才值得注入 -c insteadOf;
# rev-parse / log / describe / status 等本地只读命令加了纯属噪音。
GIT_NETWORK_SUBCOMMANDS = frozenset({'fetch', 'pull', 'ls-remote', 'clone'})


def git_insteadof_args(proxy_settings: dict | None) -> list:
    """按 config.proxy_settings 生成 git 的 ``-c url.<前缀>.insteadOf=`` 参数.

    供「启动器自己跑的 git」使用（内核更新的 fetch/pull、版本页的后台 fetch）。
    这些命令没有可改写的 URL 参数, 只能用 insteadOf 前缀匹配; 作用域限单次子进程,
    不落盘、不动仓库 origin、不设 GIT_CONFIG_GLOBAL（后者会盖掉用户自己的 ~/.gitconfig,
    让 http.proxy / credential.helper 失效）。

    与 :func:`apply_git_proxy_to_url` 的区别: 那个改的是「传给 git 的字符串」, 这个改的是
    git 内部的 URL 匹配规则。origin 已是代理地址时不会被套第二层 —— 那是 git 的前缀匹配保证的
    （已代理的 origin 不以 ``https://github.com/`` 开头）, 跟 apply 的幂等无关。

    Args:
        proxy_settings: ``config["proxy_settings"]``, None 等价于 {}

    Returns:
        argv 片段, 形如 ``['-c', 'url.https://gh-proxy.com/https://github.com/.insteadOf=https://github.com/',
        '-c', 'url...gitlab...']``。代理未启用（none / 自定义 URL 为空 / 未知模式）时返回 ``[]``,
        调用方不要发出任何 ``-c``。

    ⚠️ 每个 ``-c`` 的值必须是**单独一个 argv 元素且不带引号**。写成
    ``'url."<前缀>".insteadOf=...'`` 会让 git 把引号当字面量, 拼出
    ``"https://gh-proxy.com/https://github.com/"Comfy-Org/ComfyUI.git`` 这种坏地址 ——
    不报错, 只是换个方式失败。
    """
    args = []
    try:
        for orig in _GIT_PROXY_ORIG_PREFIXES:
            prefixed = apply_git_proxy_to_url(orig, proxy_settings)
            if not prefixed or prefixed == orig:
                continue  # 代理未启用, 少一条 -c
            args += ['-c', 'url.{0}.insteadOf={1}'.format(prefixed, orig)]
    except Exception:
        return []
    return args


def git_cmd_needs_proxy(cmd) -> bool:
    """判断一条 git 命令是否需要注入代理参数（按子命令 token, 不看 cmd[0]）.

    ``cmd[0]`` 是 git 可执行文件, 可能是 ``"git"`` 也可能是绝对路径（版本页传
    ``app.git_path``）, 所以只能按 ``cmd[1:]`` 里的 token 判定子命令。
    """
    try:
        tokens = {str(c).lower() for c in list(cmd)[1:]}
    except Exception:
        return False
    return bool(tokens & GIT_NETWORK_SUBCOMMANDS)


# ---------------------------------------------------------------------------
# 本地正向代理（Clash / v2ray / sing-box 之类）——issue #109
# ---------------------------------------------------------------------------
# 与上面三段「镜像」语义正交, 务必分清:
#   git_proxy_* / pypi_proxy_* / hf_mirror_*  = **改写落地地址**（换源）
#   local_proxy_*                             = **换传输路径**（流量怎么走出去）
# 两者正交: 开了本地代理后, hf 镜像 / gh-proxy / 阿里云 pypi 依然生效, 只是
# 这些地址的流量改为经本地代理转发（多一跳, 但依然是你选的源）。

# 必须排除的地址: 启动器自己要访问 127.0.0.1 的 Manager API
# (services/plugin_service.py 的 /manager/*), ComfyUI 内部也走 127.0.0.1.
# 不排除的话装了代理就会把插件安装/卸载/启停 + 健康探测全部打死
# (已实测: 无 NO_PROXY 时本地请求被绕进代理 → WinError 10061).
LOCAL_PROXY_BYPASS_DEFAULT = '127.0.0.1,localhost,::1'

# urllib(Python 自带) 不支持 socks; git 支持 socks5h; requests/httpx 需要 PySocks。
# 只接受 http(s), 避免用户填了 socks5 后启动器自身的 GitHub API / 公告静默失联。
_LOCAL_PROXY_SUPPORTED_SCHEMES = ('http://', 'https://')

_LOCAL_PROXY_ENV_KEYS = (
    'HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy',
)


def normalize_local_proxy_url(raw: str) -> str:
    """规范化本地代理地址；不可用时返回空串。

    只接受 http:// / https://（Clash 的 HTTP 混合端口，如 127.0.0.1:7890）。
    """
    url = (raw or '').strip().strip('`').strip()
    if not url:
        return ''
    if '://' not in url:
        # 只写了 host:port（Clash 最常见的填法）
        url = 'http://' + url
    lowered = url.lower()
    if not lowered.startswith(_LOCAL_PROXY_SUPPORTED_SCHEMES):
        return ''
    return url.rstrip('/')


def apply_local_proxy_env(proxy_settings, logger=None, env=None) -> dict:
    """把本地正向代理写进环境变量，覆盖启动器及其**所有**子进程。

    语义（issue #109）：一旦启用，启动器自身 + ComfyUI + git + pip + HF 下载
    的**所有非本地出网流量**都经这个代理；镜像站设置（hf / gh-proxy / pypi）
    依然生效，只是不再决定「怎么连」，只决定「连哪」。

    为什么直接改 ``os.environ`` 而不是逐个子进程注入:
    ``core/launcher_cmd.py`` 构造 ComfyUI env 时是 ``os.environ.copy()``,
    而全项目只有 ui_qt/pages/environment_manager_section.py 一处从零构造 env
    （且与出网无关），所以改一次 os.environ 就能覆盖全部出网路径, 不漏。

    强制同时设 ``NO_PROXY``/``no_proxy`` 排除本机, 否则启动器访问
    127.0.0.1 的 Manager API 与健康探测会被绕进代理（实测 WinError 10061）。

    Args:
        proxy_settings: ``config["proxy_settings"]``
        logger: 可选, 写一条 audit 日志
        env: 目标映射, 默认 ``os.environ``（测试可传 dict）

    Returns:
        ``{"enabled": bool, "url": str, "reason": str, "vars": {...}}``
    """
    target = os.environ if env is None else env
    result = {"enabled": False, "url": "", "reason": "", "vars": {}}
    try:
        cfg = proxy_settings or {}
        if not _as_bool(cfg.get("local_proxy_enabled")):
            return result
        url = normalize_local_proxy_url(cfg.get("local_proxy_url") or '')
        if not url:
            result["reason"] = "地址无效（需 http://host:port，Clash 混合端口如 127.0.0.1:7890）"
            if logger:
                logger.warning("[local_proxy] 已启用但地址无效，未注入: %s",
                               cfg.get("local_proxy_url"))
            return result
        for k in _LOCAL_PROXY_ENV_KEYS:
            target[k] = url
            result["vars"][k] = url
        # 追加而不是覆盖：用户自己设过 NO_PROXY 的话别把人家的排除了
        existing = (target.get('NO_PROXY') or target.get('no_proxy') or '')
        parts = [p.strip() for p in existing.split(',') if p.strip()]
        for p in LOCAL_PROXY_BYPASS_DEFAULT.split(','):
            if p and p not in parts:
                parts.append(p)
        bypass = ','.join(parts)
        target['NO_PROXY'] = bypass
        target['no_proxy'] = bypass
        result['vars']['NO_PROXY'] = bypass
        result['enabled'] = True
        result['url'] = url
        if logger:
            logger.info("[local_proxy] 已启用: %s (NO_PROXY=%s)", url, bypass)
    except Exception as e:  # 代理是增强项, 绝不能把启动器带崩
        result['reason'] = '注入异常: %s' % str(e)[:120]
        if logger:
            logger.warning("[local_proxy] 注入异常: %s", e)
    return result


def clear_local_proxy_env(proxy_settings=None, logger=None, env=None) -> dict:
    """撤销 :func:`apply_local_proxy_env` 注入的变量（用户在 GUI 里关掉开关时用）。

    **只删指向我们自己配置的地址的变量**：用户自己 export 过的 HTTP_PROXY 不能被误删,
    否则等于偷偷改了用户的进程环境。NO_PROXY / no_proxy 不动 —— 没有代理变量时它是惰性的,
    留着比"猜哪些是我们加的"安全。

    Returns:
        ``{"cleared": [...], "kept": [...]}``
    """
    target = os.environ if env is None else env
    cleared, kept = [], []
    try:
        url = normalize_local_proxy_url((proxy_settings or {}).get("local_proxy_url") or '')
        for k in _LOCAL_PROXY_ENV_KEYS:
            cur = target.get(k)
            if not cur:
                continue
            # 只有值等于本配置（或等于本配置的裸 host:port 写法）才撤
            bare = url.split('://', 1)[-1] if url else ''
            if url and cur.rstrip('/') in (url.rstrip('/'), bare.rstrip('/')):
                target.pop(k, None)
                cleared.append(k)
            else:
                kept.append(k)
    except Exception as e:
        if logger:
            logger.warning("[local_proxy] 撤销失败: %s", e)
    if cleared and logger:
        logger.info("[local_proxy] 已撤销注入: %s", ", ".join(cleared))
    return {"cleared": cleared, "kept": kept}


def check_local_proxy_reachable(url: str, timeout: float = 2.0) -> tuple:
    """探测本地代理端口是否在监听。返回 ``(ok, detail)``，永不抛。

    只做 TCP 连接测试（Clash 是本地转发端口，握手即可，不必真发请求）。
    """
    import socket

    norm = normalize_local_proxy_url(url)
    if not norm:
        return False, "地址无效"
    try:
        parsed = urlparse(norm)
        host = parsed.hostname or '127.0.0.1'
        port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    except Exception:
        return False, "地址无法解析"
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True, "%s:%s 可连接" % (host, port)
    except Exception as e:
        return False, "%s:%s 无响应（%s）" % (host, port, str(e)[:60])


def _as_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ('1', 'true', 'yes', 'on')
    return bool(v)


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
