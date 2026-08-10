"""整合包更新中心页面 + PackageApplyWorker（plan §5）。

PackageUpdatePage：卡片式布局，展示当前环境 + manifest 摘要 + 4 类 item 卡片（可勾选），
加载入口（本地文件 / URL / 粘贴 JSON），跑完显示 report 卡片。

PackageApplyWorker：把同步的 PackageUpdateService.apply() 包成异步 worker（plan §6.5.1）。
信号发回主线程，worker 内部绝不直接碰 widget（Qt 线程安全）。

主题：所有配色走 theme_manager.colors，禁硬编码 #rrggbb（AGENTS.md 主题规范）。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from PyQt5 import QtCore, QtWidgets

from .base_page import BasePage
from ui_qt.widgets import PrimaryButton, SecondaryButton
from ui_qt.widgets.dialog_helper import DialogHelper


# item kind → 风险徽章文案
_RISK_BADGE = {
    "core": "高风险",
    "model": "中风险",
    "plugin": "低风险",
    "dependency": "低风险",
}

# status → 报告卡片 marker
_STATUS_MARKER = {
    "ok": "✓", "ok_at_alt_path": "≈", "skipped": "⏭", "not_applicable": "○",
    "failed": "✗", "manual_required": "⏸", "pending": "·", "in_progress": "…",
}


class PackageApplyWorker(QtCore.QObject):
    """把同步的 PackageUpdateService.apply() 包成异步 worker。

    信号发回主线程；worker 内部绝不直接碰 widget（plan §6.5.1）。
    生命周期：page 持有引用（self._worker = worker），否则 Python GC 后 Qt 信号断；
    finished 触发后 thread.quit()+wait() 在 finally 做。
    """

    item_progress = QtCore.pyqtSignal(str, str, dict)  # (item_id, status, payload)
    finished = QtCore.pyqtSignal(dict)                 # (report)

    def __init__(self, service, manifest, item_ids=None, manual_decisions=None,
                 auto_yes=False, confirm_env_mismatch=None):
        super().__init__()
        self._service = service
        self._manifest = manifest
        self._item_ids = item_ids
        self._manual_decisions = manual_decisions or {}
        self._auto_yes = auto_yes
        self._confirm = confirm_env_mismatch
        self._thread = QtCore.QThread()
        self.moveToThread(self._thread)
        self._thread.started.connect(self._run)

    def start(self):
        self._thread.start()

    @QtCore.pyqtSlot()
    def _run(self):
        try:
            report = self._service.apply(
                self._manifest,
                item_ids=self._item_ids,
                manual_decisions=self._manual_decisions,
                auto_yes=self._auto_yes,
                confirm_env_mismatch=self._confirm,
                on_item=lambda iid, status, payload: self.item_progress.emit(iid, status, payload),
            )
            self.finished.emit(report)
        except Exception as e:
            self.finished.emit({"error": str(e), "summary": {"failed": 1}, "items": [],
                                "exit_hint": 1})
        finally:
            self._thread.quit()
            self._thread.wait()


class PackageUpdatePage(BasePage):
    """整合包更新中心页面（plan §5.2 卡片式布局）。"""

    def __init__(self, app, theme_manager, parent=None):
        super().__init__(theme_manager, parent)
        self.app = app
        self._page_title_refs = []

        _styles = theme_manager.styles if theme_manager else None
        self._px = _styles._px if _styles else (lambda b: b)
        self._pt = _styles._pt if _styles else (lambda b: b)

        self._manifest: dict | None = None
        self._manifest_source: str = ""
        self._item_checkboxes: dict[str, QtWidgets.QCheckBox] = {}
        self._model_decisions: dict[str, QtWidgets.QCheckBox] = {}  # model item_id → 「我已下载」
        self._worker: PackageApplyWorker | None = None
        self._apply_task_id: str | None = None
        self._apply_env_token: int = 0

        self._setup_ui()
        self.update_theme()

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------

    def _setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(self._px(16), self._px(16), self._px(16), self._px(16))
        layout.setSpacing(self._px(12))

        # 标题
        title = QtWidgets.QLabel("ComfyUI Mie 整合包更新中心")
        title.setStyleSheet(f"font-size: {self._pt(18)}pt; font-weight: bold;")
        self._title_label = title
        layout.addWidget(title)

        # 当前环境信息
        self._env_label = QtWidgets.QLabel("")
        self._env_label.setWordWrap(True)
        layout.addWidget(self._env_label)

        # 加载入口
        load_box = QtWidgets.QHBoxLayout()
        self._btn_file = SecondaryButton("选择本地文件...")
        self._btn_file.clicked.connect(self._on_load_file)
        self._btn_url = SecondaryButton("从 URL 加载...")
        self._btn_url.clicked.connect(self._on_load_url)
        self._btn_paste = SecondaryButton("粘贴 JSON")
        self._btn_paste.clicked.connect(self._on_load_paste)
        load_box.addWidget(self._btn_file)
        load_box.addWidget(self._btn_url)
        load_box.addWidget(self._btn_paste)
        load_box.addStretch()
        layout.addLayout(load_box)

        # manifest 摘要
        self._summary_label = QtWidgets.QLabel("")
        self._summary_label.setWordWrap(True)
        self._summary_label.setVisible(False)
        layout.addWidget(self._summary_label)

        # items 滚动区
        self._items_container = QtWidgets.QVBoxLayout()
        items_widget = QtWidgets.QWidget()
        items_widget.setLayout(self._items_container)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(items_widget)
        layout.addWidget(scroll, stretch=1)

        # 底部按钮
        bottom = QtWidgets.QHBoxLayout()
        self._btn_select_all = SecondaryButton("全选")
        self._btn_select_all.clicked.connect(self._on_select_all)
        self._btn_select_none = SecondaryButton("全不选")
        self._btn_select_none.clicked.connect(self._on_select_none)
        self._btn_apply = PrimaryButton("▶ 开始应用")
        self._btn_apply.clicked.connect(self._on_apply)
        bottom.addWidget(self._btn_select_all)
        bottom.addWidget(self._btn_select_none)
        bottom.addStretch()
        bottom.addWidget(self._btn_apply)
        layout.addLayout(bottom)

        # report 区（跑完显示）
        self._report_label = QtWidgets.QLabel("")
        self._report_label.setWordWrap(True)
        self._report_label.setVisible(False)
        layout.addWidget(self._report_label)

        self._refresh_env_display()

    # ------------------------------------------------------------------
    # 主题
    # ------------------------------------------------------------------

    def update_theme(self, theme_styles=None):
        super().update_theme(theme_styles)
        styles = theme_styles or self.theme_manager.styles
        c = self.theme_manager.colors
        # 标题
        self._title_label.setStyleSheet(
            f"font-size: {self._pt(18)}pt; font-weight: bold; color: {c.get('label')};")
        # env label
        self._env_label.setStyleSheet(f"color: {c.get('label_muted')};")
        self._summary_label.setStyleSheet(f"color: {c.get('label')};")
        self._report_label.setStyleSheet(f"color: {c.get('label')};")
        # 按钮
        self._btn_apply.setStyleSheet(styles.primary_button_style())
        for btn in (self._btn_file, self._btn_url, self._btn_paste,
                    self._btn_select_all, self._btn_select_none):
            btn.setStyleSheet(styles.secondary_button_style())

    # ------------------------------------------------------------------
    # 当前环境显示
    # ------------------------------------------------------------------

    def _refresh_env_display(self):
        try:
            cfg = self.app.config
            envs = cfg.get("environments", [])
            aid = cfg.get("active_env_id", "")
            name = next((e.get("name", "") for e in envs if e.get("id") == aid), "?")
            paths = self.app.get_active_paths() if hasattr(self.app, "get_active_paths") else {}
            root = paths.get("comfyui_root", "?")
            self._env_label.setText(f"当前环境: {name}    ComfyUI 根: {root}")
        except Exception:
            self._env_label.setText("当前环境: (读取失败)")

    # ------------------------------------------------------------------
    # 加载入口
    # ------------------------------------------------------------------

    def _svc(self):
        return self.app.services.package

    def _on_load_file(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "选择 manifest 文件", "", "JSON (*.json);;All Files (*)")
        if not path:
            return
        try:
            manifest, resolved = self._svc().load_source(path)
        except ValueError as e:
            DialogHelper.show_error(self, "加载失败", str(e))
            return
        self._set_manifest(manifest, f"文件: {resolved}")

    def _on_load_url(self):
        from ui_qt.widgets.custom_confirm_dialog import CustomConfirmDialog
        dlg = CustomConfirmDialog(
            self, title="从 URL 加载", content="粘贴 manifest 的 HTTPS URL：",
            buttons=[{"text": "取消", "role": "normal"}, {"text": "加载", "role": "primary"}],
            show_input=True, input_placeholder="https://...",
            theme_manager=self.theme_manager, min_width=480)
        if dlg.exec_() != QtWidgets.QDialog.Accepted or dlg.get_result() != 1:
            return
        url = dlg.get_input_text().strip()
        if not url:
            return
        try:
            manifest, resolved = self._svc().load_source(url)
        except ValueError as e:
            DialogHelper.show_error(self, "加载失败", str(e))
            return
        ok, err = self._svc().validate(manifest)
        if not ok:
            DialogHelper.show_error(self, "manifest 无效", err or "")
            return
        self._set_manifest(manifest, f"URL: {resolved}")

    def _on_load_paste(self):
        from ui_qt.widgets.custom_confirm_dialog import CustomConfirmDialog
        dlg = CustomConfirmDialog(
            self, title="粘贴 JSON", content="粘贴 manifest 的完整 JSON：",
            buttons=[{"text": "取消", "role": "normal"}, {"text": "加载", "role": "primary"}],
            show_input=True, input_placeholder='{"manifest_version": 1, ...}',
            theme_manager=self.theme_manager, min_width=520)
        if dlg.exec_() != QtWidgets.QDialog.Accepted or dlg.get_result() != 1:
            return
        text = dlg.get_input_text().strip()
        if not text:
            return
        try:
            from core.package_manifest import load_manifest_from_text
            manifest = load_manifest_from_text(text)
        except Exception as e:
            DialogHelper.show_error(self, "JSON 解析失败", str(e))
            return
        ok, err = self._svc().validate(manifest)
        if not ok:
            DialogHelper.show_error(self, "manifest 无效", err or "")
            return
        self._set_manifest(manifest, "粘贴的 JSON")

    # ------------------------------------------------------------------
    # manifest 设置 + 渲染卡片
    # ------------------------------------------------------------------

    def _set_manifest(self, manifest: dict, source: str):
        self._manifest = manifest
        self._manifest_source = source
        self._render_summary()
        self._render_items()
        self._report_label.setVisible(False)

    def _render_summary(self):
        m = self._manifest
        name = m.get("name") or m.get("id") or "(unnamed)"
        mid = m.get("id", "?")
        n = len(m.get("items", []))
        notes = m.get("notes_text", "")
        text = f"📋 {name}（{mid}）\n来源: {self._manifest_source}    共 {n} 项"
        if notes:
            text += f"\n备注: {notes[:200]}"
        self._summary_label.setText(text)
        self._summary_label.setVisible(True)

    def _render_items(self):
        # 清空旧卡片
        self._item_checkboxes.clear()
        self._model_decisions.clear()
        while self._items_container.count():
            w = self._items_container.takeAt(0).widget()
            if w:
                w.deleteLater()
        m = self._manifest
        if not m:
            return
        for item in m.get("items", []):
            card = self._build_item_card(item)
            self._items_container.addWidget(card)
        self._items_container.addStretch()

    def _build_item_card(self, item: dict) -> QtWidgets.QWidget:
        c = self.theme_manager.colors
        kind = item.get("kind", "?")
        iid = item.get("id", "?")
        title = item.get("title", iid)
        risk = _RISK_BADGE.get(kind, "")

        card = QtWidgets.QGroupBox()
        card.setTitle(f"[{kind}] {title}")
        card_layout = QtWidgets.QVBoxLayout(card)

        # 勾选 + 风险徽章
        top = QtWidgets.QHBoxLayout()
        cb = QtWidgets.QCheckBox("应用此项")
        cb.setChecked(True)
        self._item_checkboxes[iid] = cb
        top.addWidget(cb)
        risk_label = QtWidgets.QLabel(f"风险: {risk}")
        risk_label.setStyleSheet(f"color: {c.get('warning', '#e0a800')}; font-size: {self._pt(9)}pt;")
        top.addWidget(risk_label)
        top.addStretch()
        card_layout.addLayout(top)

        # 详情（按 kind）
        detail = self._item_detail(item)
        if detail:
            dl = QtWidgets.QLabel(detail)
            dl.setWordWrap(True)
            dl.setStyleSheet(f"color: {c.get('label_muted')}; font-size: {self._pt(9)}pt;")
            card_layout.addWidget(dl)

        # model 项特有：「我已下载」复选框 + 链接按钮
        if kind == "model":
            self._add_model_controls(card_layout, item)

        return card

    def _item_detail(self, item: dict) -> str:
        kind = item.get("kind")
        if kind == "core":
            sel = item.get("selection", {})
            return f"模式: {sel.get('mode')}    目标: {sel.get('ref', '')}"
        if kind == "plugin":
            return f"action: {item.get('action')}    spec: {item.get('spec', '(全部)')}"
        if kind == "dependency":
            pkgs = item.get("packages", [])
            specs = [p.get("spec", "") for p in pkgs]
            return f"packages: {', '.join(specs)}"
        if kind == "model":
            dest = item.get("dest", {})
            links = item.get("links", [])
            link_text = " | ".join(l.get("label", l.get("url", "")) for l in links) or "(无链接)"
            return f"→ {dest.get('category', '?')}/{dest.get('filename', '?')}\n链接: {link_text}"
        return ""

    def _add_model_controls(self, layout: QtWidgets.QVBoxLayout, item: dict):
        iid = item.get("id", "?")
        row = QtWidgets.QHBoxLayout()
        cb = QtWidgets.QCheckBox("我已下载")
        cb.toggled.connect(lambda checked, i=iid: self._on_model_verified(i, checked))
        self._model_decisions[iid] = cb
        row.addWidget(cb)
        # 打开链接按钮
        links = item.get("links", [])
        if links:
            btn_link = SecondaryButton("打开链接")
            btn_link.clicked.connect(lambda _, ls=links: self._open_first_link(ls))
            row.addWidget(btn_link)
        row.addStretch()
        layout.addLayout(row)

    def _open_first_link(self, links: list):
        from services.model_service import ModelService
        ms = getattr(self.app.services, "model", None)
        if ms is None:
            ms = ModelService(self.app)
        if links:
            ms.open_link(links[0].get("url", ""))

    def _on_model_verified(self, item_id: str, checked: bool):
        """「我已下载」勾选 → 调 verify_manual → 显示徽章。"""
        if not checked or not self._manifest:
            return
        item = next((i for i in self._manifest["items"] if i.get("id") == item_id), None)
        if not item:
            return
        try:
            ms = getattr(self.app.services, "model", None) or self._svc()._model_service()
            r = ms.verify_manual(item)
            status = r["status"]
            cb = self._model_decisions.get(item_id)
            if cb:
                marker = {"ok": "✓ 已就位", "missing": "✗ 找不到文件",
                          "checksum_mismatch": "✗ sha256 不匹配"}.get(status, status)
                cb.setText(f"我已下载 — {marker}")
        except Exception as e:
            cb = self._model_decisions.get(item_id)
            if cb:
                cb.setText(f"我已下载 — 校验失败: {e}")

    # ------------------------------------------------------------------
    # 全选 / 全不选
    # ------------------------------------------------------------------

    def _on_select_all(self):
        for cb in self._item_checkboxes.values():
            cb.setChecked(True)

    def _on_select_none(self):
        for cb in self._item_checkboxes.values():
            cb.setChecked(False)

    # ------------------------------------------------------------------
    # apply
    # ------------------------------------------------------------------

    def _on_apply(self):
        if not self._manifest:
            DialogHelper.show_info(self, "未加载", "请先加载一个 manifest")
            return
        # 组 item_ids + manual_decisions
        item_ids = [iid for iid, cb in self._item_checkboxes.items() if cb.isChecked()]
        if not item_ids:
            DialogHelper.show_info(self, "未选择", "请至少勾选一项")
            return
        manual_decisions: dict[str, str] = {}
        for iid, cb in self._model_decisions.items():
            if cb.isChecked():
                manual_decisions[iid] = "yes"

        # env-mismatch 弹窗回调（plan §6.5.3）
        def confirm_env(m):
            target = m.get("package_target", {})
            return DialogHelper.show_confirmation(
                self, "环境不匹配",
                f"此 manifest 适用于 {target.get('channel', '?')}，"
                f"当前环境可能不匹配。是否继续？")

        # 注册后台 task（plan §6.5.1：env 切换护栏自动生效）
        try:
            registry = self.app._bg_task_registry
            self._apply_task_id = registry.register(f"manifest:{self._manifest.get('id', '?')}")
        except Exception:
            self._apply_task_id = None
        self._apply_env_token = getattr(self.app, "_env_token", 0)

        self._worker = PackageApplyWorker(
            self._svc(), self._manifest,
            item_ids=item_ids, manual_decisions=manual_decisions,
            auto_yes=False, confirm_env_mismatch=confirm_env,
        )
        self._worker.item_progress.connect(self._on_item_progress)
        self._worker.finished.connect(self._on_apply_done)
        self._btn_apply.setEnabled(False)
        self._worker.start()

    def _on_item_progress(self, item_id: str, status: str, payload: dict):
        if self._apply_task_id is not None:
            try:
                cur = 0
                total = len(self._item_checkboxes)
                self.app._bg_task_registry.update(
                    self._apply_task_id,
                    status=f"[{item_id}] {status}",
                    progress=(cur, total) if total > 0 else (0, 0),
                )
            except Exception:
                pass

    def _on_apply_done(self, report: dict):
        # env_token 竞态防护（plan §6.5.2）
        if getattr(self.app, "_env_token", 0) != self._apply_env_token:
            self._persist_report(report)
            DialogHelper.show_info(
                self, "更新已完成",
                f"manifest {report.get('manifest_id', '?')} 的应用已在后台完成，"
                f"但你切换了环境，结果未刷新到当前页面。")
            self._cleanup_worker()
            return
        self._render_report(report)
        self._persist_report(report)
        self._cleanup_worker()

    def _render_report(self, report: dict):
        items = report.get("items", [])
        summary = report.get("summary", {})
        lines = ["运行结果:"]
        for it in items:
            status = it.get("status", "?")
            marker = _STATUS_MARKER.get(status, "?")
            iid = it.get("id", "?")
            suffix = ""
            if it.get("error"):
                suffix = f" — {it['error'][:60]}"
            lines.append(f"  {marker} {iid}: {status}{suffix}")
        lines.append(
            f"汇总: ok={summary.get('ok', 0)} skipped={summary.get('skipped', 0)} "
            f"failed={summary.get('failed', 0)} manual_required={summary.get('manual_required', 0)}")
        if report.get("error"):
            lines.append(f"错误: {report['error']}")
        self._report_label.setText("\n".join(lines))
        self._report_label.setVisible(True)

    def _persist_report(self, report: dict):
        """把 report 写到 launcher/manifests/runs/<run_id>.json（plan §6.7）。"""
        try:
            run_id = report.get("run_id", "unknown")
            runs_dir = Path("launcher/manifests/runs")
            runs_dir.mkdir(parents=True, exist_ok=True)
            (runs_dir / f"{run_id}.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8")
        except Exception:
            pass  # 持久化失败不影响 UI

    def _cleanup_worker(self):
        if self._apply_task_id is not None:
            try:
                has_failed = (self._worker is None or
                              self._worker is not None)  # report 已在 done 里
                self.app._bg_task_registry.complete(self._apply_task_id, error=False)
                self.app._bg_task_registry.remove(self._apply_task_id)
            except Exception:
                pass
            self._apply_task_id = None
        self._worker = None
        self._btn_apply.setEnabled(True)
