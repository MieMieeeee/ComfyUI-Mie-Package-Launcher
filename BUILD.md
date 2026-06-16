# 构建指南

本项目使用 **Nuitka 编译** + **Enigma Virtual Box 封包** 的一键构建流程。
主入口脚本：`build.py`（已封装全部步骤），也可单独使用 `build_exe_v2.py`（仅 Nuitka）。

## 一键构建

```powershell
# 使用项目内的 venv
.venv\Scripts\python.exe build.py
```

可选参数：

| 参数 | 说明 |
| --- | --- |
| `--version v1.0.13` | 设置新版本号并构建（写入 `build_parameters.json`） |
| `--test` | 构建测试通道版本（输出到 `dist\ComfyUI启动器_test.dist\` 与 `release\..._test.exe`） |
| `--evb-only` | 跳过 Nuitka 编译，仅执行 Enigma 封包（用于快速重新封包） |
| `--enigma-path "C:\path\enigmavbconsole.exe"` | 指定 Enigma 控制台路径（自动从 `C:\Program Files (x86)\Enigma Virtual Box\` 搜索） |

## 构建产物

- `dist\ComfyUI启动器.dist\ComfyUI_Launcher_Internal.exe` — Nuitka 编译后的内部 exe
- `dist\ComfyUI启动器.dist\ComfyUI_Launcher_Internal_boxed.exe` — Enigma 封包后的单文件 exe
- `release\ComfyUI启动器_v<ver>_<YYYYMMDD_HHMM>.exe` — 最终发布文件

## 关键依赖

- Python 3.12（项目根 `.venv\Scripts\python.exe`）
- Nuitka 4.x（pip install nuitka）
- Enigma Virtual Box（标准安装路径下自动检测）

## 故障排查

- **Nuitka 卡死 / 长时间无输出**：删除 `__main__.build\` 目录后重试
- **Enigma 报"文件被占用"**：关闭任何运行中的 `ComfyUI启动器.exe`，删除 `dist\ComfyUI启动器.dist\`
- **PyQt5 plugins 找不到**：确认 `.venv\Lib\site-packages\PyQt5\Qt\plugins\platforms\qwindows.dll` 存在
