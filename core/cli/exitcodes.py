"""CLI 子命令的退出码常量。

集中在此是为了：
- 文档化（每个常量自带 docstring，--help / cli.md 可引用）
- 测试化（test_cli_exitcodes.py 锁住值，避免无意改动破坏外部脚本契约）
- 一致性（避免子命令里散落 magic number）

POSIX 限制：进程退出码必须落在 0..255 内。
外部脚本（systemd / NSSM / 监控 agent）会按这些码判断是否需要重试 / 告警，
所以值的稳定性比\"看起来合理\"更重要。
"""
from typing import Final

EXIT_OK: Final[int] = 0
"""成功。start 后服务就绪、stop 成功、update 已完成、status 报告在跑中等。"""

EXIT_ERROR: Final[int] = 1
"""通用错误：配置缺失、路径不存在、启动失败、停止失败、IO 异常等。"""

EXIT_ALREADY_RUNNING: Final[int] = 2
"""start 时检测到 ComfyUI 已在运行（HTTP 可达 / 端口被占），拒绝重复启动。"""

EXIT_NOT_RUNNING: Final[int] = 3
"""stop / status 时检测到 ComfyUI 未运行，stop 是 no-op 仍返回 0；status 返回 3。"""

EXIT_UP_TO_DATE: Final[int] = 4
"""update 子命令：当前已是最新版本，未执行任何变更。"""
