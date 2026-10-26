"""静态扫描：函数作用域里引用了「任何一层作用域都没定义」的名字 → 运行时 NameError。

背景（2026-10 检查更新卡「检查中」事故）：qt_app._do_plugin_check_updates 的
on_done 闭包引用了 page_plugins——那是 _create_pages 方法的局部变量，在本方法
作用域里不存在，运行时 NameError 被 except 吞掉，导致 set_checking(False)
从未执行、插件列表永久卡「检查中…」。这类 bug 的特征：

1. 静态可查：名字在模块级、内嵌函数链、builtins 里都找不到定义；
2. 运行时必炸（第一次走到那条路径），但常被宽泛的 ``except Exception`` 吞成
   「功能静默失效」，测试很难抓到。

本测试用 stdlib symtable 做名字解析（等价于编译器的 scope 分析），对全部生产
代码目录扫描。新增代码若真的需要模块级名字，请在模块顶部定义/导入；若是
PyQt/Nuitka 注入的名字，加进 _KNOWN_INJECTED 白名单（附来源说明）。

同类已修案例（都由本扫描器首次发现）：
- qt_app.py on_done 引用 page_plugins（未定义）→ 检查中卡死；
- qt_app.py _apply_theme 引用 _get_common_input_qss / _get_secondary_btn_style
  （函数从不存在，死分支已删）；
- core/process_manager.py 用 shutil 未 import → wmic 兜底永远 False；
- ui_qt/components/sidebar.py 用 QtGui 未 import → 标题阴影从未生效；
- ui_qt/pages/launch_page.py 用 form_group（重构残留）→ 右侧按钮高度同步失效。
"""
import ast
import builtins
import os
import symtable

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 生产代码扫描范围（tests 不扫：pytest fixture 名由框架注入，静态不可见；
# .venv/release/dist 是第三方与产物）
SCAN_DIRS = ["core", "services", "ui_qt", "utils", "config"]
SCAN_ROOT_FILES = ["__main__.py", "comfyui_launcher_pyqt.py", "headless_app.py",
                   "build.py", "release.py"]

# builtins 之外允许的隐式全局：Python 模块 dunder（loader 注入，非代码赋值）
# + Nuitka 编译期注入（使用点有 try/except NameError 守卫）。
_KNOWN_INJECTED = {
    "__file__", "__name__", "__doc__", "__package__", "__spec__",
    "__loader__", "__path__", "__builtins__", "__all__", "__debug__",
    "__compiled__",  # Nuitka（qt_app._restart_app，try/except NameError 守卫）
}


def _collect_files():
    files = []
    for d in SCAN_DIRS:
        base = os.path.join(ROOT, d)
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [x for x in dirnames if x != "__pycache__"]
            for f in sorted(filenames):
                if f.endswith(".py"):
                    files.append(os.path.join(dirpath, f))
    for f in SCAN_ROOT_FILES:
        p = os.path.join(ROOT, f)
        if os.path.isfile(p):
            files.append(p)
    assert files, "扫描范围为空——目录结构变了？请更新本测试的 SCAN_DIRS"
    return files


def _undefined_implicit_globals(path):
    """返回 [(scope 链, 名字), ...]：函数作用域里 is_global 且哪儿都没定义的名字。

    symtable 的作用域判定与编译器一致：
    - 内嵌函数引用外层函数局部量 → is_free()（闭包，正确解析，不报）；
    - 引用模块级/builtin → is_global() 且名字能在模块级 locals / builtins /
      文件内 global 声明 / _KNOWN_INJECTED 里找到（正确，不报）；
    - 其余 is_global() → 运行时 NameError（就是 page_plugins 那类 bug）。
    """
    with open(path, encoding="utf-8-sig") as fh:
        src = fh.read()
    tree = ast.parse(src)
    star_imports = [
        getattr(n, "module", "") or "?"
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and any(a.name == "*" for a in n.names)
    ]
    if star_imports:
        # star import 会让模块级名字集合不可知，扫描失效——直接失败逼着处理
        # （要么改成显式导入，要么本文件豁免并注明）。
        return [(f"<module>", f"STAR_IMPORT:{m}") for m in star_imports]

    table = symtable.symtable(src, path, "exec")
    module_locals = {s.get_name() for s in table.get_symbols() if s.is_local()}
    declared_globals = {n for g in ast.walk(tree)
                        if isinstance(g, ast.Global) for n in g.names}
    known = module_locals | declared_globals | set(dir(builtins)) | _KNOWN_INJECTED

    problems = []

    def _walk(t, scope_path):
        for child in t.get_children():
            name = child.get_name()
            path_chain = scope_path + [name]
            if child.get_type() == "function":
                for sym in child.get_symbols():
                    if sym.is_global() and not sym.is_local():
                        n = sym.get_name()
                        if n not in known:
                            problems.append((".".join(path_chain), n))
            _walk(child, path_chain)

    _walk(table, [])
    return problems


@pytest.mark.parametrize("path", _collect_files(), ids=lambda p: os.path.relpath(p, ROOT))
def test_no_undefined_implicit_global_refs(path):
    problems = _undefined_implicit_globals(path)
    assert not problems, (
        "函数作用域引用了未定义的名字（运行时 NameError，常被 except 吞成"
        "功能静默失效——同 page_plugins 卡「检查中」事故）：\n  "
        + "\n  ".join(f"{scope}: {name}" for scope, name in problems)
    )
