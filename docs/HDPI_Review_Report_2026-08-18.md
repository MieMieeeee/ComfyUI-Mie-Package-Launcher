# ComfyUI 启动器 — HDPI / 分辨率变化适配审查报告（v1.1 — 修订版）

> 审查日期：2026-08-18（首次发布）/ 2026-08-18（v1.1 修订）
> 审查范围：`ui_qt/` 全模块 + 核心缩放模块 + 全局 Qt 设置
> 审查目标：评估项目在高 DPI 屏幕、多显示器切换、系统缩放百分比变化等场景下的适配完整性

---

## 〇、开工前验证清单（MUST DO FIRST）

以下是报告中最容易因行号漂移 / 上下文假设错误而在施工时产生**二次 bug** 的 3 个高危声明。**每次 PR 开工前按条目重新确认，不要直接信本报告。**

### 0-1 IconButton `self._size` 是否为未缩放 base（最危险：双重缩放）

✅ **2026-08-18 已核实安全**：

```python
# [buttons.py#L168-L172](file:///f:/ComfyUI-Mie-Package-Launcher/ui_qt/widgets/buttons.py#L168-L172)
def __init__(self, text, theme_styles, size: int = 24, parent=None):
    ...
    self._size = size                              # ← 存的是 24，原始值
    self.setFixedSize(theme_styles._px(size), ...) # ← 只有 setFixedSize 这一行套了 _px
```

- `_apply_style()` 里 `_pt(self._size // 2)` 用的是**未缩放**的 `_size`，然后 `_pt()` 再套一次缩放 — 和我们的修法语义一致。
- **结论**：建议修法 `setFixedSize(_px(self._size), _px(self._size))` 不会双重缩放。安全。

### 0-2 CircleAvatar 当前 API 契约在调用方之间**已不一致**（不是「未来 breaking」，是「当前就有两种调用方式」）

⚠️ **2026-08-18 已核实：当前 2 个调用方契约对立**：

| 调用方 | 传参写法 | 含义 | 现状是否按 DPI 缩放？ |
|---|---|---|---|
| [sidebar.py#L79](file:///f:/ComfyUI-Mie-Package-Launcher/ui_qt/components/sidebar.py#L79) | `CircleAvatar(..., size=60)` | 调用方传**未缩放**原始值 60，期望组件内部 `_px` → ❌ **当前没缩**，150% DPI 下 sidebar 头像停留在 60px（bug 已存在） |
| [cards.py#L49](file:///f:/ComfyUI-Mie-Package-Launcher/ui_qt/widgets/cards.py#L49) | `CircleAvatar(..., size=self.theme_styles._px(self.avatar_size))` | 调用方**先 _px 再传** → ✅ 缩放了，但 base 值在组件外部丢失，没法在 `update_theme` 里二次重算 |
| 单元测试 [test_circle_avatar_paint.py#L37](file:///f:/ComfyUI-Mie-Package-Launcher/tests/unit/test_circle_avatar_paint.py#L37) | `size=size` | 测 paint，尺寸随意 |

- **结论**：修法不是「平滑迁移」，而是**统一契约**。必须一次性改 3 个文件：
  1. CircleAvatar 自身：改构造函数接受**未缩放** `base_size`，内部存 `_base_size` 并在首次构造和 `update_theme` 都 `_px`。
  2. sidebar.py 调用方：保持 `size=60` 不变（天然符合新契约），但**修完后 sidebar 头像会突然从 bug 的 60px 跳回正确的缩放后尺寸**，视觉上是修复而非破坏。
  3. cards.py 调用方：从 `_px(self.avatar_size)` 改回只传 `self.avatar_size`（去掉外部那层 `_px`）。
  4. 测试：无变化。

### 0-3 qt_app.py 跨屏逻辑的大段代码范围

[qt_app.py#L4097-L4276](file:///f:/ComfyUI-Mie-Package-Launcher/ui_qt/qt_app.py#L4097-L4276) 横跨 180 行，包含 `showEvent` 监听接入、`_apply_screen_change`、`_apply_theme`、`_resize_for_scale`、`_apply_scaled_fixed_sizes` 5 个函数。施工时整体浏览一次再动。

---

## 一、整体评估（修正：用具体计数，拒绝模糊星级分母）

| 维度 | 覆盖计数 | 说明 |
|---|---|---|
| 全局 Qt High DPI 基础 | 3/3 全齐 | AA_EnableHighDpiScaling / AA_UseHighDpiPixmaps / PassThrough rounding，`hasattr` 全守护 |
| 核心缩放数学与管道 | 4/4 全齐 | `ui_scaling.py` 边界、吸附、DPI 推断、用户 override；`ThemeManager` 防抖 + 单管道；`_pt/_px` 统一换算 |
| 多屏幕跨屏切换机制 | 5/5 全齐 | 250ms 防抖、backing store 无条件重建、两条尺寸路径、同比窗口缩放、安全边距 clip |
| 用户可覆盖 UI scale + 即时预览 | 3/3 全齐 | 下拉四档、setUpdatesEnabled 包裹、即时写回 config |
| **共享基础组件 setFixed* 重算率** | **1/6 ≈ 17%** | 6 个组件（ThemeButton/LinkButton/IconButton/InfoCard/CircleAvatar/Sidebar）中仅 Sidebar 外层 scroll 在 qt_app._apply_scaled_fixed_sizes 里有兜底；本体 setFixed* 全漏 |
| **页面 / 子 section 完整实现率** | **5/14 ≈ 36%** | 实现完整的 5 个：plugins_page、environment_section、launch_controls_section、version_section、plugin_search_dialog；待修的 9 个：launch_page / webui_page / models_page / version_page / about_launcher / about_comfyui / _ScaleRow / env_manager_section / env_selector |
| **Dialog 系列主题监听率** | **1/6 ≈ 17%** | 仅 PluginSearchDialog；UpdateDialog / ProgressDialog / CustomConfirmDialog / AnnouncementDialog / BackgroundTaskPanel 全漏 |
| **单元测试覆盖：组件级 update_theme 后 setFixed* 重算** | **0/3 类缺失** | 现有 6 个测试锁的是「框架构造时正确 / 不做错误操作」；没有「改 scale 后尺寸跟随」的断言 → 回归高风险 |

**结论：架构层面 3 大支柱（Qt 属性、核心数学、跨屏管道）100% 完备可依赖；执行层覆盖计数约 25%。用户改 ui_scale 或跨屏时，QSS 字号缩了但 `setFixed*` / `setMinimum*` 的局部容器尺寸停在构造时 scale，出现半缩放视觉错位。**

---

## 二、已实现且完整的部分（无需改动）

### 2.1 全局 Qt High DPI 三件套

在 [comfyui_launcher_pyqt.py#L204-L231](file:///f:/ComfyUI-Mie-Package-Launcher/comfyui_launcher_pyqt.py#L204-L231) 的 `_configure_qt_highdpi()` 中：

1. **`AA_EnableHighDpiScaling`**：Qt 自动按系统缩放放大坐标
2. **`AA_UseHighDpiPixmaps`**：QIcon/QPixmap 走物理像素渲染（防止手动 `setDevicePixelRatio` 出只画 1/4 的 bug，见 CircleAvatar paintEvent 注释）
3. **`setHighDpiScaleFactorRoundingPolicy(PassThrough)`**：避免 Windows 150% 被某些 Qt 5.14 默认 Floor 截断为 100%

全部 `hasattr` 守护；两条构造路径（`launch_gui` 正常启动 + `_show_single_instance_dialog` 单实例提示）都会调用。

### 2.2 核心缩放模块（单一真理源）

[core/ui_scaling.py](file:///f:/ComfyUI-Mie-Package-Launcher/core/ui_scaling.py) 纯函数模块：

| 项 | 作用 |
|---|---|
| `MIN_SCALE=0.75` / `MAX_SCALE=1.25` | clamp 边界；`ThemeStyles` / `ThemeManager` 共用此处常量 |
| `snap_scale(step=0.05)` | 吸附到 5% 步长，消除浮点抖动 |
| `compute_scale_from_dpi(user_override, dpi)` | 优先级：user 覆盖 > DPI 推断；非法 override 回退 DPI（不是锁死 1.0） |
| `resolve_ui_scale(config, dpi)` | 封装 `config["ui_settings"]["ui_scale"]` 读取；空串 / `None` → 自动跟随 DPI |

### 2.3 主题 / 缩放统一管道

[ThemeManager](file:///f:/ComfyUI-Mie-Package-Launcher/ui_qt/theme_manager.py#L33-L99)：

- `set_theme()` 与 `set_scale()` 复用同一套监听器广播
- `abs(v - self._scale) < 1e-3` 防抖，无变化早退

[ThemeStyles._pt / _px](file:///f:/ComfyUI-Mie-Package-Launcher/ui_qt/theme_styles.py#L145-L161)：所有 QSS 字号/像素走这两个 helper；下限 6pt / 1px。

### 2.4 多屏幕跨屏切换（有工程经验沉淀）

[qt_app.py#L4097-L4276](file:///f:/ComfyUI-Mie-Package-Launcher/ui_qt/qt_app.py#L4097-L4276)：

- **防抖**：`showEvent` 接 `QWindow.screenChanged` → 250ms 单次 `QTimer`，拖跨屏连续触发只重算一次
- **Backing store 无条件重建**：即使 `new_scale == old_scale`，仍 `wh.create()` / 1px resize nudge。专门修掉「休眠唤醒 / 显示器电源态变化后，4K@150% Nuitka exe 只画左上 1/4」的已知坑（见 `_apply_screen_change` docstring）
- **尺寸分两条路径**：`_apply_theme` 重刷 QSS；`_apply_scaled_fixed_sizes` 单独重算侧边栏 scroll 宽、折叠按钮、主窗口 minimumSize（QSS 管不到 `setFixed*` 的像素）
- **同比窗口缩放**：`_resize_for_scale(new, old)` 按 new/old 比例缩放整窗，并 clip 到 `availableGeometry - 安全边距`；反转了「只放大不缩小」的历史 bug

### 2.5 用户可覆盖 + 即时预览

[system_settings_page.py#L401-L461](file:///f:/ComfyUI-Mie-Package-Launcher/ui_qt/pages/system_settings_page.py#L401-L461) `_on_scale_changed`：

- 下拉 4 档：自动（跟随 DPI）/ 75% / 100% / 125%
- `setUpdatesEnabled(False/True)` 包裹，同时调 `set_scale` + `_apply_theme` + `_apply_scaled_fixed_sizes` + `_resize_for_scale`，调用链和 `_apply_screen_change` 一致
- 写回 `config["ui_settings"]["ui_scale"]`

### 2.6 现有测试矩阵

| 文件 | 覆盖点 |
|---|---|
| [test_highdpi_policy.py](file:///f:/ComfyUI-Mie-Package-Launcher/tests/unit/test_highdpi_policy.py) | 源码级断言三件套调用存在 |
| [test_circle_avatar_paint.py](file:///f:/ComfyUI-Mie-Package-Launcher/tests/unit/test_circle_avatar_paint.py) | 禁止 paintEvent 手动乘 DPR / `setDevicePixelRatio` |
| [test_launch_section_dpi_resize.py](file:///f:/ComfyUI-Mie-Package-Launcher/tests/unit/test_launch_section_dpi_resize.py) | 首页 3 个 section 的 `_dpi_sized_widgets` 注册表、`_reapply_dpi_sizes` 正确性、`_resize_for_scale` 比例 |
| [test_screen_change_scaling.py](file:///f:/ComfyUI-Mie-Package-Launcher/tests/unit/test_screen_change_scaling.py) | screenChanged 防抖、backing store 刷新、`_apply_scaled_fixed_sizes` 幂等 |
| [test_gui_dpi_e2e.py](file:///f:/ComfyUI-Mie-Package-Launcher/tests/e2e/test_gui_dpi_e2e.py) | `QT_SCALE_FACTOR=1.5` 下真实启动 GUI，宽限期后断言仍存活（构造不崩） |
| [test_compiled_exe_boot.py](file:///f:/ComfyUI-Mie-Package-Launcher/tests/e2e/test_compiled_exe_boot.py) | Nuitka 编译版同路径覆盖，防 compiled-mode-only DPI 回归 |

> ⚠️ **缺口**：现有测试全是「构造时正确」+「不误操作」。**没有**「改 scale→断言尺寸跟随」的正向回归锁。P0 修复之后必须补（见第五节）。

---

## 三、发现的不完整部分

### 🟡 P2-1（第一个施工 PR：架构升基类。P0 依赖它，避免 9 份复制又清一次）

`_dpi_sized_widgets` 模式目前在 5 处**拷贝粘贴**：plugins_page.py / plugin_search_dialog.py / environment_section.py / launch_controls_section.py / version_section.py。其余 9 处要从零写，如果先写完 9 份再重构 = 9 份临时实现 + 二次 churn。

**修正排期：P2-1 第一个做**，然后 P0 页面直接用基类提供的 helper。

#### 3.1 BasePage 内置 `_dpi_sized_widgets` + `_reapply_dpi_sizes`（v1.1：用 setter-name 分发 + 不吞异常）

**禁止**字符串 `kind` 分发 + 裸 `except Exception: pass`（拼错 typo 不报错 → 静默漏重算）。用**元组 `(widget, setter_name, base)` + `getattr`**：自我描述、调用点即文档、typo 立刻 `AttributeError`，P0 期间的 typo 当场炸。

在 [BasePage](file:///f:/ComfyUI-Mie-Package-Launcher/ui_qt/pages/base_page.py) 中：

```python
from PyQt5 import QtWidgets

class BasePage(QtWidgets.QWidget):
    def __init__(self, parent=None, theme_manager=None):
        super().__init__(parent)
        ...
        # 子类在 __init__ 里向这个列表追加。空列表安全，_reapply_dpi_sizes 什么都不做。
        self._dpi_sized_widgets: list[tuple[QtWidgets.QWidget, str, int | tuple[int, int]]] = []

    def _reapply_dpi_sizes(self):
        """用 setter 名分发。setter_name 必须是 widget 上已存在的方法，否则 AttributeError。"""
        _px = self.theme_manager.styles._px
        for widget, setter_name, base in self._dpi_sized_widgets:
            setter = getattr(widget, setter_name)          # 找不到直接炸 typo
            if isinstance(base, tuple):
                setter(_px(base[0]), _px(base[1]))          # setFixedSize(w,h)
            else:
                setter(_px(base))                           # setFixedWidth(w) / setMinimumHeight(h) / ...

    def update_theme(self, theme_styles=None):
        """子类覆盖做 QSS 重算后，必须 super() 调用以重跑尺寸重算。"""
        # 基础 content 样式 ...
        self._reapply_dpi_sizes()
```

**合法的 `setter_name`（和 Qt 原生方法一一对应，不用造新字典）**：

| setter_name | base 类型 | 效果 |
|---|---|---|
| `setMinimumWidth` | int | 最小宽 |
| `setMinimumHeight` | int | 最小高 |
| `setMinimumSize` | `(w,h)` tuple | 最小尺寸 |
| `setFixedWidth` | int | 固定宽 |
| `setFixedHeight` | int | 固定高 |
| `setFixedSize` | `(w,h)` tuple | 固定尺寸 |
| `setMaximumWidth` | int | 最大宽 |
| `setMaximumHeight` | int | 最大高 |
| `setMaximumSize` | `(w,h)` tuple | 最大尺寸 |

→ 子类注册时写 `(self._port_edit, 'setFixedWidth', 60)`，比写 `'fixed'`/`'minh'` 字符串**更短、文档性更强、更安全**。

P2-1 PR 做完后：
1. 把已有的 5 份重复实现迁到基类（调用风格改为 setter-name 版；预计每行减 1 个 token）。
2. 已有 5 份迁完并跑测试绿灯 → P0 页面再开工。

---

### 🔴 P0 — 共享基础组件：`update_theme` 重算 QSS 但不重设 `setFixed*`

P2-1 合并后立即做。**一改全页面受益**。

| 组件 | 构造时设置 | `update_theme` 是否重设 | 修复（每个 2–6 行） |
|---|---|---|---|
| **ThemeButton**<br>[buttons.py#L143-L164](file:///f:/ComfyUI-Mie-Package-Launcher/ui_qt/widgets/buttons.py#L143-L164) | `setFixedWidth(_px(70))`<br>`setMinimumHeight(_px(60))` | ❌ 只 `_apply_style()` 重算 QSS | `update_theme` 末尾加：<br>`self.setFixedWidth(self.theme_styles._px(70))`<br>`self.setMinimumHeight(self.theme_styles._px(60))` |
| **LinkButton**<br>[buttons.py#L61-L120](file:///f:/ComfyUI-Mie-Package-Launcher/ui_qt/widgets/buttons.py#L61-L120) | `setMinimumHeight(_px(40))` | ❌ | `self.setMinimumHeight(self.theme_styles._px(40))` |
| **IconButton**<br>[buttons.py#L165-L193](file:///f:/ComfyUI-Mie-Package-Launcher/ui_qt/widgets/buttons.py#L165-L193) | `setFixedSize(_px(size),_px(size))`<br>（`self._size = size` 保存了**未缩放** base；已 0-1 核实） | ❌ QSS 重算了 border-radius / font-size，但外层尺寸没动 | `s = self.theme_styles._px(self._size)`<br>`self.setFixedSize(s, s)` |
| **InfoCard**<br>[cards.py#L144-L198](file:///f:/ComfyUI-Mie-Package-Launcher/ui_qt/widgets/cards.py#L144-L198) | `setMinimumHeight(_px(100))`（`__init__` 没存 base） | ❌ 只改子组件样式和子按钮主题 | `__init__` 补 `self._min_height_base = 100`<br>`update_theme` 补 `self.setMinimumHeight(self.theme_styles._px(100))` |
| **CircleAvatar**<br>[custom.py#L5-L45](file:///f:/ComfyUI-Mie-Package-Launcher/ui_qt/widgets/custom.py#L5-L45) | `setFixedSize(size, size)` 直接套入参，无 `_px`；调用方 2 种契约不一致（0-2 已核实） | ❌ 无 `update_theme` 方法 | 统一契约（1 改 3 文件）：<br>① CircleAvatar 构造函数 `size` 一律按**未缩放** base 理解；存 `self._base_size = size`；首次构造时：`s = theme_manager.styles._px(size)`；加 `update_theme()`：`s = self.theme_manager.styles._px(self._base_size); self.setFixedSize(s, s)`；还需 `self.theme_manager = theme_manager` 并在构造末尾 register，destructor 时 unregister。<br>② [sidebar.py#L79](file:///f:/ComfyUI-Mie-Package-Launcher/ui_qt/components/sidebar.py#L79)：`size=60` 不变（自然符合新契约；修完 sidebar 头像从 bug 的非缩放尺寸变为正确缩放）。<br>③ [cards.py#L49](file:///f:/ComfyUI-Mie-Package-Launcher/ui_qt/widgets/cards.py#L49)：**去掉**外层 `_px`，从 `_px(self.avatar_size)` 改为只传 `self.avatar_size`。 |
| **Sidebar（组件本体）**<br>[sidebar.py#L28-L66](file:///f:/ComfyUI-Mie-Package-Launcher/ui_qt/components/sidebar.py#L28-L66) | `setFixedWidth(_px(base))`（已存 `_expanded_base` / `_collapsed_base`） | ❌ `update_theme` 只 `_apply_style()`，本体宽度没重设 | 加：<br>`b = self._collapsed_base if self._collapsed else self._expanded_base`<br>`self.setFixedWidth(self._styles._px(b))`<br>（主窗口 `_apply_scaled_fixed_sizes` 目前只改外层 scroll area 宽，两层宽度不一致时可能出多余滚动条或白边） |

---

### 🔴 P0 — 页面级：`update_theme` 漏掉 setFixed* 重设（按**日活**拆分 A/B/C，控制 PR 体积）

P2-1 合并后，9 个页面的修法统一模式：向基类 `self._dpi_sized_widgets` 追加 `(widget, setter_name, base)` 元组；`update_theme` 末尾 `super().update_theme(...)` 触发基类 `_reapply_dpi_sizes()`。

#### P0-A（先做：launch_page，日活最高）

| 遗漏尺寸 | 位置 | 基类注册写法 |
|---|---|---|
| `right_container.setFixedWidth(_px(200))` | [launch_page.py#L93](file:///f:/ComfyUI-Mie-Package-Launcher/ui_qt/pages/launch_page.py#L93) | `(right_container, 'setFixedWidth', 200)` |
| 4 个快捷目录按钮 `setMinimumHeight(_px(32))` | [launch_page.py#L245](file:///f:/ComfyUI-Mie-Package-Launcher/ui_qt/pages/launch_page.py#L245) 周围 | 每个按钮一行：`(btnX, 'setMinimumHeight', 32)` |

#### P0-B（再做：webui_page，日活高）

| 遗漏尺寸 | 位置 | 注册写法 |
|---|---|---|
| `_port_edit.setFixedWidth(_px(60))` | [webui_page.py#L341](file:///f:/ComfyUI-Mie-Package-Launcher/ui_qt/pages/webui_page.py#L341) | `(self._port_edit, 'setFixedWidth', 60)` |
| `_cpath_btn.setFixedWidth(_px(32))` | [webui_page.py#L391](file:///f:/ComfyUI-Mie-Package-Launcher/ui_qt/pages/webui_page.py#L391) | `(self._cpath_btn, 'setFixedWidth', 32)` |
| `btn_container.setFixedWidth(_px(180))` | [webui_page.py#L447](file:///f:/ComfyUI-Mie-Package-Launcher/ui_qt/pages/webui_page.py#L447) | `(btn_container, 'setFixedWidth', 180)` |
| 4 个按钮 `setMinimumHeight` (60/40/36/36) | [webui_page.py#L458-L510](file:///f:/ComfyUI-Mie-Package-Launcher/ui_qt/pages/webui_page.py#L458-L510) | 4 行 setter-name |

#### P0-C（随后：models_page / version_page / 其它高频 utility，日活中）

| 页面 | 遗漏 | 注册写法（示意） |
|---|---|---|
| **models_page.py** | `library_list.setMinimumWidth(_px(220))`<br>`mapping_table.setMinimumHeight(_px(360))`<br>工具栏小按钮 `setFixedHeight(_px(28))` | `(library_list,'setMinimumWidth',220)`<br>`(mapping_table,'setMinimumHeight',360)`<br>每个小按钮 `(btn,'setFixedHeight',28)` |
| **version_page.py** | `pv_proxy_combo.setFixedWidth(_px(140))`<br>`timeout_combo.setFixedWidth(_px(85))`<br>`btn_upd/refresh.setMinimumWidth(...)`（**注意**：此处 base 是 `max(w1,w2)` 动态值，不是字面量 → 需要在 _dpi_sized_widgets 里写** callable**，或重写 `_reapply_dpi_sizes` 钩子。可先做其它 3 个字面量，最后单独处理此动态 minimumWidth）<br>`history_table.setMinimumHeight(_px(400))` | — |
| **_ScaleRow**（system_settings_page 内部类） | `combo.setFixedWidth(_px(160))`（在 `_build` 里） | `(combo, 'setFixedWidth', 160)` |
| **env_manager_section.py** | `list_widget.setMinimumHeight(_px(120))`<br>`self.setMinimumWidth(_px(520))` | `(list_widget,'setMinimumHeight',120)`<br>`(self,'setMinimumWidth',520)` |
| **env_selector.py** | `combo.setMinimumWidth(_px(240))` | `(combo, 'setMinimumWidth', 240)` |

#### 已降为 P1（打开一次的页，不进 P0 控 PR 体积）：

- ~~about_launcher_page.py~~（container.maxWidth=800 / card.minHeight=420 / logo_label fixedSize）
- ~~about_comfyui_page.py~~（container.maxWidth=800 / banner_label.fixedHeight=120）

**正面参考**（5 处已实现完整的页面）：[plugins_page.py#L935-L1099](file:///f:/ComfyUI-Mie-Package-Launcher/ui_qt/pages/plugins_page.py#L935-L1099)、[launch/environment_section.py](file:///f:/ComfyUI-Mie-Package-Launcher/ui_qt/pages/launch/environment_section.py)、[launch/launch_controls_section.py](file:///f:/ComfyUI-Mie-Package-Launcher/ui_qt/pages/launch/launch_controls_section.py)、[launch/version_section.py](file:///f:/ComfyUI-Mie-Package-Launcher/ui_qt/pages/launch/version_section.py)、[plugin_search_dialog.py](file:///f:/ComfyUI-Mie-Package-Launcher/ui_qt/widgets/plugin_search_dialog.py)。

---

### 🟠 P1 — 弹窗 / 常驻面板：**全 5 个已接 `theme_manager=` 入参，但没升基类管道 + 没 update_theme**

修正报告 v1.0 的错误结论：**UpdateDialog / ProgressDialog / CustomConfirmDialog 构造函数里已经接受 `theme_manager=None` 并存 `self.theme_manager`**（核实：[update_dialog.py#L18](file:///f:/ComfyUI-Mie-Package-Launcher/ui_qt/widgets/update_dialog.py#L18) + [custom_confirm_dialog.py#L9-L12](file:///f:/ComfyUI-Mie-Package-Launcher/ui_qt/widgets/custom_confirm_dialog.py#L9-L12) + [progress_dialog.py#L9-L14](file:///f:/ComfyUI-Mie-Package-Launcher/ui_qt/widgets/progress_dialog.py#L9-L14)）。PluginSearchDialog / AnnouncementDialog 亦同。

因此工作是「**升基类**」，**不破坏任何现有调用点**：

1. 在 [FramelessDraggableDialog](file:///f:/ComfyUI-Mie-Package-Launcher/ui_qt/widgets/frameless_draggable_dialog.py) 中：
   - 构造函数签名接受 `theme_manager=None`（保持向后兼容，默认 None）
   - `self.theme_manager = theme_manager`
   - 如果非 None：`theme_manager.register_listener(self._on_theme_changed_bridge)`（lambda：`lambda s: self.update_theme(s)`）
   - 提供空实现 `def update_theme(self, theme_styles=None): ...` 供子类 override
   - 提供 helper `def _px(self, b): return self.theme_manager.styles._px(b) if self.theme_manager else b`
   - `closeEvent`：如果有 theme_manager，`unregister_listener`（防止监听器泄漏保留已关闭 Dialog 的弱引用）
2. 子类逐个补 `update_theme`（约各 20–40 行），按下面清单重算：

| 组件 / 位置 | setFixed* 数 + 样式写死点 | 子类 update_theme 要做的事 |
|---|---|---|
| **BackgroundTaskPanel**（**常驻**，不关闭）<br>[background_task_panel.py](file:///f:/ComfyUI-Mie-Package-Launcher/ui_qt/widgets/background_task_panel.py) | 7 处 | 重设 7 处尺寸 + 重算 QSS 颜色 token |
| UpdateDialog<br>[update_dialog.py](file:///f:/ComfyUI-Mie-Package-Launcher/ui_qt/widgets/update_dialog.py) | 3 处 setFixed* + container QSS 按构造时 scale 写死 (border-radius/padding/font-size) | 重设 3 处尺寸 + 重新生成一遍 container QSS + 按钮 QSS 走新的 `_px/_pt` |
| ProgressDialog<br>[progress_dialog.py](file:///f:/ComfyUI-Mie-Package-Launcher/ui_qt/widgets/progress_dialog.py) | 5 处 setFixed* + 样式写死 | 同上 |
| CustomConfirmDialog<br>[custom_confirm_dialog.py](file:///f:/ComfyUI-Mie-Package-Launcher/ui_qt/widgets/custom_confirm_dialog.py) | 1 处 + 样式 + **checkbox indicator `width:16px;height:16px`（L55）漏 `_px`**（P3 同一个问题的第二处） | 尺寸 + QSS 重生成 + indicator 尺寸改 `f"{self._px(16)}px"` |
| AnnouncementDialog<br>[announcement_dialog.py](file:///f:/ComfyUI-Mie-Package-Launcher/ui_qt/widgets/announcement_dialog.py) | 2 处（`setFixedWidth(560)` + `setFixedHeight(450)` 字面量没走 `_px`） | 重设 2 处 + QSS |

**P1 附加**（原 P0 降下来的）：about_* 两个 About 页面补齐 `_dpi_sized_widgets`。

---

### 🟡 P2-2 — _CheckRow 复选框 indicator 16px 字面量（2 处）

| 位置 | 当前写法 | 修法 |
|---|---|---|
| [system_settings_page.py#L208](file:///f:/ComfyUI-Mie-Package-Launcher/ui_qt/pages/system_settings_page.py#L208) `_CheckRow` checkbox QSS | `width:16px;height:16px` 写死 | 改成 f-string 走 `_px(16)` |
| [custom_confirm_dialog.py#L55](file:///f:/ComfyUI-Mie-Package-Launcher/ui_qt/widgets/custom_confirm_dialog.py#L55) | 同上 | 同上，等 P1 CustomConfirmDialog 的 update_theme 一起做 |

---

### 🟢 P3 — 兜底保险 / 已知忽略

| 项 | 说明 | 建议 |
|---|---|---|
| **`QGuiApplication.primaryScreenChanged` 全局监听** | 当前只有 `QWindow.screenChanged`（拖窗口跨屏）。不拖窗口直接在设置里改主屏的缩放百分比 → 不触发 screenChanged → scale 不重算 | 建议加：在 QtApp 里 `QtWidgets.QGuiApplication.instance().primaryScreenChanged.connect(self._on_primary_screen_changed)`，回调里复用 `_apply_screen_change` 路径。低概率但代码量小（<20 行）。 |
| **`QScreen.logicalDotsPerInchChanged` 兜底** | 报告 v1.0 说「Windows 改缩放下窗口会消失重现，screenChanged 会自然触发」——**不一定**，取决于 Qt 版本 + Win10/11 + 是否禁用「让 Windows 自动修复应用」。加一个 fallback 监听更保险。 | 建议在已拿到的 screen 上接 `logicalDotsPerInchChanged` → 同一条 `_apply_screen_change` 路径，带相同 250ms 防抖计时器。 |
| **SplashScreen 280×160 字面量** | [comfyui_launcher_pyqt.py#L270](file:///f:/ComfyUI-Mie-Package-Launcher/comfyui_launcher_pyqt.py#L270) splash 几帧后就隐藏，且用户看不到尺寸差值 | **已知忽略，不进 P3**，标注即可 |

---

## 四、整改优先级路线图（v1.1：已重排依赖关系）

> 执行顺序严格从上到下：**先 P2-1 架构** → **再 P0 共享组件** → **再 P0-A/B/C 页面** → **再 P1** → **再 P2-2 / P3**。这样 P0 页面不用写临时的 `_reapply_dpi_sizes` 复制版本。

| 排期 | PR 内容 | 改动规模 | 依赖 |
|---|---|---|---|
| **PR #1 — P2-1 架构升基类** | BasePage 内置 setter-name `_dpi_sized_widgets`；迁移已有的 5 处复制实现；补测试断言（见第五节 5-1） | 1 基类 + 5 处改写；~60 行净增 | 无 |
| **PR #2 — P0 共享组件** | buttons.py（3 类）+ cards.py（InfoCard）+ sidebar.py（本体）+ CircleAvatar + 它的 2 个调用方统一契约 | 8 个文件，每处 2–12 行；~70 行 | PR #1 已合 |
| **PR #3 — P0-A launch_page** | `_dpi_sized_widgets` 补齐 right_container 宽 + 4 快捷按钮 minHeight；关联回归测试 5-3 | 1 文件 ~15 行 | PR #2 已合 |
| **PR #4 — P0-B webui_page** | `_dpi_sized_widgets` 补齐 7 处 | 1 文件 ~20 行 | PR #3 已合 |
| **PR #5 — P0-C 其它 utility 页** | models_page / version_page / _ScaleRow / env_manager_section / env_selector | 5 文件，每处 10–20 行；~90 行 | PR #4 已合 |
| **PR #6 — P1 常驻面板 + Dialog 升基类管道** | FramelessDraggableDialog 基类管道 + BackgroundTaskPanel + 5 个 Dialog 子类的 `update_theme`；about_* 双页降级补齐 | 基类 + 8 个子类；~280 行 | PR #5 已合 |
| **PR #7 — P2-2 收尾** | _CheckRow indicator 尺寸；CustomConfirmDialog 的同一个问题（随 P1 做也行） | 2 处 f-string 修复 | PR #6 已合 |
| **PR #8 — P3 兜底保险** | primaryScreenChanged 全局监听 + logicalDotsPerInchChanged 兜底 | < 50 行 | 任何时候可并行 |

---

## 五、回归测试补全方案（**与代码 PR 同 PR 提交**）

6 个现有测试全锁「构造时正确」。P0 修完若不补，6 个月内 `buttons.py` 重构大概率悄悄回归。

### 5-1：BasePage `_dpi_sized_widgets` 注册表 — 参数化单元

文件：`tests/unit/test_basepage_dpi_sized_widgets.py`

从现有 [test_launch_section_dpi_resize.py](file:///f:/ComfyUI-Mie-Package-Launcher/tests/unit/test_launch_section_dpi_resize.py) 抽思路，但测**基类**：

```python
@pytest.mark.parametrize("setter_name, base, expected_1x, expected_125", [
    ("setFixedWidth",      100,  100, 125),
    ("setMinimumHeight",   40,   40,  50),
    ("setMinimumSize",     (80,30), QtCore.QSize(80,30), QtCore.QSize(100,38)),
    ("setFixedSize",       (24,24), QtCore.QSize(24,24), QtCore.QSize(30,30)),
    ("setMaximumWidth",    800,  800, 1000),
])
def test_basepage_dpi_widgets_resize_apply(setter_name, base, expected_1x, expected_125, fake_theme_manager):
    """每个合法 setter_name 在 1.0→1.25 后结果正确；错误 setter_name 直接 AttributeError（不静默）。"""
```

再加 1 个反例：`(widget, 'NotExistMethod', 100)` 抛 `AttributeError`，证明**不吞异常**。

### 5-2：共享组件 — 参数化 `update_theme` 后尺寸跟随

文件：`tests/unit/test_shared_widgets_dpi_resize.py`

```python
# IconButton (已核实 _size 存的是 base)
def test_iconbutton_resize_after_set_scale():
    tm = make_theme_manager(scale=1.0)
    b = IconButton("X", tm.styles, size=24)
    assert b.width() == 24
    tm.set_scale(1.25)              # → 广播 → update_theme → setFixedSize(_px(24))
    assert b.width() == 30          # 24 × 1.25 = 30

# ThemeButton / LinkButton / InfoCard / Sidebar（展开 / 折叠态都覆盖） / CircleAvatar（sidebar 调用方契约 + cards 调用方契约）
# ... 参数化继续写
```

### 5-3：第五节手动复现的自动化（既是回归锁又是文档）

文件：`tests/e2e/test_webui_port_edit_resize.py`

用 `QT_QPA_PLATFORM=offscreen`，不测视觉，只测几何属性：

```python
def test_webui_port_edit_width_follows_ui_scale(gui_process_offscreen_1x):
    """1.0 → 1.25 后 WebUI 页 _port_edit 宽度比 ≈ 1.25。
    对应旧手动步骤：设置页切换缩放，回 WebUI 页看 port 输入框宽度是否跟随。"""
    w = launch_and_get_main_widget(gui_process_offscreen_1x)
    port_edit = w.findChild(QtWidgets.QLineEdit, "WebUIPortEdit")  # 或属性名 / objectName
    w1x = port_edit.width()

    # 模拟设置页下拉改 125%（走同一条 _on_scale_changed 路径）
    w._app._theme_manager.set_scale(1.25)
    QtCore.QCoreApplication.processEvents()
    port_edit2 = w.findChild(QtWidgets.QLineEdit, "WebUIPortEdit")
    w125 = port_edit2.width()

    # 比例断言（允许 1px floor 差）
    assert abs(w125 / w1x - 1.25) < 0.02, f"{w1x} -> {w125} not ~1.25x"
```

不需要截图，几何断言更稳。对象查找如果没 objectName，可以改成用 `findChildren` + 已知 parent + 正则。

---

## 六、（v1.1 取代原第五节：自动化复现脚本 ← 直接跑第五节 5-3 的 e2e 即可）

报告 v1.0 第五节的手动步骤已**整体升级为 `tests/e2e/test_webui_port_edit_resize.py` 的自动化脚本**（见第五节 5-3）。

- CI 里自动跑；
- 本地 `pytest tests/e2e/test_webui_port_edit_resize.py -q` 5 秒出结果，不需要手动记忆视觉点；
- 失败直接告诉你 `{w1x} -> {w125} not ~1.25x`，定位到具体哪个 widget 没跟随。

---

## 七、正面标杆代码（可直接拷贝 → P2-1 升基类后这些已自动获得）

### 7-1 BasePage `_dpi_sized_widgets`（P2-1 内置后直接用）

```python
# 在子类 __init__ 末尾注册一次：
self._dpi_sized_widgets += [
    (self.env_hf_entry,   'setMinimumWidth',  520),
    (self.hf_label,       'setFixedWidth',    100),
    (self.btn_ok,         'setMinimumHeight', 60),
    (self.banner_label,   'setFixedSize',     (300, 120)),
]
# update_theme 末尾只需要：
def update_theme(self, theme_styles=None):
    # ... 自己的 QSS 重算
    super().update_theme(theme_styles)   # ← 基类自动 _reapply_dpi_sizes()
```

### 7-2 Dialog 基类管道（P1 内置后）

在 [FramelessDraggableDialog](file:///f:/ComfyUI-Mie-Package-Launcher/ui_qt/widgets/frameless_draggable_dialog.py)：

```python
class FramelessDraggableDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, modal=True, window_type=None, theme_manager=None):
        super().__init__(...)
        self.theme_manager = theme_manager
        if theme_manager:
            theme_manager.register_listener(lambda st: self.update_theme(st))
        ...
    def update_theme(self, theme_styles=None):
        """子类覆盖。"""
        pass
    def _px(self, b):
        return self.theme_manager.styles._px(b) if self.theme_manager else b
    def _pt(self, b):
        return self.theme_manager.styles._pt(b) if self.theme_manager else b
    def closeEvent(self, event):
        if getattr(self, "theme_manager", None):
            try:
                self.theme_manager.unregister_listener(self.update_theme)
            except (ValueError, KeyError):
                pass
        super().closeEvent(event)
```

子类（例如 UpdateDialog）：

```python
def update_theme(self, theme_styles=None):
    if not self.theme_manager:
        return
    styles = theme_styles or self.theme_manager.styles
    c = self.theme_manager.colors

    # 1) 重设 setFixed*（直接用基类 helper _px）
    self.setFixedWidth(self._px(self._min_width_base))

    # 2) 重新生成 QSS（border-radius / padding / font-size 全部走新 scale）
    self.container.setStyleSheet(f"""
        QFrame#UpdateContainer {{
            border-radius: {self._px(16)}px;
            padding: {self._px(24)}px;
            ...
        }}
    """)
```
