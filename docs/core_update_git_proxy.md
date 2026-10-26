# 内核更新不走 git 代理导致「一直更新失败」——问题分析与解决方案

> 状态：**已实施**（方案 A + 超时 kill 修复，2026-10-14；全量单测通过）
> 日期：2026-10-14（含审核修订 + 实施记录见 §11）
> 影响面：所有处于「github.com 直连不通」网络环境、且 `proxy_settings.git_proxy_mode` 选了 gh-proxy / 自定义代理的用户
> 严重级别：P0（核心功能对目标用户群 100% 不可用）

---

## 1. 一句话结论

**内核更新的 git fetch/pull 从来不读 `config.proxy_settings`，永远直连仓库里存的 origin URL。**
用户配置了 gh-proxy，但那个代理只透给了 cm-cli（插件操作）子进程，内核更新这条路上完全没代理，
直连 github.com 被重置 → 每次点「更新内核」都在几秒内以同一句 `Recv failure: Connection was reset` 失败。

---

## 2. 问题现象（日志实证）

用户日志包 `comfyui-logs-20261014_100326/launcher.log`，10:01~10:03 连续 5 次点击「更新内核」，
**5 次全部失败，报错字符串完全一致**，每次耗时 5~8 秒：

```
10:01:26,833 内核更新完成: {'component': 'core', 'error': "fatal: unable to access
             'https://github.com/Comfy-Org/ComfyUI/': Recv failure: Connection was reset\n"}
10:01:26,835 WARNING 内核更新失败: fatal: unable to access ...

10:02:14,509 开始更新内核，超时设置: 120秒
10:02:22,770 内核更新完成: {'component': 'core', 'error': "fatal: unable to access ... 同上 ..."}
10:01:26,835 WARNING 内核更新失败: ...

10:02:38,702 开始更新内核，超时设置: 120秒     → 10:02:46,977 失败
10:02:53,610 开始更新内核，超时设置: 120秒     → 10:03:01,887 失败
10:03:15,733 开始更新内核，超时设置: 120秒     → 10:03:20,744 失败
```

关键点：

| 观察 | 含义 |
|---|---|
| 报错 URL 是 `https://github.com/Comfy-Org/ComfyUI`（**直连**） | 内核仓 origin 没被代理 |
| 每次 5~8 秒就返回 | 是连接被重置，**不是超时**（超时会是 120s） |
| 5 次一模一样 | 不是偶发抖动，是确定性失败，重试无用 |

同一份日志里，插件仓的 origin 全是 `https://gh-proxy.com/https://github.com/...`（**走代理**），
所以用户看到的是「插件能更新、内核就是不行」。

**附带的定位信息**：用户 config 是 `version_preferences.stable_only = false`，走的是
`upgrade_latest(stable_only=False)` 分支——该分支会把 `fetch` 的 stderr **原样**带回
（`services/version_service.py:830-838`），所以日志里能看到直连 URL 和连接错误。
稳定版分支的文案不同（API 已走代理，git fetch 失败会被吞掉，最终报「No stable tag found」），
但两条路径是同一处注入能覆盖的。

---

## 3. 根因

### 3.1 内核更新的 git 调用链，全程无代理

```
ui_qt/qt_app.py::start_update
  └─ services/version_service.py::upgrade_latest            (:746)
       ├─ run_git_network(["git","fetch","--prune"])       (:824, timeout=30)
       ├─ run_git_network(["git","pull","--ff-only"])      (:900, timeout=60)
       └─ run_git_network(["git","pull","--rebase"])       (:912, timeout=120)  ← ff-only 失败后的 fallback
              └─ VersionService.run_git_network             (:109)
                   ├─ _run_git                              (:57)
                   │    └─ utils/common.py::run_hidden      (无 env 代理)
                   └─ _run_git_cancellable                  (:144)
                        └─ subprocess.Popen                  (连 env 都不传，完全继承 os.environ)
```

`utils/common.py::run_hidden` 对 git 的唯一环境干预是低速超时
（`GIT_HTTP_LOW_SPEED_TIME=15` / `GIT_HTTP_LOW_SPEED_LIMIT=1000`，`utils/common.py:104-118`），
**没有任何代理相关注入**。git 于是直接使用仓库 `.git/config` 里存的 origin URL。

### 3.2 代理设置只喂给了 cm-cli

`config.proxy_settings.git_proxy_mode` 在启动器里有两处消费点，都**不覆盖内核 git**：

| 消费点 | 机制 | 服务对象 |
|---|---|---|
| `services/plugin_service.py::_git_proxy_config_path` (:1046 附近) → `_apply_git_proxy_env` (:1101) | 物化 `launcher/gitconfig.proxy`（`url.<前缀>.insteadOf`），用 `GIT_CONFIG_GLOBAL` 注入 | cm-cli / 插件 git 子进程 |
| `core/webui_installer.py:168,311` → `utils/net.py::apply_git_proxy_to_url` | 直接给 clone/pull 的 URL 加代理前缀 | webui 安装器 |
| （缺）内核更新 | — | **无** |

全项目 grep `GIT_CONFIG_GLOBAL` 只有 plugin_service 一处。
`services/version_service.py::_apply_proxy_to_path`（:308）虽然也读代理模式，但**只用来拼
GitHub API 的 URL**（`_get_releases` / `_get_tag_commit_via_api`），跟 git 传输层无关。

> 注：`core/webui_installer.py:4` 的文件头注释写着 webui 的 clone 代理「跟 ComfyUI 升级同源」——
> 这句话现在是**反的**：webui 有代理处理，内核升级没有。改完顺手更正。

### 3.3 同一个 bug，插件侧已经修过了

`services/plugin_service.py:473` 的 docstring 记录了同源事故：

> 代理原先只透给 cm-cli 子进程（`_run_cmcli_script`），启动器自己跑的 git（`_git_out` / `_git_run`：
> rev-parse、**ls-remote**、log）没带 env → 配置了 gh-proxy 的用户，「检查更新」的 ls-remote 直连
> github 失败 → `_git_out` 返回空串 → 判定「取不到远端 = 不落后」→ 误报「所有插件均为最新」。
> 同一时刻「更新全部」走 cm-cli（有代理）却能成功。

也就是说：插件侧的 `_git_out` / `_git_run` 后来补上了 `_git_env()`，**内核侧的 `version_service` 一直没人管**。

---

## 4. 本机复现与验证

本机 github.com 直连是通的，直接点更新**不会复现**。因此用 `insteadOf` 精确模拟用户的被墙网络，
跑**真实的** `VersionService.upgrade_latest(stable_only=False)`（脚本：`notes/repro_core_update_proxy.py`，
工作目录 `F:\tmp\cu_repro`，先 `git clone --depth 1 https://github.com/Comfy-Org/ComfyUI`）：

| 场景 | git 实际访问 | 耗时 | `upgrade_latest` 返回 |
|---|---|---|---|
| **A** 直连（本机现状） | `https://github.com/Comfy-Org/ComfyUI` | 4.5~6.8s | `{'updated': False, 'branch': 'master'}` 成功 |
| **B** 直连打死 + 启动器不挂代理 | `http://127.0.0.1:1/Comfy-Org/ComfyUI` | 2.2s | `{'error': "fatal: unable to access '...': Failed to connect to 127.0.0.1 port 1 ..."}` ← **与用户报错同形状** |
| **C** 挂上代理 gitconfig | `https://gh-proxy.com/https://github.com/Comfy-Org/ComfyUI` | 3.5~4.0s | `{'updated': False, 'branch': 'master'}` 成功 |

结论：

1. 场景 B 复刻了用户的失败（`fatal: unable to access '<url>': <连接层原因>` 由 `upgrade_latest`
   原样带回 → GUI 渲染成「内核：更新失败（...）」，与日志逐字对得上）。
2. 场景 C 证明**只要把代理规则应用到启动器自己的 git 调用，内核更新就能通**。
3. 顺带实测：本机直连可用时 fetch+pull 全程 ~5s，远低于 120s 预算（见 §6.5 的 P2 讨论）。

### 4.1 `-c url.<前缀>.insteadOf` 的本机行为核对（git 2.55）

用 `git remote get-url`（会应用 insteadOf 改写）实测四种输入：

| 输入 / 场景 | `git remote get-url origin` 输出 | 结论 |
|---|---|---|
| 基线，无 `-c` | `https://github.com/Comfy-Org/ComfyUI.git` | — |
| `-c 'url."<前缀>".insteadOf=...'`（**argv 里带引号**） | `"https://gh-proxy.com/https://github.com/"Comfy-Org/ComfyUI.git` | **坏地址**，引号被当字面量吞进 URL |
| `-c url.<前缀>.insteadOf=...`（argv 不带引号） | `https://gh-proxy.com/https://github.com/Comfy-Org/ComfyUI.git` | 正确改写 |
| origin 已是代理地址 | `https://gh-proxy.com/https://github.com/Comfy-Org/ComfyUI.git` | **不会二次套娃**（前缀匹配的是 `https://github.com/`，已代理的 origin 不以它开头） |
| origin 是 SSH `git@github.com:` | `git@github.com:Comfy-Org/ComfyUI.git` | 不被改写（SSH 本轮不在范围内） |

> ⚠️ 第一行是本方案最容易踩的坑：**每个 `-c` 必须是单独一个 argv 元素且不带引号**。
> 文档/注释里可以写 shell 形式方便阅读，但**不能把带引号的字符串塞进 argv 列表**。

---

## 5. 影响面

| 受影响对象 | 表现 | 严重度 |
|---|---|---|
| github 直连不通 + 代理模式非 none 的用户 | 「更新内核」100% 失败，无任何可用绕过（GUI 内） | P0 |
| 同上用户 | 版本管理页「提交历史」后台 fetch（`ui_qt/pages/version_page.py:406,419`，走 `run_git_network`）静默失败，列表永远不刷新 | P1 |
| 同上用户 | 弹窗标题显示「更新 ComfyUI 内核 (Comfy-Org/ComfyUI, 通过 gh-proxy)」，**与当前行为相反**；修复后自动变正确（见 §6.4） | P1（误导，仅修复前） |
| 所有用户 | 报错文案直接把 git 原始 stderr 抛给用户，没有「为什么失败 / 怎么开代理」的引导 | P2 |

---

## 6. 解决方案（审核修订版）

### 6.1 主方案：给内核侧网络 git 命令前置 `-c url.<前缀>.insteadOf=...`

在 `VersionService` 发出网络类 git 命令时，按 `config.proxy_settings` 在 git 可执行文件之后、
子命令之前插入：

```text
git -c url.https://gh-proxy.com/https://github.com/.insteadOf=https://github.com/ \
    -c url.https://gh-proxy.com/https://gitlab.com/.insteadOf=https://gitlab.com/ \
    fetch --prune
```

**前缀直接复用现成 helper，不要新写拼法**（审核新增的发现）：

```python
# utils/net.py 已有 apply_git_proxy_to_url（webui clone 就在用，自带幂等 + 尾斜杠处理）
prefix = NETUTILS.apply_git_proxy_to_url("https://github.com/", proxy_settings)
# gh-proxy -> "https://gh-proxy.com/https://github.com/"
# custom   -> "<git_proxy_url 去尾斜杠再补>/https://github.com/"
# none     -> 原样返回 => 不注入
args = ["-c", f"url.{prefix}.insteadOf=https://github.com/",
        "-c", f"url.{NET.apply_git_proxy_to_url('https://gitlab.com/', ps)}.insteadOf=https://gitlab.com/"]
```

建议在 `utils/net.py` 加一个 `git_insteadof_args(proxy_settings) -> list[str]` 薄封装，
规则拼法与 `plugin_service._git_proxy_config_path` 保持一致（github + gitlab 两个前缀）。

**为什么选它**：

- `-c` 是**单次子进程作用域**，不落盘、不改用户 `~/.gitconfig`、不设 `GIT_CONFIG_GLOBAL`；
- 天然不覆盖用户全局 gitconfig（§6.3 的坑不存在）；
- 不改仓库 origin，用户随时能在终端里看到/改回真实地址；
- `proxy_mode = none` 时 `apply_git_proxy_to_url` 原样返回 → 自然零注入；
- origin 已是代理地址时不二次套娃（§4.1 实测）。

### 6.2 注入范围与实现要点（审核逐条核对过）

| 要点 | 结论 |
|---|---|
| 注入点 | `VersionService._run_git`(:57) 与 `_run_git_cancellable`(:144) 两处，**6 个内部 `run_git_network` 调用点不用逐个改** |
| 触发子命令 | 仅 `fetch` / `pull` / `ls-remote` / `clone`（与 `utils/common.py:104-118` 已有的判定集一致）；本地只读命令（`rev-parse`/`log`/`describe`/`status`）不加 |
| 插入位置 | 紧跟 `cmd[0]`（git 可执行文件）、子命令之前 |
| ⚠️ `cmd[0]` 不一定是 `"git"` | 版本页 `ui_qt/pages/version_page.py:400,406,419` 传的是 `self.app.git_path` **全路径**。`_run_git` 里 `str(cmd[0]).lower() == "git"` 的替换逻辑对它是 no-op。**必须按子命令名判断，不能靠 `cmd[0] == "git"`** |
| ⚠️ `-c` 必须进 argv | `_run_git_cancellable`(:144) 自己 `Popen` 且**不传 `env`**，靠环境变量加不上 |
| ⚠️ 不要原地改 cmd | `_run_git` 已经会 `cmd[0] = gp` 原地改写；注入应构造**新列表**，避免 `run_git_network` 之外的调用方（如 version_page 持有的列表）被二次注入 |
| dubious ownership 重试 | `_run_git` 与 `_run_git_cancellable` 的重试分支都复用同一条 cmd，注入发生在**第一次执行之前**即可，两次都带 |
| 不覆盖的路径 | `version_page.py:415,428` 的 `else: run_hidden([git,"fetch"...])` 兜底分支绕过 version_service（仅在无 version_svc 时才走），本轮不改 |

### 6.3 已否决：不复用 `GIT_CONFIG_GLOBAL`（备选方案 B）

曾考虑把 `plugin_service._git_proxy_config_path` 抽公共模块给内核用，**本轮否决**，理由：

git 的语义是**一旦设了 `GIT_CONFIG_GLOBAL`，就不再读用户自己的 `~/.gitconfig`**。启动器生成的那份
文件只有 `insteadOf` 几行，于是用户在全局 gitconfig 里配的东西全部失效：

- `http.proxy` / `https.proxy`（靠 Clash、EasyConnect 直连的用户）
- `credential.helper`（私有仓认证）
- `http.sslBackend` 等调优

核心仓是公开仓，影响有限；`-c` 方案零副作用，没必要冒这个险。

> **顺带待办（不属于本方案，另开）**：插件侧 `_git_env` 一直在用这个机制，
> **私有插件仓的用户可能已经在丢认证**，值得单独核查。若要保留，缓解办法是在生成的
> `gitconfig.proxy` 顶部加 `[include] path = <用户 .gitconfig>`（仅当该文件存在时写入）。

### 6.4 已否决的两条附带修正

| 原建议 | 处置 | 理由 |
|---|---|---|
| 6.4.1「直连失败后自动走代理重试一次」 | **不做** | 默认配置本就是 `gh-proxy`（`config/manager.py:104-106`），不需要先失败一次；重试还会把非快进、本地修改这类真错误再跑一遍，白白放大耗时 |
| 6.4.2「弹窗标题改成读实际 origin 判断直连/代理」 | **不做** | 方案 A 不改 origin，origin 会一直是 `github.com`，用它判断会把标题说反。修好传输后 `describe_git_proxy` 拼的「通过 gh-proxy」就与真实行为一致了，不用改 |

**保留执行**：删掉死代码 `_VMStub.compute_proxied_url`（`ui_qt/qt_app.py:1043`）——全仓库无调用方，
且它拼的是短地址 `gh-proxy.com/github.com/...`，与 insteadOf 用的完整地址不是一回事，留着容易误导下一个人。

### 6.5 P2：超时倒挂 + 孤儿 git 进程（本次事故没触发，但审核指出了更深的问题）

现象链（已核对 `ui_qt/qt_app.py:3712-3735`）：

1. 外层 `future.result(timeout=120)` 到期 → 抛 `TimeoutError`；
2. 代码只调了 `future.cancel()`（:3733）——**对已经在跑的任务无效**，worker 线程继续执行；
3. 紧接着 `with ThreadPoolExecutor`（:3712）退出时 `shutdown(wait=True)` → **worker 所在的
   `_worker` 线程会一直阻塞到内层 git 结束**（内层最坏 30+60+120=210s），期间 GUI 的进度弹窗卡住；
4. 等 worker 终于返回，**成功结果也被丢弃**（`core_res` 早已被 TimeoutError 分支写成「更新超时」）。

处理建议（审核意见，采纳）：

- 超时分支改调 `self.services.version.request_cancel()`，它会 `terminate`/`kill` 正在跑的 git Popen
  （`version_service.py:83-97`），让 worker 能尽快返回；
- **单纯把 120 秒放大盖不住这条**——必须先杀掉 git 进程；
- 内层 30+60+120 只有在 `--ff-only` 失败后才加满，正常情况是 30+60；
- 这条与代理修复可以分开提交，但建议同批做，否则用户第一次遇到慢网就会遇到「弹窗卡死 + 报告超时但其实成功了」。

### 6.6 SSH remote 不在本轮范围

`git@github.com:` 开头的 origin 不会被 insteadOf 改写（§4.1 实测），也不套 `-c`。
与插件侧 `plugin_service._GIT_PROXY_ORIG_PREFIXES` 只覆盖 https 的既有取舍一致。

### 6.7 用户侧临时绕过（正式修复发布前救急）

在 ComfyUI 目录手动把 origin 改成代理 URL：

```bash
cd "<整合包根目录>/ComfyUI"
git remote set-url origin https://gh-proxy.com/https://github.com/Comfy-Org/ComfyUI
git fetch --prune && git pull --ff-only
```

或在启动器「设置 → GitHub 代理」里改成「不使用」（仅当用户本机有 Clash 等系统级代理时有效）。

---

## 7. 改动清单（方案 A 定稿）

| 文件 | 改动 |
|---|---|
| `utils/net.py` | 新增 `git_insteadof_args(proxy_settings) -> list[str]`；内部**复用已有的 `apply_git_proxy_to_url`**（:156），github + gitlab 各产出一条**不带引号**的 `-c` 参数 |
| `services/version_service.py` | `VersionService` 增 `_proxy_cmd_args()`：按子命令名（fetch/pull/ls-remote/clone）判定，构造**新列表** `[cmd[0], *args, *cmd[1:]]`；`_run_git`(:57) 与 `_run_git_cancellable`(:144) 各调一次，保证 `Popen` 路径也带上。6 个内部调用点与 version_page 的 2 个调用点均自动受益 |
| `ui_qt/qt_app.py:1043` | 删死代码 `_VMStub.compute_proxied_url`（无调用方） |
| `ui_qt/qt_app.py:3724-3735` | 超时分支改调 `services.version.request_cancel()`（§6.5，可拆成独立提交） |
| `core/webui_installer.py:4` | 更正文件头注释「跟 ComfyUI 升级同源」——现状是反的 |
| `tests/unit/test_core_update_git_proxy.py` | 新增（见 §8） |
| `AGENTS.md` | 「坑」小节补一条：内核 git 不走代理的历史与踩坑 |

---

## 8. 测试方案

新增 `tests/unit/test_core_update_git_proxy.py`：

1. **代理注入**：`proxy_mode=gh-proxy` 时，`_run_git(["git","fetch","--prune"])` 实际发出的 argv 含
   `url.https://gh-proxy.com/https://github.com/.insteadOf=https://github.com/`；
2. **argv 不带引号（回归重点）**：断言注入后的参数里**不含** `"` 字符，位置在 git 可执行文件之后、
   子命令之前。对应 §4.1 第一行那个坏地址——这是本方案唯一会静默产出坏 URL 的写法；
3. **第一次就注入**：断言**第一次**发出的 argv 里就有 `-c`，不存在「先直连、失败再带代理」的路径
   （§6.4.1 已否决该设计）；
4. **`cmd[0]` 是全路径**：用 `version_page` 的形态（`cmd[0]` = git.exe 绝对路径 + `fetch`）断言照样注入；
5. **可取消路径同样生效**：`_run_git_cancellable(["git","pull","--ff-only"])` 的 `Popen` argv 含 `-c`
   （**最容易漏的一条**，它不经过 `run_hidden`、不传 env）；
6. **不注入**：`proxy_mode=none` 时 argv 与改动前逐字相同；只读命令（`rev-parse`/`log`/`describe`）不带 `-c`；
7. **不原地改 cmd**：传入的 list 调用后未被修改（防止 version_page 持有的列表被二次注入）。

回归：全量单测按项目惯例用全新 basetemp 跑（残留 `tests/.pytest_tmp` 会批量 ERROR）：

```bash
python -m pytest tests/unit -q --basetemp=tests/.pytest_tmp_new -p no:pytest-qt
```

本机 ComfyUI 在跑时注意套用既有的密闭套路（临时端口 / `_no_real_port_scan` /
patch `_NO_PROXY_OPENER` 与 psutil），避免误碰真实服务。

---

## 9. 审核意见与处置记录（2026-10-14）

| # | 审核意见 | 处置 | 依据 |
|---|---|---|---|
| 1 | 根因与调用链与代码一致，方案 A 站得住 | 采纳 | 已复核 `_run_git` / `_run_git_cancellable` / `run_git_network` 全链路 |
| 2 | argv 不能带引号，否则得到坏地址 | **采纳并写入 §4.1 + §7 + §8.2** | 本机 git 2.55 实测复现坏地址 `"https://gh-proxy.com/https://github.com/"Comfy-Org/ComfyUI.git` |
| 3 | origin 已代理不二次套娃、SSH 不改写 | 采纳，写入 §4.1 / §6.6 | 本机实测 |
| 4 | 不做「直连失败再重试」，改为第一次就带 `-c` | **采纳**，删除原 6.4.1 | 默认配置即 `gh-proxy`（`config/manager.py:104-106`）；重试会重跑真错误 |
| 5 | 标题继续用 `describe_git_proxy`，不要读 origin | **采纳**，删除原 6.4.2 | origin 按方案 A 永远是 `github.com`，读它会把标题说反 |
| 6 | `cmd[0]` 可能是 git 全路径，要按子命令判断 | **采纳**，写入 §6.2 | `version_page.py:400,406,419` 传 `app.git_path` 全路径 |
| 7 | `-c` 必须进 argv，`_run_git_cancellable` 不传 env | 采纳，写入 §6.2 / §8.5 | 该处 `Popen(cmd, **popen_kwargs)` 无 env |
| 8 | dubious ownership 重试复用同一条 cmd，注入要在第一次执行前 | 采纳，写入 §6.2 | `_run_git` / `_run_git_cancellable` 的重试分支均复用 cmd |
| 9 | `compute_proxied_url` 删掉 | 采纳，写入 §7 | 全仓库无调用方；短地址与 insteadOf 完整地址不是一回事 |
| 10 | 超时时应调 `request_cancel()`，单纯放大秒数盖不住 | **采纳并升级**，写入 §6.5 | `qt_app.py:3733` 只调 `future.cancel()`（对运行中任务无效）+ `with` 退出 `shutdown(wait=True)` 阻塞、成功结果被丢 |
| 11 | SSH remote 不在本轮范围 | 采纳，写入 §6.6 | 与插件侧既有取舍一致 |

**审核之外我补充的两点**：

- 审核建议「前缀拼法跟 `plugin_service._git_proxy_config_path` 一致」——实现时**不要照抄那段拼法**，
  `utils/net.py:156` 已有 `apply_git_proxy_to_url`（webui clone 在用，自带幂等 + 尾斜杠处理 + 防双 prefix），
  直接复用，避免第三份 magic。
- `core/webui_installer.py:4` 的文件头注释称 webui 代理「跟 ComfyUI 升级同源」，实际是反的，
  已列入 §7 改动清单顺手更正。

---

## 10. 附：本机验证脚本

`notes/repro_core_update_proxy.py` —— 跑真实 `VersionService.upgrade_latest()` 的三场景对照
（直连可达 / 直连被打死 / 挂代理 gitconfig），用法：

```bash
mkdir -p F:/tmp/cu_repro && cd F:/tmp/cu_repro
git clone --depth 1 https://github.com/Comfy-Org/ComfyUI ComfyUI
python <仓库>/notes/repro_core_update_proxy.py
```
---

## 11. 实施记录（2026-10-14）

按审核修订稿落地，四条硬约束全部守住。

### 11.1 实际改动

| 文件 | 改动 |
|---|---|
| `utils/net.py` | 新增 `git_insteadof_args(proxy_settings)` / `git_cmd_needs_proxy(cmd)` + `GIT_NETWORK_SUBCOMMANDS`。**纯新增**（`git diff` 中无一行删除，未动任何既有逻辑），内部复用既有的 `apply_git_proxy_to_url` |
| `services/version_service.py` | 新增 `_proxy_cmd_args()` / `_apply_git_path_and_proxy()`；`_run_git` 与 `_run_git_cancellable` 各在入口调一次 |
| `ui_qt/qt_app.py` | 超时分支 `TimeoutError` 改调 `services.version.request_cancel()`（排在 `future.cancel()` 之前）；删除死代码 `_VMStub.compute_proxied_url` |
| `core/webui_installer.py` | 文件头注释更正为「两边都复用 `apply_git_proxy_to_url`；webui 改传给 git 的 URL，内核用 `-c insteadOf`、不改 origin」 |
| `tests/unit/test_core_update_git_proxy.py` | 新增 21 条（§8 全部条目） |
| `tests/unit/test_start_update_threads.py` | 新增 `TestStartUpdateTimeoutKillsGit`（行为 + 源码结构两条） |
| `AGENTS.md` | 「坑」小节补两条：内核 git 代理三约束、超时必须 `request_cancel()` |

### 11.2 四条约束的落实

1. **argv 不带引号**：`git_insteadof_args` 用 `'url.{0}.insteadOf={1}'.format(...)` 拼出**单个** argv
   元素，值里没有任何 `"`；`apply_git_proxy_to_url` 返回值与入参相同（`none` / custom URL 空 / 未知模式）
   时直接 `continue`，不产出 `-c`。测试 `test_insteadof_args_gh_proxy_shape` 断言 `not any('"' in a ...)`。
   *origin 已代理不套第二层* 是 git 的前缀匹配保证的（已代理的 origin 不以 `https://github.com/` 开头），
   跟 `apply_git_proxy_to_url` 的幂等无关 —— 注释里已写明，避免后人误解。
2. **子命令按 `cmd[1:]` token 判**：`git_cmd_needs_proxy` 集合为 `fetch` / `pull` / `ls-remote` / `clone`，
   不依赖 `cmd[0] == "git"`，版本页传 git 全路径照样命中。`utils/common.py` 的低速超时集合
   （`fetch`/`pull`/`clone`，无 `ls-remote`）**未动**，两处各司其职。
3. **先复制再改**：`_apply_git_path_and_proxy` 第一步就 `list(cmd)`，之后才换 git 路径、再插 `-c`，
   返回新列表；调用方持有的 list 不受影响（测试 `test_apply_does_not_mutate_input_list` 断言
   同一 list 连过两遍 `-c` 不会叠加）。`_run_git_cancellable` 的 dubious ownership 重试复用已注入的
   `cmd`，两次都带。
4. **`request_cancel()` 覆盖范围**：它只杀 `_run_git_cancellable` 记下的 Popen，正覆盖 `stable_only=False`
   的 `fetch --prune` / `pull --ff-only` / `pull --rebase`（用户日志失败的那几条）。稳定版分支的
   `git fetch --tags` 走 `subprocess.run`，杀不到 —— **已在 AGENTS.md 与测试 docstring 里注明**，
   这是已知边界，不是遗漏。

### 11.3 验证结果

**端到端差分（真实 git，非 mock）**：把 `git_proxy_mode=custom` 指向死端口 `http://127.0.0.1:1/`，
看流量到底走没走代理。

| 场景 | 实际发出的 argv | 结果 |
|---|---|---|
| custom → 死代理 | `git -c url.http://127.0.0.1:1/https://github.com/.insteadOf=https://github.com/ … fetch --prune` | **失败**，报错 `unable to access 'http://127.0.0.1:1/https://github.com/Comfy-Org/ComfyUI/'` → 证明流量确实被改写到代理 |
| gh-proxy | `git -c url.https://gh-proxy.com/https://github.com/.insteadOf=… fetch --prune` | 经 gh-proxy 拉取**成功**（3.7s） |
| none | `git fetch --prune` | 直连**成功**（3.5s），argv 未被污染 |

> 补充发现：`git_proxy_mode=gh-proxy` 时 `apply_git_proxy_to_url` **硬编码** `https://gh-proxy.com/`、
> 忽略 `git_proxy_url` 里的自定义值。所以造「假死代理」必须用 `custom` 模式，gh-proxy 模式做不到。

**全量单测**：`python -m pytest tests/unit -q --basetemp=<全新目录>` → **exit 0 全绿**
（`test_screen_change_scaling` 的 skip 是本机 PyQt5/sip ABI 预存问题，与本次改动无关）。

> ⚠️ 跑测试时注意两点，否则会误判成回归：
> 1. **别加 `-p no:pytest-qt`**：`test_version_workers.py` / `test_update_dialog.py` 依赖 `qtbot` fixture，
>    关掉 pytest-qt 会让它们集体 ERROR（本机确实有 pytest-qt 堆损坏的历史，但这两个文件仍需它）。
> 2. **`tests/unit/test_main_cli.py` 的两个 `status` 用例对环境敏感**：本机跑着一个打包版
>    `ComfyUI启动器.exe` 时，端口/进程收养逻辑可能让 `status` 返回 0 而非 3，偶发假失败。
>    实测：带改动失败 → stash 掉改动通过 → 恢复改动又通过，判定为环境抖动，非回归。

---

## 12. 附：本地正向代理（issue #109）

与本文的镜像代理是**两码事**，别混：

| | 镜像（`git_proxy_*` / `pypi_proxy_*` / `hf_mirror_*`） | 本地代理（`local_proxy_*`） |
|---|---|---|
| 换的是什么 | **落地地址**（换源） | **传输路径**（流量怎么走出去） |
| 作用对象 | 单个组件（git / pip / HF） | 所有非本机出网，一个开关全覆盖 |
| 实现 | `-c url.<前缀>.insteadOf` / index-url / `HF_ENDPOINT` | `HTTP(S)_PROXY` + `NO_PROXY` 环境变量 |

两者**正交**：同时开启时 = 「镜像地址经本地代理转发」，多一跳但可用。

- 实现：`utils/net.py::apply_local_proxy_env()` / `clear_local_proxy_env()`，
  注入点 `__main__.main()`（GUI/CLI/dev/打包四条路唯一公共入口）
- UI：`ui_qt/pages/launch/environment_section.py`「本地代理：」行（启用 + 地址 + 测试连接），
  **勾选启用时先弹前置条件确认**（`_on_local_proxy_checkbox_toggled`），取消会弹回勾选框且不写 config
- 测试：`tests/unit/test_local_proxy.py`
