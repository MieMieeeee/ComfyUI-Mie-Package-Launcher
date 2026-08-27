静态复核全部完成（本会话为只读评审、无 shell 工具，测试未实跑——与 v10 评审同口径，53 个用例已逐一手工推演）。以下为 v11 评审输出。

---

# t24 v11 评审：v10 十二项修订复核

**总判定：需修订后再合并。** 核心修订（F1 strict 读取、F2 state 门、F3 文档重写、F4/F5 两个应修测试、F8/F11）验证正确、质量过硬，无新增功能 bug。但修复清单存在**4 项虚报/半报**：F7（mode 行走 wrapper）完全未修、F10（utils/logging.py 注释）文件根本没动（不在 git 修改列表）、F9 只修了行号半项、F6 清单里声称的「decode 失败」用例不存在。其中 F7 使 F3 刚写进 AGENTS.md:132 的「字面量永不含前缀、包装器是前缀唯一来源」契约句被自家代码违反——文档-代码矛盾再度出现。全部剩余项均为 nit 级收尾，约 15 分钟工作量，修完可直接合并不需重审 plan。

---

## 一、F1–F12 逐项复核

| # | 声称 | 实况 | 判定 |
|---|---|---|---|
| F1 | strict + UnicodeDecodeError→unknown | `core/render_guard.py:483` 已去 `errors="replace"`（strict UTF-8）；`:485-487` `except UnicodeDecodeError` → `crash_text=""` → `_classify_last_exit("")` 命中 `:331-332` 返回 `"unknown"` → 不升级。docstring `:25`「decode 失败 → unknown」与实现一致，v10 指出的文档-实现互斥已消除 | ✓ 修复正确；**但零测试**（见 F6） |
| F2 | 恢复 v1 §1.3 state 门 | `:470-474`：state 缺失或 `state=="clean"` → 直接 `cls="clean_or_user"`（连 crash.log 都不读）；其余进分类器。5 个升级类 begin 用例已补 `state="running"` 前置（`tests/unit/test_render_guard.py:333/:351/:370/:423/:441`），新增 TestStateGate 三例（missing/clean/running） | ✓ 修复正确；测试有两处弱化（见 Q2） |
| F3 | AGENTS.md 重写 | AGENTS.md:132 已重写为分类器驱动，逐句与代码核对一致（state 门、四态不升级集合、verify 后才置位、finish 三段、哨兵不带 pid、外层永不抛） | ✓ 基本准确；两处小瑕疵（见 Q3） |
| F4 | audit 前缀动态回归测试 | `test_render_guard.py:751-784` 已落地：monkeypatch `utils.logging._crash_fh` → StringIO，真实 `begin()`，拼回 fixture 文本断言下次分类 `clean_or_user` | ✓ 闭环成立（见 Q4） |
| F5 | AST 第 5 条契约 | `test_render_guard_entry_order.py:207-236` 已落地：`finditer` + `_line_of` 行号过滤到 `fn.lineno..end_lineno` 范围 | ✓ 与 v4 Rev1 sketch 形态一致（见 Q5） |
| F6 | 补 5 类 case | 升级即清零（`:856`）、counter 不动（`:872`）、state 门 3 例（`:890-936`）、分类器 edge 4 例（`:792-845`：裸异常 case 8、`=` 退出 case 17、空块、fatal 在前 case 2）均落地；**「decode 失败」用例不存在**（全文件 grep 无任何非 UTF-8 写入或 UnicodeDecodeError 断言） | △ 大半落地，decode 缺失 |
| F7 | mode 行改走 wrapper | **未修。** `render_guard.py:545` 仍是字面量 `f"[render_guard] mode=..."` 前缀，`:551` 仍直调 `append_crash_report`。grep 证实其余 7 处 audit（`:307/:507/:513/:519/:644/:646/:649`）全走 `append_crash_audit` 包装器，唯独 mode 行违反模块自述契约（`:42-44`、`:287-289`） | ✗ 声称已修、实际未动 |
| F8 | 弹窗文案 | `ui_qt/qt_app.py:5431`、`:5440` 两处均改为「驱动修复后系统也会自动尝试回升（正常关闭累计 5 次后）」 | ✓ |
| F9 | 行号 + 有界措辞 | `:627` 行号已修正为 `(:404)`（`current_mode()` 确在 `:404`）✓；**`:39`「让 counter 永远有界」原样保留**——config 持久损坏时 promote 永远 verify 失败、counter 每次正常关闭无界 +1，措辞仍过强 | △ 半修 |
| F10 | utils/logging.py 注释 | **未修。** `utils/logging.py:157-158` 仍写「两者并存属正常交接」、`:209-210` 仍写「链式共存」；实际 `:100` `sys.excepthook = _excepthook` 直接赋值覆盖 crash hook，install_logging 之后未捕获异常不再进 crash.log。该文件不在 git 修改列表——根本没动过 | ✗ 声称已修、实际未动 |
| F11 | descope 明示 | AGENTS.md:134 新增 descope bullet：明说未落地、现状是 `DialogHelper.show_info` 单按钮、后续补法（`CustomConfirmDialog` + `get_result()`）与参考文件都给了 | ✓ 足够清楚 |
| F12 | 备案 | state.json 各写入点（begin `:530-537` / mark_running `:578-582` / 哨兵 `:605-612`）均无 counter 字段，counter 全走 side 文件，无残留读取者 | ✓ 备案合理 |

## 二、15 问逐答

**Q1（F1 正确性 / GBK 覆盖 / 测过吗）**：正确。strict UTF-8 下 GBK 字节流绝大多数为非法 UTF-8 序列，`f.read()` 抛 `UnicodeDecodeError` → 空文本 → unknown → 不升级，v10 担心的「污染 → 必升级」反转已消除。残留理论边界：GBK 字节恰巧组成合法 UTF-8 序列时会解码成乱码行、可被判 graphics_crash——这是 strict 方案的固有边界（v3 裁决本就接受「覆盖不到的宁漏勿误已尽力」），非回归。**没测过**：全测试文件无一个写非 UTF-8 字节的用例，F1 修复无任何测试锁定。

**Q2（F2 正确性 / 断言严不严 / starting 边界）**：正确。决策表完整还原 v1 §1.3 + 原始 review 口径：缺失/clean → 跳过；`running`、`starting`、损坏 JSON（`_read_json`→None→进分类器）、空 dict、垃圾值 → 进分类器。`starting` 边界没有漏——ctor 期崩溃（begin 写了 starting、没到 mark_running）下次会被分类，且与模块 docstring `:32-33`「starting/running 同一分支」自洽。断言两处弱化：(a) `test_begin_python_exception_does_not_escalate`（`:383`）和 `test_begin_clean_or_user_does_not_escalate`（`:400`）没补 `state=running` 前置，现在经 state 门路径通过——`python_exception` 分类在 begin 集成层已无判别力（仅剩 TestClassifier 的纯函数单测），这两个用例已区分不了「分类后不升级」和「门跳过」；(b) 「state=starting + graphics 段 → 升级」这一门边界无显式用例（TestAuditPrefix 只覆盖 starting + 空段的非升级向）。

**Q3（AGENTS.md 准确性）**：升级机制段（AGENTS.md:132）与代码逐句吻合，v10 的直接矛盾已消除。两处小瑕疵，均不构成矛盾：(a) state 门 bullet 只列举「`state=="running"` → 进分类器」，未提 starting/损坏值也进（代码是「非 clean 即进」），枚举不全；(b) 「三态:」冒号后实际列了四个值（含 unknown），措辞沿用 plan 术语略有歧义但行为描述正确。另注意：段尾「所有 audit 行……字面量永不含前缀」这句**文档是对的、错在代码**（F7 未修），这正是需要修 F7 而非改文档的原因。

**Q4（F4 闭环吗）**：闭环成立。机制核实：`append_crash_report`（utils/logging.py:233-246）在调用时读模块全局 `_crash_fh` 且只写 `line + "\n"`（无时间戳前缀），故 StringIO monkeypatch 生效、产出行以 `[render_guard] ` 开头成为 marker；begin 非升级路径产出两行（wrapper 的 `last_exit=` 行 + 直调的 mode 行），拼回后下次分类为 `clean_or_user`，断言通过。注意该测试锁的是**输出字节**而非「走了哪个函数」——所以它绿着的同时 F7 仍可违规（本案正是如此），二者不可互替。

**Q5（F5 落地与 v4 Rev1 一致吗）**：一致。`finditer` 全文扫描 + `_line_of` 换算行号 + 过滤到 `fn.lineno..end_lineno`（entry_order.py:214-227），三个锚点取函数范围内首现位置。对照源码核实无注释误匹配：launch_gui 体内 `PyQtLauncher()` 首现于 `comfyui_launcher_pyqt.py:407`，`render_guard.mark_running()` 于 `:410`，`window.run()` 于 `:414`，407<410<414，测试真实通过且非空洞。`re.escape` 完整串匹配正确排除了 `:409` 注释里的裸「mark_running」字样。

**Q6（F6 覆盖 / 还差什么）**：F6 清单五要素里落了四个（升级即清零、counter 不动、state 门 3 例、edge 4 例），**「decode 失败」缺失**——这是与 F1 直接联动的用例（v3 case 14），清单声称补了但没有。此外 v10 点名、v11 清单里被悄然缩水掉的仍缺：compat 未到阈值（v5 case 21：counter=3 + compat + finish → 4 不 promote 不改 mode）、多行异常消息（case 7）、不可读文件（case 11）、段边界（case 16）、相邻双 `[uncaught_exception]` marker。这些可以继续缓，但任务表不应记为已补。

**Q7（F7）**：**没修。** `render_guard.py:544-551` mode 行仍字面前缀 + 直调 `append_crash_report`，与 v10 指出的原始形态逐字相同（仅行号漂移）。全模块 8 处 crash.log 写点中 7 处已走包装器，唯独这处例外。

**Q8（F8）**：修了，两处都在（qt_app.py:5431、:5440），文案与 counter 真实语义（正常关闭累计、非连续）一致。

**Q9（F9）**：半修。行号部分（`:627`→`(:404)`）已修；`:39`「counter 永远有界」未动，措辞仍过强。

**Q10（F10）**：**没修。** 两处注释原样（`:157-158`「并存属正常交接」、`:209-210`「链式共存」），且 utils/logging.py 不在本次 git 修改清单里——文件从未被动过。修复表中「覆盖但与设计意图一致」的定性判断是对的，但它没有被写进注释。

**Q11（F11）**：足够清楚。AGENTS.md:134 写明了未落地、现状行为（show_info 单按钮）、恢复路径（改回自动 = 写 config=auto + 清 counter、不删 state）、后续补法（CustomConfirmDialog + `get_result()`）和参考文件，用户/后续 agent 可直接据此外推。

**Q12（F12）**：备案 OK。counter 全量走 side 文件、state 无 counter 字段，所有写入点核实干净。

**Q13（53 个测试）**：**静态逐一推演全部应通过，但未实跑**——本会话只读约束且无 shell 工具（与 v10 评审同口径）。数量核对：test_render_guard.py 48 个（原 38 + 新 10：TestAuditPrefix 1 + TestClassifierEdges 4 + TestBeginCounterClearing 2 + TestStateGate 3）+ test_render_guard_entry_order.py 5 个 = 53。新增 11 个用例逐一手工验证通过（含 TestAuditPrefix 的 StringIO 机制、空 config 的 verify-fail 分支、state 门三态、entry_order 三个锚点位置）；原 38 个在 state 门新语义下重推亦全部通过（两个非升级用例经门路径通过，见 Q2）。**合并门前必须实跑**：`pytest tests/unit/test_render_guard.py tests/unit/test_render_guard_entry_order.py`。

**Q14（新引入的 bug）**：未发现新的功能 bug。state 门本身的三类边界（损坏 JSON→None→进分类器、空 dict→进分类器、PermissionError 哨兵→跳过）行为均正确；wiring、finish 三段、promote/verify、counter 语义与 v10 核对通过的版本一致未动。仅两处非功能瑕疵：(a) 上述测试弱化；(b) 既有 nit（非本轮引入）：模块 docstring `:29`「begin()……写 running 标记」不准确——begin 写 starting（`:535`），running 是 mark_running 的职责，`:528` 的行内注释才是对的。

**Q15（总判定）**：**需修订后再合并**（修订全部为 nit 级收尾，无需重审 plan，修完自查即可合并不必再送评）。理由：核心正确性已过关，但 (1) F7 未修使 AGENTS.md:132 刚写入的「字面量永不含前缀」契约被 `render_guard.py:544-551` 直接违反——文档-代码矛盾是 v10 拦合并的同类问题；(2) F10 整项虚报（文件未动）；(3) F1 的 decode 路径零测试锁定；(4) 修复清单与实际不符的状态若入库会误导后续评审。

**合并前修订清单（按优先序）**：

| # | 动作 | 位置 | 量级 |
|---|---|---|---|
| R1 | mode 行改走 `append_crash_audit`：拆掉字面前缀，`escalated_from/to` 拼进 msg 后经包装器发出 | core/render_guard.py:543-553 | 5 行 |
| R2 | 两个 excepthook 注释改为「覆盖交接」事实（install_logging 直接赋值覆盖，crash.log 此后非全量异常证据，属设计意图） | utils/logging.py:157-158, :209-210 | 2 行 |
| R3 | 补 decode 失败用例：向 crash.log 写 GBK 字节 + state=running → 断言不升级且 `current_mode()` 不变 | tests/unit/test_render_guard.py | 10 行 |
| R4 | `:39` 措辞收敛（如「让 counter 在 config 可写时有界」）；顺手给 `test_begin_python_exception_does_not_escalate` 补 `state=running` 前置恢复判别力 | core/render_guard.py:39 + 测试 | 2 行 |
| R5 | 实跑两个测试文件确认 53/53 | — | 一条命令 |