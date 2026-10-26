"""Manual smoke check: an unreachable LAN model library must not freeze anything.

Run:  python notes/smoke_offline_model_lib.py
"""
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.model_path_service import ModelPathService  # noqa: E402
from utils import path_probe  # noqa: E402

UNC = "\\\\" + "no-such-nas-host-xyz123" + "\\models"   # 域名解析不到 ≈ 对端没开机


def main():
    print("path:", repr(UNC))
    print("is_unc:", path_probe.is_unc_path(UNC))
    print("is_remote:", path_probe.is_remote_path(UNC))
    print("host:", repr(path_probe.host_of(UNC)))

    tmp = tempfile.mkdtemp()
    app = MagicMock()
    app.logger = MagicMock()
    app.config = {"paths": {"comfyui_root": tmp}, "models": {}}
    svc = ModelPathService(app)
    svc._get_yaml_path = lambda: Path(tmp) / "extra_model_paths.yaml"
    svc.add_library(UNC, name="NAS")

    t0 = time.time()
    m = svc.get_mappings_for_base(UNC)
    print(f"get_mappings_for_base(offline): {time.time()-t0:.2f}s -> {len(m)} mappings")

    t0 = time.time()
    ok = svc.apply_libraries()
    report = svc.get_apply_report()
    print(f"apply_libraries(offline): {time.time()-t0:.2f}s ok={ok} "
          f"skipped={[l['name'] for l in report['skipped']]}")
    print("--- yaml ---")
    print(svc._get_yaml_path().read_text(encoding="utf-8"))

    t0 = time.time()
    svc.get_mappings_for_base(UNC)
    print(f"second call (cached): {time.time()-t0:.2f}s")

    # 本地库仍然正常
    local = Path(tmp) / "models"
    (local / "checkpoints").mkdir(parents=True, exist_ok=True)
    svc.add_library(str(local), name="Local")
    print("local mappings:", svc.get_mappings_for_base(str(local)))


if __name__ == "__main__":
    main()
