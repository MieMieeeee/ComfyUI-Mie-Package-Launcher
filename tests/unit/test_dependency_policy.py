"""dependency_policy 单测：FROZEN_PKGS 内容 / is_frozen / filter_frozen。

抽离自 services/update_service.py（v1.1.0 共享给 PackageUpdateService）。重点锁：
- 冻结清单的 6 个包名（不误带 comfyui-frontend-package / comfyui-workflow-templates）
- spec 形态（带版本约束 / extras）的包名提取
- filter_frozen 保留 allowed 顺序 + frozen 只返包名
"""
import pytest

from services.dependency_policy import FROZEN_PKGS, is_frozen, filter_frozen


# ---- FROZEN_PKGS 内容 ----

def test_frozen_pkgs_contains_exactly_six():
    """冻结清单锁定 6 个包（torch 系 + numpy），不多不少。"""
    assert FROZEN_PKGS == frozenset({
        "torch", "torchvision", "torchaudio", "triton", "xformers", "numpy",
    })


def test_frozen_pkgs_does_not_include_frontend_templates():
    """comfyui-frontend-package / comfyui-workflow-templates 刻意不在黑名单。

    它们是 ComfyUI 官方 requirements.txt pin 死的包，「更新内核」应顺带同步。
    （update_service.py 原注释明确说明，抽离时别误带。）
    """
    assert "comfyui-frontend-package" not in FROZEN_PKGS
    assert "comfyui-workflow-templates" not in FROZEN_PKGS


# ---- is_frozen ----

@pytest.mark.parametrize("spec", [
    "torch",
    "numpy",
    "numpy==2.4.6",
    "numpy>=1.20",
    "numpy<=2.0",
    "numpy != 1.19",  # 带空格 + !=
    "numpy[abc]==1.2",  # extras
    "TORCH",  # 大小写不敏感
    "TorchVision",
])
def test_is_frozen_true_for_frozen(spec):
    assert is_frozen(spec) is True


@pytest.mark.parametrize("spec", [
    "kornia",
    "kornia==0.6.12",
    "voluptuous>=0.15",
    "comfyui-frontend-package",  # 不冻结
    "opencv-python",
    "",
])
def test_is_frozen_false_for_others(spec):
    assert is_frozen(spec) is False


# ---- filter_frozen ----

def test_filter_frozen_splits_correctly():
    """一分为二：allowed 保留原 spec + 顺序；frozen 只返包名（小写）。"""
    pkgs = ["numpy==2.4.6", "kornia==0.6.12", "torch", "voluptuous>=0.15", "xformers"]
    allowed, frozen = filter_frozen(pkgs)
    assert allowed == ["kornia==0.6.12", "voluptuous>=0.15"]
    assert frozen == ["numpy", "torch", "xformers"]


def test_filter_frozen_preserves_order():
    """allowed 顺序必须与输入一致（调用方直接喂 pip，顺序影响可读性）。"""
    pkgs = ["zzz", "aaa", "torch", "mmm", "numpy"]
    allowed, _ = filter_frozen(pkgs)
    assert allowed == ["zzz", "aaa", "mmm"]


def test_filter_frozen_all_frozen():
    """全部冻结 → allowed 空，frozen 全收。"""
    allowed, frozen = filter_frozen(["torch", "numpy==1.0"])
    assert allowed == []
    assert set(frozen) == {"torch", "numpy"}


def test_filter_frozen_none_frozen():
    """无一冻结 → allowed 全收，frozen 空。"""
    allowed, frozen = filter_frozen(["kornia", "voluptuous"])
    assert allowed == ["kornia", "voluptuous"]
    assert frozen == []


def test_filter_frozen_skips_empty_strings():
    """空串 / 纯空白应被跳过，不出现在任一侧。"""
    allowed, frozen = filter_frozen(["numpy", "", "  ", "kornia"])
    assert allowed == ["kornia"]
    assert frozen == ["numpy"]
