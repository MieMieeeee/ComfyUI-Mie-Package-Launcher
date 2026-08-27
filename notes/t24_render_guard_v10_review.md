# t24 落地代码严核评审（v10）——render guard v9 plan 落地版

**总判定：需修订后再合并。** 2 项必修代码修订（begin() 读 crash.log 的 `errors="replace"` 违反评审钉死的 strict→unknown；begin() 丢失 v1 §1.3 的 state 门）、1 项必修文档同步（AGENTS.md 升级机制段与落地语义直接矛盾）、2 项计划内测试未落地（audit 前缀动态回归测试、AST 第 5 条契约）。finish()/counter/promote/mark_running/哨兵等 v9 Rev1 核心落地质量很高，逐字段忠实；问题集中在 begin() 的两处偏离和测试/文档收尾。本次为纯静态评审（只读约束，未执行测试套件），合并门前应跑一遍 `pytest tests/unit/test_render_guard.py tests/unit/test_render_guard_entry_order.py`。

---

## 1. v9 plan 关键决策落地核对

### 1.1 忠实落地的部分（核对通过）

| 规格 | 落点 | 判定 |
|---|---|---|
| v9 Rev1 finish() 三段拆分（counter 段 → promotion 段 → state 清理段） | core/render_guard.py:610-638 | ✓ 与 v9:29-56 sketch 逐行同构 |
| 无条件中间落盘写（count/last_clean_at/since_mode，int 时间戳，v8 Nit 1） | :614-622 | ✓ v1 §1.5 schema 一致 |
| promotion：去门（v4 Rev4）+ 裸 JSON verify（v4 Rev3）+ verify 过才清零 + 三种 audit 文案 | :624-635 | ✓ 文案与 v9:48-53 逐字一致 |
| `_clean_state_atomic` / `_write_clean_sentinel` helper 抽取，哨兵全字段保留（mode/started_at/version 实值 + 兜底 + note） | :572-597 | ✓ 与 v9:61-103 逐字段一致；不带 pid，符合 AGENTS.md 哨兵描述 |
| 双 except 合并单 `except Exception`（v9 评审三面验证等价） | :578-582 | ✓；外层 :639-641 兜底保持「永不抛」教义 |
| `current_mode_str` 防遮蔽（v8 bug 3） | :614 | ✓ 全函数 4 处引用同步 |
| v8 雷 `RENDER_GUARD_VERSION` / v7 雷 `_atomic_write_state` / v6 雷 `env_id` | 全仓 grep 仅存于 plan 文本 | ✓ 零未定义标识符（14/15 项核对表逐一验证：`:212/:222/:150/:198/:167/:437` 等全部有定义） |
| v9 Nit 1 删 `import io as _io` | 模块无此 import | ✓ |
| v9 Nit 2 counter 段注释 + `_read_clean_counter` 返回 dict | :271-274, :613 | ✓ |
| v6 Nit 3 wrapper 模块级 import | :65 | ✓；utils/logging 仅 stdlib，无循环 |
| v6 Rev 2 counter 无条件递增、早退只限 state 段 | :610-622 / :575-577 | ✓ |
| v6 Nit 1 begin 升级分支内层 try（异常不冒到外层回滚 env） | :481-504 | ✓ verify-fail/exception 两分支都保留 `_escalated` 信号、不清 counter |
| v5 Nit 2 begin 升级 verified 才清 counter | :483-491 | ✓ |
| mark_running 三分支（v1 §1.4 + v3 Diff 4「勿加升级逻辑」docstring） | :547-569 | ✓ clean 哨兵不动（:560-562） |
| E：封顶 `_escalated=True` 置位保留 + 弹窗 `from != to` 门 | :505-508 / ui_qt/qt_app.py:5418-5420 | ✓ 与原始 review E 项「保留置位只改弹窗」精确一致 |
| 入口 wiring：install → lock → prepare(失败分支) → begin(顶层 stmt) → ctor → mark_running → run → finish(try 内非 finally) | comfyui_launcher_pyqt.py:377/:383/:391/:407/:410/:414/:418 | ✓ :389-390 关于 AST stmt 分离的注释与 test 3 的索引机制吻合 |

### 1.2 偏离的部分（详见 §5 F1/F2/F7/F11/F12）

最重的是 **begin() 整段未按 v1 §1.3 落地**（见 F2），以及 crash.log 读取编码方式偏离 v3 评审裁决（F1）。

---

## 2. 算法正确性

### 2.1 分类器（`_classify_last_exit`，:314-358）

与 v3 终版 + v4 两处 nit 一致：段切 `starts[-2]+1:starts[-1]]`（:337，与 v3 含 `starts[-2]` 行的写法等价——该行必命中退出条件）；进入条件 `startswith`（:349，v4 nit「防幻影块」已吸收）；`block_start_marker` 冗余条件已删（v4 nit 2）；退出条件含 `=` 分隔行（:345）。<2 个 `[startup]` → unknown（:335-336）。三种主 case 行为正确：fatal 行块外 → graphics_crash（:356）；`[uncaught_exception]` 块吞掉链式/多行/裸异常 → python_exception（:358）；仅 marker → clean_or_user。

**两个算法层观察：**

- **F13（plan 继承，非落地 bug，备案）**：真实 crash.log 里每个段尾必有下一会话的 `=`×60 分隔行（utils/logging.py:194 先写 `=` 再写 `[startup]`；v3 评审 ：11 的真实样本证实段内四类行含 `=`）。该行命中退出条件会把仍开着的 `[uncaught_exception]` 块关掉 → **生产环境 python_exception 实际永远被判成 clean_or_user**，`last_exit=python_exception` 的 audit 精度损失。两者都不升级，无升级语义危害；v3 sketch 同病，属 plan 固有。落地的 7 个分类器用例 fixture 全部不含尾随 `=`，掩盖了这一点（若按 v3 case 17 写真实形态测试会暴露）。
- 与 F1 相关：docstring :25 声称「decode 失败 → unknown」，但 begin() 用 `errors="replace"`（:471）使该路径不可达——文档与实现互斥（见 F1）。

### 2.2 counter 语义 ✓

中间落盘（:618-622）使 counter 跨 state 存活、硬杀/关机既不 +1 也不清零（v3 Diff 4 #2 语义）；promote verified 后清零（:628）；verify 失败/写异常不清零（:630-635），audit 保留上下文。去门正确：已是 auto 也走 promote 写 auto + 清零（:624 无 mode 门，test :595-604 锁死）。

### 2.3 promote / verify ✓

`_verify_render_mode_written`（:248-261）是 v4 Rev3 裸 JSON 版逐字实现——`_read_json` 对缺失/损坏返 None → `isinstance` False → 校验失败，区分「wrote auto」与「config broken → auto fallback」，test :622-630 用 `{}` config 锁住判别器。`_write_render_mode_to_config` 空/损坏 config 只进程内升级不落盘（:236-239），保全 ConfigManager 损坏保护策略。

一处 nit：docstring :39「counter 永远有界」在 config 持久损坏时（promote 永远 verify 失败）不成立，措辞过强（F9）。

---

## 3. 测试覆盖完整性

现有 38 个用例（prepare 10 + begin 8 + mark_running 3 + classifier 7 + auto-recovery 5 + finish 2 + lock-failure 1 + DLL 2），与任务描述 ~37 相符。断言严格度普遍良好（escalated_detail 精确元组、config 全字段保字面对比、counter 清零精确值）。**缺失如下：**

- **F4（必修级测试缺口）**：`test_begin_audit_lines_dont_trigger_upgrade` 未落地。这是 v4 Rev2 → v5 Rev2 → v6 Rev1 → v7 Rev1 → v8 Rev1 五代打磨的终版用例——StringIO monkeypatch `_crash_fh` + 真实 begin + 对产出文本断言下次分类为 clean_or_user。它是 taskkill/双失败场景下「`[render_guard]` 前缀是唯一保护」（v6 Nit 4）的唯一端到端锁。落地实现本身合规（补上应绿），但约定无测试钉死，后人改动 wrapper 极易无声回归。
- **F5（必修级测试缺口）**：入口顺序 AST 第 5 条契约（mark_running 在 `PyQtLauncher()` 与 `window.run()` 之间）未落地。v1 §8 提出、v3 §5 修、v4 Rev1 修到终版（`finditer` + 行号过滤），链上无人砍掉；wiring 本身正确（comfyui_launcher_pyqt.py:407-414）但无契约锁。
- v1 §7 case 5「begin 升级后 counter 强制清零」无任何测试（升级即清零是 B 特性闭环的一半）。
- v5 Rev1 case 21（counter=3 + compat + finish → 4，不 promote、mode 不变）缺 compat 版：现 increment 用例（:571-582）用 auto config，「未到阈值不改 mode」未被锁。
- v4 三个便宜 case 全缺：fatal+uncaught 且 fatal 在前（case 2）、相邻双 `[uncaught_exception]` marker、marker 后空块。
- v3 清单缺：裸异常无 Traceback 头（case 8）、多行异常消息（case 7）、不可读文件（case 11）、decode 失败（case 14，与 F1 联动）、段边界（case 16）、`=` 退出条件（case 17，见 F13）。
- begin 侧缺「clean 哨兵 state + graphics 段」组合用例——恰是 F2 的判别器，其缺席与偏离本身同源。

---

## 4. 边界处理

覆盖良好：config 不存在/损坏/空（:214-219 兜底 auto、:236-239 不落盘、verify 判别，tested）；state 不存在/损坏/clean（mark_running 三分支 tested）；crash.log 不存在/1 个/0 个 `[startup]` → unknown（tested）；沙盘重定向（autouse `patch_runtime_root` + reload）正确，`_runtime_root` 函数内 deferred import 保证 patch 生效；PermissionError → 哨兵（tested，monkeypatch `os.remove` 与实现 `os.remove(str(...))` 兼容）；磁盘满 → 外层吞（promote 写失败 tested）。

两个边界备注：

- 磁盘满若击中 `_write_clean_counter`（:618），异常直接跳外层 except，`_clean_state_atomic`（:638）被跳过 → state 残留 starting/running。无害：下次 begin 重写 state，分类只看 crash.log（若按 F2 恢复门，state 残留 → 进分类器 → 段内 marker → 不升级，同样无害）。顺序与 v9 sketch 一致，属设计内。
- 断电半截行：splitlines 保留残行，若残的是 `[startup]` 则 <2 starts → unknown，宁漏勿误 ✓。

---

## 5. v9 评审没抓到的实现问题（按严重度）

### F1【必修】begin() 读 crash.log 用 `errors="replace"`，违反链上裁决的 strict→unknown — core/render_guard.py:471

v3 评审（review_v3:46）明确裁决：v2 建议的 `errors="replace"` 被改为 **strict + decode 失败 → unknown**（「宁漏勿误」），并要求 plan 明写 strict 读文件；v3 case 14 由此立。落地代码用 `errors="replace"`：外部 GBK 污染的 crash.log 解不出错，乱码行成为块外「非空非 marker 行」→ graphics_crash → **升级**。污染段不消失（直到 512KB 截断），配合 promote 回升会形成 auto→compat→safe→(5 次 clean)→auto 的振荡。v3 评审接受的边界是「污染 → 永久 unknown 不升级」，落地把它反转成「污染 → 必升级」。修法：去掉 `errors="replace"`（strict），现有 `except → crash_text=""`（:473-474）结构已就位；同步补 case 14 测试、修 docstring :25。

### F2【必修·需决策】begin() 丢失 v1 §1.3 的 state 门 — core/render_guard.py:462-475

plan 链全链一致保留该门：原始 review（review_output:119）「begin() 读到 **state=running/垃圾时**先分类再升级」；v1:73-74 `if not state_path.exists() or state_obj.get("state") == "clean": 不升级`；v4:133「no-state/clean-sentinel 两路径根本不进分类器」；v7 评审 ：21 同一口径。落地 begin() **无条件分类**，不读 state。行为差异收敛到一点：**正常关闭的会话（finish 已删 state）其段内若含良性 faulthandler 误报行（Windows 上已知的 "Windows fatal exception: code page" 类 SEH 误报，CPython gh-89120 家族）→ 下次启动误升级**。有门时该场景天然不进分类器。门的完整决策表（clean/missing→跳过；running→分类）自洽且覆盖 taskkill/断电/原生崩溃全场景，去门只新增误报面、不新增任何正确升级。更重的问题：**落地测试把偏离编码进了断言**——test_begin_graphics_crash_escalates_auto_compat（:331-335）不预写 state 即断言升级，test 注释 ：273-275 自述「v9 算法…state=clean 都不再触发升级」，但 v9 及全链无此决策。建议：恢复门（分类前读 state，missing/clean → 跳过分类，约 5 行），同步给升级类 begin 用例补 state 前置；若 maintainer 有意选纯分类器，需明示签署并同步 AGENTS.md + 补「clean 哨兵 + fatal 段 → 升级」的显式判别测试。

### F3【必修·文档】AGENTS.md 升级机制段与落地代码直接矛盾 — AGENTS.md:132

该 bullet 仍写「`begin()` 读 render_state.json：state=="clean" 或不存在 → 不升级；state=="running" → 升一级」——这是旧 state 驱动语义，与落地分类器驱动（且不论 F2 两种口径取哪种，「state=running 无条件升一级」都已不成立）矛盾；且未提 starting 态、mark_running、render_clean_counter.json、auto-promote、audit 前缀约定。AGENTS.md 是 agent 入口契约（本任务上下文即依赖它），不同步会误导后续 agent 与评审。注意这是仓库文档不是 plan 文档，不在「不改 plan」约束内。

### F4 / F5

见 §3（audit 前缀动态回归测试、AST 第 5 条契约）。

### F7【nit】begin mode 行绕过 wrapper — core/render_guard.py:528-538

v6 Nit 5 钉死「begin mode 行也走（统一约定）、包装器是前缀唯一来源、字面量永不含前缀」（v6:144，v6 评审 ：19 确认「输出字节不变」）。落地仍字面量自带 `[render_guard]` 前缀直调 `append_crash_report`。功能无损（前缀在、单次构造无双前缀风险），纯约定违规；配合 F4 的测试一起收口。

### F8【nit·文案】「连续 5 次成功启动后」两处失真 — ui_qt/qt_app.py:5431、:5440

counter 在 finish()（正常关闭）才 +1，数的是**关闭**不是**启动**；且 v3 Diff 4 #2 明确其语义是「自上次清零以来的累计」而非「连续」（硬杀不清零不断链）。建议改「正常关闭累计 5 次后」。

### F9【nit】过期注释：render_guard.py:612「(:255)」实指 current_mode() 现位于 ：404；:39「counter 永远有界」措辞过强（见 §2.3）。

### F10【nit·plan 项未落】utils/logging.py:157-158、:209-210 注释失真未修

原始 review 三-2【中】+ v1 §4 点名：「两者并存属正常交接/链式共存」实为覆盖（utils/logging.py:100 直接赋值不链式）。文件未动，误导后来人以为 crash.log 是全量异常证据。两行注释的活。

### F11【范围缺口】v1 §3.3 C 项（safe-only 确认弹窗）未落地

plan 链无人砍掉 C：升 safe 时用 CustomConfirmDialog「保留安全模式/改回自动」，改回自动写 config=auto + 清 counter、不删 state。落地对 safe 也只是 DialogHelper.show_info（qt_app.py:5423-5432）。v1 §3.2 的 `last_exit_classification()` API 同未实现——但「升级 ⟺ graphics_crash」的分类器结构已让弹窗因果文案天然为真，API 可豁免；C 是用户可感功能，descope 需明示，否则补齐。

### F12【备案·合理偏差】state.json 未按 v1 §1.1 加 consecutive_clean_closes / last_escalated_at

counter 全走 side 文件后 state 内嵌字段冗余，落地整体删除比 v9 Nit 2 预想的「改 `.get`」更干净，全仓 grep 无残留读取者。合理，备案即可。

---

## 6. 与 AGENTS.md / cli.md / 惯例的冲突

- **AGENTS.md:132 冲突（F3，唯一实质冲突）**。其余 render_guard 相关 bullet 与落地一致：prepare 失败分支只设 env（comfyui_launcher_pyqt.py:383）、begin 拿锁后调（:391）、finish 位置（:418）、crash.log `mode=` 行（render_guard.py:528-538 保留）、DLL 定位命中才设 QT_OPENGL（:377-379）、safe-UI 查询纯 env 未动（grep 证实 8 处 `is_safe_ui` 消费点原样）。
- **cli.md / CLI 路径：零冲突**。render_guard 仍 GUI-only，headless_app.py 无引用（v1 不变量 6 保持）。
- **GUI 主题规范：合规**。弹窗走 DialogHelper，无硬编码色。
- **测试惯例：合规**。沙盘 monkeypatch + autouse reload 模式沿用现有文件结构。

---

## 7. 结论与修订清单

**判定：需修订后再合并。** 核心 v9 Rev1 落地（finish/counter/promote/哨兵/防遮蔽/标识符）质量过硬，可原样保留；修订集中在 begin() 两侧与收尾：

| # | 级别 | 动作 | 位置 |
|---|---|---|---|
| F1 | 必修 | crash.log 读取去 `errors="replace"`（strict），decode 失败 → unknown；补 case 14 | core/render_guard.py:471 |
| F2 | 必修 | 恢复 v1 §1.3 state 门（或 maintainer 明示签署纯分类器并补判别测试）；同步 begin 用例 state 前置 | core/render_guard.py:462-475 |
| F3 | 必修 | AGENTS.md 升级机制段重写为分类器驱动 + 补 counter/mark_running/audit 事实 | AGENTS.md:132 |
| F4 | 应修 | 落地 v8 Rev1 终版 audit 前缀动态回归测试 | tests/unit/test_render_guard.py |
| F5 | 应修 | 落地 AST 第 5 条契约（mark_running 位置） | tests/unit/test_render_guard_entry_order.py |
| F6 | 应修 | 补：升级即清零 / compat 未到阈值 / v4 三便宜 case / case 8·11·16·17 | 同上 |
| F7-F12 | nit | mode 行走 wrapper、弹窗文案「正常关闭累计 5 次」、注释行号、utils/logging 注释、C 项 descope 明示或补齐 | 见 §5 |

F1/F2 修完后无需重审 plan（plan 未变，是代码回归 plan）；若 F2 走「签署纯分类器」路线，则属设计变更，需回补 plan 侧决策记录后再合并。