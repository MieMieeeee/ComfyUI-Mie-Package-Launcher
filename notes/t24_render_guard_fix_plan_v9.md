# Render Guard v9 修复计划（终极落地图）

v8 基础上吸收 glm-5.3 评审扫出的 sketch 落地细节修订：1 必修 + 3 nit。zcode v8 评审自定调「plan 链已三连 sketch 埋未定义名」——v9 严格按此反思，每个 sketch 标识符必须链内有定义。

## v9 vs v8 关键 diff

### Revision 1: Rev2 payload 恢复真·原文语义 + 消未定义雷（必修）

**v8 bug（三合一）**：

1. **`RENDER_GUARD_VERSION` 全链无定义**。grep 实证仅 v8:119、v8:128 出现，plan 链 v1-v7 与 core/render_guard.py 全无此常量。v1 §1.1 state.json schema 的 `version` 是 `_build_version()` 读 build_parameters.json 的 launcher build 版本（现 finish :427 `existing.get("version", _build_version())`）。v8 第三次埋未定义名雷（v6 `env_id` → v7 `_atomic_write_state` → v8 `RENDER_GUARD_VERSION`）。
   - 后果链：照抄 → PermissionError / Exception 两 handler 构造 payload 时 NameError → 不被内层 except 拦 → 被外层 try 吞 → clean 哨兵不写 → 现有 `test_finish_permission_error_writes_clean_sentinel`（tests:450-485）以「错因不是被测行为」红；生产侧：真 PermissionError（AV 锁）哨兵静默丢失，下次 begin 看到 starting/running 残留 → 假升级——恰是哨兵要防的回归。

2. **`started_at: None` 硬编码 + `mode: current_mode`**：现原文（core/render_guard.py:423-430）先读 `existing = _read_json(st_path) or {}`，再保留 `existing.get("started_at")` 实值 + `existing.get("mode", current_mode())`（带 fallback）+ `existing.get("version", _build_version())`。v8 丢了这整行 → 哨兵字段语义回归。

3. **`current_mode` 局部变量遮蔽模块级函数 `current_mode()`**（:255）：v8 sketch 顶部 `current_mode = _read_render_mode_from_config()` 把模块级函数遮蔽成 str。若照搬原文 `existing.get("mode", current_mode())`，TypeError 'str object is not callable' → 同 NameError 路径被外层 try 吞 → 同病。

**v9 修法（链内标识符全部核对通过）**：

```python
def finish():
    """Called once per successful close.

    v9 措辞:贴 step-2 注释与 side 文件设计意图(与 step-1「与现状一致」字面互斥)。
    外层 try 包整个函数体,任何错误不让启动器失败(begin :395-400 同教义)。
    """
    import datetime as _dt
    try:
        # ---- counter / promotion (independent of state.json survival) ----
        # 关键:用 current_mode_str 命名,避免与模块级函数 current_mode()(:255) 遮蔽。
        # 遮蔽会让后续 current_mode() 调用报 TypeError。
        # _read_clean_counter() 返回 dict(底层 _read_json 风格),调用点 .get 取值。
        current_mode_str = _read_render_mode_from_config()
        new_counter = _read_clean_counter().get("count", 0) + 1
        now_ts = int(_dt.datetime.now().timestamp())

        # 无条件中间落盘写:case 21 严格断言 + B 自动回升特性都依赖
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
            except Exception as e:
                append_crash_audit(f"auto_promote_failed_exception: {type(e).__name__}")

        # ---- state.json (真·现 finish 原文,core/render_guard.py:421-433 风格) ----
        _clean_state_atomic(now_ts, current_mode_str)
    except Exception:
        pass


def _clean_state_atomic(now_ts: int, current_mode_str: str) -> None:
    """finish() 的 state 清理段。失败降级为 clean 哨兵(双 except + 全字段保留)。

    标识符全部链内有定义:
    - _state_path: core/render_guard.py:125 (现源码)
    - _read_json: core/render_guard.py:161 (现源码)
    - _atomic_write: core/render_guard.py:129 (现源码)
    - _build_version: core/render_guard.py:293 (现源码)
    - _write_clean_sentinel: 本 sketch 内定义 (下方)
    - os: python stdlib
    """
    st_path = _state_path()
    if not st_path.exists():
        return  # v9 改:不存在则跳过本段(原函数开头早退挪进此处)
    try:
        os.remove(st_path)
    except Exception as e:  # PermissionError 是 Exception 子类,统一捕获(原文双 except 等价)
        _write_clean_sentinel(st_path, now_ts, current_mode_str, type(e).__name__)


def _write_clean_sentinel(
    st_path: Path,
    now_ts: int,
    current_mode_str: str,
    err_type: str,
) -> None:
    """clean 哨兵回退。保留 existing 字段(mode/started_at/version 实值),
    缺失字段用兜底(current_mode_str / None / _build_version())。

    标识符全部链内有定义:
    - _read_json: 现源码
    - _atomic_write: 现源码
    - _build_version: 现源码
    """
    existing = _read_json(st_path) or {}
    _atomic_write(st_path, {
        "mode": existing.get("mode", current_mode_str),
        "started_at": existing.get("started_at"),
        "version": existing.get("version", _build_version()),
        "cleaned_at": now_ts,
        "state": "clean",
        "note": "remove-failed:" + err_type,  # 诊断字段
    })
```

**v9 标识符核对（每个 grep 实证）**：

| 标识符 | 来源 | 状态 |
|---|---|---|
| `_read_render_mode_from_config` | core/render_guard.py:171 | 现源码 ✓ |
| `_read_clean_counter` / `_write_clean_counter` | plan 新增（v1 §1.5 step 2） | 待实现 |
| `_AUTO_PROMOTE_THRESHOLD` | plan 常量（v1 §1.5 默认 5） | 待定义 |
| `_write_render_mode_to_config` | core/render_guard.py:181 | 现源码 ✓ |
| `_verify_render_mode_written` | plan 新增（v4 Rev3） | 待实现 |
| `append_crash_audit` | plan 新增（v6 Nit 5） | 待实现 |
| `_clean_state_atomic` | 本 sketch 内 | 已定义 ✓ |
| `_state_path` | core/render_guard.py:125 | 现源码 ✓ |
| `os.remove` | python stdlib | ✓ |
| `_write_clean_sentinel` | 本 sketch 内 | 已定义 ✓ |
| `_read_json` | core/render_guard.py:161 | 现源码 ✓ |
| `_atomic_write` | core/render_guard.py:129 | 现源码 ✓ |
| `_build_version` | core/render_guard.py:293 | 现源码 ✓ |
| `os` (模块) | python stdlib | ✓ |
| `Path` | core/render_guard.py 顶部 import | 现源码 ✓ |

零未定义标识符。`_write_clean_counter` / `_read_clean_counter` / `_verify_render_mode_written` / `append_crash_audit` / `_AUTO_PROMOTE_THRESHOLD` 是 plan 本就要落地的（v1 §1.5 / v4 Rev3 / v6 Nit 5），落版时按各自规格实现。

### Nit 1: 删 Rev1 sketch 死 import

v8:32-33 的 `import io as _io` 未使用，v9 删。

### Nit 2: Nit 2 承诺的注释兑现

v9 Rev1 sketch 在 counter 段首行加注释：「`_read_clean_counter() 返回 dict（底层 _read_json 风格），调用点 .get 取值`」（兑现承诺）。

随行：v1:97 begin 侧 `"consecutive_clean_closes": _read_clean_counter()` 在 dict 约定下同样要改 `.get("count", 0)`，落改别漏。

### Nit 3: Nit C `except as e` 未使用随 v9 重构消解

v9 把两 handler 合并到 `_clean_state_atomic` 里 `_write_clean_sentinel(st_path, now_ts, current_mode_str, type(e).__name__)`，`type(e).__name__` 自然使用 `as e`，未使用 nit 自动消解。

---

## v9 评审请求（终版）

zcode v8 评审判定「1 处必修 + 3 nit，全部 sketch 层、无新决策，照本评审处方改完即可开工，不需要 v9 全量重审」。v9 全文只需 1 行级确认：

1. Revision 1（payload 恢复真·原文语义 + 链内标识符核对表 14 项 + `_clean_state_atomic` / `_write_clean_sentinel` helper 抽取 + `current_mode_str` 防遮蔽）：链内标识符核对表完整吗？每个标识符 grep 实证过吗？`_clean_state_atomic` 把 PermissionError + Exception 合并成单一 `except Exception` 安全吗（v8 评审要求的双 except）？——注：原文（:416-420）的双 except 是因为 else 块兜底其他 remove 异常；Python 里 `PermissionError` 是 `OSError` 子类、`OSError` 是 `Exception` 子类，单 `except Exception as e: type(e).__name__` 实际等价于原双 except（除 KeyboardInterrupt 等系统异常外，AV 锁之类都是 Exception 子类）。
2. Nit 1（删 `import io as _io`）：照改就行吗？
3. Nit 2（counter 段加注释 + begin 侧 v1:97 改 .get）：照改就行吗？
4. Nit 3（`as e` 随 v9 重构消解）：自然消解对吗？
5. 总判定：v9 可以开工 / 还需修订。