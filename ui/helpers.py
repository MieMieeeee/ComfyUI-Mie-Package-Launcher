from pathlib import Path

def truncate_middle(text: str, max_chars: int) -> str:
    if not text or max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return text[:max_chars]
    keep = max_chars - 1
    head = keep // 2
    tail = keep - head
    return text[:head] + "…" + text[-tail:]

def compute_elided_path_text(app, max_chars: int = 64) -> str:
    try:
        full = getattr(app, "_path_full_text", None)
        if not full:
            try:
                # 多环境支持：读激活环境的 comfyui_root（老的 comfyui_path 是死字段）
                paths = app.get_active_paths() if hasattr(app, "get_active_paths") \
                    else app.config.get("paths", {})
                full = paths.get("comfyui_root", "")
            except Exception:
                full = ""
        if not full:
            return ""
        return truncate_middle(str(full), max_chars)
    except Exception:
        try:
            return truncate_middle(str(getattr(app, "_path_full_text", "")), max_chars)
        except Exception:
            return ""