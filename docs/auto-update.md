# ComfyUI 启动器自动更新系统

## 概述

ComfyUI 启动器采用双通道自动更新机制，支持稳定版（stable）和测试版（test）两个独立更新通道。该系统允许开发者和用户在不同阶段测试新功能，同时确保大多数用户获取到经过验证的稳定版本。

双通道设计的核心优势：

- **稳定通道（stable）**：面向最终用户的正式版本，经过充分测试
- **测试通道（test）**：面向开发者和测试人员的预览版本，包含最新功能

通道选择在编译时确定，编译完成后通道信息被永久写入可执行文件，后续无法更改。

## 架构设计

### 双通道系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                      Gitee 仓库结构                          │
│  comfyui-mie-resources/                                     │
│  └── launcher/                                              │
│      ├── updates/                                           │
│      │   ├── index.json          ← 稳定版通道索引            │
│      │   └── test/                                       │
│      │       └── index.json     ← 测试版通道索引            │
│      └── releases/                                         │
│          ├── ComfyUI启动器_1.0.9.exe     ← 稳定版           │
│          └── test/                                         │
│              └── ComfyUI启动器_1.0.10-beta.exe ← 测试版     │
└─────────────────────────────────────────────────────────────┘
```

### 通道编译机制

通道信息在编译时通过 `--test` 参数指定：

| 编译参数 | 通道 | 说明 |
|---------|------|------|
| 不指定 `--test` | stable | 编译为稳定版本 |
| 指定 `--test` | test | 编译为测试版本 |

编译时，通道信息被写入 `build_parameters.json` 的 `channel` 字段，并最终编译进可执行文件。

### LauncherUpdateService 通道读取

`LauncherUpdateService` 通过内置的通道信息确定从哪里检查更新：

```python
# 通道读取逻辑（伪代码）
if self.channel == "stable":
    self.update_url = "https://gitee.com/MieMieeeee/comfyui-mie-resources/raw/master/launcher/updates/index.json"
else:
    self.update_url = "https://gitee.com/MieMieeeee/comfyui-mie-resources/raw/master/launcher/updates/test/index.json"
```

启动器通过内置的 `channel` 配置决定使用哪个 `index.json` 文件进行版本检查。

### 版本号规范与预发布版本处理

#### 版本号格式

版本号采用语义化版本格式：`v主版本.次版本.修订版本[-预发布标签]`

| 示例 | 类型 | 说明 |
|------|------|------|
| `v1.0.9` | 正式版本 | 稳定版发布 |
| `v1.0.10-beta` | 预发布版本 | 测试版发布 |
| `v1.0.10-alpha` | 预发布版本 | 开发版发布 |

#### 版本比较逻辑

版本比较遵循以下规则：

1. **正式版本优先于预发布版本**：无论版本号数字大小，正式版本永远被认为更新
2. **同类型版本按数字比较**：仅在同一类型（都是正式版本或都是预发布版本）之间进行数字比较
3. **预发布标签排序**：在同一主版本号下，`alpha` < `beta` < `rc`（候选发布）

```
v1.0.10 (正式) > v1.0.10-beta (预发布) > v1.0.9 (正式)
```

这确保了测试版不会自动覆盖稳定版，保护了大多数用户的更新体验。

## 目录结构

### Gitee 仓库目录结构

```
comfyui-mie-resources/
└── launcher/
    ├── updates/
    │   ├── index.json          # 正式版通道索引文件
    │   └── test/
    │       └── index.json     # 测试版通道索引文件
    └── releases/
        ├── ComfyUI启动器_1.0.9.exe           # 正式版安装包
        └── test/
            └── ComfyUI启动器_1.0.10-beta.exe # 测试版安装包
```

### 索引文件格式（index.json）

稳定版索引文件位于 `launcher/updates/index.json`，测试版索引文件位于 `launcher/updates/test/index.json`。

**完整字段说明：**

```json
{
  "latest_version": "v1.0.9",           // 最新版本号（不含预发布标签）
  "release_date": "2026-03-25",          // 发布日期（YYYY-MM-DD格式）
  "download_url": "https://gitee.com/MieMieeeee/comfyui-mie-resources/raw/master/launcher/releases/ComfyUI启动器_1.0.9.exe",
  "file_size": 43016400,                  // 文件大小（字节）
  "sha256": "abc123...",                  // SHA256校验和（64位十六进制）
  "changelog": "版本更新内容",            // 更新日志（支持多行）
  "min_version": "v0.0.0",               // 最低兼容版本（低于此版本需完整更新）
  "prerelease": false                     // 是否为预发布版本
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `latest_version` | string | 是 | 最新版本号，必须以 `v` 开头 |
| `release_date` | string | 是 | ISO 8601 日期格式 |
| `download_url` | string | 是 | 直链下载URL |
| `file_size` | integer | 是 | 文件大小（字节） |
| `sha256` | string | 是 | 文件完整SHA256校验和 |
| `changelog` | string | 是 | 纯文本更新日志 |
| `min_version` | string | 否 | 最低兼容版本，低于此版本需完全重新安装 |
| `prerelease` | boolean | 是 | `true` 表示预发布版本，`false` 表示正式版本 |

## 编译指南

### build_parameters.json 配置

编译参数配置文件位于项目根目录：

```json
{
  "version": "v1.0.9",
  "channel": "stable",
  "suffix": " · 构建于 2026-03-25 10:30:00",
  "mode": "nuitka_release",
  "built_at": "2026-03-25 10:30:00",
  "builder": "黎黎原上咩"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `version` | string | 版本号，编译后不可更改 |
| `channel` | string | 通道：`stable` 或 `test` |
| `suffix` | string | 编译后添加到关于窗口的附加信息 |
| `mode` | string | Nuitka编译模式，通常为 `nuitka_release` |
| `built_at` | string | 编译时间戳 |
| `builder` | string | 构建者名称 |

### 编译稳定版本

编译正式发布版本（不带 `--test` 参数）：

```bash
cd /path/to/ComfyUI-Mie-Package-Launcher

# 配置 build_parameters.json
# 确保 "channel": "stable"

# 执行编译
python build_exe_v2.py
```

编译产物：`dist/ComfyUI启动器_{版本号}.exe`

### 编译测试版本

编译测试版本（带 `--test` 参数）：

```bash
cd /path/to/ComfyUI-Mie-Package-Launcher

# 配置 build_parameters.json
# 确保 "channel": "test"

# 执行编译（带 --test 标志）
python build_exe_v2.py --test
```

编译产物：`dist/test/ComfyUI启动器_{版本号}.exe`

### 编译参数对比

| 参数 | 稳定版编译 | 测试版编译 |
|------|-----------|-----------|
| `--test` 参数 | 不指定 | 指定 |
| `channel` 字段 | `"stable"` | `"test"` |
| 输出目录 | `dist/` | `dist/test/` |
| 版本号建议 | 使用正式版本号 | 建议添加 `-beta` 后缀 |

## 发布指南

### upgrade_exe.py 脚本

发布流程使用 `upgrade_exe.py` 脚本完成，脚本位于项目根目录。

**功能：**

- 自动上传安装包到 Gitee Releases
- 自动更新对应通道的 `index.json` 索引文件
- 自动计算文件大小和 SHA256 校验和
- 支持稳定版和测试版双通道发布

### 发布到稳定通道

```bash
cd /path/to/ComfyUI-Mie-Package-Launcher

python upgrade_exe.py \
    --file "./dist/ComfyUI启动器_1.0.9.exe" \
    --version "v1.0.9" \
    --channel "stable" \
    --changelog "版本更新内容" \
    --gitee-token "your_gitee_token_here"
```

### 发布到测试通道

```bash
cd /path/to/ComfyUI-Mie-Package-Launcher

python upgrade_exe.py \
    --file "./dist/test/ComfyUI启动器_1.0.10-beta.exe" \
    --version "v1.0.10-beta" \
    --channel "test" \
    --changelog "新增功能：支持自定义主题" \
    --gitee-token "your_gitee_token_here"
```

### 发布参数详解

| 参数 | 必填 | 说明 |
|------|------|------|
| `--file` | 是 | 要发布的 `.exe` 文件路径 |
| `--version` | 是 | 版本号，必须以 `v` 开头 |
| `--channel` | 是 | 通道类型：`stable` 或 `test` |
| `--changelog` | 是 | 更新日志内容 |
| `--gitee-token` | 是 | Gitee 个人访问令牌 |
| `--min-version` | 否 | 最低兼容版本，默认为 `v0.0.0` |

### Gitee Personal Access Token 获取

1. 登录 Gitee 账号
2. 进入 **设置** → **私人令牌**
3. 点击 **生成新令牌**
4. 选择权限：`issues`（项目操作）、`pull_requests`（仓库操作）
5. 生成后复制令牌（仅显示一次）

### 发布后验证

发布完成后，请手动验证以下内容：

1. **检查 Gitee Releases**：确认文件已上传到对应仓库
2. **检查索引文件**：访问 `index.json` 确认内容正确
3. **下载测试**：下载安装包并验证 SHA256 校验和
4. **启动器测试**：在启动器中检查更新，确认能正确识别新版本

## 故障排除

### 常见问题与解决方案

#### 1. 编译后通道未生效

**症状**：编译时指定了 `--test` 参数，但启动器仍从稳定通道检查更新。

**可能原因**：

- `build_parameters.json` 中的 `channel` 字段与编译参数不匹配
- 编译产物使用了旧的 `build_parameters.json`

**解决方案**：

```bash
# 1. 清理旧的构建产物
rm -rf build/ dist/ *.build/ *.dist/

# 2. 确认 build_parameters.json 内容正确
cat build_parameters.json | grep channel

# 3. 重新编译
python build_exe_v2.py --test
```

#### 2. 版本号比较逻辑问题

**症状**：测试版 `v1.0.10-beta` 被识别为比稳定版 `v1.0.9` 更旧。

**说明**：这是预期行为。系统设计如此：正式版本（`prerelease: false`）始终被认为比预发布版本（`prerelease: true`）更新。这是保护用户避免意外安装不稳定的测试版本。

**解决方案**：

- 测试通道应仅用于收集测试反馈，不应期望自动推送
- 如需让测试用户获取测试版，应通过其他渠道（如QQ群、Discord）手动通知

#### 3. SHA256 校验和不匹配

**症状**：下载后校验和与 `index.json` 中记录的不一致。

**可能原因**：

- 文件传输过程中损坏
- 网络劫持
- `upgrade_exe.py` 计算校验和时出错

**解决方案**：

```bash
# 手动计算文件 SHA256
# Windows PowerShell
Get-FileHash -Path "ComfyUI启动器_1.0.9.exe" -Algorithm SHA256 | Format-List

# Linux/macOS
sha256sum ComfyUI启动器_1.0.9.exe
# 或
shasum -a 256 ComfyUI启动器_1.0.9.exe
```

如发现校验和不匹配，请重新上传文件并更新 `index.json`。

#### 4. Gitee 上传失败

**症状**：`upgrade_exe.py` 执行时报错，文件未能上传。

**可能原因**：

- Gitee Token 过期或权限不足
- 文件名包含特殊字符
- 仓库达到存储上限
- 网络连接问题

**解决方案**：

1. 确认 Token 有效且具有 `repo` 权限
2. 检查文件名，移除特殊字符（如 `·`、`/` 等）
3. 清理仓库中不需要的大文件
4. 重试上传操作

#### 5. index.json 格式错误

**症状**：启动器无法解析更新信息，或提示"无可用更新"。

**可能原因**：

- JSON 格式不正确（逗号、引号等）
- 必要字段缺失
- URL 无法访问

**解决方案**：

使用 JSON 验证工具检查 `index.json` 格式：

```bash
# Linux/macOS 使用 python 验证
python -c "import json; json.load(open('index.json'))"
```

确保所有必填字段存在且类型正确。

#### 6. 下载链接 404

**症状**：启动器提示下载链接无效。

**可能原因**：

- Gitee 仓库路径不正确
- 文件名与 `index.json` 中记录的不一致
- 文件上传到了错误的目录

**解决方案**：

1. 确认 Gitee 仓库中文件实际路径
2. 检查 `download_url` 字段是否正确
3. 确认文件位于 `launcher/releases/` 目录下（稳定版）或 `launcher/releases/test/` 目录下（测试版）

### 调试模式

如遇问题，可通过以下方式获取更多信息：

1. **查看启动器日志**：启动器目录下查找 `*.log` 文件
2. **检查网络请求**：使用 Fiddler 或 Chrome DevTools 监控 Gitee 请求
3. **手动模拟请求**：

```bash
# 测试 index.json 访问
curl -I "https://gitee.com/MieMieeeee/comfyui-mie-resources/raw/master/launcher/updates/index.json"
```

## 附录

### 完整发布流程示例

**稳定版发布完整流程：**

```bash
# 1. 更新版本号
# 编辑 build_parameters.json，将 version 改为 "v1.0.9"，channel 改为 "stable"

# 2. 编译
python build_exe_v2.py

# 3. 测试编译产物（可选但推荐）
./dist/ComfyUI启动器_v1.0.9.exe --version

# 4. 发布
python upgrade_exe.py \
    --file "./dist/ComfyUI启动器_v1.0.9.exe" \
    --version "v1.0.9" \
    --channel "stable" \
    --changelog "修复已知问题，提升稳定性" \
    --gitee-token "your_token_here"

# 5. 验证发布
# 浏览器打开 index.json 确认内容正确
```

### 相关文件路径

| 文件 | 路径 | 说明 |
|------|------|------|
| 编译脚本 | `build_exe_v2.py` | Nuitka 编译入口 |
| 发布脚本 | `upgrade_exe.py` | Gitee 发布脚本 |
| 编译配置 | `build_parameters.json` | 版本、通道等元信息 |
| 更新服务 | `services/LauncherUpdateService.py` | 版本检查核心逻辑 |
| 更新索引 | `launcher/updates/index.json` | Gitee 索引文件 |

### 联系方式

如遇到文档未涵盖的问题，请通过以下方式联系开发者：

- GitHub Issues：项目仓库的 Issues 页面
- QQ 群：项目 README 中公布的群号
