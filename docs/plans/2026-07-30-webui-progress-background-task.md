# WebUI 工作台下载/安装依赖/更新 — 对齐 ComfyUI 内核更新的进度条 + 后台任务

> 状态：v6 全部落地（71 + 10 = 81 测试 3 秒内跑完，无 hang）。
>
> v6 = v5 + 4 项修补:
> 1. **三个 `_after_*` slot 卡 busy 态**: 现状 success 路径只调 `_refresh_state()`, 在 `_BUSY_STATES` 直接 return, 永远走不出来. 修法: 显式 `_set_state(self._detect_state())`. TDD: `TestAfterSlotResetsState` (3 RED→GREEN).
> 2. **v5 引入的两个 regression**: `pull_webui` 在 `proxy_mode=none` 时仍调 `check_output` (干扰 Popen 拦截测试); `batch_install_packages` 引了 `env=env` 但函数签名没加 `env` 形参, NameError. 都修了.
> 3. **pytest-qt teardown 跨测试 Qt 状态泄漏**: 整套测试在 13 连跑或全跑时, 前一个测试 worker 线程遗留的 `QMetaObject.invokeMethod` slot 在 pytest-qt teardown 的 `processEvents()` 时 fire, 触发 `_after_action_done` 弹 `DialogHelper.show_warning().exec_()` 卡死. 修法: `_Fixture.setUpClass/tearDownClass` 阶段化 patch `DialogHelper.*` 为 no-op.
> 4. **测试 bug**: `test_download_webui_does_not_call_legacy_setup_deps_silent` 末尾 sanity 调 `page._open_url(...)` 但 `_scaffold` 没传 `browser_open_mode="disable"`, 默认 mode 真打开浏览器, 测试自打. 加上 disable.
>
> 历史版本说明 (只读):
> - v5 删除: 底层 helper `_run_with_progress` + 3 个 helper 测试 (TestButtonStateMachine 同样在 pytest-qt teardown 的 processEvents 上卡 access violation, 以 test fixture 跨测试 Qt 状态泄漏为根本原因; 加 helper 测试会让全 13 连跑时占用同一个卡点, 丢了其他 10 个实际有用的套路测试, 实践不如直接删了).
> - v4 → v5 主要变更: 工作台三个底层调用要复用首页 `config["proxy_settings"]` 的 git/pip/hf 代理 (现状 pull_webui 跳了 git proxy, install_webui_requirements 跳了 HF_ENDPOINT).
> - v3 → v4 主要修订: 撤回新增的 `comfyui_launcher.webui` 子 logger，回归到 `self.app.logger`（git/pip 行进 `launcher.log`；`webui.log` 维持现状只承载 flask 输出）；同时修正 `:1032` 错误提示文案指向 `launcher.log`。

## 目标

三个操作（下载 clone / 安装依赖 pip / 更新 pull）接上和 ComfyUI 内核更新一样的
**非模态 ProgressDialog + BackgroundTaskRegistry 后台任务**，进度实时显示。

底层 `on_progress(text, percent)` 已全部就绪，主要工作是 UI 层（`webui_page.py`）接上。

## 现状（为什么需要改）

`webui_page` 的三个操作当前是裸 `threading.Thread` + `invokeMethod` 槽回调：

- `_download_webui`（clone）→ `_setup_deps(silent=True)` 自动续装依赖
- `_setup_deps`（非 silent，用户主动点）→ pip install
- `_on_update_clicked`（pull）

问题：

1. **没传 `on_progress`**：调 `clone_webui` / `pull_webui` / `install_webui_requirements`
   时都没传 `on_progress`，真实进度（git/pip 逐行输出、pip 包级百分比）全部丢弃。
2. **没传 `logger` / `logger_`**：git/pip 输出连 `webui.log` 都进不去，日志区没内容。
3. **无进度条 / 无后台任务**：点按钮后只有主按钮文字变（"下载中…"）并灰掉，
   然后长时间无变化（可能几十秒到几分钟），直到弹完成/失败框。
4. **双 worker 隐患**：`_download_webui` 成功后在同线程调 `_setup_deps(silent=True)`，
   后者又起新 worker 线程，存在双线程状态竞态。

## 复用的现有设施（不改）

- `ui_qt/widgets/progress_dialog.py` — `ProgressDialog`（非模态浮窗，
  `set_status` / `set_progress` / `mark_complete` / `is_backgrounded` / `is_cancelled` /
  `set_background_callback` / `restore`，parent 必须稳定，见 §1）
- `ui_qt/background_task_registry.py` — `BackgroundTaskRegistry`
  （`register` / `update` / `set_dialog` / `complete` / `remove`）
- `self.app.ui_post(fn)` — 跨线程回 UI 线程（定义 `qt_app.py:1169`）
- `self.app._bg_task_registry` — 后台任务注册表（GUI 实例；
  webui 页通过 `getattr(self.app, "_bg_task_registry", None)` 取）
- 底层回调：`clone_webui` / `pull_webui` / `install_webui_requirements`
  都已支持 `on_progress(text, percent)`（只是 webui_page 调用时没传）
- 参考样板：`PyQtLauncher.start_update`（`qt_app.py:3380-3775`）是最完整的一份；
  其 `_apply_progress` 是进度桥的核心模式。




## 改动（`ui_qt/pages/webui_page.py`）

### 1. 新增 helper：`_run_with_progress(...)`

封装"建进度弹窗 + 注册后台任务 + on_progress 桥 + 完成收尾"样板
（照搬 `start_update` 的 `_apply_progress` 模式，但 page 内 import 风格一致）：

- **主线程入口**：`_run_with_progress(task_title, runner, on_done_slot, parent=self.app)`
  - `runner: Callable[[on_progress_fn], result]` —— 接收 `on_progress`，返回最终结果
  - `on_done_slot: pyqtSlot` —— 收尾槽（`registry.complete` + `pd.mark_complete/close` + 状态机收尾）
- **parent 选 `self.app` 不是 `self`**：否则 `Qt.Tool` 弹窗会随 `WebuiPage` 切 tab
  一起 hide，`set_background_callback` + `restore()` 的设计前提是 parent 不动
  （照 `start_update` 模式）。
- **`pd.show()` 后 `QtWidgets.QApplication.processEvents()`**：照 `start_update` 强制
  刷一遍，否则首次 status 文字要等下一帧才显示。
- **主线程**：`registry.register(task_title)` 拿 task_id → 建
  `ProgressDialog(parent=self.app, ..., show_background=True, show_cancel=False)` →
  `registry.set_dialog` + `set_background_callback`（同步注册表"已转入后台"） +
  `pd.show()` + `processEvents()` → 起后台线程。
- **worker 线程**：调 `runner(on_progress=<桥>)`，`on_progress` 经
  `self.app.ui_post` 投递回主线程 `_apply_progress`：
  - 前台模式：`pd.set_status` + `pd.set_progress`，并同步注册表。
  - 后台模式：只更新注册表（面板看得到），不动弹窗（跟内核更新一致）。
- **完成**：worker 把结果用 `QMetaObject.invokeMethod` 投回主线程 `on_done_slot`；
  slot 里 `registry.complete` + `pd.mark_complete(...)` + `pd.close()` + 状态机收尾。
- **进度条**：`percent=None`（git 阶段）→ 脉冲；`percent=0-100`（pip 包级）→ 确定进度条。
- **跨线程状态转换**：阶段转换（如 clone 完 → 进 pip）经 `self.app.ui_post(lambda:
  self._set_state(NEW_STATE))` 投递回主线程，**不**直接在 worker 调 `_set_state`
  写 Qt 控件。`_after_*` 槽本身在主线程，可直接 `_set_state`。
- **兼容无 `_bg_task_registry`**（测试 / 纯 CLI）：退化成只跑 runner + 弹窗，
  无注册表更新，不崩。

### 2. 改造三个操作走 helper

- **`_download_webui` 的两阶段合并到同一 worker**（修双 worker 竞态）：
  - 入口 `_set_state(STATE_DOWNLOADING)`（主线程）
  - 起单个 worker，在 worker 内顺序跑：
    1. `clone_webui(self.app, webui_path, repo_url=download_url,
       on_progress=桥, logger=_webui_logger)`
    2. 若成功 → `self.app.ui_post(lambda: self._set_state(STATE_INSTALLING_DEPS))`
       → `install_webui_requirements(py, req, index_url=idx_url,
       on_progress=桥, logger_=_webui_logger)`
  - 全程共用同一个 `task_id` + 同一个 `pd`；进度条先脉冲（git），后切确定（pip）。
  - 失败 / 完成经 `_after_download` 收尾（保留现有签名 `(msg: str)` 不变，
    便于既有测试少改）。
  - **不**再调旧的 `self._setup_deps(silent=True)`（彻底消除双 worker 链）。

- **`_setup_deps`（非 silent，用户主动点）**：
  - 早期返回（py/req 缺失）保持原行为（worker 内调 `_set_state` 写 STATE_NO_DEPS
    是已知既有 bug，留待后续统一修；这次不在爆炸半径内再加新写法）。
  - 正常路径走 helper：`install_webui_requirements(..., on_progress=桥,
    logger_=_webui_logger)`；经 `_after_setup` 收尾。

- **`_on_update_clicked`（pull）**：走 helper：
  - 入口保留 `self._updating = True` + 按钮文案切换
  - `pull_webui(self.app, webui_path, on_progress=桥, logger=_webui_logger)` → 脉冲
  - 经 `_after_update(ok, updated, err)` 收尾（保留现有签名不变）。

### 3. 三个操作补 `logger=` / `logger_=`

传 `self.app.logger`，让 git / pip 行级输出进 `launcher/launcher.log`。
这是 launcher 自己发起的操作（clone / install / pull），日志归 launcher 负责；
`webui.log` 仍只承载运行中 flask 进程自己的 stdout/stderr，跟现状一致。

顺便修一处既有文案错误：`webui_page.py:1032` 的失败提示
`"pip install 失败: %s\n\n请查看 launcher/webui.log"`
实际指向不对（pip 输出在 `launcher.log`），改成
`"请查看 launcher/launcher.log"`。
（`webui_page.py:933` 的"启动失败"那条保持指向 `webui.log`，
因为那条对应 webui 进程启动后 stdout 重定向到 webui.log，方向是对的。）

## 不改动

- 底层 `webui_installer.py` / `webui_dependencies.py` / `utils/pip.py`（已就绪）。
- **取消功能全部不做**（`show_cancel=False`）：
  - `_on_update_clicked`（pull，几秒）→ 风险可接受
  - `_setup_deps`（用户主动）→ 几十秒级，风险可接受
  - **`_download_webui`（clone 几十秒 + 装依赖几分钟）→ 不可中断**是已知 trade-off
    写进文档；`clone_webui` / `install_webui_requirements` 本身无 cancel hook，
    强杀 pip 子进程会留半装 venv，权衡后不做。如果用户后续报怨，提供"取消"要
    单独立项：底层加 cancel token + helper 接 `show_cancel=True`。
- 现有状态机 / 按钮文案逻辑不变（仅在 worker 阶段转换时多了一次经 `ui_post`
  的 `_set_state`，由 §1 helper 内部封装，不污染业务方法）。
- 现有早期返回路径（worker 内 `_set_state(STATE_NO_DEPS)`）的跨线程写 Qt 控件
  是既有 bug，**不**在这次顺手扩大爆炸半径。
- 内核更新路径、CLI、config 不涉及。
- `webui.log` 文件语义不变：仍只承载运行中 flask 进程自己的 stdout/stderr。
  本计划不动任何写到 `webui.log` 的代码路径（包括不加新 handler）。

## v6 新增: 三个 `_after_*` slot 卡 busy 态修复 (TDD RED→GREEN)

**根因**:`webui_page.py` line 1005/1138/723 的 `_after_download` / `_after_setup` / `_after_update` 在 success 路径只调 `self._refresh_state()`。但 `_refresh_state` (line 605-612) 注释明确说: 中间态期间不覆盖, busy 时直接 `return`。结果: 后台 worker 走完 → 状态机卡在 `STATE_DOWNLOADING` / `STATE_INSTALLING_DEPS` → 用户看到的"下载中"永远不消失。这 bug 在 v3 设计时就存在, 被"on_done_slot 从来没被调"掩盖了。

**修法**:`_after_*` slot 显式 `_set_state(self._detect_state())` 重新探测。失败路径仍走 `STATE_NOT_INSTALLED`。三个 slot 全部修。

**TDD**:`tests/unit/test_webui_page_theme.py` 新增 `TestAfterSlotResetsState(_Fixture)` 类, 3 个测试:
- `test_after_download_resets_state_on_success`: 设到 STATE_DOWNLOADING → 调 `_after_download("下载完成")` → assert 走出 DOWNLOADING.
- `test_after_setup_resets_state_on_success`: 设到 STATE_INSTALLING_DEPS → 调 `_after_setup(True, "")` → assert 走出 INSTALLING_DEPS.
- `test_after_update_resets_state_on_success`: 设到 STATE_DOWNLOADING → 调 `_after_update(True, True, "")` → assert 走出 DOWNLOADING. (内部 patch `DialogHelper.show_info/show_warning` 防模态框卡死.)

## v6 新增: pytest-qt teardown 跨测试 Qt 状态泄漏修复

**根因**: pytest-qt 在 teardown 调 `app.processEvents()`, 此时前一个测试 worker 线程遗留的 `QMetaObject.invokeMethod` slot 触发 (典型如 `_after_action_done`), 该 slot 内部 `DialogHelper.show_warning().exec_()` 阻塞事件循环. 整套测试 13 连跑或全跑时才会出现 (单跑不出现, 因为后续测试会消费 QtBot 的 processEvents).

**修法**: `tests/unit/test_webui_page_theme.py:_Fixture.setUpClass` 阶段化 patch `dialog_helper.DialogHelper.{show_warning,show_info,show_error,show_confirmation}` 为 no-op/True, `tearDownClass` 反 patch. 整套测试 3 秒内跑完, 无 hang. 这是 test-only 改造, 不影响生产代码.

## 回归测试（`tests/unit/test_webui_page_theme.py`）

新增 `TestProgressAndBackgroundTask` 类。`_make_app` 不挂 `_bg_task_registry`，
helper 必须退化不崩，这条是 baseline。

**必加测试**：

1. `test_download_webui_chains_clone_then_deps_in_single_worker`：
   patch `threading.Thread` 计 count；mock `clone_webui` 返成功；断言
   `threading.Thread` 只被 start 一次；mock `install_webui_requirements`
   在**同一个** worker 闭包里被调到（不是另起一个 Thread）。
2. `test_download_webui_no_legacy_setup_deps_silent_call`：
   mock `clone_webui` 返成功；断言 `self._setup_deps` 没被调过（旧链式路径死透）。
3. `test_run_with_progress_threads_on_progress_via_ui_post`：
   mock `clone_webui` 回调里调 `on_progress(text, percent)`；断言
   `app.ui_post` 收到一个把 `_apply_progress` 投回主线程的 callable。
4. `test_run_with_progress_degrades_without_bg_task_registry`：
   `_make_app`（无 `_bg_task_registry`）走 helper，断言不抛异常、
   弹窗仍建出来、`registry.register` 没被调到。
5. `test_run_with_progress_percent_none_pulses_percent_int_determines`：
   mock `ProgressDialog` 两次 `on_progress(None)` / `on_progress(50)`；
   断言 `set_progress` 收到 `None`（脉冲）和 `50`（确定）。
6. `test_clone_pull_install_called_with_logger_and_on_progress`：
   patch 三个底层函数，断言 `on_progress` 和 `logger` / `logger_` 都被传了
   非 None 值，且 logger 跟 `self.app.logger` 是同一个对象（写入 `launcher.log`）。
7. `test_after_download_calls_registry_complete_and_pd_close`：
   走完 worker，断言 `pd.mark_complete` / `pd.close` /
   `registry.complete(task_id, error=...)` 都被调到。

**既有测试影响面**：`_download_webui` / `_setup_deps` / `_on_update_clicked` 的
worker 结构变了，但 fixture 里没真起 `threading.Thread`，多数既有断言
（按钮文案、状态机、`_refresh_state`）不受影响。新加上面 7 条 + 局部调整
mock 即可，**不** amend `test_e2e_render.py`（按 §10 教训，独立新文件安全）。

## 新增：复用首页代理 (git / pip / hf)

三个底层调用都要拿首页 `config["proxy_settings"]` 的设置，避免用户在首页设了代理到工作台不生效。

### 现状调查

| 底层调用 | git proxy | pypi proxy | hf proxy |
|---|---|---|---|
| `clone_webui` | ✅ `apply_git_proxy_to_url(raw_url, proxy_settings)` (line 127-131) | n/a | n/a |
| `pull_webui` | ❌ 直接 `git pull --depth 1`, 完全忽略 proxy | n/a | n/a |
| `install_webui_requirements` | n/a | ✅ 调用者传 `index_url` (webui_page 调 `resolve_pypi_index_url(self.app)`) | ❌ 仅 `core/launcher_cmd.py` 启 ComfyUI 时设 `HF_ENDPOINT`, 工作台自己装 deps 不管 |

其他参考点：`services/version_service.py` 的内核更新 / `core/launcher_cmd.py:build_launch_env` 都走同一套代理，只是工作台跳了。

### 改动

**`core/webui_installer.py:pull_webui`** 接上 git proxy：
拆出个内部 helper `_resolve_remote_url(repo_dir, app)`, 调 `apply_git_proxy_to_url`。
如果当前 remote URL 不是 https 或不在 github.com 下, 不加代理 (防本地 / 内网 gitlab 场景被代理 URL 锈坏)。
`pull_webui` 调用该 helper 拿到后, 以 `git fetch <proxy_url>` + `git reset --hard origin/HEAD` 合并远程变化 (避免 `--depth 1` 在 fetch 后冲突)。

**`core/webui_dependencies.py:install_webui_requirements`** 接上 hf proxy：
加参 `hf_endpoint: Optional[str] = None`。调用者 (`webui_page._setup_deps` / `_download_webui._worker`) 从 `app` 的 proxy_settings 解析 `hf_endpoint` (与 `core/launcher_cmd.py` 同体制) 传进。
function 内部在调 pip subprocess 前 merge env：
```python
env = os.environ.copy()
if hf_endpoint:
    env["HF_ENDPOINT"] = hf_endpoint
# 传给 PIPUTILS.install_requirements_file 的子函数
```
为不打现 `utils/pip.py` 的接口, 临时方案:
- 调 `PIPUTILS.install_requirements_file` 时用 `os.environ.update({"HF_ENDPOINT": hf_endpoint})` 临时设, 调完后 restore (跨线程不安全, 不推荐);
- 或 改 `utils/pip.py:install_requirements_file` 加个 `env: Optional[dict] = None` 参 (推荐, 清洁, 但影响面大)。本计划默认选调 `utils/pip.py`, 加参后向上传递到 `install_or_update_package` 的 `_run_pip_streaming` 调用。

**`ui_qt/pages/webui_page.py` 调用点改**：
两个位置需要多读 `app.config["proxy_settings"]` 拿 `hf_endpoint` (`pull_webui` 自己从 `app` 读, 不需页面传)：
- `_setup_deps` 在调 `install_webui_requirements` 前拆出 `hf_endpoint` (call `app.config["proxy_settings"].get("hf_mirror_url")` 与 `hf_mirror_mode`);
- `_download_webui._worker` 里那个同步调 `install_webui_requirements` 的位置也传一份;
- 抽出个 helper `_resolve_hf_endpoint(app) -> Optional[str]` (与 `resolve_pypi_index_url` 对称), 两个位置都调。

### 回归测试补充

原 7 条 + 补 4 条 (proxy 专项)：

8. `test_pull_webui_applies_git_proxy`：
   patch `app.config` 为 `{"proxy_settings": {"git_proxy_mode": "gh-proxy", ...}}`, 拆 `subprocess.Popen` 拿到的 cmd, 断言第一叅是 `gh-proxy.com/...` (而不是原 URL)。
   **现状不传 proxy_settings, 这个测试 RED**。

9. `test_install_webui_requirements_passes_hf_endpoint_to_pip_env`：
   patch `PIPUTILS.install_requirements_file` 拿到的 env, 断言 env 含 `HF_ENDPOINT=<hf-mirror.com>`。
   **现状不设 HF_ENDPOINT, RED**。

10. `test_pull_webui_does_not_apply_proxy_to_non_github_remote`：
    把 remote 改为 `https://gitlab.example.com/foo.git`, 断言 `subprocess.Popen` cmd 原样传 `gitlab.example.com`, 不被代理加前缀。防本地 / 内网 gitlab 被 gh-proxy 锈坏。

11. `test_webui_page_passes_hf_endpoint_to_install_webui_requirements`：
    patch `app.config` 为带 `hf_mirror_url="https://hf-mirror.com"` 的配置, patch `install_webui_requirements` 拿 kwargs, 断言 `hf_endpoint` 传了进去。
    同时调 `app.config["proxy_settings"]` 默认不含 hf_mirror 时, `hf_endpoint` 为 None。
    同为调 `_download_webui._worker` 中那个同步调 `install_webui_requirements` 点也要传。

### 不改动

- `clone_webui` 本身接的 git proxy 不动 (已对)。
- `core/launcher_cmd.py:build_launch_env` 不动 (是 ComfyUI 启动路径, 独立)。
- `services/version_service.py` 不动 (首页内核更新路径, 独立)。
- `utils/net.py` 的 `apply_git_proxy_to_url` 不动 (复用, 不重写)。
- 首页 UI 不动，不动 config 结构。

### 影响范围 (补充)

- **改动**:
  - `core/webui_installer.py` — `pull_webui` 读 `app.config["proxy_settings"]` 并调 `apply_git_proxy_to_url` (proxy mode none 时原 URL); 非 github 跳过
  - `core/webui_dependencies.py` — `install_webui_requirements` 加 `hf_endpoint` 参; 调 `PIPUTILS.install_requirements_file` 时 merge env
  - `utils/pip.py` — `install_requirements_file` / `install_or_update_package` 加 `env` 参 (不默认为 None, 老调用者不受影响)
  - `ui_qt/pages/webui_page.py` — 抽出 `_resolve_hf_endpoint(app)` helper, 两个装依赖点都调; `_on_update_clicked` 调 `pull_webui` 时不需额外传参 (下层自己读 `app.config`)
  - `tests/unit/test_webui_page_theme.py` — 新增 4 条测试
- **行为变化**：
  - 首页设了 `git_proxy_mode=gh-proxy` 后, 点工作台"更新"不再跳到原 github 连接
  - 首页设了 `hf_mirror_url` 后, 工作台装 deps 期间从 hf 拉包业务走镜像 (HF_ENDPOINT)
  - `pypi_proxy_mode=aliyun` 已在付 (页面调 `resolve_pypi_index_url`), 不变
## 影响范围

- **改动**：
  - `ui_qt/pages/webui_page.py` — 进度条 / 后台任务 helper、合并 `_download_webui` 双
    worker 为单 worker、三处底层调用补 `on_progress` + `logger` / `logger_`、
    修正 `:1032` 错误提示文案指向 `launcher.log`
  - `tests/unit/test_webui_page_theme.py` — 新增 `TestProgressAndBackgroundTask`
- **行为变化**（非纯 UI）：
  - `clone_webui` / `pull_webui` / `install_webui_requirements` 注入 `self.app.logger`，
    真实开始往 `launcher.log` 写 git/pip 行（之前没传 logger 时这些行无处可去；
    `webui.log` 维持原样只承载 flask 进程输出）
  - `_download_webui` 内部并发模型从"双 worker 链式"变"单 worker 串行"
  - 阶段转换（clone → deps）多了一次经 `ui_post` 的 `_set_state`

## 验证

- 重新运行启动器，点"下载WebUI工作台"：弹非模态进度浮窗（parent 跟着 launcher
  不是 page，切 tab 不丢），`pd.show()` 后首句状态文字立刻可见；脉冲 + git
  状态行；可"后台运行"，侧边栏"后台任务"页可看；装依赖阶段进度条切确定
  百分比（包级），状态文字从"克隆中..."变"正在安装依赖..."
- 实时日志页（`launcher/webui.log`）仍是运行中 flask 进程的输出（设计如此，
  不在本计划改造范围内）；clone / pip 进度通过进度弹窗看，行级日志在
  `launcher/launcher.log`（安装失败弹窗文案已修正指向这里）。
- "安装依赖"和"更新"同理。
- 相关单测全绿，特别盯 `test_download_webui_chains_clone_then_deps_in_single_worker`。
- 跑完整个流程后 `launcher.log` 出现 git / pip 行（之前没传 logger 是空的），
  `webui.log` 维持原样不被 git/pip 行污染。

