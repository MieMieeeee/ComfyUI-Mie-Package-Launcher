# Review Task: plugin (custom_nodes) update subsystem

You are reviewing a PyQt5 Windows launcher for ComfyUI. This is a READ-ONLY review.
Do NOT modify any file. Do NOT run any command that writes to disk.

## Scope

Review the "plugin update" (custom_nodes update) subsystem for correctness bugs,
design weaknesses, and performance problems.

Files to review (read them in full):
- `services/plugin_service.py`   (~2100 lines) - business logic layer
- `ui_qt/pages/plugins_page.py`  (~2200 lines) - UI layer: list, selection, progress
- `ui_qt/qt_app.py`              - orchestration, progress dialogs, background tasks
  (only the plugin-related parts, roughly lines 4700-5150)
- `core/plugin_normalize.py`     - result normalization
- `services/package_update_service.py` (only the plugin section)

## Context: recent changes already made (DO NOT report these again)

These were just fixed and verified with tests. Skip them:
1. CNR plugins used to be silently skipped by force-update; now they reinstall via
   `install(cnr_id)`.
2. `_plugin_queue_identity` had a bug: `.tracking` was checked with `is_dir()` but
   Manager writes it as a FILE; also cnr_id was only read from `.git/.cnr-id` which
   CNR plugins do not have. Both fixed.
3. `outdated_plugins` was serial (50s for 31 git plugins); now 8-thread parallel (7s).
4. After update, the "has update" markers were lost because `populate()` cleared them.
   Now preserved via `repopulate_preserving_outdated`.
5. Refresh (async) vs on_done (sync) ordering was inverted; fixed with a `before_done` hook.
6. Added a "select all" button; selection state now survives tab filtering and refresh.
7. Uninstall used `glob(f"{base}*")` and could delete same-prefix sibling plugins.
   Now uses exact matching. Fixed.
8. `_git_out`/`_git_run` now pass proxy env (GIT_CONFIG_GLOBAL).
9. `update_selected`/`update_all` return values are now checked for errors.

## What to focus on

### A. Correctness and latent bugs
- Thread safety: caches (`_git_info_cache`, `_reg_cache`, `_reg_index_cache`,
  `_api_probe_cache`, `_cnr_nomove`) under the new concurrency in `outdated_plugins`.
- Cache invalidation: are all write paths evicting? Stale data risks.
- `.disabled/` directory plugins: `list_installed` returns bare dir names like
  `10s-comfy-nodes@1_0_0` for entries inside `custom_nodes/.disabled/`. Do all
  downstream paths resolve those correctly, or do they silently do nothing?
- Exception handling that swallows real errors (`except: pass`).
- Edge cases: empty list, single item, plugin deleted/renamed externally mid-operation.
- Error results: does the UI always tell the truth about what actually happened?

### B. Performance
- Any remaining serial IO that could be parallelized.
- Redundant disk/network work (e.g. repeated parsing of the same JSON cache file).
- Cache TTL sanity.

### C. Design consistency
- The three update paths (`run_update_all` / `run_update_selected` / `run_force_update`)
  are near-duplicates. Is the duplication risky (they can drift apart)?
- API path (Manager HTTP) vs cm-cli wrapper fallback: consistent degradation?
- The `_cnr_nomove` suppression set is in-memory only, lost on restart. Is that OK?

### D. Repo conventions (see `AGENTS.md` at repo root - read it first)
The repo has documented constraints, e.g.:
- cm-cli on Windows takes ~5.5 minutes due to a known Manager bug; the `cm_fast`
  wrapper exists to avoid it. Verify new code respects this.
- Manager HTTP API first, cm-cli as fallback.
- GUI colors MUST come from `theme_manager`; hardcoded `#rrggbb` is forbidden.
- Python source contains Chinese comments; do not use shell text tools to read
  source files if you can avoid it (encoding hazard), prefer your native read tool.

Check whether the code violates any of these.

## Output format

Write a markdown report in Chinese (中文) with these sections:

### 高危 (High) - user-visible errors, data loss, deadlocks
### 中危 (Medium) - UX problems or clear tech debt
### 低危 (Low) - style / readability

For each finding include:
- 一句话问题描述 (what actually goes wrong for the user)
- 代码位置 `文件路径:行号`
- 修复建议 (concrete, not "consider improving")

Rules:
- Only report issues you have code evidence for. No speculation.
- If you need to verify a hypothesis, say HOW to verify it, don't assert it.
- Do not list things that work correctly.
- Be concise. No filler.

Write the final report to `notes/review_plugin_update_report.md` — wait, you are in
read-only mode, so instead output the full report as your final answer text.
