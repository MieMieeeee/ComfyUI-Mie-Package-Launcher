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
# 在 ComfyUI 根目录下运行
python launcher/comfyui_launcher.py
```

### 快速操作
- 一键启动 ComfyUI
- 打开根/日志/输入/输出/插件目录
- 切换计算模式与网络选项

### 启动选项
- 选择启动模式（从现有 .bat 文件解析）
- 配置自定义启动参数
- 保存常用配置

## 文件结构

```
launcher/
├── comfyui_launcher_enhanced.py  # 增强版主启动器界面
├── version_manager.py            # 版本管理器（仅内核相关）
├── requirements.txt             # 依赖列表
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