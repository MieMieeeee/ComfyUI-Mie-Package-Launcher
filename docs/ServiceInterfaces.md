# View / Service 分层架构接口说明

## 总览
- View 层：`ui/*` 与入口 `comfyui_launcher_enhanced.py`，负责界面展示与交互绑定
- Service 层：`services/*` + `core/*` + `config/*` + `utils/*`，负责业务逻辑与数据操作

## 设计理念
- 明确边界：View 只做展示与交互，业务逻辑全部进入 Service
- 依赖注入：通过 `ServiceContainer` 构造服务，减少模块间耦合
- 可测试性：Service 可单测覆盖到异常路径；View 通过集成测试验证交互
- 向后兼容：入口方法与属性保持稳定，对外行为不变

## 接口
### IProcessService
- `toggle()`: 启动/停止切换
- `start()`: 显式启动
- `stop() -> bool`: 停止并返回是否成功
- `refresh_status()`: 刷新运行状态
- `monitor()`: 监控循环

### IVersionService
- `refresh(scope: str = "all")`: 按 scope 刷新版本信息（all/core_only/front_only/template_only/selected）

### IConfigService
- `load() -> dict`: 读取配置
- `save(data: dict | None)`: 保存配置
- `get(key_path: str, default)`: 点分隔键读取
- `set(key_path: str, value)`: 点分隔键写入
- `update_launch_options(**kwargs)`: 更新启动选项
- `update_proxy_settings(**kwargs)`: 更新代理设置
- `get_config() -> dict`: 获取完整当前配置

### IPackageService（预留）
- `show_version(name: str) -> str | None`: 查询包版本
- `install(name: str, index_url?: str, upgrade?: bool) -> dict`: 安装/更新包

## 依赖注入
- 容器：`services/di.py: ServiceContainer.from_app(app)`
- 提供：`process`、`version`、`config`、`update`、`git`、`network`、`runtime` 等服务实例
- 入口集成：`self.services = ServiceContainer.from_app(self)`

## 测试策略
- Service 层：单元测试与契约测试（接口行为与异常路径），目标覆盖率 ≥ 90%
- View 层：集成测试与 UI 测试（通过 mock 交互与回调验证），保证交互正确
- 层间通信：针对 `IProcessService`、`IVersionService`、`IConfigService` 编写契约测试确保入参与返回值一致

## 服务职责与迁移映射
- UpdateService：`update_frontend`、`update_templates`、`perform_batch_update`
- GitService：`resolve_git`、`apply_to_manager`
- NetworkService：`apply_pip_proxy_settings`
- RuntimeService：`pre_start_up`

## 验证与指标
- 完整性：批量更新/前端/模板库/运行时准备保持行为一致
- 性能：子进程启动/探测/终止与日志不回归
- 覆盖率：Service 层单元测试覆盖异常路径与镜像选择分支

## 兼容性与扩展
- 入口维持已有属性与方法（如 `process_manager`、`get_version_info` 等），对外接口不变
- 新增服务容器不影响现有调用；View 可以逐步迁移到服务接口
- 性能：业务逻辑与子进程管理保持原实现，拆分不引入额外开销

### IModelPathService (多库外置模型库)

多库模型補充原 ModelPathService。保证已发布版本上的单库 yaml (`comfyui:` / `ComfyUI:`)可以被保留并炸出后发布。

- `get_libraries() -> list[dict]`: 返回 `config.models.external_libraries`；每项含 `id / name / base_path / enabled / is_default`。
- `add_library(base_path: str, name=None) -> dict`: 注册新库。若 `base_path` 已存在则返回现有项。
- `remove_library(library_id: str) -> bool`: 移除指定库。底部默认被移除时自动升级剩余项为默认。
- `set_default_library(library_id: str) -> bool`: 作为默认亮；清除其他项的 `is_default` 标志。
- `enable_library(library_id: str, enabled: bool = True) -> bool`: 切换启用状态；默认库被禁用后 `is_default` 保持不变。
- `update_library(library_id: str, **fields) -> bool`: 修改名称等可写字段；`id` 字段不允许覆盖。
- `find_library_by_base_path(base_path: str) -> dict | None`: 按 `base_path` 查找现有库。
- `update_mapping(base_path: str) -> bool`: 向合同调用者提供的旧接口，迁移后路由到 `apply_libraries()`。
- `apply_libraries() -> bool`: 将全部启用库写入 yaml，使用 `mie_launcher_<id>:` 顶层名；保留所有非启动器管理的 yaml 项（如 `a1111:`）。
- `migrate_legacy_yaml() -> {migrated: bool, count: int}`: 一次性升级点：从 `comfyui:` / `ComfyUI:` / `mie_external:` 担起一条库到 `external_libraries[0]`、重命名顶层名为 `mie_launcher_<id>`、原文件备份到 `extra_model_paths.yaml.user_bak`。
- `load_yaml_data() -> dict`: 原始 yaml 读取，仅用于诊断。
- `get_external_path() -> str`: 返回默认库的 `base_path`；若 `external_libraries` 为空则降级到 yaml 原读取（幂等返回空串）。
- `is_disabled() -> bool`: 全功能禁用判定：全局 `disable_external=True` 或者库全部禁用。

数据示例：

```json
{
  "models": {
    "disable_external": false,
    "external_libraries": [
      {"id": "abc12345", "name": "SDXL", "base_path": "E:/Models/SDXL",
       "enabled": true, "is_default": true},
      {"id": "def67890", "name": "Flux",  "base_path": "F:/Models/Flux",
       "enabled": false, "is_default": false}
    ]
  }
}
```

迁移路径：

1. 启动时（GUI `qt_app.py`）或 CLI `dispatch` 中调用 `migrate_legacy_yaml()` 一次。
2. 调用 `add_library` / `remove_library` / `enable_library` / `set_default_library` 后，调用 `apply_libraries()` 持久化到 yaml。
3. 用 `models_page.refresh_from_config()` 同步 UI 表。
