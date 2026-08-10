"""依赖冻结黑名单（FROZEN_PKGS）的共享定义。

历史：原本定义在 ``services/update_service.py`` 模块顶部，只被「同步依赖库」流程
（UpdateService.perform_batch_update → install_requirements_file）用。v1.1.0 新增的
整合包更新（PackageUpdateService）也要按同一份黑名单过滤 dependency item，于是把
它抽到独立模块，两条路径共享，避免两处定义漂移。

冻结清单含义（搬自 update_service.py 原注释）：

- torch / torchvision / torchaudio / triton / xformers
  强依赖本地 CUDA 版本与驱动。随手给它们跑 pip install -U 非常容易装到与现有 CUDA
  不匹配的新版，轻者引入错误，重者整套 GPU 环境坏掉。ComfyUI Manager 也是先让 pip
  装、装完不对再 torch_rollback() 回滚，意图与我们一致。
- numpy
  大版本跳会影响 opencv / torch 等的 ABI 兼容性，在未验证环境下应避免自动跳。
  ComfyUI Manager 改为用 pip_overrides.json 强制 numpy==1.26.4，本启动器走黑名单
  跳过更安全（不联网不下载）。

**刻意不在黑名单里**：comfyui-frontend-package / comfyui-workflow-templates —— 它们是
ComfyUI 官方 requirements.txt 里 pin 死的包，「更新内核」应该顺带同步到 pin 版本。
"""
from __future__ import annotations

from typing import Iterable


FROZEN_PKGS: frozenset[str] = frozenset({
    "torch",
    "torchvision",
    "torchaudio",
    "triton",
    "xformers",
    "numpy",
})


def is_frozen(pkg_name: str) -> bool:
    """判断单个包名是否在冻结黑名单里。

    pkg_name 可以是纯包名（``"numpy"``）或带版本约束的 spec（``"numpy==2.4.6"``），
    内部只取第一个 token 比较，大小写不敏感（pip 包名规范）。
    """
    if not pkg_name:
        return False
    # spec 形如 "numpy==2.4.6" / "numpy>=1.20" / "numpy <=2.0" → 取包名部分
    name_only = pkg_name.strip().split("=")[0].split(">")[0].split("<")[0].split("!")[0]
    name_only = name_only.split("[")[0].strip()  # 剥 extras：numpy[abc]==1.2
    return name_only.lower() in FROZEN_PKGS


def filter_frozen(packages: Iterable[str]) -> tuple[list[str], list[str]]:
    """把包列表按是否冻结一分为二。

    返回 (allowed, frozen)：
    - allowed：不在黑名单里的，保留原 spec（含版本约束），顺序不变
    - frozen：命中的，只保留包名（丢版本约束，因为只是用来记 reason）

    例：filter_frozen(["numpy==2.4.6", "kornia==0.6.12", "torch"])
        → (["kornia==0.6.12"], ["numpy", "torch"])

    保留顺序、保留 spec 原文（allowed 那侧），方便调用方直接把 allowed 喂给 pip。
    """
    allowed: list[str] = []
    frozen: list[str] = []
    for pkg in packages:
        if not pkg or not pkg.strip():
            continue
        name_only = pkg.strip().split("=")[0].split(">")[0].split("<")[0].split("!")[0]
        name_only = name_only.split("[")[0].strip()
        if name_only.lower() in FROZEN_PKGS:
            frozen.append(name_only.lower())
        else:
            allowed.append(pkg.strip())
    return allowed, frozen
