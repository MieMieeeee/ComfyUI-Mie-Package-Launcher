# LaunchPage Decomposition Analysis

## File
- `ui_qt/pages/launch_page.py` (1237+ lines)
- `ui_qt/pages/base_page.py` (34 lines) — parent class

---

## Section Boundaries

### 1. LaunchControls (启动控制区块)
| Attribute | Value |
|-----------|-------|
| UI block | Lines 52–124 (`_setup_ui` zone) |
| Builder method | `_build_launch_controls()` → Lines 162–428 |
| Group box | `form_group = QtWidgets.QGroupBox("启动控制")` |

**Components:**
- 运行模式 (GPU/CPU radio) — row 0
- 端口号 + 局域网访问 — row 0 col 2
- 显存策略 + 注意力优化 — row 1
- 自动打开浏览器 + 选择浏览器 — row 2
- 复选框 (FP16/API/插件DEBUG) — row 3
- 额外选项 — row 4

---

### 2. Environment (环境配置区块)
| Attribute | Value |
|-----------|-------|
| UI block | Lines 125–133 (`_setup_ui` zone) |
| Builder method | `_build_environment_config()` → Lines 430–718 |
| Group box | `env_group = QtWidgets.QGroupBox("环境配置")` |

**Components:**
- HF 镜像源 (combo + entry) — row 0
- GitHub 代理 (combo + entry) — row 1
- PyPI 代理 (combo + entry) — row 2
- Divider — row 3
- 根目录 (readonly + 选取按钮) — row 4
- Python 路径 (readonly + 选取按钮) — row 5

---

### 3. Version (版本与更新区块)
| Attribute | Value |
|-----------|-------|
| UI block | Lines 134–146 (`_setup_ui` zone) |
| Builder method | `_build_version_section()` → Lines 720–853 |
| Group box | `ver_group = QtWidgets.QGroupBox("版本与更新")` |

**Components:**
- Version grid (7 items: 内核/前端/模板库/Python/Torch/Git/显卡驱动) — lines 735–756
- Upgrade options row: 内核升级策略 + 仅更新稳定版 + 同时更新依赖库 + 超时选择器 + 刷新按钮 + 更新按钮 — lines 758–853

**Helper:**
- `_create_version_item()` → Lines 905–954 (creates each version card)
- `_on_update_clicked()` → Lines 855–879
- `_on_refresh_clicked()` → Lines 881–903

---

### 4. QuickDir (快捷目录区块)
| Attribute | Value |
|-----------|-------|
| UI block | Lines 141–146 (`_setup_ui` zone) |
| Builder method | `_build_quick_dir()` → Lines 956–982 |
| Group box | `quick_group = QtWidgets.QGroupBox("快捷目录")` |

**Components:**
- 7 buttons: 根目录/ComfyUI日志/启动器日志/输出目录/输入目录/插件目录/模型目录

**Open handlers:**
- `_open_comfyui_log()` → 984–998
- `_open_launcher_log()` → 1000–1009
- `_open_root_dir()` → 1135–1137
- `_open_output_dir()` → 1143–1148
- `_open_input_dir()` → 1150–1155
- `_open_nodes_dir()` → 1157–1162
- `_open_models_dir()` → 1164–1169
- `_open_path()` → 1171–1180 (common)

---

## Shared / Utility Methods
| Method | Lines | Purpose |
|--------|-------|---------|
| `_on_toggle_launch()` | 1026–1029 | Toggle ComfyUI process |
| `_save_config()` | 1015–1021 | Persist app config |
| `_get_primary_button_style()` | 1011–1013 | Theme button style |
| `_get_danger_button_style()` | 1023–1024 | Danger button style |
| `_choose_root()` | 1031–1106 | Select ComfyUI root dir |
| `_choose_python()` | 1108–1133 | Select Python executable |
| `_update_button_state()` | 28–36 | Compatibility placeholder |
| `_on_theme_changed()` | 1182–1184 | Theme change callback |
| `update_theme()` | 1186–1237+ | Full theme refresh |

---

## Dependencies

### External
- `PyQt5.QtWidgets`, `QtCore`, `QtGui`
- `pathlib.Path`
- `ui_qt.theme_styles.ThemeStyles`
- `ui_qt.widgets.custom.NoWheelComboBox`

### App Services
| Service | Usage |
|---------|-------|
| `app.services.process` | `refresh_status()`, `toggle()` |
| `app.services.config` | `save()` |
| `app.config` | paths/compute_mode/port/listen_all/vram_mode/attention_mode/browser_open_mode/custom_browser_path/use_fast_mode/disable_api_nodes/disable_all_custom_nodes/extra_launch_args |
| `app.version_manager` | proxy_mode_var, proxy_url_var, proxy_mode_ui_var |
| `app.compute_mode`, `app.custom_port`, `app.listen_all` | Settings vars with `.get()`/`.set()` |
| `app.stable_only_var`, `app.auto_update_deps_var` | Version update options |
| `app.update_timeout_var` | Update timeout |

### Base Class
- `BasePage` — provides `update_theme()`, `_on_theme_changed()`, `_apply_initial_theme()`

---

## UI Layout Structure (from `_setup_ui`)
```
layout (QVBoxLayout)
├── top_row (QHBoxLayout) — 启动控制区块 + 右侧按钮容器
│   ├── form_group (QGroupBox "启动控制") — GridLayout
│   └── right_container — 启动大按钮 + 常见问题按钮
├── env_group (QGroupBox "环境配置")
├── ver_group (QGroupBox "版本与更新")
├── quick_group (QGroupBox "快捷目录")
└── stretch
```

---

## Candidate Mixins for Extraction

| Mixin | Methods | State |
|-------|---------|-------|
| `HasLaunchControls` | `_build_launch_controls`, `_on_toggle_launch` | `btn_toggle`, `btn_faq` |
| `HasEnvironmentConfig` | `_build_environment_config`, `_choose_root`, `_choose_python` | `_root_show`, `_py_show` |
| `HasVersionSection` | `_build_version_section`, `_create_version_item`, `_on_update_clicked`, `_on_refresh_clicked` | `_update_btn`, `_refresh_btn`, `_version_title_refs`, `_version_value_refs` |
| `HasQuickDir` | `_build_quick_dir`, `_open_*` (7 handlers) | `_quick_dir_buttons` |
| `HasThemeUpdates` | `update_theme` (partial) | `_styled_widgets` |
