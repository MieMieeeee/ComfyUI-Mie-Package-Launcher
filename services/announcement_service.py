from pathlib import Path
from urllib.request import urlopen, Request
import json
from datetime import datetime
import hashlib


class AnnouncementService:
    def __init__(self, app):
        self.app = app
        self._built_in_sources = [
            "https://gitee.com/MieMieeeee/comfyui-mie-resources/raw/master/launcher/announcements/index.json",
        ]
        self._last_data = None

    def _log(self, level: str, msg: str, *args):
        logger = getattr(self.app, 'logger', None)
        if logger:
            try:
                fn = getattr(logger, level, logger.info)
                fn(msg, *args)
            except Exception:
                pass

    def _get_sources(self):
        cfg = self.app.config or {}
        ann = cfg.get("announcement", {})
        src = (ann.get("source_url") or "").strip()
        backups = ann.get("fallback_urls") or []
        urls = []
        if src:
            urls.append(src)
        for u in backups:
            try:
                t = (u or "").strip()
                if t:
                    urls.append(t)
            except Exception:
                pass
        if not urls:
            try:
                self._log('info', 'announcement: using built-in defaults count=%d', len(self._built_in_sources))
            except Exception:
                pass
            urls = list(self._built_in_sources)
        try:
            self._log('info', 'announcement: sources resolved primary=%s fallback_count=%d total=%d', src or '-', len(backups or []), len(urls))
        except Exception:
            pass
        return urls

    def _get_cache_file(self):
        try:
            base = Path.cwd() / "launcher"
        except Exception:
            base = Path("launcher")
        try:
            base.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        return base / "announcement_cache.txt"

    def _get_seen_file(self):
        try:
            base = Path.cwd() / "launcher"
        except Exception:
            base = Path("launcher")
        try:
            base.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        return base / "announcement_seen.json"

    def _load_seen(self):
        try:
            f = self._get_seen_file()
            if f.exists():
                return set(json.loads(f.read_text(encoding="utf-8")) or [])
        except Exception:
            pass
        return set()

    def _mark_seen(self, aid: str):
        try:
            f = self._get_seen_file()
            seen = []
            try:
                if f.exists():
                    seen = json.loads(f.read_text(encoding="utf-8")) or []
            except Exception:
                seen = []
            if aid and aid not in seen:
                seen.append(aid)
                f.write_text(json.dumps(seen, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _compute_id(self, data: dict) -> str:
        try:
            key = f"{data.get('title') or ''}\n{data.get('content') or ''}\n{data.get('source') or ''}"
            return hashlib.sha256(key.encode('utf-8', errors='ignore')).hexdigest()
        except Exception:
            return ""

    def fetch(self):
        urls = self._get_sources()
        self._log('info', 'announcement: fetching from %d sources', len(urls))
        headers = {"User-Agent": "ComfyUI-Launcher", "Accept": "application/json, text/plain"}
        for u in urls:
            try:
                self._log('debug', 'announcement: request url=%s', u)
                req = Request(u, headers=headers)
                with urlopen(req, timeout=2.5) as resp:
                    raw = resp.read()
                    try:
                        self._log('debug', 'announcement: response bytes=%d', len(raw))
                    except Exception:
                        pass
                    txt = raw.decode("utf-8", errors="ignore").strip()
                    if not txt:
                        continue
                    if txt.startswith("{"):
                        try:
                            obj = json.loads(txt)
                        except Exception:
                            obj = {"title": "公告", "content": txt}
                        if isinstance(obj.get("items"), list):
                            try:
                                self._log('debug', 'announcement: index items=%d', len(obj.get('items') or []))
                            except Exception:
                                pass
                            items_acc = []
                            for it in obj.get("items"):
                                t = (it.get("title") or "").strip() or "公告"
                                c = (it.get("content") or "").strip()
                                ru = it.get("rules") or {}
                                mv = it.get("min_version")
                                Mv = it.get("max_version")
                                al = it.get("allow_versions")
                                de = it.get("deny_versions")
                                ve = it.get("version") or it.get("version_expr")
                                sa = it.get("start_at")
                                ea = it.get("end_at")
                                if mv or Mv or al or de or ve or sa or ea:
                                    ru = {"min_version": mv, "max_version": Mv, "allow_versions": al, "deny_versions": de, "version": ve, "start_at": sa, "end_at": ea}
                                try:
                                    self._log('debug', 'announcement: candidate title=%s rules=%s', t, ru)
                                except Exception:
                                    pass
                                if ru and not self._is_allowed(ru):
                                    continue
                                if ru and not self._in_time_window(ru):
                                    continue
                                url2 = (it.get("url") or "").strip()
                                if url2 and not c:
                                    try:
                                        r2 = Request(url2, headers=headers)
                                        with urlopen(r2, timeout=2.5) as resp2:
                                            raw2 = resp2.read()
                                            tx2 = raw2.decode("utf-8", errors="ignore").strip()
                                            if tx2.startswith("{"):
                                                try:
                                                    o2 = json.loads(tx2)
                                                except Exception:
                                                    o2 = {"title": t, "content": tx2}
                                                t = (o2.get("title") or "").strip() or t
                                                c = (o2.get("content") or "").strip() or tx2
                                            else:
                                                c = tx2
                                    except Exception:
                                        continue
                                if c:
                                    items_acc.append({"title": t, "content": c, "source": url2 or u, "rules": ru})
                            # 聚合所有满足条件的条目
                            if items_acc:
                                agg = []
                                for i, itz in enumerate(items_acc, 1):
                                    agg.append(f"【{itz.get('title') or '公告'}】\n{itz.get('content') or ''}")
                                sep = "\n\n" + ("-" * 64) + "\n\n"
                                content_all = sep.join(agg)
                                self._log('info', 'announcement: aggregated %d items from index', len(items_acc))
                                return {"title": f"公告（{len(items_acc)} 条）", "content": content_all, "source": u, "rules": {}}
                            continue
                        redir = (obj.get("redirect") or "").strip()
                        if redir:
                            try:
                                r2 = Request(redir, headers=headers)
                                with urlopen(r2, timeout=2.5) as resp2:
                                    raw2 = resp2.read()
                                    tx2 = raw2.decode("utf-8", errors="ignore").strip()
                                    if tx2.startswith("{"):
                                        try:
                                            o2 = json.loads(tx2)
                                        except Exception:
                                            o2 = {"title": "公告", "content": tx2}
                                        tt = (o2.get("title") or "").strip() or "公告"
                                        cc = (o2.get("content") or "").strip() or tx2
                                        ru = o2.get("rules") or {}
                                        mv = o2.get("min_version")
                                        Mv = o2.get("max_version")
                                        al = o2.get("allow_versions")
                                        de = o2.get("deny_versions")
                                        ch = o2.get("channels")
                                        sa = o2.get("start_at")
                                        ea = o2.get("end_at")
                                        if mv or Mv or al or de or ch or sa or ea:
                                            ru = {"min_version": mv, "max_version": Mv, "allow_versions": al, "deny_versions": de, "channels": ch, "start_at": sa, "end_at": ea}
                                        self._log('info', 'announcement: redirect loaded url=%s title=%s', redir, tt)
                                        return {"title": tt, "content": cc, "source": redir, "rules": ru}
                                    else:
                                        self._log('info', 'announcement: redirect loaded url=%s text', redir)
                                        return {"title": "公告", "content": tx2, "source": redir, "rules": {}}
                            except Exception:
                                pass
                        title = (obj.get("title") or "").strip() or "公告"
                        content = (obj.get("content") or "").strip() or txt
                        rules = obj.get("rules") or {}
                        min_v = obj.get("min_version")
                        max_v = obj.get("max_version")
                        allow = obj.get("allow_versions")
                        deny = obj.get("deny_versions")
                        ve = obj.get("version") or obj.get("version_expr")
                        sa = obj.get("start_at")
                        ea = obj.get("end_at")
                        if min_v or max_v or allow or deny or ve or sa or ea:
                            rules = {"min_version": min_v, "max_version": max_v, "allow_versions": allow, "deny_versions": deny, "version": ve, "start_at": sa, "end_at": ea}
                        self._log('info', 'announcement: single item loaded title=%s', title)
                        return {"title": title, "content": content, "source": u, "rules": rules}
                    else:
                        self._log('info', 'announcement: plain text loaded from %s', u)
                        return {"title": "公告", "content": txt, "source": u, "rules": {}}
            except Exception:
                continue
        self._log('warning', 'announcement: all sources failed or empty')
        return None

    def _load_build_params(self):
        try:
            import sys, json as _json
            from pathlib import Path as _P
            candidates = []
            try:
                candidates.append(_P(getattr(sys, '_MEIPASS', '')) / 'build_parameters.json')
            except Exception:
                pass
            try:
                candidates.append(_P(sys.executable).resolve().parent / 'build_parameters.json')
            except Exception:
                pass
            try:
                candidates.append(_P(__file__).resolve().parents[1] / 'build_parameters.json')
            except Exception:
                pass
            try:
                candidates.append(_P.cwd() / 'build_parameters.json')
            except Exception:
                pass
            params = {}
            for p in candidates:
                try:
                    if p.exists():
                        with open(p, 'r', encoding='utf-8') as f:
                            params = _json.load(f) or {}
                        break
                except Exception:
                    pass
            ver = str(params.get('version') or '').strip()
            mode = str(params.get('mode') or '').strip()
            self._log('debug', 'announcement: build params version=%s mode=%s', ver, mode)
            return {"version": ver, "mode": mode}
        except Exception:
            return {"version": "", "mode": ""}

    def _version_tuple(self, s: str):
        try:
            v = (s or '').strip()
            if v.startswith('v') or v.startswith('V'):
                v = v[1:]
            parts = v.split('.')
            nums = []
            for p in parts:
                try:
                    nums.append(int(''.join(ch for ch in p if ch.isdigit())))
                except Exception:
                    nums.append(0)
            while len(nums) < 3:
                nums.append(0)
            return tuple(nums[:3])
        except Exception:
            return (0, 0, 0)

    def _is_allowed(self, rules: dict) -> bool:
        try:
            bp = self._load_build_params()
            cur_v = self._version_tuple(bp.get('version') or '')
            # 1) 解析 version 表达式，支持 > >= < <= == * 多条件（AND）
            ve = (rules.get('version') or '').strip()
            if ve:
                if not self._match_version_expr(ve, cur_v):
                    return False
            # 2) 兼容旧字段：min/max/allow/deny
            min_v = self._version_tuple(rules.get('min_version') or '') if rules.get('min_version') else None
            max_v = self._version_tuple(rules.get('max_version') or '') if rules.get('max_version') else None
            allow = rules.get('allow_versions') or None
            deny = rules.get('deny_versions') or None
            if deny:
                ds = [str(x).strip() for x in (deny if isinstance(deny, list) else [deny]) if str(x).strip()]
                if ds:
                    cur_vs = (bp.get('version') or '').strip()
                    if cur_vs in ds:
                        return False
            if allow:
                as_ = [str(x).strip() for x in (allow if isinstance(allow, list) else [allow]) if str(x).strip()]
                if as_:
                    cur_vs = (bp.get('version') or '').strip()
                    if cur_vs not in as_:
                        return False
            if min_v and cur_v < min_v:
                return False
            if max_v and cur_v > max_v:
                return False
            return True
        except Exception:
            return True

    def _match_version_expr(self, expr: str, cur_v: tuple[int, int, int]) -> bool:
        try:
            e = expr.strip()
            if not e:
                return True
            if e == '*':
                return True
            parts = [p for p in e.replace('&&', ' ').replace(',', ' ').split() if p]
            for p in parts:
                op = None
                val = p
                for candidate in ('>=', '<=', '==', '>', '<'):
                    if p.startswith(candidate):
                        op = candidate
                        val = p[len(candidate):]
                        break
                v_tup = self._version_tuple(val)
                if op == '==':
                    if not (cur_v == v_tup):
                        return False
                elif op == '>=':
                    if not (cur_v >= v_tup):
                        return False
                elif op == '<=':
                    if not (cur_v <= v_tup):
                        return False
                elif op == '>':
                    if not (cur_v > v_tup):
                        return False
                elif op == '<':
                    if not (cur_v < v_tup):
                        return False
                else:
                    # 默认为相等
                    if not (cur_v == v_tup):
                        return False
            return True
        except Exception:
            return True

    def _in_time_window(self, rules: dict) -> bool:
        try:
            sa = (rules.get('start_at') or '').strip()
            ea = (rules.get('end_at') or '').strip()
            if not sa and not ea:
                return True
            now = datetime.utcnow()
            def _parse(s):
                for fmt in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d'):
                    try:
                        return datetime.strptime(s, fmt)
                    except Exception:
                        pass
                return None
            if sa:
                ps = _parse(sa)
                if ps and now < ps:
                    self._log('info', 'announcement: outside start window start_at=%s now_utc=%s', sa, now.isoformat())
                    return False
            if ea:
                pe = _parse(ea)
                if pe and now > pe:
                    self._log('info', 'announcement: outside end window end_at=%s now_utc=%s', ea, now.isoformat())
                    return False
            return True
        except Exception:
            return True

    def show_if_available(self):
        ann_cfg = self.app.config.get("announcement", {}) if isinstance(self.app.config, dict) else {}
        enabled = bool(ann_cfg.get("enabled", True))
        self._log('info', 'announcement: start check enabled=%s', enabled)
        if not enabled:
            return
        import threading
        def worker():
            data = self.fetch()
            if not data:
                try:
                    cache = self._get_cache_file()
                    if cache.exists():
                        txt = cache.read_text(encoding="utf-8", errors="ignore").strip()
                        if txt:
                            self._log('info', 'announcement: using cache for popup size=%d', len(txt))
                            def _show_cache():
                                try:
                                    from PyQt5 import QtWidgets
                                    QtWidgets.QMessageBox.information(getattr(self.app, 'window', None) or None, "公告", txt)
                                except Exception:
                                    pass
                            try:
                                self.app.root.after(0, _show_cache)
                            except Exception:
                                pass
                        else:
                            try:
                                (Path.cwd() / 'launcher' / 'announcement_debug.log').write_text('no_data_and_empty_cache', encoding='utf-8')
                            except Exception:
                                pass
                            self._log('warning', 'announcement: no data and cache empty')
                except Exception:
                    pass
                return
            rules = data.get("rules") or {}
            self._log('debug', 'announcement: rules=%s', rules)
            if rules and not self._is_allowed(rules):
                try:
                    (Path.cwd() / 'launcher' / 'announcement_debug.log').write_text('blocked_by_rules', encoding='utf-8')
                except Exception:
                    pass
                self._log('info', 'announcement: blocked by rules')
                return
            aid = self._compute_id(data)
            try:
                seen = self._load_seen()
                if aid and aid in seen:
                    self._log('info', 'announcement: already seen id=%s', aid[:8])
                    return
            except Exception:
                pass
            try:
                mf = self._get_seen_file().parent / 'announcement_muted.json'
                if mf.exists():
                    lst = json.loads(mf.read_text(encoding='utf-8')) or []
                    if aid and aid in lst:
                        self._log('info', 'announcement: muted id=%s', aid[:8])
                        return
            except Exception:
                pass
            title = data.get("title") or "公告"
            content = data.get("content") or ""
            try:
                self._last_data = data
            except Exception:
                pass
            try:
                cache = self._get_cache_file()
                cache.write_text(content or "", encoding="utf-8")
                self._log('debug', 'announcement: cache updated size=%d', len(content))
            except Exception:
                pass
            def _show_popup():
                try:
                    from PyQt5 import QtWidgets, QtCore
                    self._log('info', 'announcement: show title=%s size=%d source=%s', title, len(content), data.get('source'))
                    dlg = QtWidgets.QDialog(getattr(self.app, 'window', None) or None)
                    dlg.setWindowTitle(title)
                    layout = QtWidgets.QVBoxLayout(dlg)
                    text = QtWidgets.QTextEdit()
                    text.setReadOnly(True)
                    text.setPlainText(content)
                    layout.addWidget(text)
                    btns = QtWidgets.QDialogButtonBox()
                    ack_btn = btns.addButton("知道了", QtWidgets.QDialogButtonBox.AcceptRole)
                    mute_btn = btns.addButton("不再弹出", QtWidgets.QDialogButtonBox.DestructiveRole)
                    layout.addWidget(btns)
                    def _ack():
                        try:
                            if aid:
                                self._mark_seen(aid)
                                self._log('debug', 'announcement: marked seen id=%s', aid[:8])
                        except Exception:
                            pass
                        dlg.accept()
                    def _mute():
                        try:
                            if aid:
                                mf2 = self._get_seen_file().parent / 'announcement_muted.json'
                                lst2 = []
                                try:
                                    if mf2.exists():
                                        lst2 = json.loads(mf2.read_text(encoding='utf-8')) or []
                                except Exception:
                                    lst2 = []
                                if aid not in lst2:
                                    lst2.append(aid)
                                    mf2.write_text(json.dumps(lst2, ensure_ascii=False, indent=2), encoding='utf-8')
                                self._log('info', 'announcement: muted id=%s', aid[:8])
                        except Exception:
                            pass
                        dlg.accept()
                    ack_btn.clicked.connect(_ack)
                    mute_btn.clicked.connect(_mute)
                    dlg.resize(max(560, dlg.sizeHint().width()), max(380, dlg.sizeHint().height()))
                    dlg.setModal(True)
                    dlg.show()
                except Exception:
                    pass
            try:
                self.app.root.after_idle(_show_popup)
            except Exception:
                pass
        try:
            threading.Thread(target=worker, daemon=True).start()
        except Exception:
            pass

    def show_cached_popup(self):
        try:
            data = self._last_data
        except Exception:
            data = None
        if not data:
            try:
                cache = self._get_cache_file()
                if cache.exists():
                    txt = cache.read_text(encoding="utf-8", errors="ignore").strip()
                    if txt:
                        data = {"title": "公告", "content": txt}
            except Exception:
                pass
        if not data:
            try:
                from PyQt5 import QtWidgets
                QtWidgets.QMessageBox.information(getattr(self.app, 'window', None) or None, "公告", "暂无公告")
            except Exception:
                pass
            return
        title = data.get("title") or "公告"
        content = data.get("content") or ""
        def _show():
            try:
                from PyQt5 import QtWidgets
                dlg = QtWidgets.QDialog(getattr(self.app, 'window', None) or None)
                dlg.setWindowTitle(title)
                layout = QtWidgets.QVBoxLayout(dlg)
                text = QtWidgets.QTextEdit()
                text.setReadOnly(True)
                text.setPlainText(content)
                layout.addWidget(text)
                btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok)
                layout.addWidget(btns)
                btns.accepted.connect(dlg.accept)
                dlg.resize(max(560, dlg.sizeHint().width()), max(380, dlg.sizeHint().height()))
                dlg.setModal(True)
                dlg.show()
            except Exception:
                pass
        try:
            self.app.root.after(0, _show)
        except Exception:
            pass
