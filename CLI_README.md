# ComfyUI启动器 CLI 使用说明

## 默认行为（双击运行）

双击 `ComfyUI启动器.exe` → 启动 GUI 图形界面（正常启动器）

---

## CLI 模式（命令行参数）

| 命令 | 说明 |
|------|------|
| `ComfyUI启动器.exe --start` | **无 GUI 启动 ComfyUI** - 后台运行，适合服务器/静默启动 |
| `ComfyUI启动器.exe --stop` | **停止 ComfyUI** - 优雅关闭进程 |
| `ComfyUI启动器.exe --status` | **查看状态** - 检查 ComfyUI 是否在运行 |

---

## 使用场景

### 场景1：后台启动（无界面）

```batch
ComfyUI启动器.exe --start
```

→ 只显示控制台输出，ComfyUI 在后台运行，不弹窗

### 场景2：开机自启动

```batch
# 创建一个 batch 文件
@echo off
ComfyUI启动器.exe --start
```

→ 加入 Windows 任务计划程序，实现开机后台启动 ComfyUI

### 场景3：检查状态

```batch
ComfyUI启动器.exe --status
```

→ 输出 `ComfyUI is running` 或 `ComfyUI is not running`

### 场景4：停止服务

```batch
ComfyUI启动器.exe --stop
```

→ 优雅停止 ComfyUI 进程

---

## 注意事项

1. **配置文件**：CLI 模式同样读取 `launcher/config.json` 中的配置
2. **端口检测**：`--status` 通过 HTTP 请求检测 8188 端口
3. **进程管理**：`--start` 会保存进程 PID，`--stop` 通过 PID 关闭
