"""伴生服务（companion services）框架.

把「与 ComfyUI 平级、但伴生于它」的服务（openjutsu 等）纳入统一生命周期:
  - 声明: spec.py 的 ServiceSpec 代码级注册表 (不做任意用户自定义服务)
  - 位置: 服务 100% 在整合包路径下 (环境的 comfyui_root 下, root 相对包根)
  - 生命周期: manager.py 的 start / stop / status (服务为单元, 内部 1~N 条命令是实现细节)
  - 存储: pidstore.py v2 多进程 pidfile (<cwd>/launcher/<service_id>.pid)
  - 进程: proctree.py 身份门 + 进程树终止 + 端口清残

跟 webui 五件套 (core/webui_*.py) 的关系 (strangler 策略, 见
docs/companion-services-design.md §2): 本期 webui 运行时**不走**本框架,
webui 在注册表中仅为名义条目 (runtime="webui-legacy"), CLI `service ... webui`
转发老实现; P2 再把 webui 迁移过来. 这样老用户零回归风险.

不依赖 PyQt5, CLI / GUI 两侧复用 (与 WebuiProcessManager 同一约束).
"""
from core.companion.spec import (
    IdentityRule,
    PortBinding,
    ServiceSpec,
    BUILTIN_SERVICES,
)

__all__ = [
    "IdentityRule",
    "PortBinding",
    "ServiceSpec",
    "BUILTIN_SERVICES",
]
