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

# ---- package 子命令专属（v1.1.0 新增）----
# 注意：6/7/8 已被 webui 占用（见下方），package 复用会违反「跨子命令含义稳定」契约，
# 所以 package 用空闲的 5 + 全新 9/10/11 段。

EXIT_PACKAGE_PARTIAL_FAILURE: Final[int] = 5
"""package apply：部分失败（≥1 项 item.status == failed）。
ok / ok_at_alt_path / skipped / not_applicable / manual_required / pending 都不算失败。"""

EXIT_PACKAGE_PRECONDITION: Final[int] = 9
"""package apply：前置不兼容。
dirty tree + clean_untracked=false 且 stash 失败 / env 不匹配且用户拒绝（apply 启动前短路）。"""

EXIT_PACKAGE_MANIFEST_INVALID: Final[int] = 10
"""package：manifest 无效。
schema 错 / sha256 不符 / manifest_version 超出启动器支持范围 / 未知 item kind。"""

EXIT_PACKAGE_SOURCE_UNREACHABLE: Final[int] = 11
"""package：源不可达 / 非 HTTPS。
文件不存在 / URL 拉取失败 / JSON 解析失败 / manifest URL 是 HTTP（HTTP 直接拒绝）。"""

# ---- webui 子命令专属 ----
# 这三个码当前在 cmd_webui.py 里以裸 magic number 形式使用，集中命名化以便统一管理。
# 语义绑死 webui，package 不得复用（见上方 package 段）。

EXIT_WEBUI_CORE_NOT_RUNNING: Final[int] = 6
"""webui start：传了 --with-comfyui 但 ComfyUI 未在运行。"""

EXIT_WEBUI_NOT_INSTALLED: Final[int] = 7
"""webui：路径未安装（用 webui install 拉取）。
被 tests/e2e/test_webui_cli_e2e.py 锁住：webui 未安装必须返 7。"""

EXIT_WEBUI_DEPS_MISSING: Final[int] = 8
"""webui：依赖缺失（用 webui setup 安装）。"""
