# ComfyUI 启动器 CLI

> CLI 文档已迁移并更新到 [`docs/cli.md`](docs/cli.md)。
> AI agent 操作入口：[`AGENTS.md`](AGENTS.md)。

本文件旧版的 `--start` / `--stop` / `--status` flag 接口**已废弃**。
当前 CLI 采用子命令形式（所有命令支持 `--json` 与稳定退出码）：

```bash
ComfyUI启动器.exe status --json     # 查询状态（0=在跑 / 3=未跑 / 1=异常）
ComfyUI启动器.exe start             # 启动
ComfyUI启动器.exe stop              # 停止
ComfyUI启动器.exe info --json       # 看配置
ComfyUI启动器.exe help              # 完整帮助
```

完整子命令、flag、Exit codes、Output schema 与 systemd / NSSM / cron 示例请见
[`docs/cli.md`](docs/cli.md)。
