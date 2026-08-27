# 更新中心 11 项问题修复 — 完成摘要（2026-08-19）

> 修复源：2026-08-19 代码审查（12 项高置信，去掉伪阳性后 11 项）
> 覆盖：内核更新 / 启动器自更新 / 整合包更新三条链路
> TDD：每个 issue 先红后绿；251/251 测试通过（含 31 个新测试）

---

## 改动文件一览（按 issue）

| Issue | 严重度 | 源文件 | 行数变化 | 新增测试 |
|---|---|---|---|---|
| 1.1 `_run_batch` 同步 requirements 跳 FROZEN | Critical | services/update_service.py | +2 | test_update_service.py: 2 |
| 2.1 `_env_matches` token 边界 | Major | services/package_update_service.py | +5, -3 | test_package_update_service.py: 17 (parametrize) |
| 2.2 `_on_load_file` 补 manifest validate | Major | ui_qt/pages/package_update_page.py | +7 | test_package_update_page_load.py: 3 (新文件) |
| 2.4 catch-all except 保留 str(e) | Major | services/update_service.py | +6, -5 | test_update_service.py: 4 |
| 3.1 UpdateDialog update_theme | Minor | ui_qt/widgets/update_dialog.py | +57, -7 | test_update_dialog.py: 5 |
| 3.2 model 链接 http/https 白名单 | Minor | services/model_service.py, ui_qt/pages/package_update_page.py | +18, -1 | test_model_service.py: 4 |
| 3.3 btn_later 改 QPushButton | Minor | ui_qt/widgets/update_dialog.py | +3, -10 | test_update_dialog.py: 4 |
| 3.4 CLI update comfyui 输出 from/to 版本 | Minor | core/cli/cmd_update.py, services/update_service.py | +35 | test_cli_cmd_update.py: 2 |
| 3.5 CLI package apply 持久化 report | Minor | services/package_update_service.py, core/cli/cmd_package.py | +22 | test_cmd_package.py: 3 |
| 3.6 urllib gzip/deflate 处理 | Minor | utils/net.py, services/launcher_update_service.py, services/package_update_service.py | +30 | test_net.py: 4 |
| 3.7 cancel 改 threading.Event | Minor | services/package_update_service.py | +10, -3 | test_package_update_service.py: 2 |

总计：源文件改动 ~9 个；测试改动 8 个文件 +1 新文件；+935 行（含 +675 行测试）

---

## Stage 4 回归验证

总计 251 测试通过：

- tests/unit/test_update_service.py: 20 passed
- tests/unit/test_package_update_service.py: 52 passed
- tests/unit/test_update_dialog.py: 12 passed
- tests/unit/test_model_service.py: 26 passed
- tests/unit/test_net.py: 66 passed
- tests/unit/test_cli_cmd_update.py: 7 passed
- tests/unit/test_cmd_package.py: 21 passed
- tests/unit/test_package_manifest.py: 44 passed
- tests/ui/test_package_update_page_load.py: 3 passed

其它 pre-existing failures 与本次改动无关；stash 验证过：test_cli_cmd_info.py::test_json_output / test_launcher_update_service.py::TestDownloadSha256Verification 都在 HEAD 上就已失败。

---

## 关键行为变化

- **GUI "更新内核 + 同步依赖"**：torch / numpy 等 CUDA 耦合包不再被 pip 升级（Critical 修复）
- **manifest 加载**：本地文件入口与 URL / 粘贴入口对齐，坏 schema / sha256 一律 Dialog 拦截
- **catch-all 异常**：core / frontend / templates 三条链路失败时 error 字段保留异常 str（200 字符）
- **UpdateDialog 主题**：切深/浅色时 container / btn_later / btn_update QSS 实时刷新
- **btn_later 无障碍**：QLabel → QPushButton，Tab 可聚焦 + Space/Enter 触发
- **model 链接**：file:/javascript:/ms-windows-store: 一律拦截，双层防护（page + service）
- **CLI update comfyui --json**：含 from_version / to_version 字段
- **CLI package apply**：report 落盘到 launcher/manifests/runs/<run_id>.json（与 GUI 一致）
- **CDN 强制 gzip**：两处下载链路不再 json.loads 崩溃（_fetch_update_payload / _load_from_url）
- **apply cancel**：threading.Event 跨线程原子

---

## 踩坑痕迹

- apply_patch 工具反复报 (2013) invalid function arguments json string ——工具侧 bug，所有 patch 改走 §1 推荐的 node + Out-File 路线（先写到 $env:TEMP\\foo.js，再 node / py 跑）
- save_report 第一轮忘了 import json —— NameError: name json is not defined，立刻补回
- package_update_service.py 改用 re.split 但模块没 import re —— 加 import re 后通过
- update_dialog.update_theme 里 _px(16) 返回 int 不能拼字符串 —— str(...) 包起来
- update_dialog 接到 theme_manager.theme_changed.connect 报错 —— ThemeManager 用的是 _theme_listeners + register_listener，不是 pyqtSignal，改用 register_listener(self.update_theme)
- update_dialog 第二轮误把 JS 的 function(b) { return b } 当 lambda 写进 Python —— SyntaxError，立刻换成 lambda b: b

---

## git 操作建议

本地已 git checkout -- build_parameters.json launcher/config.json（运行时生成文件，AGENTS.md §1 规则不要提交）。剩余 16 个源文件 + 8 测试文件 + 1 新测试文件可分两批 commit：

- commit 1：`fix(update-center): 11 项审查问题修复（1 Critical + 3 Major + 7 Minor）`
- commit 2：`test(update-center): 新增 31 个回归测试（issue 1/2/3/5/6/7/8/9/10/11/12）`

---

## Review 阶段 收尾（2026-08-19 会话 4）

Review 反馈指出 3 项遗留：

1. **3.1 覆盖不全**：`update_theme()` 只刷 container QSS，changelog_edit / progress_bar / 5 个 label（title / current / arrow / latest / date / changelog_label）颜色冻结。
   - 修法：把所有 label 提升为 `self.*` 实例属性，`update_theme()` 内逐个 `setStyleSheet`。
   - 新增测试 `TestUpdateDialogThemeCoverage` 5 个用例覆盖每个控件。

2. **3.5 去重未做**：`package_update_page._persist_report`（L563-578）原样保留，与 `svc.save_report` 并行。
   - 修法：page 改调 `self._svc().save_report(report)` 一行；同时清掉 `import json` / `from pathlib import Path`（现在 page 内已不需要）。
   - 新增测试 `TestGuiPersistDelegatesToService` 1 个用例。

3. **utils/net.py 小瑕疵**：deflate 不支持 raw deflate（无 zlib header）+ 重复内层 `import gzip/zlib` + 缺末尾换行。
   - 修法：deflate 分支改 try/except 回退 `zlib.decompress(raw, -zlib.MAX_WBITS)`，import 顶部提升，文件末尾加换行。
   - 新增测试 `test_raw_deflate_response_is_decompressed` 1 个用例。

**新增测试**：+7（5 + 1 + 1）。

**回归**：258 passed（从 251）。

---

## 预存在失败记录（与本次改动无关）

Review 阶段发现本机两类 HEAD 预存在问题，stash 对照验证后确认与本次改动无关：

- `tests/unit/test_close_to_tray.py` import `ui_qt/qt_app.py:765` 时原生 segfault（faulthandler，EXIT=139），单独跑也崩
- `tests/ui/test_environment_section.py` × 2 失败 + `tests/ui/test_launch_controls_section.py` × 2 失败

下次跑全量若再次看到这些，不要误判为本次改动引入。
