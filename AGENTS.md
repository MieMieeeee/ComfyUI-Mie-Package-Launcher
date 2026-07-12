# AGENTS.md — 给 AI agent 的操作指南

> 本文件是 agent 操作本启动器的入口。完整 CLI 契约见 [`docs/cli.md`](docs/cli.md)。

## 这是什么

ComfyUI 启动器（PyQt5，Windows）。无参数启动 = GUI 图形界面；带子命令 = headless CLI，
复用 GUI 同一套启动/停止路径，适合自动化、监控、开机自启。

## 怎么调用

**agent / 自动化推荐 `ComfyUI-CLI.cmd`**：和下面 `ComfyUI启动器.exe` 行为完全等价（参数 + 退出码透传），但名字带 -CLI，对监控脚本 / NSSM / systemd / GitHub Actions 更友好。必须和 `ComfyUI启动器.exe` 同目录。

```bash
# 打包版（部署/运维场景，agent 通常用这个）—— exe 会自动切到自身所在目录找配置
ComfyUI启动器.exe <command> [--json] [-v]

# 开发版（从仓库根目录跑）
python __main__.py <command> [--json] [-v]
```

- **无子命令** → `ComfyUI启动器.exe`（裸跑）会启动 GUI；`ComfyUI-CLI.cmd`（裸跑）会转发到 `help`，不弹窗口。
- 所有子命令都支持 `--json`（输出**单行** JSON，便于解析）和 `-v`/`--verbose`（可叠加 `-vv`）。

## 子命令速查（agent 最常用）

| 目的 | 命令 | 判断方式 |
|---|---|---|
| 健康检查 | `status --json` | 退出码 `0`=在跑 / `3`=未跑 / `1`=异常；或解析 `.running` |
| 启动 | `start` | 阻塞到 `/system_stats` 就绪；加 `--no-wait` 立即返回 |
| 停止 | `stop` | 幂等，未跑也退 `0`；加 `--force` 直接 `taskkill /F` |
| 重启 | `restart` | stop 旧 + start 新 |
| 看配置 | `info --json` | `.comfyui_path` `.python_path` `.port` `.launcher_version` |
| 看日志 | `logs comfyui -n 100 --no-follow` | `comfyui` / `launcher` 二选一；**务必带 `--no-follow`** |
| 更新内核 | `update comfyui --dry-run` 然后 `update comfyui` | 先 dry-run 看会做什么 |
| 查帮助 | `help` / `help <command>` / `<command> --help` | — |

典型自动化节奏：`status --json` 判断在不在跑 → 不在就 `start` → 失败就 `logs comfyui --no-follow` 排查。

## 机器契约（agent 解析依据）

- **`--json` 输出**：每个命令都是单行 JSON，字段 schema 见 `docs/cli.md` 每个子命令的 *Output schema* 段。
- **退出码**（定义在 `core/cli/exitcodes.py`，跨命令稳定）：

  | 码 | 含义 | 出现在 |
  |---|---|---|
  | 0 | 成功 | 所有 |
  | 1 | 通用错误（路径缺失/env/IO/超时） | 所有 |
  | 2 | start 拒绝重复（已在跑） | start |
  | 3 | 未在跑 | status |
  | 4 | 已是最新 | update |

- 推荐用法：**按退出码分支 + 解析 `--json` 字段**，不要正则匹配人类文案。

## 关键路径

| 文件 | 含义 |
|---|---|
| `launcher/config.json` | 配置（端口、路径、启动选项）—— **机器本地，含绝对路径，勿提交运行时改动** |
| `launcher/launcher.log` | 启动器自身日志 |
| `<comfyui_root>/user/comfyui.log` | ComfyUI 输出日志（`logs comfyui` 读这个） |
| `launcher/comfyui.pid` | 跨进程 PID 协调（JSON：pid/port/started_at/log_path），stale 当不存在 |

端口默认 `8188`，来自 `config.json` 的 `launch_options.default_port`。

## 坑（agent 易踩）

- **`logs -f` 会永久阻塞**，自动化/脚本里禁用，要 `--no-follow`。
- **无子命令 = GUI**：如果 agent 想跑 CLI 却只执行了 `ComfyUI启动器.exe`（不带子命令），会弹 GUI 而非执行命令。
- `--start` / `--stop` / `--status` 这类**老 flag 已废弃**（旧文档可能还写），现在是子命令：`start` / `stop` / `status`。
- 配置改动会落到 `launcher/config.json`，里面是本机绝对路径——**不要把运行时生成的 config 改动提交进 git**。
- 调试模式：在 `launcher/` 目录下建一个 `is_debug` 文件（内容随意），日志变详细。

## 深入

- 完整 CLI 参考（每命令 flag / Exit codes / Output schema / systemd / NSSM / cron 示例）：[`docs/cli.md`](docs/cli.md)
- 服务接口契约：[`docs/ServiceInterfaces.md`](docs/ServiceInterfaces.md)
