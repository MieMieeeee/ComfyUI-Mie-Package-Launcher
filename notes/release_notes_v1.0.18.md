## v1.0.18 更新内容

### 插件管理（本次最大的一块）
- **CNR 插件更新死循环修复**（issue #107）：CNR 插件重装后上游元数据版本没变时，不再反复标「有更新」，断掉「扫描说有更新 → 更新 → 版本没动」的永久循环。
- **装卸不再走 Manager 队列 API**：install/update 改用 `cm_fast` 包装器直接执行。原先队列任务完成后 Manager 网页端会弹「Apply/重启」，用户一点就 `os.execv` 换 PID —— 启动器的 pidfile 跟踪不到，下次启动还会二次触发依赖重装链，把运行中的 ComfyUI 静默搞死（2026-10-03 事故）。
- **卸载/禁用/启用改走磁盘直连**：Manager HTTP 队列 API + 启动器本地 rmtree / 加 `.disabled` 后缀，不经 cm-cli（原生 cm-cli 每次调用要 5.5 分钟，还删不动只读 git pack）。
- **更新进度条**：cm-cli 输出流式解析 k/N，插件页实时显示「已完成 / 总数」；强制更新会接住普通更新的结论合并输出，不再两次提示打架。
- **检查更新提速**：git 插件的 `ls-remote` 改 8 路并发（30+ git 插件：串行 ~50s → 约 7s）；`git pull` 失败会区分网络/镜像问题与代码冲突，前者提示重试或换代理。
- **插件页交互**：刷新不再冲掉「有更新」标记，支持全选与批量更新；检查完成但 worker 异常时也会落到错误通道（不再卡在「检查中」）。

### 网络与代理
- **本地正向代理（Clash 等）**（issue #109）：环境区新增「本地代理」行。启用后启动器自身、ComfyUI、git、pip、模型下载等**所有非本机出网**流量都改走代理；与镜像源正交（hf / gh-proxy / 阿里云 pypi 照常生效），`127.0.0.1` 始终绕过；只接受 http(s)，填 socks5 会让 urllib 直接失联。
- **「更新内核」终于走 git 代理**：之前 fetch/pull 硬直连 origin，配了 gh-proxy 也必然失败（2026-10-14 事故，`fatal: unable to access ... Recv failure`）。现在按配置的镜像前缀生成 `-c url.<前缀>.insteadOf=` 传给 git；更新超时也改成真正杀掉 git 进程（原来只 `future.cancel()`，杀不掉已在跑的进程）。

### 稳定性
- **进程收养**：pidfile 失联但端口确实被 ComfyUI 占用时，用端口 + 身份校验找回 PID 并重写 pidfile，外部重启后 stop/status 不再失联。
- **webui PID 复用身份门**：`webui.pid` 残留的 PID 被无关进程复用时会误报「已启动」，stop 甚至会误杀（实测误杀过 Grok Bot.exe）；现在校验 cmdline 特征。
- **托盘「退出并关闭 ComfyUI」修复**（issue #108）：该菜单项之前在 ComfyUI 未运行时是禁用的，用户点了没反应，以为菜单坏了；现在永远可点，退出链路改为菜单触发后延迟执行 close 并复位标志位。
- **端口探测快路径**：一次拿全系统连接表代替逐进程扫描（上千进程时旧实现要几秒且跑在 UI 线程，表现为点「一键启动」按钮卡住）；本机探测绕开系统代理。
- **渲染守卫与崩溃留痕**：auto → compat → safe 两级阶梯 + 崩溃分类器 + clean 哨兵；崩溃时写 `launcher/crash.log`（faulthandler + 早期 excepthook），闪退反馈可直接看日志。

### 外置模型库
- **yaml 漂移检测**：整合包更新或手动编辑改过 `extra_model_paths.yaml` 后，启动时检测到与配置不一致会询问是否重写；按「库集合」记指纹，不会反复追问同一个漂移。
- **局域网共享不可达不再卡死整窗**：外置库指向 `\\NAS\...` 且对端没开机时，改为短超时探测对端 + 全部磁盘访问有界（原先在 GUI 线程里直接 `exists()` / `iterdir()`，一次扫描能冻住窗口几十秒）。
- **离线不降级配置**：对端不可达时沿用 yaml 里原有的映射，绝不把该库降级成「只有 base_path」——那会让 ComfyUI 静默少加载模型。界面会标「⚠离线」并说明「已保留原有配置，未刷新映射」。

### ComfyUI 兼容
- **资源系统（Assets）默认关闭**：ComfyUI 0.40+ 新增的资源系统会在本地建 SQLite 索引并扫描 models / input / output（NAS 上可能扫好几分钟、硬盘狂响，且同一目录再起第二个实例会因共用数据库直接退出）。启动器一直带 `--windows-standalone-build`，那个开关会顺手把它打开；现在新增「启用资源系统」选项，默认不勾即显式传 `--disable-assets`，ComfyUI 低于 0.40 不支持该参数时自动跳过。

### 其他
- 窗口尺寸记忆默认高度 900 → 960（环境区多了一行本地代理）。
- CLI：`update comfyui --json` 补充 `from_version` / `to_version`。
- 打包：`opengl32sw.dll` 随 exe 分发（Windows DLL 搜索 exe 目录优先，零改动 EVB）；EVB 封包补进 `cm_fast.py`。
- 版本号唯一事实源迁到 `core/version.py`（编译期打进 exe，不再有 `build_parameters.json` 与源码漂移）。
- 启动页新增「环境变量」输入框（K=V, K2=V2），注入到 ComfyUI 子进程。

> 已知限制：**应用内「检查更新」目前拿不到版本信息**。它读的是 Gitee 上的 `launcher/updates/index.json`，而 Gitee 单文件上限 50MB，装不下 120MB 的 exe，所以这条自动更新通道暂不启用；请到本仓库的 Releases 页面手动下载新版。
