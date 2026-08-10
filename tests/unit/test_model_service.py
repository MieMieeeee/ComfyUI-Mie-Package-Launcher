"""ModelService 单测：resolve_dest / verify_manual / open_link（plan §3.1.2）。

重点锁：
- resolve_dest：library_id="default"/null → default 库；hex id → 精确匹配；找不到 → ValueError
- resolve_dest：非标准 category 不阻断（只调 is_standard_category 判定）
- verify_manual：ok / missing / checksum_mismatch 三态，**无 size_mismatch**（size_hint 不参与）
- verify_manual：alt_path 覆盖（浏览按钮，at_alt_path 标记）
- open_link：接受 http/https，不抛
"""
import hashlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from services.model_service import (
    ModelService,
    VERIFY_OK,
    VERIFY_MISSING,
    VERIFY_CHECKSUM_MISMATCH,
)


def _mps_mock(default_base="F:/ComfyUI_Models", libraries=None):
    """构造一个假的 ModelPathService，带 standard_map / get_libraries / get_external_path。"""
    mps = MagicMock()
    mps.standard_map = [
        ("checkpoints", "models/checkpoints/"),
        ("text_encoders", "models/text_encoders/"),
        ("loras", "models/loras/"),
        ("vae", "models/vae/"),
        ("audio_encoders", "models/audio_encoders/"),
        ("model_patches", "models/model_patches/"),
    ]
    mps.get_external_path.return_value = default_base
    if libraries is None:
        libraries = [
            {"id": "2cff1773", "name": "default", "base_path": default_base,
             "enabled": True, "is_default": True},
            {"id": "1e17c54f", "name": "extra", "base_path": "E:/Models",
             "enabled": True, "is_default": False},
        ]
    mps.get_libraries.return_value = libraries
    return mps


def _app(mps=None):
    app = MagicMock()
    if mps is None:
        mps = _mps_mock()
    app.services.model_path = mps
    return app


# ===========================================================================
# resolve_dest
# ===========================================================================

class TestResolveDest:
    def test_default_magic_string_uses_default_library(self):
        svc = ModelService(_app())
        p = svc.resolve_dest("default", "loras", "x.safetensors")
        assert str(p).replace("\\", "/").endswith("ComfyUI_Models/loras/x.safetensors")

    def test_null_library_id_equals_default(self):
        svc = ModelService(_app())
        p1 = svc.resolve_dest(None, "loras", "x.safetensors")
        p2 = svc.resolve_dest("default", "loras", "x.safetensors")
        assert p1 == p2

    def test_empty_library_id_equals_default(self):
        svc = ModelService(_app())
        p1 = svc.resolve_dest("", "loras", "x.safetensors")
        p2 = svc.resolve_dest("default", "loras", "x.safetensors")
        assert p1 == p2

    def test_hex_id_exact_match(self):
        svc = ModelService(_app())
        p = svc.resolve_dest("1e17c54f", "vae", "y.safetensors")
        assert str(p).replace("\\", "/").endswith("E:/Models/vae/y.safetensors")

    def test_unknown_hex_id_raises(self):
        svc = ModelService(_app())
        with pytest.raises(ValueError, match="找不到 library_id"):
            svc.resolve_dest("deadbeef", "loras", "x.safetensors")

    def test_no_default_library_raises(self):
        """external_libraries 里没有 is_default=True 的条目 → ValueError。"""
        mps = _mps_mock(libraries=[
            {"id": "abc", "base_path": "F:/X", "is_default": False},
        ])
        mps.get_external_path.return_value = ""  # default 库找不到
        svc = ModelService(_app(mps=mps))
        with pytest.raises(ValueError, match="default 外置模型库"):
            svc.resolve_dest("default", "loras", "x.safetensors")

    def test_non_standard_category_still_resolves(self):
        """非标准 category（如 qwen-tts）不阻断 resolve_dest（plan §2.2.3）。"""
        svc = ModelService(_app())
        p = svc.resolve_dest("default", "qwen-tts", "z.safetensors")
        assert "qwen-tts" in str(p)

    def test_is_standard_category_true_for_known(self):
        svc = ModelService(_app())
        assert svc.is_standard_category("loras") is True
        assert svc.is_standard_category("checkpoints") is True

    def test_is_standard_category_false_for_unknown(self):
        svc = ModelService(_app())
        assert svc.is_standard_category("qwen-tts") is False
        assert svc.is_standard_category("lora") is False  # 漏 s 拼错

    def test_standard_categories_fallback_when_mps_missing(self):
        """ModelPathService 不可用时兜底用 plan §2.2.3 列的 12 个。"""
        app = MagicMock()
        app.services.model_path = MagicMock()
        app.services.model_path.standard_map = [("__getattribute__", "")]  # 触发异常
        with patch.object(ModelService, "_get_model_path_service", side_effect=Exception):
            svc = ModelService(app)
            keys = svc._standard_category_keys()
        assert "checkpoints" in keys
        assert "diffusion_models" in keys
        assert len(keys) == 12


# ===========================================================================
# verify_manual
# ===========================================================================

class TestVerifyManual:
    def test_missing_file(self, tmp_path):
        """文件不存在 → status=missing。"""
        mps = _mps_mock(default_base=str(tmp_path))
        svc = ModelService(_app(mps=mps))
        item = {"dest": {"library_id": "default", "category": "loras", "filename": "nope.safetensors"}}
        r = svc.verify_manual(item)
        assert r["status"] == VERIFY_MISSING
        assert r["at_alt_path"] is False

    def test_ok_without_checksum(self, tmp_path):
        """文件存在 + manifest 没带 checksum → status=ok（只看文件存在）。"""
        mps = _mps_mock(default_base=str(tmp_path))
        svc = ModelService(_app(mps=mps))
        cat_dir = tmp_path / "loras"
        cat_dir.mkdir()
        (cat_dir / "x.safetensors").write_bytes(b"model data")
        item = {"dest": {"library_id": "default", "category": "loras", "filename": "x.safetensors"}}
        r = svc.verify_manual(item)
        assert r["status"] == VERIFY_OK
        assert r["at_alt_path"] is False

    def test_ok_with_matching_checksum(self, tmp_path):
        """文件存在 + sha256 匹配 → ok。"""
        mps = _mps_mock(default_base=str(tmp_path))
        svc = ModelService(_app(mps=mps))
        cat_dir = tmp_path / "vae"
        cat_dir.mkdir()
        content = b"model data"
        (cat_dir / "y.safetensors").write_bytes(content)
        expected = hashlib.sha256(content).hexdigest()
        item = {
            "dest": {"library_id": "default", "category": "vae", "filename": "y.safetensors"},
            "checksum": {"type": "sha256", "value": expected},
        }
        r = svc.verify_manual(item)
        assert r["status"] == VERIFY_OK

    def test_checksum_mismatch(self, tmp_path):
        """文件存在但 sha256 不符 → checksum_mismatch（带 expected/actual）。"""
        mps = _mps_mock(default_base=str(tmp_path))
        svc = ModelService(_app(mps=mps))
        cat_dir = tmp_path / "vae"
        cat_dir.mkdir()
        (cat_dir / "y.safetensors").write_bytes(b"actual content")
        item = {
            "dest": {"library_id": "default", "category": "vae", "filename": "y.safetensors"},
            "checksum": {"type": "sha256", "value": "0" * 64},  # 故意错的 hash
        }
        r = svc.verify_manual(item)
        assert r["status"] == VERIFY_CHECKSUM_MISMATCH
        assert r["expected"] == "0" * 64
        assert r["actual"] == hashlib.sha256(b"actual content").hexdigest()

    def test_checksum_case_insensitive(self, tmp_path):
        """声明的 sha256 大写也能匹配（hex a-f vs A-F）。"""
        mps = _mps_mock(default_base=str(tmp_path))
        svc = ModelService(_app(mps=mps))
        cat_dir = tmp_path / "vae"
        cat_dir.mkdir()
        content = b"data"
        (cat_dir / "z.safetensors").write_bytes(content)
        expected = hashlib.sha256(content).hexdigest().upper()
        item = {
            "dest": {"library_id": "default", "category": "vae", "filename": "z.safetensors"},
            "checksum": {"type": "sha256", "value": expected},
        }
        r = svc.verify_manual(item)
        assert r["status"] == VERIFY_OK

    def test_no_size_mismatch_status(self, tmp_path):
        """verify_manual 不返 size_mismatch（size_hint 不参与校验，plan §2.2.3）。

        即使 size_hint 与实际差很多，status 也只可能是 ok/missing/checksum_mismatch。
        """
        mps = _mps_mock(default_base=str(tmp_path))
        svc = ModelService(_app(mps=mps))
        cat_dir = tmp_path / "loras"
        cat_dir.mkdir()
        (cat_dir / "x.safetensors").write_bytes(b"tiny")  # 实际 4 字节
        item = {
            "dest": {"library_id": "default", "category": "loras", "filename": "x.safetensors"},
            "size_hint": "3.5 GB",  # hint 说 3.5GB，实际 4 字节，差很多
        }
        r = svc.verify_manual(item)
        assert r["status"] == VERIFY_OK  # 仍 ok（size_hint 不影响）
        assert "size_mismatch" not in r["status"]

    def test_alt_path_overrides_manifest_dest(self, tmp_path):
        """alt_path（浏览按钮）覆盖 manifest 指定路径，at_alt_path=True。"""
        mps = _mps_mock(default_base=str(tmp_path))
        svc = ModelService(_app(mps=mps))
        # manifest 指定 loras/x.safetensors（不存在），但用户浏览指向了别处的文件
        alt = tmp_path / "downloads" / "x.safetensors"
        alt.parent.mkdir()
        alt.write_bytes(b"found here")
        item = {"dest": {"library_id": "default", "category": "loras", "filename": "x.safetensors"}}
        r = svc.verify_manual(item, alt_path=alt)
        assert r["status"] == VERIFY_OK
        assert r["at_alt_path"] is True
        assert r["path"] == str(alt)

    def test_alt_path_missing(self, tmp_path):
        """alt_path 指向的文件不存在 → missing + at_alt_path=True。"""
        mps = _mps_mock(default_base=str(tmp_path))
        svc = ModelService(_app(mps=mps))
        item = {"dest": {"library_id": "default", "category": "loras", "filename": "x.safetensors"}}
        r = svc.verify_manual(item, alt_path=tmp_path / "nonexistent.safetensors")
        assert r["status"] == VERIFY_MISSING
        assert r["at_alt_path"] is True


# ===========================================================================
# open_link
# ===========================================================================

class TestOpenLink:
    def test_calls_webbrowser_open(self):
        svc = ModelService(_app())
        with patch("services.model_service.webbrowser.open", return_value=True) as m:
            r = svc.open_link("https://pan.quark.cn/s/xxx")
        m.assert_called_once_with("https://pan.quark.cn/s/xxx")
        assert r is True

    def test_accepts_http(self):
        """open_link 接受 http（网盘短链，plan §6.4），不阻断。"""
        svc = ModelService(_app())
        with patch("services.model_service.webbrowser.open", return_value=True):
            r = svc.open_link("http://short.link/abc")
        assert r is True

    def test_empty_url_returns_false(self):
        svc = ModelService(_app())
        assert svc.open_link("") is False

    def test_exception_returns_false_not_raise(self):
        svc = ModelService(_app())
        with patch("services.model_service.webbrowser.open", side_effect=Exception("no browser")):
            assert svc.open_link("https://x") is False
