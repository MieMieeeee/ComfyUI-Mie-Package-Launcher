"""启动器版本号 —— 唯一事实源（代码控制）。

发版改这里（或 `python build.py --version vX.Y.Z`，会自动改写本文件）。
运行时各读者（crash.log / CLI info / 关于页 / 自更新版本比较）直接
import 本常量；`build_parameters.json` 只保留编译脚本自动插入的
元数据（built_at / suffix / mode / builder / channel），不再携带
version——生成物里的版本号曾与源码脱节（root 与 launcher/ 两份
json 各自漂移），改为编译期随代码打进 exe 后不可能再漂。
"""

LAUNCHER_VERSION = "v1.0.18"
