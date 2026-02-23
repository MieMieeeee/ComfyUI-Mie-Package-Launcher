# ComfyUI 启动器样式重构计划

## 目标
将所有样式提取到独立模块，实现主题统一管理，拆分大文件便于维护。

## 文件结构
```
ui_qt/
├── qt_app.py              # 主入口（精简至约 1500 行）
├── theme_styles.py         # 主题样式管理（已完成）
├── theme_manager.py        # 主题管理器
├── pages/
│   ├── __init__.py
│   ├── base_page.py        # 页面基类
│   ├── launch_page.py      # 启动与更新页面
│   ├── version_page.py     # 内核版本管理页面
│   ├── models_page.py      # 外置模型库页面
│   ├── about_me_page.py    # 关于我页面
│   ├── about_comfyui_page.py  # 关于 ComfyUI 页面
│   └── about_launcher_page.py  # 关于启动器页面
├── widgets/
│   ├── __init__.py
│   ├── buttons.py          # 按钮组件
│   ├── inputs.py           # 输入框组件
│   ├── cards.py            # 卡片组件
│   └── tables.py           # 表格组件
└── components/
    ├── sidebar.py          # 侧边栏组件
    └── nav.py             # 导航组件
```

## 任务列表

### 阶段 1：基础架构准备
- [x] 创建 `theme_manager.py` - 主题管理器
- [x] 创建 `pages/__init__.py` - 页面包
- [x] 创建 `widgets/__init__.py` - 组件包
- [x] 创建 `components/__init__.py` - 组件包

### 阶段 2：组件库开发
- [x] 创建 `widgets/buttons.py`
  - PrimaryButton（主要按钮）
  - SecondaryButton（次级按钮）
  - LinkButton（链接按钮）
  - IconButton（图标按钮）
  - ThemeButton（主题按钮）

- [x] 创建 `widgets/inputs.py`
  - StyledComboBox（样式化下拉框）
  - StyledLineEdit（样式化输入框）
  - ReadOnlyField（只读字段）

- [x] 创建 `widgets/cards.py`
  - ProfileCard（个人卡片）
  - InfoCard（信息卡片）
  - HeroCard（英雄卡片）

- [x] 创建 `widgets/tables.py`
  - StyledTableWidget（样式化表格）

### 阶段 3：侧边栏组件
- [x] 创建 `components/sidebar.py`
- [x] 创建 `components/nav.py`

### 阶段 4：页面重构 - 关于我页面
- [x] 创建 `pages/about_me_page.py`
- [x] 从 qt_app.py 提取关于我页面代码
- [x] 应用新样式

### 阶段 5：页面重构 - 关于 ComfyUI 页面
- [ ] 创建 `pages/about_comfyui_page.py`
- [ ] 从 qt_app.py 提取关于 ComfyUI 页面代码
- [ ] 应用新样式

### 阶段 6：页面重构 - 关于启动器页面
- [x] 创建 `pages/about_launcher_page.py`
- [x] 从 qt_app.py 提取关于启动器页面代码
- [x] 应用新样式

### 阶段 7：页面重构 - 外置模型库页面
- [ ] 创建 `pages/models_page.py`
- [ ] 从 qt_app.py 提取外置模型库页面代码
- [ ] 应用新样式

### 阶段 8：页面重构 - 内核版本管理页面
- [x] 创建 `pages/version_page.py`
- [x] 从 qt_app.py 提取内核版本管理页面代码
- [x] 应用新样式

### 阶段 9：页面重构 - 启动页面
- [x] 创建 `pages/launch_page.py`
- [x] 从 qt_app.py 提取启动页面代码
- [x] 应用新样式

### 阶段 10：主入口重构
- [x] 添加新页面模块导入
- [x] 创建所有新页面类（launch_page, version_page, models_page, about_me_page, about_comfyui_page, about_launcher_page）
- [x] 集成新页面到主入口（带特性标志）
- [x] 添加新页面主题切换支持
- [ ] 清理冗余的页面构建代码（待测试后）
- [ ] 全面测试新页面功能

#### 如何启用新页面
在 `launcher/config.json` 中添加：
```json
{
  "ui_settings": {
    "use_new_pages": true
  }
}
```

启用后将使用重构后的页面组件。默认使用原始内联代码以确保稳定性。

## 进度记录

| 日期 | 完成阶段 | 备注 |
|--------|----------|------|
| 2026-02-19 | 方案制定 | 完成 |
| 2026-02-19 | 阶段1：基础架构准备 | 完成 |
| 2026-02-19 | 阶段2：组件库开发 | 完成 |
| 2026-02-19 | 阶段3：侧边栏组件 | 完成 |
| 2026-02-19 | 阶段4：关于我页面 | 完成 |
| 2026-02-19 | 阶段5：关于ComfyUI页面 | 完成 |
| 2026-02-19 | 阶段6：关于启动器页面 | 完成 |
| 2026-02-19 | 阶段7：外置模型库页面 | 完成 |
| 2026-02-19 | 阶段8：内核版本管理页面 | 完成 |
| 2026-02-19 | 阶段9：启动页面 | 完成 |
| 2026-02-19 | 阶段10：主入口重构 | 完成 |

## 样式对照表

| 样式元素 | 旧代码位置 | 新代码位置 |
|----------|------------|----------|
| 全局主题颜色 | palette 字典 | ThemeColors 类 |
| 内容区样式 | _apply_theme 函数 | ThemeStyles.content_style_* |
| 导航按钮样式 | nav_style 格式化 | ThemeStyles.nav_button_style |
| 折叠/展开按钮 | 硬编码 QSS | ThemeStyles.collapse_button_style 等 |
| 主题按钮 | 硬编码 QSS | ThemeStyles.theme_button_style |
| 表格样式 | history_table.setStyleSheet | ThemeStyles.table_style |
| 卡片样式 | profile_card.setStyleSheet | ThemeStyles.card_style |
| 链接按钮 | _make_link 函数 | ThemeStyles.link_button_style |
| 次级按钮 | secondary_btn_style | ThemeStyles.secondary_button_style |
| 输入框样式 | common_input_qss | ThemeStyles.input_style |
