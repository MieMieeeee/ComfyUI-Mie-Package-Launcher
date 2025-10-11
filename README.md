# ComfyUI 启动器

一个专为 ComfyUI 设计的图形化启动器，提供便捷的启动选项管理与版本更新。

## 功能特性

### 核心功能
- **多模式启动**: 支持多种启动配置（CPU、GPU、镜像源等）
- **版本信息**: 显示 ComfyUI、前端、模板库、Python、Torch 版本
- **批量更新**: 一键选择并更新内核/前端/模板库
- **配置管理**: 保存和管理启动参数配置

### 版本与更新
- 获取并展示版本信息
- 选择更新项目并执行批量更新
- 支持快速刷新状态

## 使用方法

### 启动启动器
```bash
# 在 ComfyUI 根目录下运行（增强版界面）
python launcher/comfyui_launcher_enhanced.py
```

### 快速操作
- 一键启动 ComfyUI
- 打开根/日志/输入/输出/插件目录
- 切换计算模式与网络选项

### 启动选项
- 选择启动模式（从现有 .bat 文件解析）
- 配置自定义启动参数
- 保存常用配置

### 调试模式与日志
- 默认情况下，命令输出日志被严格收敛：每次命令的 `stdout`/`stderr` 最多记录少量行（默认 10 行），`netstat -ano` 仅记录行数摘要，避免日志膨胀。
- 开启调试模式：在 `launcher` 目录创建一个文件 `is_debug`（内容随意，如 `debug`）。存在该文件时，日志级别提升为 `DEBUG`，命令输出将更详细（按字符截断，默认 4000 字）。
- 关闭调试模式：删除 `launcher/is_debug` 文件即可恢复到普通模式。
- 可选高级调节：
  - 非调试模式下的每次输出行数上限可通过环境变量 `COMFYUI_LAUNCHER_LOG_LINES_LIMIT` 设置，例如：`5`。
  - 调试模式下的字符截断长度可通过 `COMFYUI_LAUNCHER_LOG_OUTPUT_LIMIT` 设置，例如：`2000`。
  - 配置文件 `launcher/config.json` 中的 `advanced.show_debug_info` 为 `true` 时，会自动创建 `launcher/is_debug` 文件以便开启调试模式（不会自动删除你手动创建的标记文件）。

## 文件结构

```
launcher/
├── comfyui_launcher_enhanced.py  # 增强版主启动器界面
├── version_manager.py            # 版本管理器（仅内核相关）
├── requirements.txt             # 依赖列表
├── logger_setup.py              # 日志安装与级别控制（支持 is_debug 文件）
├── utils.py                     # 命令执行与日志输出（支持按行/字符截断）
├── config.json                  # 启动器配置（含 show_debug_info 开关）
├── is_debug                     # 可选：存在即开启调试模式
└── README.md                   # 说明文档
```

## 技术实现

- **GUI框架**: Tkinter（Python标准库）
- **版本管理**: 使用 Git 获取与更新 ComfyUI 内核
- **进程管理**: subprocess 管理 ComfyUI 进程
- **配置存储**: JSON 格式配置文件

## 注意事项

1. 确保在 ComfyUI 根目录下运行启动器
2. 备份操作可能需要较长时间，请耐心等待
3. 恢复备份前请确保 ComfyUI 已停止运行
4. 备份文件存储在 `backups` 目录下

## 兼容性

- Python 3.7+
- Windows 系统
- 支持 ComfyUI 各版本

## 开发说明

本启动器主要使用 Python 标准库开发，无需额外安装依赖包。如需扩展功能，可参考 `requirements.txt` 中的可选依赖。

## 打包 EXE

支持使用 PyInstaller 将启动器打包为独立的 `ComfyUI启动器.exe`。

### 环境准备
- 安装 PyInstaller（推荐使用项目内的嵌入式 Python）：
  - Windows PowerShell：
    - ``python -m pip install pyinstaller``

### 方式一：使用脚本构建（推荐）
- 在项目根目录运行：
  - ``python launcher\build_exe.py``（默认构建完整版启动器）
  - 或 ``python launcher\build_exe.py 2``（构建“简化测试版”）
- 构建完成后，脚本会将 `launcher\dist\ComfyUI启动器.exe` 拷贝到项目根目录为 `ComfyUI启动器.exe`。

### 方式二：使用 spec 文件构建
- 进入 `launcher` 目录：
  - ``pyinstaller ComfyUI启动器.spec``（窗口模式，图标与资源已配置）
  - ``pyinstaller 测试启动器.spec``（简化测试版）

### 构建产物位置
- `launcher\dist\ComfyUI启动器.exe`（PyInstaller 默认输出）
- 项目根目录的 `ComfyUI启动器.exe`（使用脚本时会自动复制）

### 说明与提示
- 打包脚本内置常用的 `hidden-import` 与 `exclude-module` 配置，适配 Windows 环境与 Tkinter GUI。
- 若你希望自定义图标，替换 `launcher\rabbit.ico` 即可。
- 调试日志可通过在 `launcher` 目录下创建 `is_debug` 文件开启；打包后的 EXE 同样支持该开关。