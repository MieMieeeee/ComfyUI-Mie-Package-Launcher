# Task: Fix long-failing test cases under tests/unit

You are working in `F:\ComfyUI-Mie-Package-Launcher` (ComfyUI launcher, PyQt5, Windows).
Goal: bring every file listed below back to "all passed (or passed + justified SKIPPED)",
then write a repair report.

## Encoding guardrails (read first — this repo has Chinese comments)

- Source and test files contain Chinese comments/docstrings encoded in UTF-8.
- When you must read a file through a shell, use `Get-Content -Encoding UTF8` (pwsh)
  or `python -c "print(open(p, encoding='utf-8').read())"`. NEVER rely on default
  encoding — on this machine a default-encoded read garbles UTF-8 Chinese into mojibake.
- Prefer your native file-edit tool for edits. NEVER do shell read-modify-write
  round trips on files containing Chinese.
- After editing, verify `git diff --stat <file>` shows only intended hunks; if you see
  whole-file rewrites or mojibake in the diff, revert that edit and redo it properly.
- Write the final report in English.

## How to run tests (pitfalls)

- Command: `python -m pytest tests/unit/<file>.py` (Git Bash or cmd).
- **Do NOT pass an extra `-q`**: `pyproject.toml` addopts already includes `-q`;
  adding another makes `-qq` which suppresses the summary line.
- Running the whole `tests/unit` directory crashes natively on this machine (see
  group E). Run files one by one.
- Repo conventions are documented in `AGENTS.md` (theme colors via theme_manager,
  render guard, multi-environment paths, etc.).

## Failure inventory (all verified as pre-existing via git-stash A/B on clean HEAD)

### A. Hardcoded stale assertion

1. `test_cli_cmd_info.py::TestInfo::test_json_output` — line 51:
   `assert '2026-09-03 11:13:47' == '2026-07-25 17:10:12'`.
   Root cause direction: the test hardcodes the `built_at` value from
   `build_parameters.json`, which is a generated file that changes every build.
   The test already patches `_resolve_version`; the correct fix is most likely to
   also patch `_resolve_build_time` (defined in `core/cli/cmd_info.py`) so the
   assertion does not depend on the generated file.

### B. Mock mismatch / stale tests (classify product bug vs stale test before fixing)

2. `test_version_workers.py::TestComfyUIVersionWorker::test_successful_version_detection_with_tag`
   — line 343: `assert 'v1.0.0' in 'abc1234'`. The version worker failed to detect
   the tag; likely the mocked git output no longer matches the parsing logic
   (git version differences?). 
3. `test_version_page.py` — 4 failures: `test_local_commits_work_calls_fetch_all_commits`,
   `test_fetch_and_load_work_skips_when_git_lock_busy`,
   `test_fetch_and_load_work_loads_commits_after_fetch`,
   `test_local_loader_load_end_to_end`. Symptom: `assert [] == [['abc', ...]]` —
   mocked commit data never got loaded. Suspect wrong patch target or the page's
   loader behavior changed. Classify each as stale test or product regression.
4. `test_net.py` — 7 ERRORS (not failures): the whole `TestApplyPipProxySettings`
   class (5) plus 2 in `TestNetworkService`. Whole-class errors usually mean a
   fixture / import / nonexistent patch target. Inspect the error details first.
5. `test_core_tools.py::TestCoreTools::test_probe_is_http_reachable_fallback`.
6. `test_config_service.py::TestConfigServiceCharacterization::test_service_save_then_reload_returns_equivalent_config`.
7. `test_log_package_service.py::TestCreateLogPackage::test_writes_zip_with_all_three_files_when_all_exist`
   — line 47: `assert 'comfyui.log' in {'config.json', 'launcher.log', 'manifest.txt'}` —
   the produced zip is missing comfyui.log. Classify product bug vs test data issue.

### C. model_path: 21 failures across two files (the big cluster — find the common root cause first)

8. `test_model_path_service.py` — 7 failures:
   `TestLoadCurrentConfig::test_load_current_config_parses_valid_yaml`,
   `TestUpdateMapping::test_update_mapping_creates_yaml_file`,
   `TestUpdateMapping::test_update_mapping_writes_mie_launcher_block`,
   `TestUpdateMapping::test_update_mapping_includes_base_path`,
   `TestUpdateMapping::test_update_mapping_creates_backup_file`,
   `TestUpdateMappingSDStyle::test_update_mapping_sd_style_generates_correct_yaml`.
   Assertions are mostly `assert False` (yaml file / backup file never created).
9. `test_model_path_service_multi.py` — 14 failures, assertions include
   `assert False is True`, `assert 0 == 1`, `assert '' == 'E:/Legacy'`.
   System under test: `services/model_path_service.py` — the "model path config"
   service that writes `extra_model_paths.yaml`, creates a `.yaml.bak` backup
   before writing, and handles multi-library mapping. 21 failures across two
   files most likely share one root cause (e.g. the service now expects a new
   interface/field on the app mock that the tests never provide, or a shared
   helper's behavior changed).

### D. Download sha256 verification: 2 failures

10. `test_launcher_update_service.py::TestDownloadSha256Verification`:
    `test_download_update_skips_sha256_when_empty`,
    `test_download_update_verifies_sha256_success`.
    NOTE: the file `tests/unit/test_launcher_update_service.py` MAY be edited only
    if the root cause is in the test itself. If the root cause is in
    `services/launcher_update_service.py` product code, DO NOT edit it — document
    the finding in the report only (that file has uncommitted in-flight work).

### E. Native crash (sip ABI access violation — environment limitation)

11. `test_close_to_tray.py::test_no_ask_uses_saved_minimize` — line 48 imports
    `ui_qt.qt_app`, and the module-level statement at `ui_qt/qt_app.py:765`
    (`class PyQtLauncher(QtWidgets.QMainWindow, process_events.ProcessCallback)`)
    triggers an access violation that hard-kills the process with no pytest summary.
    The repo already has an ESTABLISHED guard pattern for exactly this environment
    limitation — see `tests/unit/test_launch_section_dpi_resize.py:230/251/268/290`
    and `tests/unit/test_screen_change_scaling.py:297` (read the code to see how
    the "probe whether import crashes" guard is implemented). Add the same guard
    to `test_close_to_tray.py`. Do NOT delete the test.
    Note: the two referenced files already have working guards (they print SKIPPED
    and then the process still dies during final teardown on this machine — that
    teardown crash is a known environment symptom and is OUT OF SCOPE here).

## Fix rules (hard constraints)

1. For every failure, classify the root cause into one of three buckets:
   product bug / stale test (mock mismatch, hardcoded values) / environment limit.
   Fixing product code takes priority over changing tests. Any assertion change
   must come with the root-cause justification. Do NOT weaken assertions just to
   get green.
2. Product-code fixes must follow `AGENTS.md` (no hardcoded theme colors, no raw
   QMessageBox, etc.).
3. Environment-limit cases use the repo's existing SKIPPED guard pattern with a
   stated reason.
4. **Do NOT touch these files** (uncommitted in-flight work, out of scope):
   `core/version.py`, `build.py`, `upgrade_exe.py`, `utils/logging.py`,
   `core/cli/cmd_info.py`, `services/launcher_update_service.py`,
   `services/version_service.py`, `ui_qt/pages/about_launcher_page.py`,
   `ui_qt/pages/launch/launch_controls_section.py`, `AGENTS.md`, `cli.md`,
   `docs/auto-update.md`, `build_parameters.json`,
   `tests/unit/test_version_source.py`, `tests/unit/test_launch_options_alignment.py`,
   `tests/unit/test_checkout_local_modifications.py`,
   `tests/unit/test_launcher_update_service.py` (exception: see group D note).
5. Forbidden: `git commit`, `git stash`, `git checkout --`, `git reset`.
   Never modify `launcher/config.json` (local runtime config).
6. After fixing, verify file by file: `python -m pytest tests/unit/<file>.py` —
   each target file must reach all passed (or passed + justified skipped).
7. Also re-run `python -m pytest tests/unit/test_plugin_service.py
   tests/unit/test_config_migrations.py` as a quick no-regression sanity set if
   you touch shared helpers.

## Deliverable

Write the repair report to `notes/codex_test_repair_report.md` (English), one entry
per failure: test id → root-cause class (product bug / stale test / env limit) →
one-line root cause → what files changed → verification command and its result.
End with: full list of modified files, and any unfixed items with reasons.
