# 启动器公告机制（Gitee 仓库方案）

> 面向维护者：如何发一条公告、公告在客户端怎么弹、哪些坑会让你以为"发了但没弹"。

## 一、整体链路

```
Gitee 仓库 comfyui-mie-resources
  └─ launcher/announcements/index.json          ← 索引（决定弹哪几条）
       └─ launcher/announcements/YYYY/MM/*.json  ← 单条公告（标题 + 正文）
                    │
                    │ HTTPS GET（超时 2.5s，urllib 自动跟随 302）
                    ▼
services/announcement_service.py::AnnouncementService.fetch()
                    │
                    │ 后台守护线程 → app.ui_post() 切回主线程
                    ▼
ui_qt/widgets/announcement_dialog.py::AnnouncementDialog
                    │
                    └─ 按钮：「不再弹出」(destructive) / 「知道了」(primary)
```

关键代码位置：

| 文件 | 作用 |
|---|---|
| `services/announcement_service.py` | 抓取、解析、规则过滤、去重、静默、弹窗调度 |
| `ui_qt/widgets/announcement_dialog.py` | 弹窗 UI（继承 `CustomConfirmDialog`，滚动文本区） |
| `services/startup_service.py::start_announcements_only()` | 启动时唯一触发点（只拉公告，不做 Git/版本远程访问） |
| `ui_qt/qt_app.py:5640` | 调用 `startup.start_announcements_only()` |
| `ui_qt/pages/about_launcher_page.py:387` | 「🔔 查看公告」手动入口 → `show_cached_popup()` |
| `config/manager.py:118` | 默认配置 `announcement.{enabled, source_url, fallback_urls}` |

## 二、发布一条公告（实际操作）

### 1. 资源仓库位置

本机工作副本：`F:\comfyui-mie-resources`
远程：`git@gitee.com:MieMieeeee/comfyui-mie-resources.git`（分支 `master`，已跟踪 `origin/master`）

### 2. 目录约定

```
launcher/announcements/
├── index.json                                   ← 索引：放哪几条、给谁看
└── 2026/
    └── 03/
        └── 20260302-启动闪退的解决方案.json      ← 单条公告：标题 + 正文
```

单条公告文件用「年月日-标题.json」命名，按年/月分目录。**index.json 里通过 `url` 字段绝对地址引用**（Gitee raw URL，文件名含中文要 URL 编码）。

### 3. 单条公告文件格式

```json
{
  "title": "重要提示：启动闪退的解决方案",
  "content": "如果启动 ComfyUI 直接闪退……\n\n✅ 解决方法一（推荐）：\n……",
  "version": "*",
  "start_at": "2026-03-02 00:00:00"
}
```

### 4. index.json 索引格式

```json
{
  "items": [
    {
      "url": "https://gitee.com/MieMieeeee/comfyui-mie-resources/raw/master/launcher/announcements/2026/03/20260302-%E5%90%AF%E5%8A%A8%E9%97%AA%E9%80%80%E7%9A%84%E8%A7%A3%E5%86%B3%E6%96%B9%E6%A1%88.json",
      "version": "*"
    }
  ]
}
```

客户端会把命中的多条合并成一篇，标题变成「公告（N 条）」，每条以 `【标题】` 开头，条目之间用 64 个 `-` 分隔。

### 5. 发布步骤

```bash
cd /f/comfyui-mie-resources
# 1. 写公告文件 + 更新 index.json
# 2. 本地自测（用仓库里的调试脚本）
cd /f/ComfyUI-Mie-Package-Launcher
python scripts/test_fetch_announcement.py     # 走线上真实 URL，把结果写到 launcher/announcement_test_output.txt
# 3. 提交推送
cd /f/comfyui-mie-resources
git add launcher/announcements
git commit -m "新增公告：xxx"
git push origin master
```

推送后约 1 分钟内所有客户端下次启动即可看到。

> 想在推送前先本地验证：把 `launcher/config.json` 的 `announcement.source_url` 临时改成 `file:///F:/comfyui-mie-resources/launcher/announcements/index.json`——`urlopen` 支持 file:// 协议。

### 6. 其他可用格式（都支持，但有坑，见第五节）

| 格式 | 用法 |
|---|---|
| 纯文本 | URL 直接返回非 JSON 文本 → 整段当正文，标题固定「公告」 |
| 单条 JSON | URL 直接返回 `{title, content, ...}` → 一条公告 |
| 跳转 | URL 返回 `{"redirect": "<另一个URL>"}` → 跟到目标 URL 再解析 |
| 索引 | URL 返回 `{"items": [...]}` → 上面说的多条目模式 |

## 三、显示规则（rules）

规则字段可以写在**索引条目**上，也可以写在单条公告文件里——**但只有索引条目上的生效**（见坑 ①）。

| 字段 | 含义 | 例子 |
|---|---|---|
| `version` / `version_expr` | 版本表达式，`>` `>=` `<` `<=` `==` `*`，多条件空格/逗号/`&&` 分隔为 AND | `">=1.0.5"`、`"*"` |
| `min_version` / `max_version` | 版本区间（含端点） | `"v1.0.3"` |
| `allow_versions` / `deny_versions` | 白名单 / 黑名单（字符串精确匹配当前版本号） | `["v1.0.18"]` |
| `start_at` / `end_at` | 时间窗口，**UTC**（客户端用 `datetime.utcnow()` 比较） | `"2026-03-02 00:00:00"` |
| `rules` | 把上述字段包成对象 | `{"rules": {...}}` |

**没有任何规则的条目永远会弹**——这是最安全的默认值。

## 四、客户端行为

- **时机**：GUI 启动后异步拉取（不阻塞启动），2.5s 超时/源；拉取失败会回落到本地缓存 `launcher/announcement_cache.txt` 继续弹。
- **去重键**：`sha256(title + content + source)`。同一条内容重复发不会重复弹。
- **「知道了」**：**不记录**，下次启动继续弹（代码里注释明说是有意为之）。
- **「不再弹出」**：ID 写入 `launcher/announcement_muted.json`，此后永久不再弹这条。
- **手动查看**：「关于」页 → 「🔔 查看公告」→ 显示 `_last_data` 或缓存内容，没有就提示「暂无公告」。
- **可关**：配置里 `announcement.enabled = false` 关闭。

### 客户端本地文件（均在 `launcher/` 目录）

| 文件 | 用途 |
|---|---|
| `announcement_cache.txt` | 最近一次成功抓取的正文（离线回落 + 「查看公告」用） |
| `announcement_muted.json` | 被「不再弹出」的公告 ID 列表 |
| `announcement_seen.json` | 已读列表——**当前生产代码不会写**（`_mark_seen` 无调用方），属于预留 |
| `announcement_debug.log` | 被规则拦下 / 无数据且缓存为空时的诊断标记 |

> 注意这些路径是 `Path.cwd() / "launcher"`。打包版 exe 会切到自身目录，所以正常；开发版从仓库根跑也对；若从别的 cwd 启动，文件会散落到别处。

## 五、坑（实测结论，容易白干）

### ① 规则要写在 index.json 条目上，不是公告文件里

`_parse_index_items()` 只从索引条目读取 `min_version` / `version` / `start_at` 等；通过 `url` 取回的公告文件**只贡献 `title` 和 `content`**，它内部的规则字段被丢弃。

现存的两条公告（`20260302-…json`、`20251209-…json`）规则都写在文件里，实际生效的是索引里的 `"version": "*"`。**想按版本/时间投放，必须在 index.json 的对应条目上写规则。**

### ② 版本规则目前完全失效（真 bug）

版本号来源是 `build_parameters.json` 的 `version` 字段，但该文件**只含 `suffix/mode/built_at/builder/channel`，没有 `version`**（版本号的唯一事实源是 `core/version.py::LAUNCHER_VERSION`，见 AGENTS.md）。于是 `cur_v` 恒为 `(0,0,0)`，实测：

```
{'version': '*'}          -> allowed = True
{'version': '>=1.0.5'}    -> allowed = False   ← 被拦
{'min_version': 'v1.0.3'} -> allowed = False   ← 被拦
{'version': '1.0.18'}     -> allowed = False   ← 被拦
```

**现在只有 `"*"` 能过**；任何具体版本条件都会把公告拦死。修法二选一：
- 让 `_load_build_params()` 兜底读 `core/version.py::LAUNCHER_VERSION`（注意打包成 exe 后 `core/version.py` 不在文件系统上，得靠编译期注入 `version` 到 `build_parameters.json`）；
- 或在 `_is_allowed()` 里直接用 `from core.version import LAUNCHER_VERSION`（打包可用，因为已编译进二进制）。

### ③ 单条公告格式不校验时间窗口

`show_if_available()` 只判 `_is_allowed(rules)`，**没有判 `_in_time_window(rules)`**；而 `_in_time_window` 只在索引多条目路径里被逐条调用。实测：一条带 `start_at: 2099-01-01` 的单条公告，规则仍判定"允许"，照样弹窗。

索引格式不受此影响（每条都过时间窗口）。

### ④ 时间窗口是 UTC，不是本地时间

`_in_time_window()` 用 `datetime.utcnow()`。`start_at` / `end_at` 必须按 UTC 写，否则会有 8 小时偏差。

### ⑤ `channels` 字段是死字段

`_parse_json_payload()` 和 `_parse_index_items()` 都不把 `channels` 收进 rules，`_is_allowed()` 也不判断它。只有 `redirect` 分支会收集 `channels`，但同样没人消费。想按渠道（stable/test）投放，目前做不到。

### ⑥ 「知道了」等于没看

想"确认过就别再弹"，当前实现做不到——`_mark_seen()` 无调用方，`announcement_seen.json` 永远为空。唯一能永久屏蔽某条公告的手段是用户点「不再弹出」。

### ⑦ index.json 会把多条合成一篇

一次只能看到一个弹窗。发布多条公告时，用户要在一个滚动框里看完所有条目。紧急公告建议**单独一个 index 项**或用单条 JSON 格式。

### ⑧ Gitee raw 是 302 跳转

`https://gitee.com/.../raw/master/...` 会 302 到 `raw.giteeusercontent.com`。客户端 `urlopen` 会自动跟随（实测 HTTP 200，能正常取到）；但手工用 `curl` 调试**必须加 `-L`**，否则只看到 501 字节的跳转页。

## 六、本地调试

```bash
cd /f/ComfyUI-Mie-Package-Launcher
python scripts/test_fetch_announcement.py
# 输出：解析后的 JSON（title/content/rules/source）
# 落盘：launcher/announcement_test_output.txt
```

看日志：`launcher/launcher.log` 里搜 `announcement:` 前缀，涵盖抓取源、命中条目、规则拦截、弹窗、缓存等全链路。

单元测试：`tests/unit/test_announcement_service.py`（覆盖解析、规则、静默、缓存回落等）。
