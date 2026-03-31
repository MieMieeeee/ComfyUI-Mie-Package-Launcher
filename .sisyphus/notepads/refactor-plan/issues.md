
## F4 Scope Fidelity Check — Issues Found (2026-03-31)

### Critical Scope Violations

1. **NEW: `__main__.py` + `core/cli_start.py` + `headless_app.py`** — Entirely new CLI entry point with --start/--stop/--status. Not extracted from existing code. New user-visible feature.

2. **NEW: `services/launcher_update_service.py` (476 lines)** — Complete auto-update service: checks remote for new versions, downloads EXE, SHA256 verification, replaces running executable. Wired into `services/di.py`. Major new feature.

3. **NEW: `ui_qt/widgets/update_dialog.py` (343 lines)** — New Qt dialog for update flow (progress bar, changelog display). User-visible UI addition.

4. **NEW: `core/process_events.py` (104 lines)** — Brand-new event bus system (ProcessEvent enum + callbacks). Not extracted from existing patterns — old code had no event system.

5. **NEW: `core/app_state.py` (53 lines)** — New dataclass, not extracted from anywhere.

6. **NEW: `upgrade_exe.py` (258 lines)** — New release publishing script (developer tool).

7. **`build_exe_v2.py`** — New --test flag, channel field, entry point changed to __main__.py. Supports dual-channel auto-update feature.

8. **`ui_qt/pages/about_launcher_page.py`** — New "检查更新" (Check for Update) button/card added.

9. **`services/version_service.py`** — New `_get_tag_commit_via_api()` method adds API-first strategy for tag resolution (behavior change to update flow).

### Behavior Changes Beyond Allowed Scope

10. **`core/process_manager.py`** — `DialogHelper` replaced with native `QMessageBox` (UX change: loss of themed dialogs, Chinese button text). `emit_event()` calls added throughout. `_post_to_ui()` adds Tkinter fallback path.

11. **`services/announcement_service.py`** — Beyond the allowed malformed JSON fix: massive refactoring + `after_idle` changed to `after(0)` for popup dispatch + defensive `getattr` guarding on `root`.

### Bug Found

12. **`core/process_manager.py`** — `import shutil` removed but `shutil.which("wmic")` still called at line ~545. Silent NameError on Windows disables wmic-based process detection when psutil unavailable.

### Items Within Scope

- `config/manager.py` — atomic_write_json is a reliability enhancement (OK), config structure/values unchanged (OK)
- `utils/pip.py` — error_code dual-write is additive (OK per task-9 plan)
- `ui_qt/pages/launch/` sections — Legitimate extraction from launch_page.py (OK, though minor additions like "显示命令行窗口" checkbox)
- `core/version_workers.py` — Extracted from qt_app.py (OK, though adds retry logic)
- `comfyui_launcher_pyqt.py` — Safe launch_gui() extraction (OK)
- Deleted test files — All 13 were hardcoded-path tests, documented in .deleted-tests-list.txt (OK)
- Contract matrix (task-2) — All 14 interface, 7 event, 6 config, 5 CLI contracts preserved per task-11 evidence (OK)
- Locked decisions — All 4 preserved (OK)
- Task-11 regression/contract diff — PASS, 0 breaking changes detected, coverage 50%→54% (OK)

