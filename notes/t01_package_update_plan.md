# 整合包更新能力（Update Requirement Package）方案

> 跟踪项目：`F:\ComfyUI-Mie-Package-Launcher`（启动器）
> 关联项目：`E:\HH`（V9 整合包制作工作区）、`C:\PP\V9\V9-Large\ComfyUI_Mie_2026_V9.0_Large`（已发布整合包样例）
> 版本：v3.3a（2026-08-11）

## 修订摘要

| 版本 | 改动 |
|---|---|
| v1 | 初稿 |
| v2 | 细化四类 item schema + Phase 划分 |
| v3 | 核对仓库现状：退出码改 5/9/10/11 避开 webui 6/7/8；`perform_batch_update` 改重构；`get_releases`→`list_releases` 包装；`checkout_ref.min` 走全量过滤；sha256 canonical 规则；补 satisfied 表 / library_id 映射 / 插件契约归一化 / GUI 注册 6 处 / env 切换护栏 / `_env_token`；Phase 1 估时上调；§9.3 V8→V9 |
| v3.1 | 二次 review：size_hint 三处矛盾统一为「不参与校验」（方案 A）；sha256 命令 `utf-8`→`utf-8-sig` 处理 BOM；status 枚举加 `not_applicable`；report item 加结构化 `reason`；`channel master` satisfied 改 `merge-base`；report 持久化 `runs/<run_id>.json`；apply 线程模型明确化；§6.5 加 registry 代码片段；非标准 category 警告；`diff_basis` 字段；删已答完的待决问题 |
| v3.2 | 三次 review（核对代码）：`open_link` 接受 http/https；plugin 归一化按 action+force 显式分支，补第三类 `force_update_selected`（返 list）；category 列表以代码实际 12 key 为准；`perform_batch_update` 薄包装；exit 5 触发表；`PackageApplyWorker` 骨架；自签证书预期 / model 浏览按钮 / plugin 多 spec 说明 / §10.5 Q6 标已接受；`_do_update` 字段陷阱警告 |
| **v3.3** | **四次 review**：① 删 `env_mismatch_rejected` 死代码 reason，§6.5 新增「env 不匹配前置检测」小节（短路 exit 9，不进 item 循环）；② `ok_at_alt_path` 加进 status 枚举 + `verified_at_alt_path` reason + summary 计数；③ 修 §5.6 typo；④ plugin force 归一化第三分支修 `detail` 语义混淆（成功路径 error 置 None，别把「已是最新」塞进 error）；⑤ plugin install 回滚明示「rmtree-only，pip 依赖不回收」；⑥ cache_ttl（3 天）/ runs_ttl（30 天）分开 |
| **v3.3a** | **实施后 review**：① **worker 死锁 bug** —— `_run` 的 finally 里调 `thread.quit()+wait()` 会让 QThread 在自己的 slot 里等自己退出 = 死锁；改为信号链清理（`finished → thread.quit → thread.finished → deleteLater`），§6.5.1 骨架同步改；② **`_cleanup_worker` has_failed 恒等式** —— `self._worker is None or self._worker is not None` 恒 True 但赋给 `error=False`，failed 任务侧栏不警告；改为 caller 从 `report["summary"]["failed"]` 读 has_failed 传入；③ `_render_report` 汇总补 `ok_at_alt_path`/`not_applicable`；④ `_persist_report` 失败 `logger.warning`（别静默）；⑤ `_on_item_progress` 维护 cursor（进度条才动）；⑥ §6.5.1 加 registry `failed → error=True` 调用示范 |

---

## 0. 目标与范围

UP 主制作一个 JSON manifest 文件（称「更新需求包」），描述本次要做的 4 类变更；启动器读取后向用户展示「需求 / 当前环境 / 即将执行」三栏对比，让用户逐项确认后执行。

**4 类变更：**

1. **ComfyUI 内核**：升级到指定版本（精确 / 最低 / 通道 / commit 四种 mode）
2. **插件**：安装 / 卸载 / 启用 / 禁用 / 更新（custom_nodes）
3. **模型**：列出下载链接（夸克盘 / 百度盘 / HuggingFace 等），引导用户手动下载到目标路径，启动器校验文件存在
4. **依赖库**：精确安装 pip spec 列表（不走整文件 requirements.txt 同步）

**manifest 来源：**

- 本地文件（用户从 UP 公众号 / 网盘下到本地，启动器读这个文件）
- HTTPS URL（用户在 GUI 粘贴 / CLI 传；UP 视频描述里附；每次 URL 不同）
- GUI 文本框直接粘贴 JSON

**不做的事：**

- 不设计 manifest 仓库 / 自动更新通道（stable / test 都不做）
- 不自动检查、不自动下载
- 不下载模型（model 项永远是用户手动下载，启动器只校验）
- 不动启动器自身的更新路径（与 manifest 路径解耦，可同一天发）

---

## 1. 现状盘点

### 1.1 整合包结构（E:\HH 制作的 V9 大整合包）

```
ComfyUI_Mie_2026_V9.0/                   ← Package 根
├── ComfyUI/                              ← ComfyUI git 仓库
│   ├── custom_nodes/                     ← 插件（git clone 装在这里）
│   ├── models/                           ← ComfyUI 自带模型（一般为空）
│   ├── requirements.txt                  ← 依赖清单
│   └── extra_model_paths.yaml            ← 外置模型库映射
├── python_embeded/
│   └── python.exe                        ← 嵌入式 Python（所有 pip 装这里）
├── launcher/                             ← 启动器产物
│   ├── config.json                       ← 配置
│   ├── launcher.log
│   └── update/                           ← 现有官方 stock updater
├── tools/PortableGit/                    ← 内嵌 git
└── 其它
```

- 三个发布版本：cu130 base / cu130 large / cu126 base
- Source 只读、Package 可写；所有更新只能落 Package
- 现有 `update/` 是 ComfyUI 官方 stock updater（pygit2 + master/tag + requirements.txt），不支持 pin 插件 / 模型 / 精细依赖

### 1.2 启动器现状（已具备的能力，可复用）

| 模块 | 能力 | 复用方式 |
|---|---|---|
| `services.update_service.UpdateService` | 内核 git + 前端/模板库 pip + requirements.txt 同步 | **`perform_batch_update` 是零参数方法，靠读 `self.app.*_var` GUI flag 驱动，不能直接被 CLI/PackageUpdateService 复用**。需重构：抽出 `_run_batch(selection, components)` 内核（接受显式 selection dict），让 `perform_batch_update` 和新增的 `run_targeted_update` 都调它 |
| `services.update_service.FROZEN_PKGS` | 模块级常量 `{torch, torchvision, torchaudio, triton, xformers, numpy}`（`update_service.py:26`） | 抽到 `services/dependency_policy.py` 共享 |
| `services.plugin_service.PluginService` | cm-cli install/uninstall/disable/enable/check-updates/force-update | 直接复用，**但返回契约有两套**：install/uninstall/enable/disable 返 `{ok, log, error}`，update_all/update_selected 返 `{updated, up_to_date, log, error}` —— PackageUpdateService 需写 adapter 归一化成统一 report item |
| `services.plugin_service.force_update_selected` | stash + pull --ff-only，绕 cm-cli 的 dirty 树拒绝 | **仅对 git 插件有效**，非 git 仓库返 `skipped`（`_force_update_one`），manifest plugin 项 `force=true` 若 spec 是 CNR id 非 git 会静默 skip，需在 UI 提示 |
| `services.version_service.VersionService` | `_checkout_tag` / `_checkout_commit` / `upgrade_latest` / `get_latest_stable_kernel`（均存在） | 复用 `_checkout_*`；新增 `checkout_ref(mode, ref)` 统一入口。**注意 `get_releases` 不存在**，只有私有 `_get_releases(force_refresh, mark_failed)`（带缓存 + 60s 失败冷却）—— `list_releases` = 公开包装它 |
| `utils.pip.install_or_update_package` / `install_requirements_file` | 单包 / 文件 pip 安装 + 进度 + 错误码（`pip.py:94` / `pip.py:657`） | 直接复用 |
| `utils.net.get_pypi_index_url_for_mode` | 镜像设置统一读取（`net.py:91`，返回 `aliyun/tsinghua/huaweicloud` URL，其它返 None） | 直接复用；`custom`/`none` 的兜底在调用方 |
| `services.launcher_update_service.LauncherUpdateService` | 启动器自身更新（Gitee index.json + sha256 + apply_update.bat） | 不动；启动器自身更新与本方案解耦 |
| `ui_qt.BackgroundTaskRegistry` | 后台任务注册 + 进度 + 找回（`background_task_registry.py`） | 直接复用；**只有单轴 progress tuple，无 sub-step API** —— 子步骤靠反复 `update(task_id, status=新文案, progress=(cur,total))` 模拟 |
| `core.update_summary.format_update_summary` | 内核 + 依赖结果的格式化摘要（`update_summary.py:22`） | 扩展支持插件 / 模型项 |
| `core.cli.exitcodes` | 0/1/2/3/4 稳定退出码 | 复用 + 新增 5/9/10/11；**6/7/8 已被 webui 占用，package 不得复用**（见 §4） |
| `services.model_path_service.ModelPathService` | 外置模型库（`extra_model_paths.yaml`）；`get_external_path()` 返 default 库 base_path，`get_libraries()` 返 `config["models"]["external_libraries"]` 列表（每项 `{id, name, base_path, enabled, is_default}`） | 复用解析 model 落点；id 是 8 位 hex（如 `2cff1773`），manifest 的 `library_id="default"` 是 magic string，需映射到 `is_default=True` 那条 |

**缺口：**

- 无 ModelService（仅做 verify_manual，不下载）
- 无 PackageUpdateService / manifest 概念
- 内核升级只支持 stable/master 二态
- 依赖升级走整文件 requirements.txt（无子集操作）
- `perform_batch_update` 与 GUI var 强耦合，无 selection 入参
- GUI 无「按 manifest 应用」入口
- CLI 无 `package` 子命令

---

## 2. manifest schema

### 2.1 顶层 schema

```json
{
  "manifest_version": 1,
  "id": "v9.0.1-to-v9.0.2",
  "name": "V9.0.1 → V9.0.2 增量更新",
  "package_target": {
    "min_version": "9.0.0",
    "max_version": "9.0.1",
    "channel": "v9"
  },
  "released_at": "2026-08-15T10:00:00+08:00",
  "notes_text": "本次更新说明（纯文本）",
  "sha256": "<hash-of-canonical-json>",
  "items": [
    { "id": "core-1", "kind": "core", ... },
    { "id": "plugin-1", "kind": "plugin", ... },
    { "id": "model-1", "kind": "model", ... },
    { "id": "dep-1", "kind": "dependency", ... }
  ]
}
```

字段说明：

- `manifest_version` 必填；启动器读 `> 它能处理的最高版本`（常量 `SUPPORTED_MANIFEST_VERSION = 1`，定义在 `core/package_manifest.py` 模块顶部）→ 拒绝（exit 10）
- `package_target` 定位本次更新适用的整合包版本范围；不匹配时仍允许运行但弹强提示
- `sha256` 可选；URL 拉取时强烈推荐（UP 在视频描述同步给出），本地文件可省
- `items[]` 本次要执行的项；逐项可被用户跳过 / 重试

#### sha256 canonical JSON 规则（**UP 主与启动器必须用同一套**）

canonical = 对**去掉 `sha256` 字段后**的对象做：

```python
canonical = json.dumps(obj_without_sha, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

- `sort_keys=True`：key 按字典序
- `ensure_ascii=False`：中文不转义（manifest 大量中文，转义后 hash 与本地编辑器算的不一致）
- `separators=(",", ":")`：无多余空白

**给 UP 主的生成命令**（放进 README / 制作流程文档）：

```bash
python -c "import json,hashlib,sys; d=json.load(open(sys.argv[1],encoding='utf-8-sig')); d.pop('sha256',None); print(hashlib.sha256(json.dumps(d,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode('utf-8')).hexdigest())" manifest.json
```

> ⚠️ **UP 主必须用此命令生成**，手算或用别的工具（如 `shasum` 整文件）会因为空白 / 中文转义对不上。校验失败时 UI 要把「期望值 / 实算值 / canonical 预览」三样都展示，方便 UP 主排查。
>
> ⚠️ **编码**：`encoding='utf-8-sig'`（不是 `utf-8`）—— Python 3.7+ 内置，会自动剥离 UTF-8 BOM。**Windows 记事本保存的文件默认带 BOM**，用 `utf-8` 会抛 `json.JSONDecodeError: Unexpected UTF-8 BOM`；启动器加载 manifest 时也用 `utf-8-sig` 读，两边一致。

### 2.2 四类 item

#### 2.2.1 `kind: "core"` —— 内核

```json
{
  "id": "core-bump",
  "kind": "core",
  "title": "升级 ComfyUI 内核到 v0.27.4",
  "selection": {
    "mode": "min",
    "ref": "v0.27.4"
  },
  "components": {
    "frontend": true,
    "templates": true,
    "requirements_sync": true,
    "clean_untracked": false
  },
  "stop_running_first": true,
  "restart_after": true
}
```

- `mode` ∈ `exact` | `min` | `channel` | `commit`
  - `exact` 切到 `ref` 指定的 tag（无则报错）
  - `min` 找 `>= ref` 的最新 stable tag（**走 `_get_releases()` 全量过滤，不是 `get_latest_stable_kernel`**，后者只返最新一个；无则标 `skipped: no version >= ref`）
  - `channel` 走 `stable` / `master` 二态（保留现有 `upgrade_latest` 行为）
  - `commit` 切到 `ref` 指定的 commit hash
- dirty tree 走 `git stash` + `pull`（与现有 update.py 一致）；`clean_untracked=true` 走 `git clean -fdx`（破坏性，UP 显式 opt-in）
- `requirements_sync=true` 时跑 requirements.txt 同步，仍走 FROZEN_PKGS 黑名单
- `stop_running_first=true` 时先停 ComfyUI；`restart_after=true` 时跑完重启

#### 2.2.2 `kind: "plugin"` —— 插件

```json
{
  "id": "plugin-qwen3-tts",
  "kind": "plugin",
  "title": "安装 qwen3-tts-comfyui 插件",
  "action": "install",
  "spec": "qwen3-tts-comfyui@nightly",
  "force": false,
  "restart_after": false
}
```

- `action` ∈ `install` | `uninstall` | `enable` | `disable` | `update`
- `spec` 单值：`dir_name` / git URL / CNR id / `name@version` / `name@nightly`。**当前 schema 不支持 `spec` 列表 / 一个 item 跑多个插件** —— 批量场景（如更新 5 个插件）每个插件独立写一个 item。是否加多 spec 支持见 §10.5 Q1
- `action=update` 时 `spec` 省略 → 更新全部
- `force=true` 走 `force_update_selected`（stash + pull --ff-only，绕 cm-cli 的 dirty 树拒绝）。**限制：`force_update_selected` 仅对 git 插件有效，CNR id 非 git 仓库会返 `skipped`（`plugin_service.py:502` 的 `_force_update_one`）。** PackageUpdateService 收到 `skipped` 时标 `not_applicable` + `reason=not_git_for_force`（见 §3.1.1），GUI 给提示徽章
- 直接映射到 `PluginService` 现成方法，零修改（返回契约归一化见 §3.2，**三套契约**都要归一）

#### 2.2.3 `kind: "model"` —— 模型（**完全手动下载**）

```json
{
  "id": "model-qwen3-tts",
  "kind": "model",
  "title": "下载 Qwen3-TTS-12Hz-1.7B-VoiceDesign",
  "links": [
    { "label": "夸克网盘", "url": "https://pan.quark.cn/s/xxx" },
    { "label": "HuggingFace", "url": "https://huggingface.co/Qwen/..." }
  ],
  "dest": {
    "library_id": "default",
    "category": "qwen-tts",
    "filename": "Qwen3-TTS-12Hz-1.7B-VoiceDesign.safetensors"
  },
  "size_hint": "3.5 GB",
  "checksum": {
    "type": "sha256",
    "value": "..."
  },
  "skip_if_exists": true
}
```

- `links[]` 有序；UI 第一个展示为「首选」；可为空（合法），UI 显示「暂无下载链接」徽章
- `dest.library_id` 解析为外置模型库路径：
  - **`"default"`（magic string）** → 映射到 `external_libraries` 里 `is_default=True` 的那条的 `base_path`
  - **8 位 hex id（如 `"2cff1773"`）** → 按 `id` 精确匹配
  - 找不到 → 报错 exit 1
  - 兼容值 `null` → 等同 `"default"`
- `dest.category` 落到哪个类目子目录。**标准类目以 `ModelPathService.standard_map`（`model_path_service.py:23-36`，实例属性 list of tuples）的 key 为准**，实际 12 个：

  ```
  checkpoints, text_encoders, clip_vision, configs, controlnet,
  diffusion_models, embeddings, loras, upscale_models, vae,
  audio_encoders, model_patches
  ```

  （注意：`clip` / `unet` 不是独立 key —— 它们分别是 `text_encoders` / `diffusion_models` 的**回退子路径**；`vae_approx` / `ipadapter` / `qwen-tts` 都不在 standard_map，靠 `_collect_extra_mappings` 目录扫描兜底发现。）处理规则：
  - 在标准集内 → 直接落
  - **不在标准集内**（UP 主拼错如 `lora` 漏 s，或新模型类型如 `qwen-tts`）→ GUI 弹「非标准类目 `xxx`，确定要建吗？」警告（可继续）/ CLI stderr warning，但仍允许落（自动 `mkdir(parents=True)`）。**不阻断**，只提示 —— 因为新模型类型早期就是 plugin 自管，硬拒会挡住合法用例
- `dest.filename` 必填；缺则校验失败
- `size_hint` **仅 UI 展示用**（卡片上写「~3.5 GB」），**不参与任何校验和 satisfied 判定**（避免不同精度变体 fp16/fp32/EXL2 字节数对不上，强校验会误报）。UI 若发现实际文件大小与 `size_hint` 偏差 >50%，给黄色「文件大小差异大，请确认不是下错版本」提示，但不阻塞 verify
- `checksum` 可选：有就严格校验（sha256），没有就只看文件存在
- `skip_if_exists=true` 目标文件已存在则跳过
- **启动器不做下载**，仅 `webbrowser.open` 打开链接 + 校验文件

#### 2.2.4 `kind: "dependency"` —— 依赖库

```json
{
  "id": "dep-numpy-fix",
  "kind": "dependency",
  "title": "降级 numpy 到 2.4.6",
  "packages": [
    { "spec": "numpy==2.4.6", "force_reinstall": true },
    { "spec": "kornia==0.6.12", "force_reinstall": false },
    { "spec": "voluptuous>=0.15" }
  ],
  "skip_frozen": true,
  "index_url_override": null,
  "restart_after": false
}
```

- 走 `utils.pip.install_or_update_package`（单包操作 + 进度 + 错误码）
- `force_reinstall=true` 加 `--force-reinstall` flag
- `skip_frozen=true`（默认）时 `torch` / `torchvision` / `torchaudio` / `triton` / `xformers` / `numpy` 被静默跳过 + 标 `skipped`，提示「V9 制作流程里这些是手动 wheel」
- `index_url_override`：`null` 走 config 里的 pypi_proxy_mode；`"none"` 强制官方源；URL 字符串用这个
- spec 必带操作符（`==` / `>=` 等），与现有 `_find_requirement_spec` 一致

### 2.3 完整示例

```json
{
  "manifest_version": 1,
  "id": "v9.0.1-to-v9.0.2",
  "name": "V9.0.1 → V9.0.2 增量更新",
  "package_target": { "min_version": "9.0.0", "max_version": "9.0.1", "channel": "v9" },
  "released_at": "2026-08-15T10:00:00+08:00",
  "notes_text": "本次更新：内核 v0.27.4 修复 X；新增 Qwen3-TTS 工作流所需插件；numpy 锁定 2.4.6；用户需手动下载 Qwen3-TTS 模型。",
  "sha256": "...",
  "items": [
    {
      "id": "core-bump", "kind": "core", "title": "ComfyUI 内核升级到 v0.27.4",
      "selection": { "mode": "min", "ref": "v0.27.4" },
      "components": { "frontend": true, "templates": true, "requirements_sync": true }
    },
    {
      "id": "plugin-mienodes", "kind": "plugin", "title": "更新 ComfyUI_MieNodes",
      "action": "update", "spec": "ComfyUI_MieNodes@nightly"
    },
    {
      "id": "dep-numpy", "kind": "dependency", "title": "锁定 numpy==2.4.6",
      "packages": [{ "spec": "numpy==2.4.6", "force_reinstall": true }]
    },
    {
      "id": "model-qwen3-tts", "kind": "model",
      "title": "下载 Qwen3-TTS-12Hz-1.7B-VoiceDesign",
      "links": [
        { "label": "夸克网盘", "url": "https://pan.quark.cn/s/xxx" },
        { "label": "HuggingFace", "url": "https://huggingface.co/Qwen/..." }
      ],
      "dest": { "library_id": "default", "category": "qwen-tts", "filename": "..." },
      "size_hint": "3.5 GB",
      "skip_if_exists": true
    }
  ]
}
```

---

## 3. 服务层设计

### 3.1 三个新增 service

#### 3.1.1 `services.package_update_service.PackageUpdateService`

职责：

- 加载 manifest（本地文件 / HTTPS URL / 粘贴的 JSON）
- 校验 schema / sha256
- 与当前 env 做 diff（哪些 item 已满足 / 哪些需要执行）
- 协调四项 item 执行
- 记录每项结果，返回结构化 report
- 接受 `on_item(item_id, status, payload)` 回调
- 支持取消

公开方法：

```python
class PackageUpdateService:
    def __init__(self, app): ...
    def load_source(self, source: str) -> tuple[dict, str]:  # 返回 (manifest, resolved_cache_path)
    def validate(self, manifest: dict) -> tuple[bool, str | None]: ...
    def diff_against_current(self, manifest: dict) -> dict: ...
    def apply(
        self,
        manifest: dict,
        item_ids: list[str] | None = None,
        manual_decisions: dict | None = None,   # {item_id: "yes" | "skip"}
        on_item: Callable | None = None,
    ) -> dict: ...
    def cancel(self): ...
    def build_report(self) -> dict: ...
```

返回 report schema：

```json
{
  "manifest_id": "v9.0.1-to-v9.0.2",
  "run_id": "2026-08-15T10-00-00-abc123",
  "started_at": "...",
  "finished_at": "...",
  "env_id": "env_default",
  "items": [
    {
      "id": "core-bump",
      "kind": "core",
      "title": "...",
      "status": "ok|ok_at_alt_path|skipped|not_applicable|failed|manual_required|pending|in_progress",
      "reason": null,
      "before": {...},
      "after": {...},
      "log": "...",
      "error": null
    }
  ],
  "summary": {
    "total": 4, "ok": 2, "ok_at_alt_path": 0, "skipped": 1, "not_applicable": 1,
    "failed": 0, "manual_required": 0
  }
}
```

`status` 枚举：

- `ok` 已应用变更（model 项 = 文件在 manifest 指定路径就位）
- `ok_at_alt_path` **model 项专属** —— 文件存在且 checksum 对，但用户通过 §5.6「浏览...」按钮指向了非 manifest 指定路径，且拒绝移动。与 `ok` 分开记：ComfyUI 不会扫描该路径，用户需手动挪。`after.path` 字段记录实际路径
- `skipped` **本可执行但选择不执行** —— 已满足条件（含 `skip_if_exists` 命中、`min` mode 已达、用户主动跳过、dependency 黑名单命中）
- `not_applicable` **系统不支持，无法执行** —— 如 plugin `force=true` 但 spec 是非 git 仓库（`force_update_selected` 对 CNR id 返 skipped）。与 `skipped` 分开记，避免污染 summary 里「用户预期跳过」的语义
- `manual_required` model 项，用户没勾任何框
- `failed` 失败，error 字段有详情
- `pending` 未开始（被 `--items` 过滤掉）
- `in_progress` 正在跑

`reason` 结构化枚举（`skipped` / `not_applicable` / `ok_at_alt_path` 有值，其它为 `null`；agent 可按此 grep 分类）：

- `user_skipped` — 用户在 GUI 取消勾选 / CLI `--manual-skip`
- `up_to_date` — 版本已满足（core / dep）
- `frozen_pkg` — dependency 命中 FROZEN_PKGS 黑名单
- `min_version_reached` — core `min` 模式当前已 >= ref
- `file_exists` — model `skip_if_exists` 命中
- `not_git_for_force` — plugin `force=true` 但非 git 仓库
- `no_version_ge_ref` — core `min` 模式找不到 >= ref 的 stable tag
- `verified_at_alt_path` — model 文件 verify 通过但用户拒绝移到 manifest 指定路径（status=`ok_at_alt_path` 专用）

> **注意**：env 不匹配是 **apply 启动前的短路检测**（§6.5.3），直接 exit 9，不进 item 循环，因此**没有 `env_mismatch_rejected` 这个 reason**（曾经的 v3.1 死代码，已删）。

#### satisfied 判定表（`diff_against_current` 的依据，决定默认勾选）

| kind | 判定为 satisfied（默认不勾） | 否则（默认勾） |
|---|---|---|
| `core` | `exact`: 当前 HEAD tag == ref；`min`: 当前 tag >= ref 且为 stable；`channel stable`: 当前是最新 stable；`channel master`: **当前 HEAD 是 origin/master 的祖先**（`git merge-base --is-ancestor HEAD origin/master` 返 0）—— 用祖先判定而非精确相等，因为 master 是滚动的，用户停在 HEAD 前几个 commit 也算「已经在 master 轨道上」；`commit`: 当前 HEAD hash == ref | 任意不满足 |
| `plugin` | `install`: dir 已存在；`uninstall`: dir 不存在；`enable`: dir 存在且未 disable；`disable`: dir 存在且已 disable；`update`: **永远判 satisfied=false**（见下方说明） | 反之 |
| `model` | 文件存在；若 manifest 带 `checksum` 则 sha256 匹配。**`size_hint` 不参与判定**（仅 UI 展示） | 文件缺失 / sha256 不符 |
| `dependency` | `pip show <pkg>` 版本满足 spec（用 `packaging.specifiers` 判 `==`/`>=`/`<=` 等） | 版本不满足或未装 |

> **说明 1**：`core` 的版本比较用 `packaging.version` 解析 `vX.Y.Z` tag（剥 `v` 前缀）。`channel master` 用 `merge-base --is-ancestor` 而非 `HEAD == origin/master`：后者在用户停在 HEAD 前一两个 commit 时永远 false，导致永远默认勾、永远"需要更新"，不符合直觉。
>
> **说明 2**：`plugin update` 故意不判 satisfied 是因为「检查远端是否有更新」要走网络（cm-cli check-update），diff 阶段不应该联网。但这会让 agent / 高级用户从 diff 看不出「这次到底要不要更」。折中：diff 输出对 `update` 类 plugin 额外标记 —— 见下方 `diff_basis` 字段。

#### diff 输出额外字段 `diff_basis`（透明化默认勾选的依据）

```json
"diff": {
  "items_already_satisfied": ["dep-numpy"],
  "items_to_apply": ["core-bump", "plugin-mienodes", "model-qwen3-tts"],
  "items_manual_required": [],
  "diff_basis": {
    "plugin-mienodes": "plugin_update_skips_satisfied_check_by_design"
  }
}
```

`diff_basis` 对「默认勾但并非一定有变更」的 item 给原因（目前只有 plugin update 这一种）。agent 拿到后可判断「这个 item 是真有版本差异，还是为了安全默认勾」，避免误报「需要更新」。

#### 3.1.2 `services.model_service.ModelService`（**只验证，不下载**）

> 命名提示：与已有 `services/model_path_service.py`（管外置库 CRUD）区分，本 service 管的是「manifest 里 model 项的路径解析 + 文件校验」。如担心混淆，可命名为 `services/manifest_model_service.py`。

职责：

- `resolve_dest(library_id, category, filename)` → 算绝对路径
  - `library_id="default"` 或 `null` → 走 default 外置库（`ModelPathService.get_external_path()`）
  - 8 位 hex id → 从 `get_libraries()` 按 id 精确匹配
  - 找不到 library_id → 报错 exit 1
  - 找不到 category 子目录 → 自动 `mkdir(parents=True)`
- `verify_manual(item)` → 扫目标路径，返回 `ok / missing / checksum_mismatch`
  - **不返 `size_mismatch`** —— `size_hint` 仅 UI 展示用，不参与校验（避免 fp16/fp32/EXL2 变体字节数不同误报；详见 §2.2.3）
  - `checksum` 有就严格校验 sha256；没有就只看文件存在
- `open_link(url)` → `webbrowser.open(url)`，**接受 http / https**（不阻断）。HTTPS-only 规则仅适用于 **manifest 源 URL**（§3.1.1 `load_source` 那一层，见 §6.4）；model `links[].url` 因网盘短链经常是 HTTP，必须放行。UI 调 `open_link` 前若 url 是 http，按 §6.4 给「非 HTTPS」徽章提示，但函数本身正常打开

**不安装任何额外 pip 包**（huggingface_hub / modelscope / requests 都不引入）。

#### 3.1.3 `services.dependency_policy.DependencyPolicy`（FROZEN_PKGS 共享）

把 `services/update_service.py:26` 的 `FROZEN_PKGS` 抽出来集中：

```python
# services/dependency_policy.py
FROZEN_PKGS = frozenset({
    "torch", "torchvision", "torchaudio", "triton", "xformers", "numpy",
})

def is_frozen(pkg: str) -> bool: ...
def filter_frozen(packages: list[str]) -> tuple[list[str], list[str]]:  # (allowed, frozen)
```

`UpdateService` 改为从这里 import；`PackageUpdateService` 也从这里读。**注意：`comfyui-frontend-package` / `comfyui-workflow-templates` 刻意不在黑名单里**（`update_service.py:22-25` 注释），迁移时别误带。

### 3.2 对现有 service 的扩展

#### `VersionService` 新增 `checkout_ref` / `list_releases`

```python
def checkout_ref(self, mode: str, ref: str) -> dict:
    if mode == "exact":
        return self._checkout_tag(ref)
    if mode == "commit":
        return self._checkout_commit(ref)
    if mode == "min":
        # ⚠️ 必须走 _get_releases() 全量过滤，不能只用 get_latest_stable_kernel
        # （后者只返最新一个 stable，拿不到「>= ref 的候选集」）
        releases = self._get_releases(force_refresh=True)
        candidates = [r for r in releases if _is_stable(r) and _parse_ver(r["tag"]) >= _parse_ver(ref)]
        if not candidates:
            return {"ok": False, "skipped": True, "reason": f"no stable version >= {ref}"}
        candidate_tag = max(candidates, key=lambda r: _parse_ver(r["tag"]))["tag"]
        return self._checkout_tag(candidate_tag)
    if mode == "channel":
        return self.upgrade_latest(stable_only=(ref == "stable"))
    raise ValueError(f"unknown mode: {mode}")

def list_releases(self, refresh: bool = False) -> list[dict]:
    """公开包装 _get_releases(force_refresh=refresh, mark_failed=False)。
    GUI「可选版本」下拉用；失败不抛，返空列表。"""
    return self._get_releases(force_refresh=refresh, mark_failed=False)
```

- 版本解析用 `packaging.version.Version`（剥 `v` 前缀）
- `_is_stable` 复用现有判定（`is_stable_version`）
- 新增方法记得同步检查 `services/interfaces.py` 的 `IVersionService` 抽象

#### `UpdateService` 重构（**不是简单复用**）

现状：`perform_batch_update(self)` 零参数，靠读 `self.app.update_core_var` 等 GUI var 驱动。PackageUpdateService / CLI 没有 `app.*_var`，无法直接调。

**重构方案**（薄包装，省掉重复）：

抽私有内核 `_run_batch(self, selection, components, on_progress=None) -> Tuple[List[Dict], str]`，接受显式 `{core, frontend, templates, requirements_sync}` 形态。两个公开方法都是它的薄包装，**不再重复主逻辑**：

```python
def _run_batch(self, selection: dict, components: dict,
               on_progress=None) -> Tuple[List[Dict], str]:
    """实际干活的内核（重构自原 perform_batch_update 的方法体）。"""
    ...  # 原 perform_batch_update 方法体搬到这里，self.app.*_var 读取替换为 selection 形参

def perform_batch_update(self) -> Tuple[List[Dict], str]:
    """GUI 入口：从 app.*_var 读 selection 后调 _run_batch（行为与重构前一致）。"""
    selection = {
        "core":             self.app.update_core_var.get(),
        "frontend":         self.app.update_frontend_var.get(),
        "templates":        self.app.update_template_var.get(),
        "requirements_sync": bool(self.app.auto_update_deps_var.get()),
    }
    components = {"stable_only": self._safe_get_stable_only_flag()}
    return self._run_batch(selection, components)

def run_targeted_update(self, selection: dict, components: dict | None = None,
                        on_progress=None) -> Tuple[List[Dict], str]:
    """CLI / PackageUpdateService 入口：直接传 selection，不读 GUI var、不污染默认开关。"""
    return self._run_batch(selection, components or {}, on_progress=on_progress)
```

> 这是中等规模重构，会动到 GUI 内核更新路径的核心方法。Phase 1 必须做回归测试：跑现有 `tests/unit/test_update_service.py` + GUI 手动验一次内核更新流程，确认 `_run_batch` 抽出后 `perform_batch_update` 行为不变。

#### `PluginService` 返回契约归一化（**三套契约，按 action 显式分支**）

核对代码后确认 PluginService 有**三套**返回契约（不是两套）：

| 调用路径 | action | 返回类型 | 字段集 |
|---|---|---|---|
| `_lifecycle`（`plugin_service.py:478-486`） | install / uninstall / enable / disable | `dict` | `{ok, log, error}` |
| `_do_update`（`plugin_service.py:513-529`） | update_all / update_selected（`force=false`） | `dict` | `{updated, up_to_date, log, error}` |
| `force_update_selected`（`plugin_service.py:488`）→ `_force_update_one`（`:496-511`） | update（`force=true`） | **`list[dict]`** | 每项 `{name, ok, skipped, detail}` |

PackageUpdateService 里写 adapter，**按 `action` + `force` 显式分支**（不用 `set >= set` 子集判断 —— 那种写法在底层多返一个字段时就静默走错分支）：

```python
def _normalize_plugin_result(self, raw, action: str, force: bool, spec: str) -> dict:
    """归一化成统一 report item 的 {ok, error, extra}。"""
    if action in ("install", "uninstall", "enable", "disable"):
        # raw = {ok, log, error}
        return {"ok": bool(raw.get("ok")), "error": raw.get("error")}
    if action == "update" and not force:
        # raw = {updated, up_to_date, log, error}
        return {"ok": not raw.get("error"), "error": raw.get("error")}
    if action == "update" and force:
        # raw = list[{name, ok, skipped, detail}] —— 按 spec 取对应项
        item = next((x for x in raw if x.get("name") == spec), None)
        if item is None:
            return {"ok": False, "error": f"force_update_selected 未返回 {spec} 的结果"}
        if item.get("skipped"):  # 非 git 仓库 → not_applicable
            return {"ok": False, "not_applicable": True,
                    "reason": "not_git_for_force", "error": item.get("detail")}
        # ⚠️ detail 语义随 ok 变化（核对 _force_update_one :506-511）：
        #   成功路径 detail = pull stdout 或 "已是最新"（非空正常文本）
        #   失败路径 detail = "pull 失败 (rc=...): ..."
        # 不能无条件 error=item.get("detail") —— 会让成功项的 error 塞进「已是最新」，report 看起来全是 error。
        # detail 成功时该进 log（或丢弃），失败时才进 error。
        ok = bool(item.get("ok"))
        return {
            "ok": ok,
            "error": None if ok else item.get("detail"),
            "log": item.get("detail") if ok else None,
        }
    raise ValueError(f"unknown plugin action: {action}")
```

> ⚠️ **`_do_update` 字段陷阱**（核对代码 `plugin_service.py:527-529` 发现）：`up_to_date` **恒为 False**（硬编码），`updated` 在成功路径（rc=0）**恒为 True**。源码注释明说「cm-cli update 输出是人类文本，难以可靠区分『真更新了』与『本就最新』，保守按『跑过更新流程』报 updated=True」。**归一化逻辑不能依赖 `up_to_date` / `updated` 表达「真的更新了」语义** —— `ok` 只看 `error` 是否为 None 即可，别去读 `updated`/`up_to_date`。

#### `LauncherUpdateService` 不动

启动器自身更新路径与 manifest 路径解耦，可同一天发 launcher v1.1.0 + V9.0.1→V9.0.2 manifest。

---

## 4. CLI 设计

新增子命令：`comfyui-launcher package <action> <path-or-url>`

| action | 用途 |
|---|---|
| `show` | 加载 manifest，打印摘要 + 与当前 env 对照的 diff |
| `diff` | 只输出 diff 段（agent 快速判断用） |
| `apply` | 应用 manifest |

**参数自动判别：** `http://` / `https://` 前缀走 URL 下载到 cache；其他当本地文件路径。HTTPS 强制（HTTP 直接 exit 11）。

### 4.1 `package show <path-or-url>`

Output schema（`--json`）：

```json
{
  "manifest": { ... 完整 manifest ... },
  "valid": true,
  "validation_error": null,
  "diff": {
    "items_already_satisfied": ["dep-numpy"],
    "items_to_apply": ["core-bump", "plugin-mienodes", "model-qwen3-tts"],
    "items_manual_required": []
  },
  "current_versions": { "comfyui": "v0.27.0", "python": "3.13.12" }
}
```

### 4.2 `package diff <path-or-url>`

只输出 diff 段。

### 4.3 `package apply <path-or-url> [flags]`

| flag | 默认 | 说明 |
|---|---|---|
| `--items ID1,ID2,...` | 全部 | 只跑指定 item_id，其它 pending |
| `--dry-run` | off | 校验 + 模拟跑，不实际改文件 / pip / git |
| `--auto-yes` | off | 跳过所有交互确认（脚本用） |
| `--manual-yes` | off | model 项视作用户已自行下载 → verify_manual |
| `--manual-skip` | off | 全部 model 项标 skipped |
| `--env ENV_ID` | active | 一次性指定 env（不写回 config） |

#### Exit codes（**唯一定义处**；§6 各护栏节按此表归类，不再重复列）

| 码 | 含义 | 触发场景（对应章节） |
|---|---|---|
| 0 | 全部 ok / skipped / not_applicable（无 failed） | 正常完成 |
| 1 | 通用错误 | 未归类的异常 |
| **5** | 部分失败（≥1 项 `failed`） | 任一 item 执行失败（§3.1.1 status） |
| **9** | 前置不兼容 | dirty tree + `clean_untracked=false` 且 stash 失败（§6.1）/ env 不匹配且用户拒绝（§6.5.3，apply 启动前短路） |
| **10** | manifest 无效 | schema 错 / sha256 不符（§6.3）/ `manifest_version > SUPPORTED`（§2.1）/ 未知 kind（§6.4） |
| **11** | 源不可达 / 非 HTTPS | 文件不存在 / URL 拉取失败 / JSON 解析失败 / manifest URL 是 HTTP（§6.4） |

> 表里每行的「触发场景」指向具体护栏节，但**退出码数值的唯一来源是本表**。其它节只描述场景，不另立码值。

**exit 5 触发判定（哪些 status 算「失败」）**：

| item.status | 触发 exit 5? | 理由 |
|---|---|---|
| `ok` / `ok_at_alt_path` / `skipped` / `not_applicable` / `manual_required` / `pending` | **否** | `ok_at_alt_path` 是「verify 通过，只是位置不对」算成功；`not_applicable` 是「系统不支持，问之前不知道」无可指责；`manual_required` 是「用户没指示，尊重选择」同 `pending`；都不算失败 |
| `failed` | **是** | 「想干、用户也确认了，但出错」—— 唯一触发 exit 5 的 |

> 即：`exit_code = 5 if any(item.status == "failed" for item in report.items) else 0`（1/9/10/11 是更早阶段短路，不进 report）。这样用户跑完一个全是 `manual_required`（model 项都没勾）的 manifest 也不会 exit 5。

> **为什么不用 6/7/8：** 这三个码当前是 webui 子命令的专属语义（`cmd_webui.py` 里裸 magic number，未进 `exitcodes.py`），且 7 被 e2e 测试锁住（`tests/e2e/test_webui_cli_e2e.py:125` 断言 webui 未安装返 7）。`cli.md:332-345` 明确声明「webui 的退出码仅 webui 子命令返回」。package 复用 6/7/8 会让外部监控脚本无法区分来源，违反「跨子命令含义稳定」契约。改用空闲的 5 + 全新 9/10/11 段。

#### 顺手做的 webui 退出码命名化（纯重构，不改语义）

把 `cmd_webui.py` 里 6/7/8 的裸 magic number 提到 `exitcodes.py`，加命名常量：

```python
# core/cli/exitcodes.py（新增）
EXIT_PACKAGE_PARTIAL_FAILURE = 5     # package: ≥1 项 failed
# 6/7/8 保留给 webui（见下）
EXIT_WEBUI_CORE_NOT_RUNNING = 6      # webui: --with-comfyui 时 ComfyUI 未跑
EXIT_WEBUI_NOT_INSTALLED = 7         # webui: 路径未安装
EXIT_WEBUI_DEPS_MISSING = 8          # webui: 依赖缺失
EXIT_PACKAGE_PRECONDITION = 9        # package: 前置不兼容
EXIT_PACKAGE_MANIFEST_INVALID = 10   # package: manifest 无效
EXIT_PACKAGE_SOURCE_UNREACHABLE = 11 # package: 文件/URL 不可达
```

`cmd_webui.py` 改为引用命名常量。这是独立 PR，可与 package 功能并行，不破坏现有 webui 行为 / 测试。

**Output schema（`--json`）：** 完整 report（见 §3.1.1）。

### 4.4 parser.py / main.py 改动

- `parser.py`：`SUBCOMMANDS`（`:22-33`，当前 10 项）加 `"package"`；新增 `_PACKAGE_EPILOG`（仿 `_WEBUI_EPILOG`，含 Exit codes 段列 0/1/5/9/10/11 + Output schema 段）；`build_parser()` 加 sp；用 `_add_env_arg(sp)`（`:304-313`）挂 `--env`
- `main.py`：`_DISPATCH`（`:20-31`）加 `("package", cmd_package)`；模块需有 `run(args, app) -> int`

---

## 5. GUI 设计

### 5.1 入口位置与注册（**6 处改动点**）

侧边栏放「更新中心」，位于「ComfyUI 内核版本管理」和「插件」之间。

> ⚠️ **导航不是用 `components/nav.py`/`sidebar.py`**（那是未接线的早期抽象）。实际注册全硬编码在 `ui_qt/qt_app.py::_setup_ui`。加一个页面要**同步改 6 处**，漏任何一处都会出 bug：

| # | 位置 | 改什么 |
|---|---|---|
| 1 | `qt_app.py:39-49` | import `from ui_qt.pages.package_update_page import PackageUpdatePage` |
| 2 | `qt_app.py:2066-2078` `btns` dict | 加 `btns["package"] = NavBtn("📦 更新中心")`。**dict 插入顺序 = 侧边栏显示顺序**，插在 version 和 plugins 之间 |
| 3 | `qt_app.py:2299-2355` 页面实例化 | `page_package = PackageUpdatePage(app=self, theme_manager=self.theme_manager)`，参照 `PluginsPage`（`:2346`） |
| 4 | `qt_app.py:2358-2370` `self._new_pages` dict | **必须加 `self._new_pages["package"] = page_package`**，否则主题切换 / env 刷新遍历 `self._new_pages` 时取不到本页 |
| 5 | `qt_app.py:2449-2459` `content.addWidget(wrap_in_scroll(...))` | 加页面到 QStackedWidget，顺序要和 `pages` dict 一致 |
| 6 | `qt_app.py:2461-2473` `pages` dict | 加 `pages["package"] = page_package`。**key 集合必须 == `btns` 的 key 集合**，否则 `_select_tab`（`:2475-2488`）`list(pages.keys()).index(name)` 会 KeyError |

`PackageUpdatePage` 构造签名参照 `LaunchPage.__init__(self, app, theme_manager, parent=None)`（`launch_page.py:17`），继承 `BasePage`，实现 `update_theme(self, theme_styles)`（主题切换会自动被调，见下）。

### 5.2 主题更新机制（已自动覆盖，无需额外接线）

`_apply_theme`（`qt_app.py:1870-1880`）遍历 `self._new_pages` 调每个页面的 `update_theme(theme_styles)`。只要：
- 页面进了 `self._new_pages`（§5.1 第 4 处）
- 实现 `update_theme(self, theme_styles)`（参照 `LaunchPage.update_theme` `launch_page.py:518-555`，转发到子 section）

主题切换就自动生效，**不需要单独订阅 ThemeManager**。页内额外 `setStyleSheet` 的控件必须在 `update_theme` 里重应用（AGENTS.md 主题规范硬性要求）。

### 5.3 页面布局（卡片式）

```
+----------------------------------------------------+
| ComfyUI Mie 整合包更新中心                          |
+----------------------------------------------------+
| 当前环境: V9.0.1 (cu130 base)  内核: v0.27.0       |
| Python: 3.13.12   ComfyUI-Manager: v4.x            |
| 外置模型库: 3 个（default: F:\ComfyUI_Models）      |
+----------------------------------------------------+
| 加载 manifest:                                       |
|  [选择本地文件...]  [从 URL 加载...]  [粘贴 JSON]    |
+----------------------------------------------------+
| manifest 摘要                                        |
|   V9.0.1 → V9.0.2 增量更新                          |
|   发布: 2026-08-15   共 4 项                        |
|   备注: 本次更新：内核 v0.27.4 修复 X；新增 ...      |
+----------------------------------------------------+
| 更新项清单（每项一张卡片，可勾选/展开）               |
| ☑ [core] 升级 ComfyUI 内核到 v0.27.4                 |
|     当前: v0.27.0  →  目标: v0.27.4  模式: min      |
|     风险: dirty tree 将自动 stash                    |
|     ☑ 会同步 requirements.txt（受 FROZEN_PKGS 保护）|
| ☑ [plugin] 更新 ComfyUI_MieNodes                    |
|     action: update   spec: ComfyUI_MieNodes@nightly |
| ☑ [dep] 锁定 numpy==2.4.6                            |
|     packages: numpy==2.4.6 (force_reinstall)        |
| ☑ [model] 下载 Qwen3-TTS-12Hz-1.7B                  |
|     ~3.5 GB  → F:\ComfyUI_Models\qwen-tts\          |
|     链接: [夸克网盘 ▼] [HuggingFace ▼]               |
|     ☐ 我已下载  ☐ 暂不下载                            |
+----------------------------------------------------+
| [取消] [全选] [全不选] [▶ 开始应用]                  |
+----------------------------------------------------+
```

跑完后底部追加报告卡片：

```
+----------------------------------------------------+
| 运行结果                                             |
| ✓ core-bump       ok  (3.2s)  v0.27.0 → v0.27.4    |
| ✓ plugin-mienodes ok  (1.5s)  NIGHTLY@abc1234      |
| ✓ dep-numpy       ok  (4.1s)  numpy==2.4.6         |
| ⏸ model-qwen3-tts manual_required  未勾选          |
| [重新运行失败项] [重新校验模型项] [导出 report.json] |
+----------------------------------------------------+
```

### 5.4 逐项确认 UX

- 默认全勾
- 每项根据 `kind` 显示风险徽章：core=高风险，model=中风险，plugin/dep=低风险
- 每项可点击展开看细节（before / after、命令预览、来源 URL 等）
- 「▶ 开始应用」按勾选顺序串行执行（pip/git 不能并发）
- 任一项失败 → 弹窗问「继续后续 / 停止」
- 全跑完 → 报告卡片 + 导出 / 重跑按钮

### 5.5 后台执行

- 包级 task（`task_<n>`）注册到 `BackgroundTaskRegistry`，title = manifest.id
- **registry 只有单轴 progress tuple，无 sub-step API**：每项作为子步骤，通过反复调 `registry.update(task_id, status=<新文案>, progress=(cur,total))` 模拟（参照内核更新 `qt_app.py:3456-3485` 的 `_apply_progress` 写法）
- ProgressDialog 显示当前项 + 整体进度（i/N + 当前项的子进度）
- 用户最小化 → 后台跑 + 侧栏按钮高亮
- 用户取消 → `PackageUpdateService.cancel()`，安全停 git / pip

### 5.6 模型项的 UI 特殊处理

- 「打开下载链接 ▼」下拉：点哪个链接就 `open_link` 哪个（接受 http/https，见 §3.1.2）
- 「目标路径」旁边有「复制」按钮 + 「打开所在文件夹」按钮（`os.startfile` / `xdg-open`）
- 「我已下载」复选框 → 勾选后调 `verify_manual` → 显示「✓ 已就位」/「✗ 找不到文件」/「✗ sha256 不匹配」徽章（**无「大小不匹配」** —— `size_hint` 不参与校验，见 §2.2.3；若实际大小与 hint 偏差 >50% 另给黄色软提示）
- 「⏭ 暂不下载」复选框 → 整次 apply 时该项 `skipped`
- 「重新校验模型项」按钮（跑完整次 apply 后用户补下完了模型）
- **「浏览...」按钮**（覆盖目标路径）：用户可能把文件下到了 `D:\Downloads\xxx.safetensors` 而非 manifest 指定路径。点「浏览...」选文件 → UI 把 verify 目标临时指向该路径 → verify 通过后提示用户是否复制/移动到 manifest 指定路径（因为 ComfyUI 只扫标准类目目录，放错位置 ComfyUI 看不到）。若用户同意移动 → 实际挪文件后 status=`ok`；若用户拒绝移动 → status=`ok_at_alt_path` + `reason=verified_at_alt_path`，`after.path` 记录实际路径，UI 给警告徽章「文件在临时位置，ComfyUI 不识别」。**`dest.filename` 在 manifest 层不可编辑**（schema 固定），浏览只是 verify 阶段的临时覆盖

### 5.7 manifest 加载入口（三个）

1. **选择本地文件**（文件对话框，默认过滤 `*.json` / `*.yaml`，支持拖拽到页面）
2. **从 URL 加载**（弹小窗接收 URL → `urllib.request` 下载到 cache → 校验 sha256）
3. **粘贴 JSON**（文本框，临时落到 `launcher/manifests/cache/pasted_<ts>.json`）

Cache 目录：`launcher/manifests/cache/<sha256-of-url-or-path>_<fetched-at-iso>.json`；reload 同 URL 命中本地 cache（HTTP `If-Modified-Since` 拿 304）。保留 30 天自动清理。

### 5.8 弹窗走共享设施（AGENTS.md 主题规范）

manifest URL 输入、sha256 不匹配详情、逐项确认等弹窗，用 `DialogHelper`（`ui_qt/widgets/dialog_helper.py`）+ `CustomConfirmDialog`（`ui_qt/widgets/custom_confirm_dialog.py`，构造接 `theme_manager=`）。

- 单按钮提示：`DialogHelper.show_info/show_warning/show_error`
- 是/否确认：`DialogHelper.show_confirmation`（返 bool）
- URL 输入框：`CustomConfirmDialog(..., show_input=True, input_placeholder="https://...")`
- sha256 详情：`CustomConfirmDialog` 多行 content 展示「期望 / 实算 / canonical 预览」

**禁止** `QtWidgets.QMessageBox.xxx(...)`。

---

## 6. 安全护栏

### 6.1 dirty tree 保护

- 跑 core 项前 `git status --porcelain` 非空 + `clean_untracked=false` → stash + pull
- stash 失败 → 报错 + 不执行，exit 9
- `clean_untracked=true` 走 `git clean -fdx`（破坏性，UP 显式 opt-in）

### 6.2 FROZEN_PKGS 黑名单

- `dependency` 项里的 `torch` / `torchvision` / `torchaudio` / `triton` / `xformers` / `numpy` 走 `skip_frozen=true`（默认）时被静默跳过 + 标 `skipped`，提示「V9 制作流程里这些是手动 wheel」
- GUI 临时勾掉「遵守黑名单」（针对特殊 manifest，不暴露给默认用户）

### 6.3 manifest 完整性

- `sha256` 字段填了 → 校验失败直接 exit 10（canonical 规则见 §2.1）
- 没填 → GUI 弹窗 / CLI stderr 警告，不阻止
- `manifest_version > 启动器支持的最高版本`（`SUPPORTED_MANIFEST_VERSION`）→ exit 10
- `package_target` 不匹配当前 env → 弹强警告，但仍允许放行

### 6.4 网络安全

- manifest URL **HTTPS 强制**（HTTP 直接 exit 11）
- model `links[].url` 接受 HTTP（网盘经常用 HTTP 短链）；UI 显示时给「非 HTTPS」徽章；`open_link` 本身不阻断（§3.1.2）
- 不下载可执行文件（item kind 只允许 4 类，其它 schema 一律 exit 10）
- **TLS 证书**：`load_source` 用 `urllib.request` 拉 manifest URL，默认 `verify=True`（严格校验证书）。UP 主自建服务器用自签证书会 SSL 错误 → exit 11。**Phase 1 实现默认严格校验；自签证书的 config 开关（`package_update.allow_self_signed`）留到 Phase 4 之后**（避免 Phase 1 引入降级安全面的风险）。在此期间 UP 主若用自签，建议改用本地文件分发或上正规证书

### 6.5 副作用范围与多环境隔离

- 所有动作只动当前 active env 的 comfyui_root（多 env 隔离）
- ComfyUI 在跑 + core 项 → 先 stop（`stop_running_first=true` 默认；finish 后 `restart_after=true` 默认）
- 模型落到 `external_libraries` 而非 Package 内

#### apply 的线程模型（**决定后续两节护栏的前提**）

`PackageUpdateService.apply()` 本身是**同步阻塞方法**（串行跑完所有 item 才返回），不自己开线程。但 GUI 不能在主线程调它（会冻结 UI 数分钟）—— **GUI 必须把 `apply()` 丢到工作线程**（`QThread` / `QRunnable` + worker pool），通过信号回主线程更新 UI。CLI 则直接在主线程同步调。

这个线程模型是下面两节护栏的前提：
- **§6.5.1 env 切换护栏**：因为 apply 在工作线程跑、UI 仍可点，用户可能尝试切环境 → 需护栏
- **§6.5.2 `_env_token` 防护**：因为 apply 异步、回调跨线程，用户可能在 apply 跑期间切环境 → 回调需 token 检查

> 若实现时图省事在主线程同步跑 apply（UI 假死），这两节护栏都不会被触发，但 UX 不可接受 —— Phase 3 实施时**必须**用工作线程。

#### 6.5.1 apply 期间阻止 env 切换（复用现有护栏 + 代码片段）

现有两个 env 切换入口都已挂钩 `app.has_active_background_tasks()`（`qt_app.py:3220-3243`）：
- 启动页下拉 `environment_selector.py:290-297`
- 设置页环境管理 `environment_manager_section.py:375-382`

`has_active_background_tasks()` 在 `registry.count_active() > 0` **或** `_update_running=True` 时返 True。**推荐做法（零改动护栏）**：apply 开始时注册 task，apply 完销毁 —— 两个切换入口的护栏自动生效，无需改 `has_active_background_tasks()`。

```python
# PackageUpdatePage._on_apply_clicked（主线程）
task_id = self.app._bg_task_registry.register(f"manifest:{manifest['id']}")
self._apply_task_id = task_id

worker = PackageApplyWorker(self.service, manifest, item_ids, manual_decisions)
# PackageApplyWorker 是 QObject + moveToThread 的标准套路；
# 用 pyqtSignal 把 on_item 回调 / 完成事件发回主线程
worker.item_progress.connect(self._on_item_progress)   # (item_id, status, payload)
worker.finished.connect(self._on_apply_done)           # (report)
worker.start()  # 内部 QThread.start()

def _on_item_progress(self, item_id, status, payload):
    # 更新 ProgressDialog + registry 单轴进度（模拟子步骤）
    cur, total = self._progress_of(item_id)
    self.app._bg_task_registry.update(
        self._apply_task_id,
        status=f"[{item_id}] {payload.get('label', status)}",
        progress=(cur, total),
    )

def _on_apply_done(self, report):
    has_failed = report["summary"]["failed"] > 0
    self.app._bg_task_registry.complete(self._apply_task_id, error=has_failed)
    self.app._bg_task_registry.remove(self._apply_task_id)
    self._apply_task_id = None
    self._render_report(report)   # 报告卡片 + 持久化（见 §6.6）
```

> `PackageApplyWorker.start()` 内部把 `service.apply(...)` 的同步调用包进 QThread；`on_item` 回调里 `emit` 信号（不直接碰 widget，符合 Qt 线程安全）。参照内核更新的 `qt_app.py:3456-3485` 进度推送写法。

**`PackageApplyWorker` 骨架**（Phase 3 要写的 class，避免实施者现查 Qt threading pattern 踩坑 —— 典型坑：worker 跨线程访问 widget 段错误；**更隐蔽的坑：slot 在自己的线程里调 `thread.wait()` 会死锁**）：

```python
class PackageApplyWorker(QtCore.QObject):
    """把同步的 PackageUpdateService.apply() 包成异步 worker。
    信号发回主线程，worker 内部绝不直接碰 widget。"""
    item_progress = QtCore.pyqtSignal(str, str, dict)  # (item_id, status, payload)
    finished = QtCore.pyqtSignal(dict)                 # (report)

    def __init__(self, service, manifest, item_ids, manual_decisions):
        super().__init__()
        self._service = service
        self._manifest = manifest
        self._item_ids = item_ids
        self._manual_decisions = manual_decisions
        self._thread = QtCore.QThread()
        self.moveToThread(self._thread)
        self._thread.started.connect(self._run)
        # ⚠️ 清理由信号链完成，不在 _run 的 finally 里调 thread.quit/wait（会死锁）：
        #   finished → thread.quit（退出事件循环）→ thread.finished → deleteLater（释放 worker）
        self.finished.connect(self._thread.quit)
        self._thread.finished.connect(self.deleteLater)

    def start(self):
        self._thread.start()

    @QtCore.pyqtSlot()
    def _run(self):
        """工作线程里跑 apply()。不做线程清理（那由主线程信号链完成）。"""
        try:
            report = self._service.apply(
                self._manifest,
                item_ids=self._item_ids,
                manual_decisions=self._manual_decisions,
                on_item=lambda iid, status, payload: self.item_progress.emit(iid, status, payload),
            )
            self.finished.emit(report)
        except Exception as e:
            self.finished.emit({"error": str(e), "summary": {"failed": 1}})
```

> 生命周期要点：① worker 必须被 page 持有（`self._worker = worker`），否则 Python 侧 GC 后 Qt 信号断；② **清理由信号链做**：`finished → thread.quit → thread.finished → deleteLater`，page 侧在 `_on_apply_done` 里只 `self._worker = None` 释放 Python 引用（Qt 侧 deleteLater 接管）；③ **不要在 `_run` 的 finally 里调 `thread.wait()`** —— slot 在自己的线程里跑，wait 等自己退出 = 死锁（v3.3a 修复的 bug）；④ `on_item` 回调是 lambda 包装 emit —— `apply()` 在工作线程调它，emit 跨线程投递到主线程队列，`_on_item_progress` 在主线程执行，安全碰 widget。

**registry 调用（含 failed → error=True，影响侧栏按钮警告）**：

```python
def _on_apply_done(self, report: dict):
    # has_failed 从 report 读（plan §4.3：仅 failed 触发，not_applicable/manual_required 不算）
    has_failed = report.get("summary", {}).get("failed", 0) > 0
    # ... env_token 防护 / 渲染 / 持久化 ...
    self._cleanup_worker(has_failed)  # ← 必须传 has_failed

def _cleanup_worker(self, has_failed: bool):
    if self._apply_task_id is not None:
        # error=has_failed 控制 registry.complete：True 时侧栏按钮显示警告
        self.app._bg_task_registry.complete(self._apply_task_id, error=has_failed)
        self.app._bg_task_registry.remove(self._apply_task_id)
        self._apply_task_id = None
    self._worker = None  # Qt 侧由 deleteLater 接管
```

> ⚠️ **不要在 `_cleanup_worker` 里自己算 `has_failed`**（v3.3a 修复的 bug：旧代码
> `self._worker is None or self._worker is not None` 恒为 True 但赋给 `error=False`，
> 导致所有任务都标成功，failed 任务侧栏不警告）。`has_failed` 必须由 caller 从
> `report["summary"]["failed"]` 读后传入。

#### 6.5.2 `_env_token` 竞态防护（**仅 GUI 异步路径需要**）

因为 apply 在工作线程跑、用户可能在 apply 期间切环境，完成回调跨线程回到主线程时，当前 active env 可能已经变了。回调若直接用「现在的 active env」渲染报告，会把 A env 的 apply 结果画到 B env 的页面上。

防护：apply 开始时捕获 `_env_token`，完成回调里比对（参照 `qt_app.py:2900-2910` version worker 的写法）：

```python
def _on_apply_clicked(self):
    self._apply_env_token = self.app._env_token   # 捕获
    # ... 启动 worker（见 6.5.1）

def _on_apply_done(self, report):
    if self.app._env_token != self._apply_env_token:
        # 用户在 apply 期间切了环境：不渲染到当前页面，只持久化 report + 提示
        self._persist_report(report)   # 仍写到 runs/<run_id>.json（见 §6.6）
        DialogHelper.show_info(
            self, "更新已完成",
            f"manifest {report['manifest_id']} 的应用已在后台完成，"
            f"但你切换了环境，结果未刷新到当前页面。可到「更新中心」历史记录查看。")
        return
    # token 一致，正常渲染
    self._render_report(report)
```

`_env_token` 在 `refresh_after_env_switch`（`qt_app.py:3159`）开头自增。CLI 同步路径不需要这个检查（apply 跑完才返回，期间没人能切环境）。

> **scope 提示**：本节防护仅针对「apply 完成回调渲染错 env」。apply **执行过程中**写错 env 的问题由 §6.5.1 的切换护栏兜底（用户根本切不了）。两者覆盖不同时间窗口，不重复。

#### 6.5.3 env 不匹配的前置检测（**apply 启动前短路，exit 9**）

manifest 的 `package_target.channel`（如 `"v9"`）描述本次更新适用的整合包系列。apply **启动前**先做一次 env 匹配检测 —— 不匹配时弹窗确认，用户拒绝则**直接 exit 9，不进 item 循环**（因此没有 item 会带 `env_mismatch_rejected` reason，§3.1.1 reason 枚举里这条已在 v3.3 删除）。

```python
# PackageUpdateService.apply() 入口（CLI 同步 / GUI worker 内部都先调这个）
def apply(self, manifest, item_ids=None, manual_decisions=None,
          on_item=None, auto_yes=False, confirm_env_mismatch=None):
    target = manifest.get("package_target", {})
    if target and not self._env_matches(target):
        # GUI: confirm_env_mismatch 是 page 传进来的回调（弹 DialogHelper.show_confirmation）
        # CLI: confirm_env_mismatch 默认 None；auto_yes=True 直接放行，否则视为拒绝（非交互）
        if auto_yes or (confirm_env_mismatch and confirm_env_mismatch(manifest)):
            pass  # 用户确认继续
        else:
            # 短路：返回空 items 的 report，调用方据 summary.exit_hint=9 退出
            return self._build_env_reject_report(manifest, exit_hint=9)
    # ... 进入 item 循环
```

`_env_matches(target)` 判定：
- 解析 `target.channel`（如 `"v9"`）与当前 env 的归属（粗略用 env name / comfyui_root 路径里的版本标识判，如 name 含 "V9" 或路径含 `V9-Large` → channel `"v9"`）
- `target.channel` 缺失 → 视为匹配（不阻断，向后兼容老 manifest）
- 匹配 → 放行；不匹配 → 进 confirm 流程

**CLI 行为**（`cmd_package.py`）：
- 默认非交互：env 不匹配 + 未传 `--auto-yes` → 视为拒绝，exit 9，stderr 提示「manifest 适用于 {channel}，当前 env 不匹配；加 --auto-yes 强制」
- `--auto-yes` → 跳过 prompt 直接放行

**GUI 行为**（`PackageUpdatePage`）：
- env 不匹配 → `DialogHelper.show_confirmation(parent, "环境不匹配", "此 manifest 适用于 {channel}，你当前是 {current}。是否继续？")`
- 用户点「否」→ 不启动 worker，页面显示「已取消：环境不匹配」，不写 run 记录（没跑就没 report）
- 用户点「是」→ `confirm_env_mismatch` 返 True，apply 继续

> **设计选择**：env 错是硬失败（exit 9），不做成 pseudo-item 计入 summary —— 否则外部监控（看 exit code）检测不到 env 问题。这覆盖了 §4.3 exit 9 表里「env 不匹配且用户拒绝」那一行。

### 6.6 回滚（best-effort）

- core 项 checkout 失败 → 自动 `git checkout -` 回退到原 HEAD
- **plugin 项 install 失败** → install 若因 git clone 半截失败，dir 可能已存在但不完整。回滚策略：**rmtree-only** —— 先 `shutil.rmtree(<不完整目录>, ignore_errors=True)` 再报错（调 `cm-cli uninstall` 在不完整 dir 上可能失败，rmtree 更稳）。**注意：cm-cli install 流程通常是 git clone → pip install plugin 的 requirements.txt，rmtree 只删 dir，不撤销 pip 装的依赖包。** 当前方案接受「pip 包不回收」限制 —— 因为拿不到 cm-cli 内部装的依赖清单（无留痕），盲目 `pip uninstall` 风险更高。report 里 failed item 的 `error` 字段补一句「部分 pip 依赖可能未回收，如需清理请手动 `pip uninstall`」。Phase 1 实施时**别自作多情加 pip uninstall 逻辑**
- dependency 项失败 → **不自动回滚**（复杂且容易引入新问题），仅在 report 标 failed + 建议用户手工 `pip install <原版本>`
- model 项失败 → 删未完成的临时文件（`<dest>.partial`）
- **不**做「快照整个 Package」—— 留给 UP 主的外部 backup 工具

### 6.7 report 持久化（**失败留痕，便于排查**）

`PackageUpdateService.apply()` 跑完后，**无论成功失败都自动写盘**：

- `launcher/manifests/runs/<run_id>.json` —— 完整 report（§3.1.1 schema + `env_id` 字段，标明跑在哪个环境）
- `launcher/manifests/runs/<run_id>.log` —— 仅 `failed` / `not_applicable` item 的 `log` 字段聚合（成功 item 不写日志，避免噪音）

`<run_id>` 形如 `2026-08-15T10-00-00-abc123`（ISO 时间 + 短 hash，保证同秒多次跑不冲突）。CLI 和 GUI 共用同一路径。

**CLI**：每次 `package apply` 跑完自动写；`--json` 仍照常打到 stdout（持久化是额外副作用，stdout 是机器接口）。stderr 追加一行人读提示：`[package] report written: launcher/manifests/runs/<run_id>.json`。

**GUI**：「导出 report.json」按钮 = 弹文件对话框，默认指向 `runs/<run_id>.json`，用户可另存。页面另加「历史记录」折叠区，列出最近 20 份 run（时间 / manifest_id / summary.ok vs failed），点击可重新渲染报告卡片。

清理策略：走 `runs_ttl_days`（默认 30 天，见 §7），独立于 `cache_ttl_days`。Phase 4 实施（~20 行：`_persist_report` + `_load_run_history`）。

---

## 7. 配置（launcher/config.json 改动）

新增段（manifest 路径在 UI 输入，不在 config 里）：

```json
{
  "package_update": {
    "respect_frozen_pkgs": true,
    "cache_dir": "launcher/manifests/cache/",
    "runs_dir": "launcher/manifests/runs/",
    "cache_ttl_days": 3,
    "runs_ttl_days": 30
  }
}
```

> TTL 分开管（语义不同，别合并）：
> - `cache_ttl_days`（默认 **3 天**）：URL 拉的 manifest 本地缓存，短 TTL —— 用户重读同一 URL 时希望尽快拿新版，不宜太长
> - `runs_ttl_days`（默认 **30 天**）：apply 历史报告，长 TTL —— 用户要查「上周跑挂的那次是为什么」，不宜太短
>
> `runs_dir` 存 apply 的 report 留痕（§6.7）。两条 TTL 各走自己的清理任务。

### 配置加载路径（**走 manager.py 默认值，不是 migrations.py**）

`config/migrations.py` 只处理 `environments` 迁移，没有「加新顶层段」的通用钩子。正确做法：

1. **`config/manager.py` 的默认 config 模板**带上 `"package_update": {...}` 默认段（含三个默认 key）
2. 读取处用 `self.config.get("package_update", {}).get("respect_frozen_pkgs", True)` 兜底（兼容没升级 config 的老用户）
3. **不动 `migrations.py`**（无历史数据需迁移）

> ⚠️ ConfigManager（GUI）和 HeadlessAppContext（CLI）两条加载路径都要带上默认段（模块 docstring `migrations.py:14-16` 强调两条路径都跑迁移，新段则需在两者的默认 config 里都加）。

不动的现有段：

- `integrations.comfyui_manager_git_path` 已经在 model 项执行时被 PluginService 复用
- `models.external_libraries` 已经在 model 项落盘时被 ModelPathService 复用
- `proxy_settings.*` 镜像设置已经走 `utils.net` 共享
- `version_preferences.*` GUI 默认值，不动

---

## 8. 分阶段落地

### Phase 1 — 后端骨架（2.5-3 天，**较 v2 上调**）

1. `core/package_manifest.py` —— schema dataclass + 校验（`sha256` canonical 规则见 §2.1；`SUPPORTED_MANIFEST_VERSION = 1` 常量；URL 拉取走 `urllib.request` 落到 `launcher/manifests/cache/`；HTTPS-only）
2. `services/package_update_service.py` —— load / validate / diff（含 satisfied 判定表 §3.1.1）/ apply / report
3. `services/model_service.py`（或 `manifest_model_service.py`） —— **只做** `resolve_dest`（含 `library_id="default"` 映射）/ `verify_manual` / `open_link`；无外部包依赖
4. `services/version_service.py` 扩展 `checkout_ref(mode, ref)`（注意 `min` 走 `_get_releases` 全量过滤）+ `list_releases(refresh)`
5. `services/dependency_policy.py` —— FROZEN_PKGS 抽出来共享
6. **`services/update_service.py` 重构**：抽 `_run_batch(selection, components)`，`perform_batch_update` 改为读 GUI var 调它，新增 `run_targeted_update` —— **含回归测试**
7. **`core/cli/exitcodes.py`**：新增 5/9/10/11 + webui 6/7/8 命名化（独立 PR 可并行）
8. 单元测试：`test_package_manifest.py` / `test_package_update_service.py` / `test_model_service.py` / `test_dependency_policy.py` / `test_checkout_ref.py`（覆盖 4 mode）

### Phase 2 — CLI 入口（0.5-1 天）

1. `core/cli/cmd_package.py` —— `package show / diff / apply`
2. `core/cli/parser.py` —— 加 `package` 子命令（`SUBCOMMANDS` `:22-33`）+ `_PACKAGE_EPILOG`
3. `core/cli/main.py` —— `_DISPATCH`（`:20-31`）注册
4. `cmd_webui.py` —— 6/7/8 改引用命名常量（若 Phase 1 的 exitcodes PR 未含）
5. `cli.md` 同步文档（package 段 + 退出码表补 5/9/10/11）
6. CLI 单测 `tests/unit/test_cmd_package.py`（mock 服务，验证 exit code / json schema）

### Phase 3 — GUI 页面（2-3 天）

1. `ui_qt/pages/package_update_page.py` —— 卡片式布局 + 每项勾选 + ProgressDialog 集成，继承 `BasePage`，实现 `update_theme`；**含 `PackageApplyWorker(QObject)` 骨架**（§6.5.1，把同步 `apply()` 包成异步 worker，pyqtSignal 回主线程）
2. `ui_qt/qt_app.py` `_setup_ui` —— **6 处改动**（见 §5.1）：import / `btns` / 实例化 / `_new_pages` / `content.addWidget` / `pages`
3. `ui_qt/qt_app.py` `refresh_after_env_switch`（`:3147-3218`）—— 加一个 try/except 刷新分支（参照现有 6 个分支，刷新本页的当前环境展示）
4. `ui_qt/qt_app.py` `_apply_theme`（`:1870-1880`）—— 无需改（自动遍历 `_new_pages`）
5. `ui_qt/widgets/dialog_helper.py` —— 加 `show_url_load_dialog` / `show_sha256_detail_dialog` / 非标准 category 警告（走 `CustomConfirmDialog`）
6. 手动 GUI 测（不改 test_e2e，避免风格回归）

### Phase 4 — 合成 manifest + 端到端 + report 持久化（1 天）

1. **造一份合成 manifest**（覆盖 V9 已知修复 + 1 个插件 + 1 个依赖 + 1 个模型），不依赖 UP 主外部交付
2. CLI `package apply <local>` + GUI 双跑，记录全 exit / report
3. **实现 report 持久化**（§6.7）：`_persist_report` 写 `runs/<run_id>.json` + `.log`；GUI 加「历史记录」折叠区列最近 20 份 run（~20 行）
4. 修真发现的小问题
5. UP 主真 manifest 到货后补跑（不阻塞排期）

### Phase 5 — 安全 / 回归（1 天）

1. fuzz 校验：畸形 manifest（缺字段、kind 非法、URL 不通、sha256 不对）→ exit 10
2. 跑现有 `tests/unit/` + `tests/integration/` 全套，确认没破现有 update / plugins / webui 路径（**特别是 `perform_batch_update` 重构后的内核更新流程**）
3. dirty tree 测试：人为 git status 脏 → 跑 core 项 → 确认 stash + 恢复
4. 多 env：active=env_default 时 apply 一份 v9 manifest → 确认拒绝（exit 9 + 提示 env 不匹配）
5. env 切换护栏：apply 跑到一半尝试切环境 → 确认被阻止（§6.5.1）
6. env_token 防护：apply 在工作线程跑期间手动改 active env → 完成回调走 `_env_token` 不一致分支，不渲染错 env（§6.5.2）

### Phase 6 — 文档 + 发布（半天）

1. `cli.md` 加 `package` 段（含 5/9/10/11 退出码）
2. `README.md` 加「更新中心」使用说明 + 截图 + **UP 主的 sha256 生成命令**
3. `AGENTS.md` 加一行 `package` 子命令清单 + 退出码说明
4. 发 launcher v1.1.0（含新页面）

**总计约 8-9.5 天**（v2 的 7-8 天 + 重构/回归 buffer）。

---

## 9. 测试策略

### 9.1 单元（必跑）

- `test_package_manifest.py`：schema 校验、sha256 canonical 校验（含中文 / 空白变体）、version 校验、未知 kind 拒绝、HTTPS 强制、`SUPPORTED_MANIFEST_VERSION` 边界
- `test_package_update_service.py`：mock 各 sub-service，验证编排逻辑（顺序、跳过、失败传播、取消）；**satisfied 判定表全覆盖**（4 kind × 满足/不满足）
- `test_model_service.py`：用临时目录测 `resolve_dest`（含 `library_id="default"` 映射、hex id 精确匹配、找不到 id 报错、**非标准 category 警告但不阻断**）/ `verify_manual` 各种状态（缺文件 / 错 sha256 / **不测 size，因 `size_hint` 不参与校验**）/ `open_link` 不抛
- `test_cmd_package.py`：mock 服务，验证 exit code（0/1/5/9/10/11）/ json schema
- `test_checkout_ref.py`：覆盖 exact / min（含「无候选」分支）/ channel / commit 四种 mode 的 stub；**min 模式必须用 `_get_releases` mock 验证全量过滤**
- `test_dependency_policy.py`：FROZEN_PKGS 过滤正确（含「不误带 frontend/templates」断言）
- `test_update_service_refactor.py`：**重构回归** —— 验证 `_run_batch` 抽出后 `perform_batch_update` 行为不变（传相同 selection，结果一致）

### 9.2 集成（必跑）

- 跑一份真实 manifest（用 V9.0.1 → V9.0.2 那份）在临时 Package 副本上，验证全报告
- 跑一份失败 manifest（带不存在的 huggingface repo / 不通的链接），验证 exit 5 + item.status=failed
- 跑一份全是 `manual_required`（model 项都没勾）的 manifest，验证 **exit 0**（不是 5）
- 跑 plugin `force=true` 对 CNR 非 git 仓库，验证标 `not_applicable` + `reason=not_git_for_force`，且 **exit 0**；同时验证成功路径 force 的 `error` 字段为 None（detail 进 log，不进 error）
- 跑 model「浏览...」指向非 manifest 路径 + 拒绝移动，验证 status=`ok_at_alt_path` + `reason=verified_at_alt_path` + `after.path` 记录实际路径，且 **exit 0**
- 跑 dirty tree + 缺 clean_untracked，确认 exit 9
- 跑 env 不匹配（manifest channel=v9，当前 env 是 v8）+ GUI 点「否」/ CLI 无 `--auto-yes` → 确认 exit 9 + 不写 run 记录（§6.5.3）
- 跑 env 不匹配 + `--auto-yes` / GUI 点「是」→ 确认放行，正常进 item 循环

### 9.3 手工 GUI（在干净 V9 env 上跑）

- 加载本地 manifest → 勾选 → 跑 → 看报告
- 测 model 项「我已手动下载」勾选 + verify 各种状态（就位 / 缺文件 / sha256 不符）；测 `size_hint` 与实际偏差 >50% 时给黄色软提示但不阻塞
- 测 model「浏览...」按钮：指向非 manifest 路径 → verify 通过 → 点「是移动」→ status=`ok`；点「不移动」→ status=`ok_at_alt_path` + 警告徽章
- 测 dirty tree 提示 / FROZEN_PKGS 跳过（验证 `skipped` 徽章显示 `reason=frozen_pkg`）
- 测 plugin `force=true` 对非 git 仓库 → 验证标 `not_applicable` + `reason=not_git_for_force`（不是混进 `skipped`）；测 git 仓库 force 成功时 report 的 error 字段为空（不把「已是最新」塞进 error）
- 测非标准 category 警告弹窗（如 `lora`）→ 确认能继续落盘
- 测从 URL 加载（mock 一个本地 httpserver 返 manifest）
- 测 sha256 不匹配时的「期望/实算/canonical 预览」详情弹窗
- 测主题切换（深/浅）页面颜色不冻结
- 测 apply 跑到一半切环境被阻止（§6.5.1 护栏）
- 测 apply 跑完期间切环境 → 完成回调走 `_env_token` 分支，提示「结果未刷新」（§6.5.2）
- 测 env 不匹配前置弹窗：加载 channel=v9 manifest 到 v8 env → 弹「环境不匹配」→ 点「否」不启动 worker / 点「是」继续（§6.5.3）
- 测 report 持久化：跑完查 `launcher/manifests/runs/<run_id>.json` + `.log` 存在；「历史记录」区能列出并重渲染

---

## 10. 已知风险 / 待决问题

### 10.1 model 落点

V9 制作流程目前还没彻底统一「Package 不带模型」（build_process_v9.md §7「Package 体积优化」里 UP 拍板「UP 后续处理」）。本方案默认 model 落 `external_libraries`，等同 V8 模型库策略；如果 UP 后续决定「落 Package 内」，manifest 里 `dest.library_id=null` + `dest.category="<path>"` 也兼容。

### 10.2 「逐项确认」的 UX 灵活性

当前设计 = 全部加载 → 用户勾选 → 串行跑。「重跑失败项」按钮支持，单独取消 / 重跑单项放在 Phase 3 后期。

### 10.3 启动器自身更新与「manifest 更新」不冲突

`LauncherUpdateService` 走 gitee 上的 launcher 自己的 exe + sha256；`PackageUpdateService` 走本地文件 / 用户粘贴的 URL。两条独立路径，UP 可以同一天发「启动器 v1.1.0」+「整合包 v9.0.1→v9.0.2 manifest」。

### 10.4 跨 env 的 apply

CLI `--env ENV_ID` 一次性指定；不写回 config。GUI 走 active env。多 env 时不允许 manifest「同时改多个 env」，单次 apply 只动一个 env。

### 10.5 实施前需 UP 主确认的问题

1. **plugin 项 spec 多值**：要不要支持「同时多个插件」逗号分隔？默认单值
2. **GUI 入口名**：「更新中心」/「增量更新」/「V9 增量补丁」三选一
3. **manifest 分发渠道**：UP 主自己的发布流程；跟启动器无关（启动器只负责读取）
4. **「粘贴 JSON」UI 要不要**：建议保留，应对「UP 没给 URL 只贴了全文在公众号」的场景
5. **「重新跑 model verify」按钮**：跑完整次 apply 后用户补下完模型时，是否给个「重新校验模型项」按钮（不重跑 core / plugin / dep）
6. ~~`perform_batch_update` 重构风险接受度~~ —— **已接受**（v3.2 薄包装方案落地，§3.2 已定）；Phase 1 含回归测试，无需再问

---

## 11. 一句话总览

> UP 主手写一份 JSON 描述 4 类变更（核心 / 插件 / 模型 / 依赖），通过本地文件或 HTTPS URL 加载到启动器；启动器在 GUI「更新中心」页展示「当前环境 / 需求 / 即将执行」三栏对比，让用户逐项勾选确认后串行执行（GUI 用 `PackageApplyWorker` 丢工作线程跑，主线程不冻结）；模型项不走下载，只给链接列表（接受 http/https 网盘短链）+ 校验文件存在（`size_hint` 仅展示不校验），「浏览...」覆盖路径时区分 `ok` / `ok_at_alt_path` 两种就位状态；apply 启动前做 env 不匹配前置检测（不匹配弹窗，拒绝直接 exit 9 短路）；FROZEN_PKGS 黑名单 / dirty tree 自动 stash / sha256 校验（canonical JSON 规则统一，`utf-8-sig` 读 BOM）/ 多 env 隔离 + env 切换护栏（注册到 registry 自动生效）+ `_env_token` 竞态防护（异步回调渲染）五项护栏保底；plugin 归一化覆盖三套返回契约（lifecycle / do_update / force_update_selected），force 成功路径 detail 进 log 不进 error；report 自动持久化到 `runs/<run_id>.json` 失败留痕（`runs_ttl_days` 与 `cache_ttl_days` 分开）；exit 5 仅由 `failed` 触发（`ok_at_alt_path`/`not_applicable`/`manual_required` 不算失败），退出码用全新 5/9/10/11 段避开 webui 的 6/7/8；分 6 个 phase 落地，含 `perform_batch_update` 薄包装重构回归，总计约 8-9.5 天。
