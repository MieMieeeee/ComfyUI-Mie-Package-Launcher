@echo off
REM ==========================================================
REM ComfyUI启动器-CLI.cmd - thin wrapper around ComfyUI启动器.exe
REM ==========================================================
REM 背景：exe 本身支持 headless CLI 子命令。
REM 启动器 + 默认 GUI 子系统让 agent / 监控脚本心存疑虑。
REM
REM 这个 .cmd 给 agent 一个明显是 CLI 的入口。
REM 只做参数转发，不会调 GUI 分支代码（无窗口、无 Qt init）。
REM
REM 用法（与直接调 GUI exe 完全等价）：
REM     ComfyUI启动器-CLI.cmd status --json
REM     ComfyUI启动器-CLI.cmd start
REM     ComfyUI启动器-CLI.cmd stop
REM     ComfyUI启动器-CLI.cmd info --json
REM     ComfyUI启动器-CLI.cmd help
REM
REM 退出码：与 GUI exe 的 CLI 模式严格一致（见 cli.md）。
REM 无参数调用 → 转发到 help（绝不弹 GUI 窗口）。
REM ==========================================================
REM
REM 安装：把本文件放到 ComfyUI启动器.exe 同级目录即可。
REM 或随 release zip 一起分发到用户机器的安装目录。
REM ==========================================================

setlocal

set "SCRIPT_DIR=%~dp0"
set "EXE="

REM 自动发现 exe。优先级：root onefile > dist/onefile > onedir (Nuitka) > onedir (PyInstaller)
if exist "%SCRIPT_DIR%ComfyUI启动器.exe" set "EXE=%SCRIPT_DIR%ComfyUI启动器.exe"
if not defined EXE if exist "%SCRIPT_DIR%dist\ComfyUI启动器.exe" set "EXE=%SCRIPT_DIR%dist\ComfyUI启动器.exe"
if not defined EXE if exist "%SCRIPT_DIR%ComfyUI启动器.dist\ComfyUI_Launcher_Internal.exe" set "EXE=%SCRIPT_DIR%ComfyUI启动器.dist\ComfyUI_Launcher_Internal.exe"
if not defined EXE if exist "%SCRIPT_DIR%ComfyUI启动器.dist\ComfyUI启动器.exe" set "EXE=%SCRIPT_DIR%ComfyUI启动器.dist\ComfyUI启动器.exe"
if not defined EXE if exist "%SCRIPT_DIR%dist\ComfyUI启动器.dist\ComfyUI启动器.exe" set "EXE=%SCRIPT_DIR%dist\ComfyUI启动器.dist\ComfyUI启动器.exe"

if not defined EXE (
    1>&2 echo [ComfyUI启动器-CLI] ERROR: ComfyUI启动器.exe not found.
    1>&2 echo [ComfyUI启动器-CLI] Searched:
    1>&2 echo [ComfyUI启动器-CLI]   %SCRIPT_DIR%ComfyUI启动器.exe
    1>&2 echo [ComfyUI启动器-CLI]   %SCRIPT_DIR%dist\ComfyUI启动器.exe
    1>&2 echo [ComfyUI启动器-CLI]   %SCRIPT_DIR%ComfyUI启动器.dist\
    1>&2 echo [ComfyUI启动器-CLI]   %SCRIPT_DIR%dist\ComfyUI启动器.dist\
    1>&2 echo [ComfyUI启动器-CLI] Reinstall the launcher, or place this .cmd next to ComfyUI启动器.exe.
    endlocal & exit /b 1
)

REM 无参数 → 转发到 help，避免误触 GUI
if "%~1"=="" (
    "%EXE%" help
    endlocal & exit /b %ERRORLEVEL%
)


REM 防呆：首参必须是已知子命令。exe 的 _is_cli_invocation() 对未知首参会 fall through 弹 GUI，
REM 这里提前 fail-fast，避免 automation 脚本误触窗口。flags (-v / --json / -h 等) 不算首参。
setlocal EnableDelayedExpansion
set "FIRST_CMD="
REM -h / --help 是 CLI invocation 边界（exe 的 _is_cli_invocation() 直接 accept），先放行
for %%a in (%*) do if /i "%%~a"=="-h" set "FIRST_CMD=help"
for %%a in (%*) do if /i "%%~a"=="--help" set "FIRST_CMD=help"
REM 其余情况下，找首参：跳过 flags
if not defined FIRST_CMD (
    for %%a in (%*) do (
        if not defined FIRST_CMD (
            set "ITEM=%%a"
            if not "!ITEM:~0,1!"=="-" set "FIRST_CMD=!ITEM!"
        )
    )
)
if not defined FIRST_CMD set "FIRST_CMD=__NONE__"
set "VALID="
for %%c in (start stop status restart info logs update plugins help) do if /i "%FIRST_CMD%"=="%%c" set "VALID=1"
if not defined VALID (
    if /i "%FIRST_CMD%"=="__NONE__" (
        1>&2 echo [ComfyUI启动器-CLI] ERROR: missing subcommand, only flags given.
    ) else (
        1>&2 echo [ComfyUI启动器-CLI] ERROR: unknown command: %FIRST_CMD%
    )
    1>&2 echo [ComfyUI启动器-CLI] Available: start stop status restart info logs update plugins help
    1>&2 echo [ComfyUI启动器-CLI] Run "ComfyUI启动器-CLI help" for usage.
    endlocal & endlocal & exit /b 1
)
endlocal

REM 透传所有参数 + 退出码。注意用 exit /b 不要 exit（否则会关掉调用方 shell）。
"%EXE%" %*
endlocal & exit /b %ERRORLEVEL%
