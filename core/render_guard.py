"""渲染模式守卫：检测上次异常退出并自动升级渲染模式。

三态 (render mode values):
  - ``auto``  : 默认，使用 Qt 默认渲染（硬件）。
  - ``compat``: 软件渲染 (``QT_OPENGL=software``，要求 opengl32sw.dll 可定位)
  - ``safe``  : ``compat`` + 禁用阴影/透明效果（``LAUNCHER_SAFE_UI=1``）

两级升级阶梯（只升不降，用户手动复位）:
    auto --异常退出--> compat --异常退出--> safe（封顶）

状态文件 (``launcher/render_state.json``) 与 side counter 文件
(``launcher/render_clean_counter.json``):
  - state 记录本次会话状态: starting / running / clean（哨兵）
  - counter 记录自上次升级/promote 清零以来的「成功 close 累计」（非「连续
    close」，硬杀 / 关机等无 finish() 异常退出既不 +1 也不清零）

crash.log 分类器（v9 三态分类器）:
  - 段取「倒数第二 [startup] 到最后一 [startup]」（本次 install_crash_reporting
    写最后一行作为锚点）
  - 结构性块排除: [uncaught_exception] marker 行起，到下一个 marker /
    [startup] / = 分隔行止整块跳过（链式异常 / 多行消息 / 裸异常全部安全）
  - 块外任何非空非 marker 行 = native crash 证据 → graphics_crash
  - 块内走完无块残留 → python_exception（与渲染模式无关，不升级）
  - 段内只有 marker → clean_or_user（用户主动 kill / 托盘关机强杀，不升级）
  - 段不可知（无 [startup] / decode 失败）→ unknown（保守不升级）

生命周期拆成多个入口, 规避与单实例锁的竞态:
  - ``prepare()`` 幂等，只读 config + 设 env，不碰任何状态文件
  - ``begin()`` 拿到互斥锁后调用: 升级判断 + 写 running 标记 + crash 记录
  - ``mark_running()`` PyQtLauncher() 构造后调用, starting → running 保字段
  - ``finish()`` window.run() 正常返回后调用（不得放 finally）
  - ``mark_running()`` 不参与升级判定（starting/running 走同一分支, 分类依据
    是 crash.log 内容, 不是 state 值）

auto-promote（5 次成功 close 后自动回升 auto）:
  - 在 finish() 里, counter >= 5 时触发
  - 写 config + 裸 JSON 回读校验（区分「wrote auto」与「config broken → auto
    fallback」）→ 校验通过才清 counter, 失败写 audit 保留 counter
  - 已是 auto 时也触发（去门, no-op promote）, counter 在 config 可写时有界（config 持久损坏时 verify 永远失败, counter 不清零, 见 §9 边界）

audit 行约定（v6 Nit 5 钉死）:
  - 所有 audit 行必须以 [render_guard] 前缀走 ``append_crash_audit()`` 包装器
  - 字面量永不含前缀, 包装器是前缀唯一来源 → 双前缀零风险
  - 这是 tray-resident/taskkill 场景下分类器不被误触的唯一保护

对外查询接口全基于环境变量（不依赖本模块初始化顺序），任何位置都可调用:
  - ``current_mode()`` → str
  - ``is_safe_ui()`` → bool
  - ``escalated_this_run()`` → bool
  - ``escalated_detail()`` -> tuple[str, str] | None

纯 stdlib（加上 ``config.manager.atomic_write_json`` 的轻量复用，不 import Qt）。
"""

from __future__ import annotations

import datetime
import json
import os
import sys
from pathlib import Path
from typing import Optional, Tuple

# v6 Nit 3: 模块级 import（v9 Nit 3 同款, v6 评审时 deferred, v9 改模块级）
from utils.logging import append_crash_report

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VALID_MODES = {"auto", "compat", "safe"}
_ESCALATION_ORDER = ["auto", "compat", "safe"]

# v1 §1.5: 5 次成功 close 触发 auto 回升
_AUTO_PROMOTE_THRESHOLD = 5

# crash.log 分类器 marker 行集合（块排除的进入/退出条件）
_MARKER_PREFIXES = ("[startup]", "[hint]", "[render_guard]")


# ---------------------------------------------------------------------------
# DLL locator (module-level cache, so prepare called twice only scans once)
# ---------------------------------------------------------------------------

_dll_cached: bool = False
_dll_path: Optional[Path] = None


def _locate_opengl32sw() -> Optional[Path]:
    """Search opengl32sw.dll in candidate locations, cache result forever."""
    global _dll_cached, _dll_path
    if _dll_cached:
        return _dll_path
    _dll_cached = True

    candidates: list[Path] = []

    try:
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir / "opengl32sw.dll")
        candidates.append(exe_dir / "_internal" / "PyQt5" / "Qt5" / "bin" / "opengl32sw.dll")
    except Exception:
        pass

    try:
        import importlib.util
        spec = importlib.util.find_spec("PyQt5")
        if spec is not None and getattr(spec, "origin", None):
            pkg = Path(spec.origin).resolve().parent
            candidates.append(pkg / "Qt5" / "bin" / "opengl32sw.dll")
            candidates.append(pkg / "Qt" / "bin" / "opengl32sw.dll")
    except Exception:
        pass

    for c in candidates:
        try:
            if c.exists() and c.is_file():
                _dll_path = c
                break
        except Exception:
            continue
    return _dll_path


# ---------------------------------------------------------------------------
# Runtime root + file path helpers
# ---------------------------------------------------------------------------

def _runtime_root() -> Path:
    try:
        from utils.paths import resolve_runtime_root
        return resolve_runtime_root()
    except Exception:
        return Path.cwd()


def _launcher_dir() -> Path:
    d = _runtime_root() / "launcher"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return d


def _config_path() -> Path:
    return _launcher_dir() / "config.json"


def _state_path() -> Path:
    return _launcher_dir() / "render_state.json"


def _clean_counter_path() -> Path:
    """Side counter 文件路径（与 state.json 分离, finish 路径不依赖 state 存活）。"""
    return _launcher_dir() / "render_clean_counter.json"


def _crash_log_path() -> Path:
    return _launcher_dir() / "crash.log"


# ---------------------------------------------------------------------------
# Atomic I/O
# ---------------------------------------------------------------------------

def _atomic_write(target: Path, payload: dict) -> None:
    """原子写 JSON（优先复用 config.manager.atomic_write_json；fallback 自己实现）。"""
    try:
        from config.manager import atomic_write_json
        atomic_write_json(target, payload)
        return
    except Exception:
        pass
    import os as _os
    import tempfile as _tf
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = _tf.mkstemp(
        dir=str(target.parent),
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    try:
        with _os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.flush()
            _os.fsync(f.fileno())
        _os.replace(tmp_path, target)
    except Exception:
        try:
            if _os.path.exists(tmp_path):
                _os.unlink(tmp_path)
        except Exception:
            pass
        raise


def _read_json(path: Path) -> Optional[dict]:
    try:
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _read_render_mode_from_config() -> str:
    """读 launcher/config.json → ui_settings.render_mode；任何异常退回 auto。"""
    cfg = _read_json(_config_path()) or {}
    ui = cfg.get("ui_settings") if isinstance(cfg, dict) else None
    mode = ui.get("render_mode") if isinstance(ui, dict) else None
    if mode in _VALID_MODES:
        return mode  # type: ignore[return-value]
    return "auto"


def _write_render_mode_to_config(mode: str) -> None:
    """原子升级 ui_settings.render_mode，其他所有字段一字不动保留。

    破坏 config 中的其他字段（proxy/environments/custom 等）是致命的，
    我们采用「完整读 → 仅改这一个 key → 原子写回」策略。

    如果 config 整个缺失或损坏到 `{}` 程度（原子写正常路径下不会发生），
    跳过持久化，避免把「只有 ui_settings.render_mode 这一个键的空壳文件」
    回写给 ConfigManager，让它自己的损坏保护策略生效。
    """
    if mode not in _VALID_MODES:
        mode = "auto"
    cfg = _read_json(_config_path()) or {}
    if not isinstance(cfg, dict):
        cfg = {}
    if not cfg:
        # 空/损坏 config：只进程内升级，不落盘
        return
    ui = cfg.setdefault("ui_settings", {})
    if not isinstance(ui, dict):
        ui = {}
        cfg["ui_settings"] = ui
    ui["render_mode"] = mode
    _atomic_write(_config_path(), cfg)


def _verify_render_mode_written(target: str) -> bool:
    """裸 JSON 校验, 区分「写入了 target」与「config broken → auto fallback」。

    v3 Diff 3 的 _read_render_mode_from_config 对 config 缺失/损坏兜底返回
    "auto", 让回读校验恒真空转。这里改用裸 JSON: 文件不存在 / 解析失败
    → _read_json 返回 None → isinstance(None, dict) False → 校验失败。
    """
    raw = _read_json(_config_path())
    if not isinstance(raw, dict):
        return False
    ui = raw.get("ui_settings")
    if not isinstance(ui, dict):
        return False
    return ui.get("render_mode") == target


# ---------------------------------------------------------------------------
# Side counter (clean_close_count)
# ---------------------------------------------------------------------------
# v3 Diff 4 改名: 从 consecutive_clean_closes 改 clean_close_count
# (counter 实际语义是「自上次升级/promote 清零以来的 clean 关闭累计」, 不
# 是「连续」- 硬杀/关机等无 finish() 异常退出既不 +1 也不清零)

def _read_clean_counter() -> dict:
    """读 side counter 文件, 缺省空 dict。返回 dict, 调用点 .get("count", 0) 取值。"""
    obj = _read_json(_clean_counter_path()) or {}
    return obj if isinstance(obj, dict) else {}


def _write_clean_counter(payload: dict) -> None:
    """原子写 side counter 文件。"""
    if not isinstance(payload, dict):
        return
    _atomic_write(_clean_counter_path(), payload)


# ---------------------------------------------------------------------------
# Audit 行包装器 (v6 Nit 5)
# ---------------------------------------------------------------------------
# 所有 audit 行必须以 [render_guard] 前缀走此包装器, 字面量永不含前缀,
# 包装器是前缀唯一来源 → 双前缀零风险。
# tray-resident/taskkill 场景下分类器不被误触的唯一保护。

def append_crash_audit(msg: str) -> None:
    """写一条 [render_guard] audit 行到 crash.log。

    msg 是字面量, 不含 [render_guard] 前缀。包装器加前缀。
    若 utils.logging._crash_fh 未装 (None), 静默 no-op（不抛）。
    """
    if not msg:
        return
    try:
        append_crash_report(f"[render_guard] {msg}")
    except Exception:
        pass


def _append_audit(cls: str) -> None:
    """begin 写分类 audit（v1 §1.3）：让下次 begin() 分类器知道上次 exit 类型。"""
    append_crash_audit(f"last_exit={cls}")


# ---------------------------------------------------------------------------
# crash.log 分类器 (v3 块排除算法)
# ---------------------------------------------------------------------------

def _classify_last_exit(text: str) -> str:
    """三态分类上次会话退出原因。

    Returns
    -------
    str in {"graphics_crash", "python_exception", "clean_or_user", "unknown"}

    算法:
      1. 段取「倒数第二 [startup] 到最后一 [startup]」（本次 install_crash_reporting
         写最后一行作为锚点）
      2. 不足 2 个 [startup] → unknown（文件不存在 / 首次启动 / 刚截断）
      3. 结构性块排除: [uncaught_exception] marker 行起, 到下一个 marker 行止
         整块跳过（块内链式异常 / 多行消息 / 裸异常全部安全）
      4. 块外任何非空非 marker 行 = native crash 证据 → graphics_crash
      5. 块内走完无块残留 → python_exception（与渲染模式无关, 不升级）
      6. 段内只有 marker → clean_or_user（用户主动 kill / 托盘关机强杀, 不升级）
    """
    if not text:
        return "unknown"
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith("[startup]")]
    if len(starts) < 2:
        return "unknown"
    seg = lines[starts[-2] + 1:starts[-1]]

    in_marker_block = False
    for line in seg:
        s = line.strip()
        if not s:
            continue
        # 退出块: 下一个 marker 行
        if any(s.startswith(p) for p in _MARKER_PREFIXES) or s.startswith("="):
            in_marker_block = False
            continue
        # 进入块: [uncaught_exception] marker（startswith, 防幻影块）
        if line.startswith("[uncaught_exception]"):
            in_marker_block = True
            continue
        # 块内: 跳过
        if in_marker_block:
            continue
        # 块外: 任何非空非 marker 行 = native crash 证据
        return "graphics_crash"

    return "python_exception" if in_marker_block else "clean_or_user"


# ---------------------------------------------------------------------------
# Mode / env application
# ---------------------------------------------------------------------------

def _apply_mode_env(mode: str) -> None:
    """根据 mode 设置三个环境变量：LAUNCHER_RENDER_MODE / LAUNCHER_SAFE_UI / QT_OPENGL。"""
    if mode not in _VALID_MODES:
        mode = "auto"
    os.environ["LAUNCHER_RENDER_MODE"] = mode

    if mode == "safe":
        os.environ["LAUNCHER_SAFE_UI"] = "1"
    else:
        os.environ.pop("LAUNCHER_SAFE_UI", None)

    if mode in ("compat", "safe"):
        if _locate_opengl32sw() is not None:
            os.environ["QT_OPENGL"] = "software"
    # auto: 不动 QT_OPENGL, 让用户自己设的值或 Qt 默认行为生效


# ---------------------------------------------------------------------------
# Escalation bookkeeping
# ---------------------------------------------------------------------------

_escalated: bool = False
_escalation_detail: Optional[Tuple[str, str]] = None


def _next_mode(mode: str) -> str:
    """升一级，safe 封顶。非法 mode → 先归一 auto → 再升级。"""
    if mode not in _VALID_MODES:
        mode = "auto"
    idx = _ESCALATION_ORDER.index(mode)
    if idx + 1 < len(_ESCALATION_ORDER):
        return _ESCALATION_ORDER[idx + 1]
    return "safe"


# ---------------------------------------------------------------------------
# Public API: pure env queries
# ---------------------------------------------------------------------------

def current_mode() -> str:
    m = os.environ.get("LAUNCHER_RENDER_MODE", "auto")
    return m if m in _VALID_MODES else "auto"


def is_safe_ui() -> bool:
    return os.environ.get("LAUNCHER_SAFE_UI", "0") == "1"


def escalated_this_run() -> bool:
    return _escalated


def escalated_detail() -> Optional[Tuple[str, str]]:
    return _escalation_detail if _escalated else None


# ---------------------------------------------------------------------------
# Public API: lifecycle
# ---------------------------------------------------------------------------

def prepare() -> None:
    """读 config 并设置模式对应的环境变量。幂等，不写状态文件。"""
    try:
        mode = _read_render_mode_from_config()
        _apply_mode_env(mode)
    except Exception:
        try:
            _apply_mode_env("auto")
        except Exception:
            pass


def _build_version() -> str:
    try:
        from utils.logging import _read_build_version
        v = _read_build_version(_runtime_root())
        return v
    except Exception:
        return "unknown"


def begin() -> None:
    """拿到互斥锁后调用：升级判断 + 写 starting 标记 + crash 记录。

    完整步骤:
      1. 读 crash.log 取「上次会话」分类 (graphics_crash / python_exception /
         clean_or_user / unknown)
      2. graphics_crash → 升一级（原子写 config + 重新应用 env, verify 校验）
      3. 写 state = starting + last_exit audit 行（让下次 begin 分类器知道）
      4. 其他分类 → 不升级, 仅写 state=starting + audit

    防御性: 任何错误不让启动器失败（外层 try/except 兜底）。
    """
    global _escalated, _escalation_detail
    _escalated = False
    _escalation_detail = None

    try:
        base_mode = _read_render_mode_from_config()
        final_mode = base_mode

        # ---- v1 §1.3 state 门 (v10 F2): missing/clean → 跳过分类 ----
        # 正常关闭的会话 (finish 已删 state, 或写了 clean 哨兵) 其段内若含
        # 良性 faulthandler 误报行 (Windows 上已知 SEH 误报家族), 下次启动
        # 不应误升级。running 态才进分类器（taskkill/断电/原生崩溃的全场景覆盖）。
        st_path_early = _state_path()
        state_alive = st_path_early.exists()
        state_obj_early = _read_json(st_path_early) if state_alive else None
        if not state_alive or (isinstance(state_obj_early, dict) and state_obj_early.get("state") == "clean"):
            cls = "clean_or_user"  # 直接走不升级分支, 不读 crash.log
        else:
            # ---- 升级判定: 分类器驱动 ----
            crash_text = ""
            try:
                cp = _crash_log_path()
                if cp.exists():
                    # v3 评审裁决 strict + decode 失败 → unknown（宁漏勿误）,
                    # errors="replace" 会让乱码行成为块外证据, 反向触发误升级。
                    with open(cp, "r", encoding="utf-8") as f:
                        crash_text = f.read()
            except UnicodeDecodeError:
                # 非 UTF-8 污染 → 走 unknown 分支, 不升级
                crash_text = ""
            except Exception:
                crash_text = ""
            cls = _classify_last_exit(crash_text)

        if cls == "graphics_crash":
            # 真原生崩溃: 升一级
            new_mode = _next_mode(base_mode)
            if new_mode != base_mode:
                try:
                    _write_render_mode_to_config(new_mode)
                    if _verify_render_mode_written(new_mode):
                        # verified: 升级信号 + counter 清零
                        _escalated = True
                        _escalation_detail = (base_mode, new_mode)
                        final_mode = new_mode  # 与 verify_failed / except 分支同构
                        try:
                            _write_clean_counter({"count": 0, "last_clean_at": None, "since_mode": new_mode})
                        except Exception:
                            pass
                        append_crash_audit(f"escalated (mode={new_mode})")
                    else:
                        # verify 失败: 进程内升级 + 升级信号保留, counter 不清
                        final_mode = new_mode
                        _escalated = True
                        _escalation_detail = (base_mode, new_mode)
                        append_crash_audit(f"escalate_failed_verify (target={new_mode})")
                except Exception as e:
                    # 写异常: 进程内升级 + 升级信号保留, counter 不清
                    final_mode = new_mode
                    _escalated = True
                    _escalation_detail = (base_mode, new_mode)
                    append_crash_audit(f"escalate_failed_exception: {type(e).__name__}")
            else:
                # safe 封顶, 升级信号仍置位（弹窗提示）
                _escalated = True
                _escalation_detail = (base_mode, base_mode)

        # ---- 模式确定后: 重设 env ----
        _apply_mode_env(final_mode)

        # ---- 写 starting 标记（mark_running() 会改 running）----
        try:
            state_payload = {
                "mode": final_mode,
                "pid": os.getpid(),
                "started_at": int(datetime.datetime.now().timestamp()),
                "version": _build_version(),
                "state": "starting",
            }
            _atomic_write(_state_path(), state_payload)
        except Exception:
            pass

        # ---- crash.log 补分类 audit 行 + mode 行 ----
        # v11 R1: 全部走 append_crash_audit wrapper, 字面量永不含前缀,
        # 包装器是前缀唯一来源 (AGENTS.md:132 契约)。
        _append_audit(cls)
        try:
            line = (
                f"mode={final_mode} escalated={_escalated} "
                f"version={_build_version()}"
            )
            if _escalation_detail:
                f, t = _escalation_detail
                line += f" escalated_from={f} escalated_to={t}"
            append_crash_audit(line)
        except Exception:
            pass
    except Exception:
        # 防御性: 任何错误不让启动器失败
        try:
            _apply_mode_env("auto")
        except Exception:
            pass


def mark_running() -> None:
    """PyQtLauncher() 构造后调用: state=starting → running, 保字段。

    不要在此函数加升级逻辑（v3 Diff 4 钉死）:
      starting/running 走同一 begin() 分支, 分类依据是 crash.log 内容, 不是
      state 值。mark_running() 是纯诊断信息, 留作将来策略扩展（比如 starting
      期 crash 优先升级）。当前实现不参与升级判定。

    不存在的 state.json → 写 running（兜底, begin() 写失败场景）
    clean 哨兵 → 不动（上次 finish 删除失败, 已被保护, 重写会丢诊断信息）
    """
    try:
        st_path = _state_path()
        existing = _read_json(st_path)
        if isinstance(existing, dict) and existing.get("state") == "clean":
            return
        payload = dict(existing) if isinstance(existing, dict) else {}
        payload["state"] = "running"
        if "started_at" not in payload:
            payload["started_at"] = int(datetime.datetime.now().timestamp())
        _atomic_write(st_path, payload)
    except Exception:
        pass


def _clean_state_atomic(now_ts: int, current_mode_str: str) -> None:
    """finish() 的 state 清理段。失败降级为 clean 哨兵（双 except 合并, helper
    抽取后结构化等价）。"""
    st_path = _state_path()
    if not st_path.exists():
        return
    try:
        os.remove(str(st_path))
    except Exception as e:
        # PermissionError 是 Exception 子类, 统一捕获。AV 锁之类也走哨兵。
        _write_clean_sentinel(st_path, now_ts, current_mode_str, type(e).__name__)


def _write_clean_sentinel(st_path: Path, now_ts: int, current_mode_str: str, err_type: str) -> None:
    """clean 哨兵回退。保留 existing 字段 (mode/started_at/version 实值),
    缺失字段用兜底 (current_mode_str / None / _build_version())。
    """
    existing = _read_json(st_path) or {}
    _atomic_write(st_path, {
        "mode": existing.get("mode", current_mode_str),
        "started_at": existing.get("started_at"),
        "version": existing.get("version", _build_version()),
        "cleaned_at": now_ts,
        "state": "clean",
        "note": "remove-failed:" + err_type,
    })


def finish() -> None:
    """window.run() 正常返回后调用：counter 段 + promotion 段 + 清理 state。

    不得放在 finally 里（否则 PyQtLauncher 构造抛异常时会误清标记）。

    步骤:
      1. counter 递增 + 无条件中间落盘写（独立于 state.json 存活, B 回升依赖）
      2. counter >= 5 → promotion 段（写 config + verify + 清零 / no-op promote）
      3. state.json 清理（os.remove + 双 except 降级 clean 哨兵）
    """
    try:
        # ---- counter / promotion (independent of state.json survival) ----
        # current_mode_str 命名避免与模块级函数 current_mode()(:404) 遮蔽。
        # _read_clean_counter 返回 dict, 调用点 .get 取值。
        current_mode_str = _read_render_mode_from_config()
        new_counter = _read_clean_counter().get("count", 0) + 1
        now_ts = int(datetime.datetime.now().timestamp())

        _write_clean_counter({
            "count": new_counter,
            "last_clean_at": now_ts,
            "since_mode": current_mode_str,
        })

        if new_counter >= _AUTO_PROMOTE_THRESHOLD:
            try:
                _write_render_mode_to_config("auto")
                if _verify_render_mode_written("auto"):
                    _write_clean_counter({"count": 0})
                    append_crash_audit(f"auto_promoted (counter={new_counter})")
                else:
                    append_crash_audit(f"auto_promote_failed_verify (mode={current_mode_str})")
                    # counter 不清零, 中间落盘已保留 new_counter
            except Exception as e:
                append_crash_audit(f"auto_promote_failed_exception: {type(e).__name__}")
                # counter 不清零

        # ---- state.json 清理 (真·现 finish 原文风格) ----
        _clean_state_atomic(now_ts, current_mode_str)
    except Exception:
        # 任何错误不让启动器失败 (与 begin 同构)
        pass