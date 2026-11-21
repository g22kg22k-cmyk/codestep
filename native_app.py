"""Native Tk desktop UI with real external Python/IDLE and Rust (rustc) sync."""
from __future__ import annotations

from datetime import date, timedelta
import io
import json
import keyword
import math
from pathlib import Path
import queue
import random
import re
import struct
import sys
import threading
import time
import tokenize
import tkinter as tk
from tkinter import filedialog, font as tkfont, messagebox, ttk
import wave

from code_executor import run_repl_command, run_workspace_script
from learning import (UNITS, LESSONS, QUESTIONS, SAMPLES, LESSON_BY_ID, QUESTION_BY_ID, LANGS, LEVELS,
                      ProgressStore, activity_today, add_activity, badges, compare_written_output, finish_lesson,
                      is_unlocked, next_lesson, streak)
from python_bridge import (WorkspaceManager, discover_editors, discover_python_runtime,
                           discover_rust_runtime, discover_setup_status, get_setup_catalog,
                           launch_default_editor, launch_folder, launch_idle,
                           launch_installer_terminal, launch_rust_terminal, launch_terminal,
                           launch_vscode, read_text_safe, run_rust_script, scan_deliverables,
                           text_digest, verify_workspace_question, write_text_safe)

BG = "#f4f7f5"
WHITE = "#ffffff"
SURFACE = "#f8faf9"
INK = "#1b2e26"
MUTED = "#5e7166"
GREEN = "#1b875b"
GREEN_HOVER = "#146d49"
PALE = "#e6f4ed"
PALE_HOVER = "#d5ecdf"
LINE = "#dce5df"
PY_BLUE = "#306998"
PY_BLUE_PALE = "#ebf2f8"
PY_GOLD = "#d4a62a"
RUST_ORANGE = "#b84324"
RUST_PALE = "#fdf0ec"

# VS Code Dark+ / authentic Python editor & Windows Terminal colors
CODE_BG = "#1e1e1e"
CODE_HEADER = "#252526"
CODE_BORDER = "#30343a"
CODE_FG = "#d4d4d4"
CODE_GUTTER = "#858585"
CODE_SELECT = "#264f78"

TERM_BG = "#0c0c0c"
TERM_BAR = "#1f2328"
TERM_BORDER = "#2d333b"
TERM_FG = "#f2f2f2"
TERM_DIM = "#8b949e"
TERM_PROMPT = "#4ec9b0"
TERM_CMD = "#dcdcaa"
TERM_ERR = "#f44747"

FONT = "맑은 고딕"
CODE_FONT = "Consolas"
DPI_SCALE = 1.0

PY_CTRL_KEYWORDS = {
    "as", "assert", "async", "await", "break", "case", "continue", "del",
    "elif", "else", "except", "finally", "for", "from", "if", "import",
    "match", "pass", "raise", "return", "try", "while", "with", "yield",
}
PY_BUILTINS = {
    "abs", "all", "any", "bool", "dict", "enumerate", "float", "format",
    "input", "int", "isinstance", "len", "list", "map", "max", "min",
    "open", "print", "range", "repr", "round", "set", "sorted", "str",
    "sum", "tuple", "type", "zip",
}
RUST_CTRL_KEYWORDS = {
    "as", "break", "continue", "else", "for", "if", "in", "loop", "match", "return", "while",
}
RUST_KEYWORDS = {
    "bool", "char", "const", "crate", "enum", "f32", "f64", "false", "fn", "i32", "i64",
    "impl", "isize", "let", "mod", "move", "mut", "pub", "ref", "self", "Self", "static",
    "str", "struct", "super", "trait", "true", "type", "u32", "u64", "unsafe", "use",
    "usize", "where", "String", "Vec", "Option", "Result",
}
RUST_BUILTINS = {
    "Err", "None", "Ok", "Some", "clone", "collect", "contains", "enumerate", "expect",
    "filter", "format", "is_empty", "iter", "len", "main", "map", "parse", "pop",
    "print", "println", "push", "rev", "split_whitespace", "to_string", "trim", "unwrap",
}
_RUST_TOKEN_RE = re.compile(
    r"//[^\n]*|/\*[\s\S]*?\*/|r#\"[\s\S]*?\"#|\"(?:\\.|[^\"\\])*\"|\b\d[\d_]*(?:\.\d[\d_]*)?(?:[iu](?:8|16|32|64|size)|f(?:32|64))?\b|\b[A-Za-z_][A-Za-z0-9_]*!?"
)
LANG_META = {
    "python": {
        "name": "Python",
        "filename": "main.py",
        "practice": "practice.py",
        "example": "example.py",
        "comment": "#",
        "accent": PY_BLUE,
        "pale": PY_BLUE_PALE,
        "border": "#cfe0ef",
        "badge_fg": PY_BLUE,
        "code_type": "실제 Python 실기",
    },
    "rust": {
        "name": "Rust",
        "filename": "main.rs",
        "practice": "practice.rs",
        "example": "example.rs",
        "comment": "//",
        "accent": RUST_ORANGE,
        "pale": RUST_PALE,
        "border": "#eed1c8",
        "badge_fg": RUST_ORANGE,
        "code_type": "실제 Rust 실기",
    },
}

_CHIME_CACHE = {}


def _build_chime_wav(correct: bool) -> bytes:
    """Synthesize a soft, low-volume acoustic chime as 16-bit mono PCM WAV bytes."""
    rate = 44100
    notes = (
        [(523.25, 0.0, 0.13, 3000), (659.25, 0.085, 0.16, 3100), (783.99, 0.17, 0.24, 3300)]
        if correct
        else [(349.23, 0.0, 0.11, 2500), (277.18, 0.085, 0.17, 2300)]
    )
    total_samples = int(rate * (max(start + dur for _, start, dur, _ in notes) + 0.02))
    samples = [0.0] * total_samples
    for freq, start_t, dur, amp in notes:
        s0 = int(start_t * rate)
        n = int(dur * rate)
        attack = max(1, int(0.018 * rate))
        for i in range(n):
            idx = s0 + i
            if idx >= total_samples:
                break
            t = i / rate
            env_attack = 0.5 * (1.0 - math.cos(math.pi * min(1.0, i / attack)))
            env_decay = math.exp(-5.8 * (i / n))
            tone = (
                math.sin(2.0 * math.pi * freq * t)
                + 0.22 * math.sin(4.0 * math.pi * freq * t)
                + 0.06 * math.sin(6.0 * math.pi * freq * t)
            )
            samples[idx] += amp * env_attack * env_decay * tone
    pcm = bytearray()
    for val in samples:
        clamped = max(-32767, min(32767, int(val)))
        pcm += struct.pack("<h", clamped)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm)
    return buf.getvalue()


def _get_chime_bytes(correct: bool) -> bytes:
    key = bool(correct)
    if key not in _CHIME_CACHE:
        _CHIME_CACHE[key] = _build_chime_wav(key)
    return _CHIME_CACHE[key]


def _chime_file(correct: bool, folder) -> Path:
    """Write the chime next to the progress file once and return its path."""
    data = _get_chime_bytes(correct)
    target = Path(folder) / "sounds" / ("chime-correct.wav" if correct else "chime-retry.wav")
    try:
        if target.stat().st_size == len(data):
            return target
    except OSError:
        pass
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def px(value):
    """Scale pixel dimensions to match Tk's point-based fonts on high-DPI Windows."""
    if isinstance(value, tuple):
        return tuple(px(part) for part in value)
    return round(value * DPI_SCALE)


ROUTES = [
    ("setup", "◈", "준비"),
    ("python", "▤", "Python 학습"),
    ("rust", "❖", "Rust 학습"),
    ("review", "↻", "오답 노트"),
    ("playground", "</>", "코드 연습장"),
    ("achievements", "☆", "나의 성취"),
    ("settings", "⚙", "설정"),
]
TYPE_NAMES = {"choice": "알맞은 답 고르기", "fill": "빈칸 채우기", "order": "코드 순서 맞추기", "code": "실제 코드 작성 실기", "output": "실행 결과 직접 쓰기"}


def _route_colors(route):
    if route == "python":
        return PY_BLUE_PALE, PY_BLUE, "#b9d4ea"
    if route == "rust":
        return RUST_PALE, RUST_ORANGE, "#ecc6bb"
    return PALE, GREEN, "#b9dfd0"


def _clean_prose_text(text):
    if not isinstance(text, str):
        return text
    cleaned = re.sub(r"\*\*([^*]+?)\*\*", r"\1", text)
    cleaned = re.sub(r"`([^`\n]+?)`", r"\1", cleaned)
    cleaned = re.sub(r"\$([^$\n]+?)\$", lambda m: m.group(1).replace("\\log", "log").strip(), cleaned)
    # The Korean UI font draws "\" as a won sign (\d+ looks like ₩d+). U+29F5 looks like a real
    # backslash at normal width. Display only: answers, copied code and code editors keep "\".
    return cleaned.replace("\\", "⧵")


def _safe_bg(widget, fallback=BG):
    try:
        bg = widget.cget("bg")
        return bg or fallback
    except (tk.TclError, AttributeError):
        return fallback


def _rounded_rect_points(x1, y1, x2, y2, radius, steps=8):
    w = max(0.0, float(x2) - float(x1))
    h = max(0.0, float(y2) - float(y1))
    r = max(0.0, min(float(radius), w / 2.0, h / 2.0))
    if r <= 0.5:
        return [x1, y1, x2, y1, x2, y2, x1, y2]
    pts = []
    corners = [
        (x2 - r, y1 + r, -math.pi / 2.0, 0.0),
        (x2 - r, y2 - r, 0.0, math.pi / 2.0),
        (x1 + r, y2 - r, math.pi / 2.0, math.pi),
        (x1 + r, y1 + r, math.pi, 1.5 * math.pi),
    ]
    for cx, cy, start, end in corners:
        for step in range(steps + 1):
            ang = start + (end - start) * (step / steps)
            pts.extend((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    return pts


def _draw_rounded_rect(canvas, x1, y1, x2, y2, radius, fill="", outline="", width=1, tags=()):
    pts = _rounded_rect_points(x1, y1, x2, y2, radius)
    if len(pts) <= 8:
        return canvas.create_rectangle(x1, y1, x2, y2, fill=fill, outline=outline, width=width, tags=tags)
    return canvas.create_polygon(pts, smooth=False, fill=fill, outline=outline, width=width, tags=tags)


_GLYPH_CACHE = {}
_INK_CACHE = {}
_GDI = {}
# Fonts Windows/Tk may draw a symbol from when the UI font lacks it; matched by advance width.
_FALLBACK_FACES = ("Segoe UI Emoji", "Segoe UI Symbol", "Cambria Math", "Segoe UI", "Gulim", "MS Gothic",
                   "Microsoft YaHei", "Yu Gothic", "Arial")


def _gdi_glyph(face, px_height, bold, ch):
    """Ink box of one glyph from Windows: (left bearing, ink width, advance, ink top, ink bottom), or None.

    Tk can only report a text item's line box (ascent + descent and advance widths), not where the
    letters are actually drawn. For Korean text that box puts the visible letters 1-3 px low, and a
    symbol taken from another font can carry several px of empty space on one side.
    """
    key = (face, px_height, bold, ch)
    if key in _GLYPH_CACHE:
        return _GLYPH_CACHE[key]
    result = None
    if sys.platform == "win32" and len(ch) == 1 and ord(ch) <= 0xFFFF:
        try:
            import ctypes
            from ctypes import wintypes
            if not _GDI:
                gdi32 = ctypes.windll.gdi32

                class GLYPHMETRICS(ctypes.Structure):
                    _fields_ = [("gmBlackBoxX", wintypes.UINT), ("gmBlackBoxY", wintypes.UINT),
                                ("gmptGlyphOrigin", wintypes.POINT), ("gmCellIncX", ctypes.c_short),
                                ("gmCellIncY", ctypes.c_short)]

                class MAT2(ctypes.Structure):
                    _fields_ = [("m", ctypes.c_int32 * 4)]

                gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
                gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
                gdi32.CreateFontW.restype = ctypes.c_void_p
                gdi32.CreateFontW.argtypes = [ctypes.c_int] * 5 + [wintypes.DWORD] * 8 + [wintypes.LPCWSTR]
                gdi32.SelectObject.restype = ctypes.c_void_p
                gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
                gdi32.GetGlyphIndicesW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
                gdi32.GetGlyphOutlineW.restype = wintypes.DWORD
                gdi32.GetGlyphOutlineW.argtypes = [ctypes.c_void_p, wintypes.UINT, wintypes.UINT, ctypes.c_void_p,
                                                   wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p]
                _GDI.update(gdi32=gdi32, dc=gdi32.CreateCompatibleDC(None), fonts={}, GM=GLYPHMETRICS,
                            identity=MAT2((ctypes.c_int32 * 4)(0x10000, 0, 0, 0x10000)))
            gdi32, dc = _GDI["gdi32"], _GDI["dc"]
            font_key = (face, px_height, bold)
            hfont = _GDI["fonts"].get(font_key)
            if hfont is None:
                hfont = gdi32.CreateFontW(-px_height, 0, 0, 0, 700 if bold else 400, 0, 0, 0, 1, 0, 0, 5, 0, face)
                _GDI["fonts"][font_key] = hfont
            if hfont and dc:
                gdi32.SelectObject(dc, hfont)
                index = (wintypes.WORD * 1)()
                gdi32.GetGlyphIndicesW(dc, ch, 1, index, 1)  # GGI_MARK_NONEXISTING_GLYPHS
                metrics = _GDI["GM"]()
                if index[0] != 0xFFFF and gdi32.GetGlyphOutlineW(dc, ord(ch), 0, ctypes.byref(metrics), 0, None,
                                                                 ctypes.byref(_GDI["identity"])) != 0xFFFFFFFF:
                    top = metrics.gmptGlyphOrigin.y
                    result = (metrics.gmptGlyphOrigin.x, metrics.gmBlackBoxX, metrics.gmCellIncX,
                              top, top - metrics.gmBlackBoxY)
        except (AttributeError, OSError, ValueError):
            result = None
    _GLYPH_CACHE[key] = result
    return result


def _side_bearings(face, px_height, bold, ch, tk_advance):
    """Empty space (left, right) around a glyph as Tk draws it; 0 when the drawing font is unknown."""
    if ch.isspace():
        return tk_advance, tk_advance
    for candidate in (face,) + _FALLBACK_FACES:
        glyph = _gdi_glyph(candidate, px_height, bold, ch)
        if glyph and (candidate == face or abs(glyph[2] - tk_advance) <= 1):
            left, width, advance = glyph[0], glyph[1], glyph[2]
            return max(0, left), max(0, advance - left - width)
    return 0, 0


def _text_ink_offset(widget, font_spec, text, horizontal=True):
    """(dx, dy) that moves a bbox-centered text item so its visible letters are centered instead."""
    text = str(text or "")
    key = (str(font_spec), text, horizontal)
    if key in _INK_CACHE:
        return _INK_CACHE[key]
    dx = dy = 0.0
    try:
        fnt = tkfont.Font(root=widget, font=font_spec)
        actual = fnt.actual()
        size = int(actual.get("size", 0))
        px_height = round(size * float(widget.tk.call("tk", "scaling"))) if size > 0 else abs(size)
        face, bold = actual.get("family", FONT), actual.get("weight") == "bold"
        if any("가" <= ch <= "힣" or "ㄱ" <= ch <= "ㆎ" for ch in text):
            reference = "가"  # Korean letters fill a taller box than Latin capitals
        elif any(ch.isascii() and ch.isalnum() for ch in text):
            reference = "H"
        else:
            reference = None  # symbols only (hearts, >_): center on the symbols' own ink below
        glyph = _gdi_glyph(face, px_height, bold, reference) if reference and px_height else None
        if reference is None and px_height:
            boxes = [_gdi_glyph(face, px_height, bold, ch) for ch in set(text) if not ch.isspace()]
            boxes = [box for box in boxes if box]
            if boxes and len(boxes) == len({ch for ch in text if not ch.isspace()}):
                glyph = (0, 0, 0, max(box[3] for box in boxes), min(box[4] for box in boxes))
        if glyph:
            ascent, descent = fnt.metrics("ascent"), fnt.metrics("descent")
            line_center = (descent - ascent) / 2.0          # y grows downward from the baseline
            ink_center = -(glyph[3] + glyph[4]) / 2.0
            dy = line_center - ink_center
        if horizontal and text.strip() and "\n" not in text:
            first, last = text[0], text[-1]
            left = _side_bearings(face, px_height, bold, first, fnt.measure(first))[0]
            right = _side_bearings(face, px_height, bold, last, fnt.measure(last))[1]
            dx = (right - left) / 2.0
    except (tk.TclError, ValueError, TypeError):
        dx = dy = 0.0
    if len(_INK_CACHE) > 4000:
        _INK_CACHE.clear()
    _INK_CACHE[key] = (dx, dy)
    return dx, dy


def _center_canvas_bbox(canvas, item_id, cx, cy, center_x=True, center_y=True):
    bbox = canvas.bbox(item_id)
    if not bbox:
        return
    dx = (cx - (bbox[0] + bbox[2]) / 2.0) if center_x else 0.0
    dy = (cy - (bbox[1] + bbox[3]) / 2.0) if center_y else 0.0
    if canvas.type(item_id) == "text":
        text = canvas.itemcget(item_id, "text")
        wrapped = float(canvas.itemcget(item_id, "width") or 0) > 0
        ink_dx, ink_dy = _text_ink_offset(canvas, canvas.itemcget(item_id, "font"), text,
                                          horizontal=center_x and not wrapped)
        dx += ink_dx if center_x else 0.0
        dy += ink_dy if center_y else 0.0
    if abs(dx) > 0.1 or abs(dy) > 0.1:
        canvas.move(item_id, dx, dy)


def _font_obj(widget, font_spec):
    return tkfont.Font(root=widget, font=font_spec)


def _measure_text_box(widget, text, font_spec, wraplength=0):
    fnt = _font_obj(widget, font_spec)
    linespace = max(1, fnt.metrics("linespace"))
    raw = text if isinstance(text, str) else str(text)
    if not wraplength or wraplength <= 0:
        lines = raw.splitlines() or [""]
        w = max((fnt.measure(ln) for ln in lines), default=0)
        return w, linespace * len(lines)
    # Approximate wrapped visual lines using actual font metrics word-by-word
    total_lines = 0
    max_w = 0
    for para in (raw.splitlines() or [""]):
        if not para:
            total_lines += 1
            continue
        cur = ""
        for ch in para:
            cand = cur + ch
            if cur and fnt.measure(cand) > wraplength:
                max_w = max(max_w, fnt.measure(cur))
                total_lines += 1
                cur = ch.lstrip() if ch == " " else ch
            else:
                cur = cand
        if cur or not para:
            max_w = max(max_w, fnt.measure(cur))
            total_lines += 1
    return min(max_w, int(wraplength)), linespace * max(1, total_lines)


def _pack_chip_flow(parent, chip_specs, gap_x=6, gap_y=5, max_width=940, bg=BG):
    """Pack dynamically sized pills/buttons into clean left-aligned wrapping rows."""
    max_w = px(max_width)
    row_frame = tk.Frame(parent, bg=bg)
    row_frame.pack(fill="x")
    cur_x = 0
    gx = px(gap_x)
    gy = px(gap_y)
    widgets = []
    for builder in chip_specs:
        widget = builder(row_frame)
        w = max(px(24), widget.winfo_reqwidth())
        if cur_x > 0 and cur_x + gx + w > max_w:
            widget.destroy()
            row_frame = tk.Frame(parent, bg=bg)
            row_frame.pack(fill="x", pady=px((gy / max(0.5, DPI_SCALE), 0)))
            widget = builder(row_frame)
            w = max(px(24), widget.winfo_reqwidth())
            cur_x = 0
        widget.pack(side="left", padx=(0, gx))
        cur_x += w + gx
        widgets.append(widget)
    return widgets


class RoundedFrame(tk.Frame):
    """Smooth rounded Frame that keeps standard pack/grid/cget('bg') compatibility."""

    def __init__(self, parent, bg=WHITE, padx=14, pady=14, border=LINE, radius=12, outer_bg=None, border_width=1):
        self._card_bg = bg
        self._border = border
        self._radius = px(radius)
        self._border_w = border_width
        self._outer_bg = outer_bg if outer_bg is not None else _safe_bg(parent, BG)
        self._last_size = (0, 0)
        super().__init__(
            parent,
            bg=bg,
            padx=px(padx) if isinstance(padx, (int, float)) else tuple(px(v) for v in padx),
            pady=px(pady) if isinstance(pady, (int, float)) else tuple(px(v) for v in pady),
            bd=0,
            highlightthickness=0,
        )
        self._backdrop = tk.Canvas(
            self,
            bg=self._outer_bg,
            highlightthickness=0,
            bd=0,
            takefocus=0,
        )
        self._backdrop.place(x=0, y=0, relwidth=1, relheight=1, bordermode="ignore")
        tk.Widget.lower(self._backdrop)
        self._backdrop.bind("<Configure>", self._redraw, add=True)

    def set_colors(self, bg=None, border=None, border_width=None):
        if bg is not None:
            self._card_bg = bg
            super().configure(bg=bg)
        if border is not None:
            self._border = border
        if border_width is not None:
            self._border_w = border_width
        self._last_size = (0, 0)
        self._redraw()

    def _redraw(self, event=None):
        w = event.width if event else self._backdrop.winfo_width()
        h = event.height if event else self._backdrop.winfo_height()
        if w < 4 or h < 4:
            return
        if (w, h) == self._last_size and event is not None:
            return
        self._last_size = (w, h)
        self._backdrop.delete("bg")
        inset = max(0.5, self._border_w / 2.0)
        outline = self._border if self._border else ""
        bw = self._border_w if outline else 0
        _draw_rounded_rect(
            self._backdrop,
            inset,
            inset,
            w - inset - 1,
            h - inset - 1,
            self._radius,
            fill=self._card_bg,
            outline=outline,
            width=bw,
            tags=("bg",),
        )
        self._backdrop.tag_lower("bg")


class PillBadge(tk.Canvas):
    """Smooth rounded capsule or squircle badge with bbox-centered typography."""

    def __init__(self, parent, text, fg=INK, bg=PALE, border=None, size=8, bold=True,
                 padx=9, pady=3, radius=None, min_width=0, min_height=0, font_family=FONT):
        self._text = _clean_prose_text(text)
        self._fg = fg
        self._fill = bg
        self._border = border
        self._font = (font_family, size, "bold" if bold else "normal")
        self._padx = px(padx)
        self._pady = px(pady)
        self._radius = None if radius is None else px(radius)
        outer_bg = _safe_bg(parent, BG)
        tw, th = _measure_text_box(parent, self._text, self._font)
        w = max(px(min_width), tw + self._padx * 2)
        h = max(px(min_height), th + self._pady * 2)
        super().__init__(parent, width=w, height=h, bg=outer_bg, highlightthickness=0, bd=0, takefocus=0)
        self._draw(w, h)
        self.bind("<Configure>", lambda e: self._draw(e.width, e.height), add=True)

    def set_text(self, text, fg=None, bg=None, border=None):
        self._text = _clean_prose_text(text)
        if fg is not None:
            self._fg = fg
        if bg is not None:
            self._fill = bg
        if border is not None:
            self._border = border
        tw, th = _measure_text_box(self, self._text, self._font)
        w = tw + self._padx * 2
        h = th + self._pady * 2
        super().configure(width=w, height=h)
        self._draw(w, h)

    def configure(self, cnf=None, **kw):
        if cnf:
            kw.update(cnf)
        text = kw.pop("text", None)
        fg = kw.pop("fg", None)
        bg = kw.pop("bg", None)
        border = kw.pop("border", None)
        if text is not None or fg is not None or bg is not None or border is not None:
            self.set_text(self._text if text is None else text, fg=fg, bg=bg, border=border)
        if kw:
            super().configure(**kw)

    config = configure

    def cget(self, key):
        if key == "text":
            return self._text
        if key == "fg":
            return self._fg
        if key in ("bg", "background"):
            return self._fill
        return super().cget(key)

    __getitem__ = cget

    def _draw(self, w, h):
        if w < 4 or h < 4:
            return
        self.delete("all")
        r = (h / 2.0) if self._radius is None else self._radius
        outline = self._border if self._border else ""
        bw = 1 if outline else 0
        _draw_rounded_rect(self, 0.5, 0.5, w - 1.5, h - 1.5, r, fill=self._fill, outline=outline, width=bw)
        tid = self.create_text(w / 2.0, h / 2.0, text=self._text, fill=self._fg, font=self._font, anchor="center", justify="center")
        _center_canvas_bbox(self, tid, w / 2.0, h / 2.0, center_x=True, center_y=True)


class RoundedProgressBar(tk.Canvas):
    """Smooth pill progress bar replacing stiff rectangular ttk.Progressbar."""

    def __init__(self, parent, fill=GREEN, trough="#dce6df", maximum=100, value=0, length=200, height=8):
        self._fill = fill
        self._trough = trough
        self._maximum = max(1, float(maximum))
        self._value = max(0.0, float(value))
        h = max(px(6), px(height))
        w = max(px(40), px(length))
        super().__init__(parent, width=w, height=h, bg=_safe_bg(parent, BG), highlightthickness=0, bd=0, takefocus=0)
        self.bind("<Configure>", lambda e: self._draw(e.width, e.height), add=True)
        self._draw(w, h)

    def configure(self, cnf=None, **kw):
        changed = False
        if "value" in kw:
            self._value = max(0.0, float(kw.pop("value")))
            changed = True
        if "maximum" in kw:
            self._maximum = max(1.0, float(kw.pop("maximum")))
            changed = True
        if kw or cnf:
            super().configure(cnf, **kw) if cnf else super().configure(**kw)
        if changed:
            self._draw(max(self.winfo_width(), int(float(self.cget("width")))),
                       max(self.winfo_height(), int(float(self.cget("height")))))

    config = configure

    def _draw(self, w, h):
        if w < 4 or h < 4:
            return
        self.delete("all")
        r = h / 2.0
        _draw_rounded_rect(self, 0, 0, w - 1, h - 1, r, fill=self._trough, outline="")
        ratio = min(1.0, max(0.0, self._value / self._maximum))
        if ratio > 0:
            fw = max(h, ratio * (w - 1))
            _draw_rounded_rect(self, 0, 0, min(w - 1, fw), h - 1, r, fill=self._fill, outline="")


class SoftButton(tk.Canvas):
    """Canvas-drawn rounded pill/card button preserving tk.Button invoke/configure/cget API."""

    _PALETTES = {
        # (bg, fg, active, hover, border, disabled_bg, disabled_fg)
        "primary": (GREEN, WHITE, "#126141", GREEN_HOVER, GREEN, "#c8dbd1", "#f4f7f5"),
        "py": (PY_BLUE, WHITE, "#1e4568", "#25537a", PY_BLUE, "#c5d6e4", "#f4f8fb"),
        "rust": (RUST_ORANGE, WHITE, "#812b14", "#98351a", RUST_ORANGE, "#e4c9c1", "#fcf6f4"),
        "secondary": (PALE, GREEN, "#c6e5d5", PALE_HOVER, "#bce0ce", "#eef4f0", "#8da196"),
        "ghost": ("#eff4f1", MUTED, "#dbe5df", "#e3ece7", "#d3dfd8", "#f3f6f4", "#9eaba4"),
        "dark": ("#2b3137", "#d8dee4", "#3b434c", "#353c44", "#3b424a", "#25292e", "#6f7781"),
        "danger": ("#b85c50", WHITE, "#8f4137", "#9e4b40", "#b85c50", "#dfb8b3", "#fbf4f3"),
    }

    def __init__(self, parent, text, command, kind="primary", **options):
        self._kind = kind if kind in self._PALETTES else "primary"
        bg, fg, active, hover, border, dis_bg, dis_fg = self._PALETTES[self._kind]
        self._bg = options.pop("bg", bg)
        self._fg = options.pop("fg", fg)
        self._active_bg = options.pop("activebackground", active)
        self._hover_bg = hover
        self._dis_bg = dis_bg
        self._dis_fg = options.pop("disabledforeground", dis_fg)
        self._base_border = options.pop("highlightbackground", border)
        self._border = self._base_border
        self._border_w = max(1, int(options.pop("highlightthickness", 1)))
        self._padx = int(options.pop("padx", px(13)))
        self._pady = int(options.pop("pady", px(6)))
        self._font = options.pop("font", (FONT, 9, "bold"))
        self._anchor = options.pop("anchor", "center")
        self._wrap = int(options.pop("wraplength", 0) or 0)
        self._radius_opt = options.pop("radius", None)
        self._pill = bool(options.pop("pill", False))
        self._badge_text = options.pop("badge", None)
        self._width_chars = options.pop("width", 0)
        self._min_width = options.pop("min_width", 0)
        self._state = options.pop("state", "normal")
        self._text = _clean_prose_text(text)
        self._command = command
        self._hovered = False
        self._pressed = False
        self._focused = False
        self._auto_height_w = None
        self._canvas_items = None
        self._vis_sig = None
        options.pop("activeforeground", None)
        options.pop("relief", None)
        options.pop("bd", None)
        options.pop("cursor", None)
        takefocus = options.pop("takefocus", 1)

        outer_bg = _safe_bg(parent, BG)
        req_w, req_h = self._calc_size(parent)
        super().__init__(
            parent,
            width=req_w,
            height=req_h,
            bg=outer_bg,
            highlightthickness=0,
            bd=0,
            cursor="hand2" if self._state != "disabled" else "",
            takefocus=takefocus,
        )
        self._redraw(req_w, req_h)
        self.bind("<Configure>", lambda e: self._redraw(e.width, e.height), add=True)
        self.bind("<Enter>", self._on_enter, add=True)
        self.bind("<Leave>", self._on_leave, add=True)
        self.bind("<ButtonPress-1>", self._on_press, add=True)
        self.bind("<ButtonRelease-1>", self._on_release, add=True)
        self.bind("<FocusIn>", lambda _: self._set_focus(True), add=True)
        self.bind("<FocusOut>", lambda _: self._set_focus(False), add=True)
        self.bind("<Return>", lambda e: None if (e.state & 0x4) else self.invoke(), add=True)
        self.bind("<space>", lambda _: self.invoke(), add=True)

    def _calc_size(self, ref_widget):
        badge_extra = px(28) if self._badge_text else 0
        max_text_w = max(px(40), self._wrap - badge_extra) if self._wrap > 0 else 0
        tw, th = _measure_text_box(ref_widget, self._text, self._font, max_text_w)
        if self._width_chars:
            char_w = _font_obj(ref_widget, self._font).measure("M")
            tw = max(tw, int(self._width_chars * char_w))
        req_w = tw + badge_extra + self._padx * 2
        if self._min_width:
            req_w = max(req_w, px(self._min_width))
        req_h = th + self._pady * 2
        if self._badge_text:
            req_h = max(req_h, px(34))
        return max(px(28), req_w), max(px(24), req_h)

    def _set_focus(self, focused):
        if self._focused == focused:
            return
        self._focused = focused
        self._redraw()

    def _on_enter(self, _):
        if self._state != "disabled" and not self._hovered:
            self._hovered = True
            self._redraw()

    def _on_leave(self, _):
        if self._hovered or self._pressed:
            self._hovered = False
            self._pressed = False
            self._redraw()

    def _on_press(self, _):
        if self._state != "disabled":
            self._pressed = True
            if not self._focused:
                self._focused = True
                self.focus_set()
            self._redraw()

    def _on_release(self, event):
        was_pressed = self._pressed
        self._pressed = False
        w, h = self.winfo_width(), self.winfo_height()
        inside = 0 <= event.x <= w and 0 <= event.y <= h
        self._hovered = inside and self._state != "disabled"
        self._redraw()
        if was_pressed and inside and self._state != "disabled" and self._command:
            self._command()

    def invoke(self):
        if self._state != "disabled" and self._command:
            return self._command()
        return None

    def cget(self, key):
        if key == "state":
            return self._state
        if key == "text":
            return self._text
        if key in ("bg", "background"):
            return self._bg
        if key == "fg":
            return self._fg
        return super().cget(key)

    __getitem__ = cget

    def configure(self, cnf=None, **kw):
        resize = False
        if cnf:
            kw.update(cnf)
        before = (
            self._kind,
            self._bg,
            self._fg,
            self._active_bg,
            self._hover_bg,
            self._dis_bg,
            self._dis_fg,
            self._base_border,
            self._border,
            self._border_w,
            self._state,
        )
        if "kind" in kw:
            kind = kw.pop("kind")
            if kind in self._PALETTES:
                self._kind = kind
                bg, fg, active, hover, border, dis_bg, dis_fg = self._PALETTES[kind]
                self._bg = bg
                self._fg = fg
                self._active_bg = active
                self._hover_bg = hover
                self._dis_bg = dis_bg
                self._dis_fg = dis_fg
                self._base_border = border
                self._border = border
        if "text" in kw:
            new_txt = _clean_prose_text(kw.pop("text"))
            if new_txt != self._text:
                self._text = new_txt
                self._auto_height_w = None
                resize = True
        if "command" in kw:
            self._command = kw.pop("command")
        if "state" in kw:
            new_state = kw.pop("state")
            if new_state != self._state:
                self._state = new_state
                new_cursor = "hand2" if self._state != "disabled" else ""
                if super().cget("cursor") != new_cursor:
                    kw["cursor"] = new_cursor
                if self._state == "disabled":
                    self._hovered = False
                    self._pressed = False
        if "disabledbackground" in kw:
            self._dis_bg = kw.pop("disabledbackground")
        if "disabledforeground" in kw:
            self._dis_fg = kw.pop("disabledforeground")
        if "highlightbackground" in kw:
            self._border = kw.pop("highlightbackground")
        if "highlightthickness" in kw:
            self._border_w = max(0, int(kw.pop("highlightthickness")))
        if "bg" in kw:
            self._bg = kw.pop("bg")
        if "fg" in kw:
            self._fg = kw.pop("fg")
        if "font" in kw:
            new_font = kw.pop("font")
            if new_font != self._font:
                self._font = new_font
                self._auto_height_w = None
                resize = True
        if kw:
            super().configure(**kw)
        after = (
            self._kind,
            self._bg,
            self._fg,
            self._active_bg,
            self._hover_bg,
            self._dis_bg,
            self._dis_fg,
            self._base_border,
            self._border,
            self._border_w,
            self._state,
        )
        if resize:
            req_w, req_h = self._calc_size(self)
            cur_w = int(float(super().cget("width")))
            cur_h = int(float(super().cget("height")))
            if req_w != cur_w or req_h != cur_h:
                super().configure(width=req_w, height=req_h)
                self._redraw(req_w, req_h)
            else:
                self._redraw()
        elif after != before:
            self._redraw()

    config = configure

    def _visual_state(self):
        disabled = self._state == "disabled"
        if disabled:
            fill = self._dis_bg
            fg = self._dis_fg
            outline = self._border if self._border != self._bg else "#d9e2dd"
        elif self._pressed:
            fill = self._active_bg
            fg = self._fg
            outline = self._border
        elif self._hovered:
            fill = self._hover_bg
            fg = self._fg
            outline = "#b4c9bd" if self._kind == "ghost" and self._border not in (GREEN, "#b85c50") else self._border
        else:
            fill = self._bg
            fg = self._fg
            outline = self._border
        if self._focused and not disabled:
            outline = "#5aa47f" if self._kind == "ghost" and self._border not in (GREEN, "#b85c50") else self._border

        bw = max(1, self._border_w)
        if self._badge_text is not None:
            if self._border == "#b85c50":
                b_fill, b_fg = "#b85c50", WHITE
            elif self._kind == "secondary" or self._border == GREEN:
                b_fill, b_fg = GREEN, WHITE
            else:
                b_fill = "#e4ece7" if not disabled else "#eaefec"
                b_fg = INK if not disabled else "#93a29a"
        else:
            b_fill, b_fg = None, None
        return fill, fg, outline, bw, b_fill, b_fg

    def _redraw(self, w=None, h=None):
        if w is None:
            w = self.winfo_width()
            if w < 4:
                w = int(float(super().cget("width")))
        if h is None:
            h = self.winfo_height()
            if h < 4:
                h = int(float(super().cget("height")))
        if w < 4 or h < 4:
            return
        fill, fg, outline, bw, b_fill, b_fg = self._visual_state()
        inset = max(1.0, float(px(1)), bw / 2.0)
        geom_sig = (
            w,
            h,
            round(inset, 2),
            self._text,
            self._font,
            self._badge_text,
            self._wrap,
            self._anchor,
            self._radius_opt,
            self._pill,
            self._padx,
            self._pady,
        )
        vis_sig = (fill, fg, outline, bw, b_fill, b_fg)
        items = self._canvas_items
        if items is not None and items["geom"] == geom_sig:
            if vis_sig == self._vis_sig:
                return
            self.itemconfigure(items["bg"], fill=fill, outline=outline, width=bw if outline else 0)
            if items["badge_bg"] is not None:
                self.itemconfigure(items["badge_bg"], fill=b_fill)
            if items["badge_txt"] is not None:
                self.itemconfigure(items["badge_txt"], fill=b_fg)
            self.itemconfigure(items["txt"], fill=fg)
            self._vis_sig = vis_sig
            return

        self.delete("all")
        r = (h / 2.0) if self._pill else px(self._radius_opt if self._radius_opt is not None else 10)
        bg_id = _draw_rounded_rect(self, inset, inset, w - inset - 1, h - inset - 1, r, fill=fill, outline=outline, width=bw)
        b_bg_id = None
        b_txt_id = None

        if self._badge_text is not None:
            badge_sz = px(22)
            bx = self._padx + badge_sz / 2.0
            by = h / 2.0
            b_bg_id = _draw_rounded_rect(
                self,
                bx - badge_sz / 2.0,
                by - badge_sz / 2.0,
                bx + badge_sz / 2.0,
                by + badge_sz / 2.0,
                px(7),
                fill=b_fill,
                outline="",
            )
            b_txt_id = self.create_text(bx, by, text=str(self._badge_text), fill=b_fg, font=(FONT, 9, "bold"), anchor="center")
            _center_canvas_bbox(self, b_txt_id, bx, by, center_x=True, center_y=True)
            tx = self._padx + badge_sz + px(11)
            wrap = max(px(60), w - tx - self._padx)
            tid = self.create_text(tx, h / 2.0, text=self._text, fill=fg, font=self._font, anchor="w", justify="left", width=wrap)
            _center_canvas_bbox(self, tid, tx, h / 2.0, center_x=False, center_y=True)
        elif self._anchor == "w":
            tx = self._padx
            wrap = max(px(60), w - self._padx * 2) if self._wrap else 0
            tid = self.create_text(tx, h / 2.0, text=self._text, fill=fg, font=self._font, anchor="w", justify="left", width=wrap)
            _center_canvas_bbox(self, tid, tx, h / 2.0, center_x=False, center_y=True)
        else:
            cx, cy = w / 2.0, h / 2.0
            wrap = max(px(60), w - self._padx * 2) if self._wrap else 0
            tid = self.create_text(cx, cy, text=self._text, fill=fg, font=self._font, anchor="center", justify="center", width=wrap)
            _center_canvas_bbox(self, tid, cx, cy, center_x=True, center_y=True)

        self._canvas_items = {
            "geom": geom_sig,
            "bg": bg_id,
            "badge_bg": b_bg_id,
            "badge_txt": b_txt_id,
            "txt": tid,
        }
        self._vis_sig = vis_sig

        if (self._wrap > 0 or self._badge_text is not None) and w >= px(80):
            tb = self.bbox(tid)
            if tb:
                need_h = max(px(34 if self._badge_text else 24), int(math.ceil((tb[3] - tb[1]) + self._pady * 2)))
                if abs(need_h - h) > 2 and self._auto_height_w != w:
                    self._auto_height_w = w
                    super().configure(height=need_h)


class NavPill(tk.Canvas):
    """Sidebar navigation item with uniform centered icon slot and soft rounded highlight."""

    def __init__(self, parent, route, glyph, text, command):
        self._route = route
        self._glyph = glyph
        self._text = text
        self._command = command
        self._active = False
        self._hovered = False
        self._last_sig = None
        self._active_bg, self._active_fg, self._active_border = _route_colors(route)
        h = px(36)
        super().__init__(parent, width=px(168), height=h, bg=WHITE, highlightthickness=0, bd=0, cursor="hand2", takefocus=1)
        self._redraw(px(168), h)
        self.bind("<Configure>", lambda e: self._redraw(e.width, e.height), add=True)
        self.bind("<Enter>", lambda _: self._set_hover(True), add=True)
        self.bind("<Leave>", lambda _: self._set_hover(False), add=True)
        self.bind("<ButtonRelease-1>", self._on_click, add=True)
        self.bind("<Return>", lambda e: None if (e.state & 0x4) else self.invoke(), add=True)
        self.bind("<space>", lambda _: self.invoke(), add=True)

    def _set_hover(self, state):
        if self._hovered == state:
            return
        self._hovered = state
        self._redraw()

    def _on_click(self, event):
        if 0 <= event.x <= self.winfo_width() and 0 <= event.y <= self.winfo_height():
            self.invoke()

    def invoke(self):
        if self._command:
            return self._command()
        return None

    def set_active(self, active):
        new_active = bool(active)
        if self._active == new_active:
            return
        self._active = new_active
        self._redraw()

    def configure(self, cnf=None, **kw):
        # Kept compatible if any caller updates highlight/colors
        kw.pop("bg", None)
        kw.pop("fg", None)
        kw.pop("highlightbackground", None)
        kw.pop("font", None)
        if kw:
            super().configure(cnf, **kw) if cnf else super().configure(**kw)
        self._redraw()

    config = configure

    def _redraw(self, w=None, h=None):
        w = w or max(px(168), self.winfo_width())
        h = h or max(px(36), self.winfo_height())
        if w < 10 or h < 10:
            return
        sig = (w, h, self._active, self._hovered, self._text)
        if sig == self._last_sig:
            return
        self._last_sig = sig
        self.delete("all")
        if self._active:
            fill, outline, fg, bold = self._active_bg, self._active_border, self._active_fg, True
        elif self._hovered:
            fill, outline, fg, bold = "#f2f7f4", "#e3ece6", INK, False
        else:
            fill, outline, fg, bold = WHITE, "", MUTED, False
        if fill != WHITE or outline:
            _draw_rounded_rect(self, 1, 1, w - 2, h - 2, px(10), fill=fill, outline=outline, width=1 if outline else 0)
        if self._active:
            _draw_rounded_rect(self, px(4), px(8), px(7), h - px(8), px(2), fill=self._active_fg, outline="")
        glyph_font = (CODE_FONT if self._glyph == "</>" else FONT, 8 if self._glyph == "</>" else 10, "bold" if self._active else "normal")
        gid = self.create_text(px(21), h / 2.0, text=self._glyph, fill=fg, font=glyph_font, anchor="center")
        _center_canvas_bbox(self, gid, px(21), h / 2.0, center_x=True, center_y=True)
        tid = self.create_text(px(39), h / 2.0, text=self._text, fill=fg, font=(FONT, 10, "bold" if bold else "normal"), anchor="w")
        _center_canvas_bbox(self, tid, px(39), h / 2.0, center_x=False, center_y=True)


class LessonNode(tk.Canvas):
    """Smooth rounded squircle lesson path node with mathematically centered vector icon."""

    def __init__(self, parent, state_kind, accent, command, midterm=False):
        # state_kind: "done" | "current" | "locked"
        self._state_kind = state_kind
        self._accent = accent
        self._command = command
        self._midterm = bool(midterm)
        self._hovered = False
        sz = px(54)
        super().__init__(parent, width=sz, height=sz, bg=_safe_bg(parent, WHITE),
                         highlightthickness=0, bd=0, cursor="hand2" if state_kind != "locked" else "", takefocus=1)
        self._draw(sz, sz)
        self.bind("<Enter>", lambda _: self._set_hover(True), add=True)
        self.bind("<Leave>", lambda _: self._set_hover(False), add=True)
        self.bind("<ButtonRelease-1>", self._on_click, add=True)
        self.bind("<Return>", lambda e: None if (e.state & 0x4) else self.invoke(), add=True)

    def _set_hover(self, val):
        if self._state_kind != "locked":
            self._hovered = val
            self._draw(self.winfo_width(), self.winfo_height())

    def _on_click(self, e):
        if 0 <= e.x <= self.winfo_width() and 0 <= e.y <= self.winfo_height():
            self.invoke()

    def invoke(self):
        if self._command:
            return self._command()
        return None

    def _draw(self, w, h):
        w = max(px(54), w)
        h = max(px(54), h)
        self.delete("all")
        cx, cy = w / 2.0, h / 2.0
        if self._state_kind == "done":
            fill = "#d7efe2" if self._hovered else PALE
            outline = "#9ed3b8"
            fg = GREEN
        elif self._state_kind == "current":
            if self._midterm:
                fill = "#b3690e" if self._hovered else "#c97a16"
            else:
                base = self._accent
                fill = ("#25537a" if base == PY_BLUE else "#98351a" if base == RUST_ORANGE else GREEN_HOVER) if self._hovered else base
            outline = fill
            fg = WHITE
        else:
            fill = "#f8f1df" if self._midterm else "#eef3f0"
            outline = "#e5cf9c" if self._midterm else "#d5e0da"
            fg = "#b08b46" if self._midterm else "#8b9b92"
        _draw_rounded_rect(self, 2, 2, w - 3, h - 3, px(17), fill=fill, outline=outline, width=1)
        if self._state_kind == "done":
            s = px(9)
            self.create_line(cx - s * 0.85, cy + s * 0.05, cx - s * 0.2, cy + s * 0.7, cx + s * 0.9, cy - s * 0.65,
                             fill=fg, width=max(2, px(2.6)), capstyle="round", joinstyle="round")
        elif self._state_kind == "current":
            if self._midterm:
                # Distinct crown/flag emblem for stage midterm exams
                pts = [
                    cx - px(10), cy + px(7),
                    cx - px(11), cy - px(6),
                    cx - px(4.5), cy,
                    cx, cy - px(9),
                    cx + px(4.5), cy,
                    cx + px(11), cy - px(6),
                    cx + px(10), cy + px(7),
                ]
                self.create_polygon(pts, fill=fg, outline="")
            else:
                r_out = px(10.5)
                r_in = px(4.5)
                pts = []
                for k in range(10):
                    ang = -math.pi / 2.0 + k * (math.pi / 5.0)
                    rad = r_out if k % 2 == 0 else r_in
                    pts.extend((cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
                self.create_polygon(pts, fill=fg, outline="")
        else:
            r = px(7.5)
            self.create_polygon(cx, cy - r, cx + r, cy, cx, cy + r, cx - r, cy,
                                fill="", outline=fg, width=max(1, px(1.8)), joinstyle="round")


def _draw_badge_medallion(parent, glyph, unlocked, bg=WHITE):
    sz = px(54)
    c = tk.Canvas(parent, width=sz, height=sz, bg=bg, highlightthickness=0, bd=0, takefocus=0)
    cx, cy = sz / 2.0, sz / 2.0
    if unlocked:
        outer_r, inner_r = px(23), px(19)
        c.create_oval(cx - outer_r, cy - outer_r, cx + outer_r, cy + outer_r, fill="#fbf3d8", outline="#ebd38a", width=1)
        c.create_oval(cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r, fill="#fff9e8", outline="")
        fg = PY_GOLD
    else:
        outer_r = px(22)
        c.create_oval(cx - outer_r, cy - outer_r, cx + outer_r, cy + outer_r, fill="#f2f6f4", outline="#dce5df", width=1)
        fg = "#9fb0a7"
    gid = c.create_text(cx, cy, text=glyph, fill=fg, font=(FONT, 17), anchor="center")
    _center_canvas_bbox(c, gid, cx, cy, center_x=True, center_y=True)
    return c


def _draw_brand_emblem(parent):
    sz = px(36)
    c = tk.Canvas(parent, width=sz, height=sz, bg=_safe_bg(parent, WHITE), highlightthickness=0, bd=0, takefocus=0)
    _draw_rounded_rect(c, 1, 1, sz - 2, sz - 2, px(10), fill=GREEN, outline="#146d49", width=1)
    tid = c.create_text(sz / 2.0, sz / 2.0, text=">_", fill="#ffde57", font=(CODE_FONT, 13, "bold"), anchor="center")
    _center_canvas_bbox(c, tid, sz / 2.0, sz / 2.0, center_x=True, center_y=True)
    return c


def label(parent, text, size=11, color=INK, bold=False, **options):
    options.setdefault("bg", _safe_bg(parent, BG))
    options.setdefault("anchor", "w")
    default_justify = "center" if options.get("anchor") == "center" else "left"
    options.setdefault("justify", default_justify)
    return tk.Label(parent, text=_clean_prose_text(text), fg=color, font=(FONT, size, "bold" if bold else "normal"), **options)


def fit_wrap(widget, margin=0, minimum=120):
    """Wrap a label at the width its container really has, instead of a fixed pixel width.

    Fixed widths left a wide empty strip on the right of lesson cards on large windows. Use only
    where the container's width comes from the layout (cards with fill="x", grid columns), never
    where the container shrinks to fit the label, or the two would keep resizing each other.
    """
    master = widget.master

    def update(_=None):
        try:
            if not widget.winfo_exists() or not master.winfo_exists():
                return
            pad = int(float(str(master.cget("padx") or 0))) * 2 if "padx" in master.keys() else 0
            available = master.winfo_width() - pad - px(margin)
            current = int(float(str(widget.cget("wraplength") or 0)))
            if available >= px(minimum) and abs(available - current) > 3:
                widget.configure(wraplength=available)
        except (tk.TclError, ValueError):
            pass

    master.bind("<Configure>", update, add="+")
    widget.after_idle(update)
    return widget


def pill(parent, text, fg=INK, bg=PALE, border=None, size=8, bold=True, padx=9, pady=3, radius=None, min_width=0, min_height=0, font_family=FONT):
    return PillBadge(parent, text, fg=fg, bg=bg, border=border, size=size, bold=bold,
                     padx=padx, pady=pady, radius=radius, min_width=min_width, min_height=min_height, font_family=font_family)


def button(parent, text, command, kind="primary", **options):
    return SoftButton(parent, text, command, kind=kind, **options)


def card(parent, bg=WHITE, padding=14, border=LINE, radius=12):
    return RoundedFrame(parent, bg=bg, padx=padding, pady=padding, border=border, radius=radius)


def configure_code_tags(widget):
    for name, color in [
        ("kw_ctrl", "#c586c0"),
        ("keyword", "#569cd6"),
        ("builtin", "#dcdcaa"),
        ("string", "#ce9178"),
        ("comment", "#6a9955"),
        ("number", "#b5cea8"),
    ]:
        widget.tag_configure(name, foreground=color)


configure_python_tags = configure_code_tags


def apply_python_syntax(widget, text):
    for name in ("kw_ctrl", "keyword", "builtin", "string", "comment", "number"):
        widget.tag_remove(name, "1.0", "end")
    try:
        prev_keyword_def = False
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            tag = None
            if token.type == tokenize.STRING:
                tag = "string"
                prev_keyword_def = False
            elif token.type == tokenize.COMMENT:
                tag = "comment"
            elif token.type == tokenize.NUMBER:
                tag = "number"
                prev_keyword_def = False
            elif token.type == tokenize.NAME:
                word = token.string
                if word in PY_CTRL_KEYWORDS:
                    tag = "kw_ctrl"
                elif keyword.iskeyword(word):
                    tag = "keyword"
                elif prev_keyword_def or word in PY_BUILTINS:
                    tag = "builtin"
                prev_keyword_def = word in ("def", "class")
            else:
                if token.type not in (tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT):
                    prev_keyword_def = False
            if tag:
                widget.tag_add(tag, f"{token.start[0]}.{token.start[1]}", f"{token.end[0]}.{token.end[1]}")
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass


def _advance_text_pos(text, prev_idx, target_idx, line, col):
    chunk = text[prev_idx:target_idx]
    newlines = chunk.count("\n")
    if newlines:
        return line + newlines, len(chunk) - chunk.rfind("\n") - 1
    return line, col + len(chunk)


def apply_rust_syntax(widget, text):
    """Apply VS Code Dark+ syntax highlighting tags for Rust code."""
    for name in ("kw_ctrl", "keyword", "builtin", "string", "comment", "number"):
        widget.tag_remove(name, "1.0", "end")
    idx = 0
    line = 1
    col = 0
    prev_decl = False
    for match in _RUST_TOKEN_RE.finditer(text):
        start, end = match.span()
        line, col = _advance_text_pos(text, idx, start, line, col)
        end_line, end_col = _advance_text_pos(text, start, end, line, col)
        idx = end
        tok = match.group(0)
        tag = None
        if tok.startswith("//") or tok.startswith("/*"):
            tag = "comment"
        elif tok.startswith('"') or tok.startswith('r#"'):
            tag = "string"
            prev_decl = False
        elif tok[0].isdigit():
            tag = "number"
            prev_decl = False
        else:
            bare = tok.rstrip("!")
            if bare in RUST_CTRL_KEYWORDS:
                tag = "kw_ctrl"
            elif bare in RUST_KEYWORDS:
                tag = "keyword"
            elif tok.endswith("!") or prev_decl or bare in RUST_BUILTINS:
                tag = "builtin"
            prev_decl = bare in ("fn", "struct", "enum", "trait")
        if tag:
            widget.tag_add(tag, f"{line}.{col}", f"{end_line}.{end_col}")
        line, col = end_line, end_col


def apply_code_syntax(widget, text, lang="python"):
    if lang == "rust":
        apply_rust_syntax(widget, text)
    else:
        apply_python_syntax(widget, text)


def code_block(parent, text, dark=False, height=None, lang="python", wrap_chars=78, radius=11):
    box_bg = CODE_BG if dark else "#f2f6f3"
    box_border = CODE_BORDER if dark else "#d8e4dd"
    lines = text.splitlines() or [""]
    est_lines = sum(max(1, math.ceil(max(1, len(ln)) / max(24, wrap_chars))) for ln in lines)
    if height is None:
        height = max(1, min(9, est_lines))
    overflows = est_lines > height
    shell = RoundedFrame(parent, bg=box_bg, padx=13, pady=8, border=box_border, radius=radius)
    widget = tk.Text(
        shell,
        height=height,
        wrap="word",
        bg=box_bg,
        fg=CODE_FG if dark else INK,
        font=(CODE_FONT, 10),
        relief="flat",
        bd=0,
        padx=0,
        pady=0,
        spacing1=2,
        spacing3=2,
        selectbackground=CODE_SELECT if dark else "#cde3d6",
        highlightthickness=0,
        cursor="xterm",
    )
    widget.insert("1.0", text)
    if dark:
        configure_code_tags(widget)
        apply_code_syntax(widget, text, lang)
    widget.configure(state="disabled")
    if overflows:
        bar_kw = {"style": "Dark.Vertical.TScrollbar"} if dark else {}
        vbar = ttk.Scrollbar(shell, orient="vertical", command=widget.yview, **bar_kw)
        widget.configure(yscrollcommand=vbar.set)
        vbar.pack(side="right", fill="y", padx=px((4, 0)))
        widget.pack(side="left", fill="both", expand=True)
    else:
        widget.pack(fill="both", expand=True)

    def _set_text(new_text, adjust_height=False):
        if widget.get("1.0", "end-1c") == new_text:
            return
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", new_text)
        if dark:
            apply_code_syntax(widget, new_text, lang)
        if adjust_height:
            new_lines = new_text.splitlines() or [""]
            new_est = sum(max(1, math.ceil(max(1, len(ln)) / max(24, wrap_chars))) for ln in new_lines)
            widget.configure(height=max(1, min(9, new_est)))
        widget.configure(state="disabled")

    shell.text = widget
    shell.set_text = _set_text
    return shell


def configure_terminal_tags(widget):
    widget.tag_configure("dim", foreground=TERM_DIM)
    widget.tag_configure("prompt", foreground=TERM_PROMPT)
    widget.tag_configure("cmd", foreground=TERM_CMD)
    widget.tag_configure("stdout", foreground=TERM_FG)
    widget.tag_configure("stderr", foreground=TERM_ERR)
    widget.tag_configure("ok", foreground=TERM_PROMPT)


def create_terminal_box(parent, title, entries, height=7, header_actions=None):
    """Build a smoothly rounded Windows Terminal / Python CLI widget."""
    shell = RoundedFrame(parent, bg=TERM_BG, padx=11, pady=9, border=TERM_BORDER, radius=12)
    bar = tk.Frame(shell, bg=TERM_BG)
    bar.pack(fill="x", pady=px((0, 6)))
    pill(bar, ">_", fg="#ffde57", bg=PY_BLUE, size=8, bold=True, padx=6, pady=2, radius=6, font_family=CODE_FONT).pack(side="left", padx=px((0, 8)))
    tk.Label(bar, text=title, bg=TERM_BG, fg="#d8dee4", font=(FONT, 9, "bold")).pack(side="left")
    if header_actions:
        for caption, cmd in header_actions:
            button(bar, caption, cmd, "dark", padx=px(9), pady=px(3), font=(FONT, 8, "bold"), radius=8).pack(side="right", padx=px((6, 0)))
    tk.Frame(shell, bg="#22272e", height=1).pack(fill="x", pady=px((0, 6)))

    text = tk.Text(
        shell,
        height=height,
        wrap="word",
        bg=TERM_BG,
        fg=TERM_FG,
        insertbackground=TERM_FG,
        selectbackground=CODE_SELECT,
        font=(CODE_FONT, 10),
        relief="flat",
        bd=0,
        padx=px(2),
        pady=px(2),
        spacing1=2,
        spacing3=2,
        highlightthickness=0,
        cursor="xterm",
    )
    configure_terminal_tags(text)
    for tag, content in entries:
        if content:
            text.insert("end", content, tag)
    total_lines = int(text.index("end-1c").split(".")[0])
    box_height = int(str(text.cget("height") or 7))
    if total_lines > box_height and text.master is not shell:
        vbar = ttk.Scrollbar(text.master, orient="vertical", style="Dark.Vertical.TScrollbar", command=text.yview)
        text.configure(yscrollcommand=vbar.set)
        vbar.pack(side="right", fill="y", padx=px((4, 0)))
        text.pack(side="left", fill="both", expand=True)
    else:
        text.pack(fill="both", expand=True)
    text.configure(state="disabled")
    text.see("end")
    return shell, text


def _draw_window_dots(parent, bg):
    w, h = px(44), px(14)
    c = tk.Canvas(parent, width=w, height=h, bg=bg, highlightthickness=0, bd=0, takefocus=0)
    r = px(4.5)
    cy = h / 2.0
    for idx, color in enumerate(("#ff5f56", "#ffbd2e", "#27c93f")):
        cx = px(6) + idx * px(14)
        c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=color, outline="")
    return c


def create_code_shell(parent, title, right_action=None, bg=CODE_BG, border=CODE_BORDER, radius=12):
    """Build a rounded dark code window frame with macOS-style dots and header action."""
    shell = RoundedFrame(parent, bg=bg, padx=11, pady=9, border=border, radius=radius)
    bar = tk.Frame(shell, bg=bg)
    bar.pack(fill="x", pady=px((0, 6)))
    _draw_window_dots(bar, bg).pack(side="left", padx=px((0, 4)))
    tk.Label(bar, text=title, bg=bg, fg="#d8dee4", font=(CODE_FONT, 9, "bold")).pack(side="left", padx=px((4, 0)))
    if right_action:
        caption, cmd = right_action
        button(bar, caption, cmd, "dark", padx=px(9), pady=px(3), font=(FONT, 8, "bold"), radius=8).pack(side="right")
    tk.Frame(shell, bg="#2c3138", height=1).pack(fill="x", pady=px((0, 6)))
    return shell


def editor_header_bar(parent, title, right_action=None):
    """Build a dark VS Code-style header bar directly inside a rounded bar."""
    bar = RoundedFrame(parent, bg=CODE_HEADER, padx=10, pady=6, border=CODE_BORDER, radius=10)
    bar.pack(fill="x", pady=px((0, 4)))
    _draw_window_dots(bar, CODE_HEADER).pack(side="left", padx=px((0, 4)))
    tk.Label(bar, text=title, bg=CODE_HEADER, fg="#d0d7de", font=(CODE_FONT, 9, "bold")).pack(side="left", padx=px((4, 0)))
    if right_action:
        caption, cmd = right_action
        button(bar, caption, cmd, "dark", padx=px(8), pady=px(2), font=(FONT, 8, "bold"), radius=8).pack(side="right")
    return bar


class ScrollArea(tk.Frame):
    def __init__(self, parent, background=BG):
        super().__init__(parent, bg=background)
        self.canvas = tk.Canvas(self, bg=background, highlightthickness=px(0), bd=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y", padx=px((0, 2)), pady=px(4))
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas, bg=background)
        self.window = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self._last_bbox = None
        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(self.window, width=event.width))

    def _on_inner_configure(self, _=None):
        bbox = self.canvas.bbox("all")
        if not bbox:
            return
        if bbox != self._last_bbox:
            self._last_bbox = bbox
            self.canvas.configure(scrollregion=bbox)
        content_h = bbox[3] - bbox[1]
        canvas_h = self.canvas.winfo_height()
        if canvas_h > 4 and content_h <= canvas_h and self.canvas.yview()[0] > 0.0:
            self.canvas.yview_moveto(0)

    def ensure_visible(self, widget):
        if not widget or not widget.winfo_exists():
            return
        bbox = self.canvas.bbox("all")
        canvas_h = self.canvas.winfo_height()
        if not bbox or canvas_h <= 4:
            return
        total_h = bbox[3] - bbox[1]
        if total_h <= canvas_h:
            return
        y_top = widget.winfo_rooty() - self.inner.winfo_rooty()
        y_bot = y_top + widget.winfo_height() + px(12)
        view_top_frac, view_bot_frac = self.canvas.yview()
        view_top = view_top_frac * total_h
        view_bot = view_bot_frac * total_h
        if y_bot > view_bot:
            target = max(0.0, min(1.0, (y_bot - canvas_h) / total_h))
            self.canvas.yview_moveto(target)
        elif y_top < view_top:
            target = max(0.0, min(1.0, y_top / total_h))
            self.canvas.yview_moveto(target)


class CodeEditor(tk.Frame):
    def __init__(self, parent, value, on_change=None, on_run=None, height=15, lang="python", bordered=False):
        super().__init__(parent, bg=CODE_BG, highlightbackground=CODE_BORDER, highlightthickness=px(1) if bordered else 0, bd=0)
        self.on_change = on_change
        self.lang = lang
        self.highlight_job = None
        self._suppress_change = False
        self.text = tk.Text(
            self, bg=CODE_BG, fg=CODE_FG, insertbackground="#aeafad",
            font=(CODE_FONT, 11), height=height, wrap="none", undo=True, maxundo=100,
            relief="flat", bd=0, padx=px(10), pady=px(6), spacing1=1, spacing3=1,
            selectbackground=CODE_SELECT, tabs=(40,), highlightthickness=0,
        )
        self.lines = tk.Text(
            self, bg=CODE_BG, fg=CODE_GUTTER, font=(CODE_FONT, 11), width=4,
            height=height, wrap="none", relief="flat", bd=0, padx=px(6), pady=px(6),
            spacing1=1, spacing3=1, takefocus=0, state="disabled", highlightthickness=0,
        )
        divider = tk.Frame(self, bg="#2b3038", width=1)
        vertical = ttk.Scrollbar(self, orient="vertical", style="Dark.Vertical.TScrollbar", command=self._scroll)
        horizontal = ttk.Scrollbar(self, orient="horizontal", style="Dark.Horizontal.TScrollbar", command=self.text.xview)
        self.text.configure(yscrollcommand=lambda first, last: (vertical.set(first, last), self.lines.yview_moveto(first)), xscrollcommand=horizontal.set)
        self.lines.grid(row=0, column=0, sticky="ns")
        divider.grid(row=0, column=1, sticky="ns", pady=px(4))
        self.text.grid(row=0, column=2, sticky="nsew")
        vertical.grid(row=0, column=3, sticky="ns", pady=px(2))
        horizontal.grid(row=1, column=2, sticky="ew", padx=px((0, 2)), pady=px((2, 0)))
        self.columnconfigure(2, weight=1)
        self.rowconfigure(0, weight=1)
        configure_code_tags(self.text)
        self.text.bind("<<Modified>>", self._changed)
        self.text.bind("<Tab>", self._tab)
        for seq in ("<Control-Return>", "<Control-KP_Enter>"):
            self.text.bind(seq, lambda _: (on_run() if on_run else None, "break")[-1])
        self.set(value)

    def set_lang(self, lang):
        if lang != self.lang:
            self.lang = lang
            self.highlight()

    def _scroll(self, *args):
        self.text.yview(*args)
        self.lines.yview(*args)

    def _tab(self, _):
        if self.text.cget("state") != "disabled":
            self.text.insert("insert", "    ")
        return "break"

    def get(self):
        return self.text.get("1.0", "end-1c")

    def set(self, value, notify=False):
        was_disabled = self.text.cget("state") == "disabled"
        self._suppress_change = not notify
        try:
            self.text.configure(state="normal")
            self.text.delete("1.0", "end")
            self.text.insert("1.0", value)
            self.text.edit_reset()
            self.text.edit_modified(False)
            self.highlight()
            if was_disabled:
                self.text.configure(state="disabled")
        finally:
            self._suppress_change = False
        if notify and self.on_change:
            self.on_change(self.get())

    def set_silent(self, value):
        if self.get() == value:
            return
        self.set(value, notify=False)

    def _changed(self, _):
        if not self.text.edit_modified():
            return
        self.text.edit_modified(False)
        if not self._suppress_change and self.on_change:
            self.on_change(self.get())
        if self.highlight_job:
            self.after_cancel(self.highlight_job)
        self.highlight_job = self.after(120, self.highlight)

    def highlight(self):
        self.highlight_job = None
        text = self.get()
        self.lines.configure(state="normal")
        self.lines.delete("1.0", "end")
        self.lines.insert("1.0", "\n".join(str(i + 1) for i in range(text.count("\n") + 1)))
        self.lines.configure(state="disabled")
        apply_code_syntax(self.text, text, self.lang)

    def destroy(self):
        if self.highlight_job:
            self.after_cancel(self.highlight_job)
        super().destroy()


def draw_mascot(canvas, theme="green", scale=1.0):
    halo, shadow, laptop_edge = {
        "python": ("#dae8f4", "#c5d8ea", "#355570"),
        "rust": ("#f7dfd7", "#e8c8bd", "#5c362c"),
    }.get(theme, ("#d7ede0", "#c3dfd0", "#2f5745"))
    # Symmetric character composition centered around x=120 in a 240x190 design box
    canvas.create_oval(28, 6, 212, 178, fill=halo, outline="")
    canvas.create_oval(34, 167, 206, 183, fill=shadow, outline="")
    canvas.create_line(
        148, 126, 176, 134, 198, 120, 195, 102,
        fill="#2c996b", width=max(4, px(18 * scale)), smooth=True, capstyle="round",
    )
    canvas.create_oval(82, 82, 158, 148, fill="#33a172", outline="")
    canvas.create_oval(97, 94, 143, 138, fill="#b7e5cc", outline="")
    # Head and symmetrical crest/face
    canvas.create_polygon(119, 32, 108, 12, 121, 9, 123, 30, fill=PY_BLUE, outline="", smooth=True)
    canvas.create_polygon(121, 32, 133, 13, 145, 20, 127, 33, fill="#ffd43b", outline="", smooth=True)
    canvas.create_oval(72, 30, 168, 98, fill="#45b884", outline="")
    # Left & right eyes (x=99, x=141 -> symmetric +-21 around 120)
    canvas.create_oval(91, 49, 107, 71, fill=WHITE, outline="")
    canvas.create_oval(133, 49, 149, 71, fill=WHITE, outline="")
    canvas.create_oval(96, 55, 103, 67, fill=INK, outline="")
    canvas.create_oval(138, 55, 145, 67, fill=INK, outline="")
    canvas.create_oval(98, 57, 101, 60, fill=WHITE, outline="")
    canvas.create_oval(140, 57, 143, 60, fill=WHITE, outline="")
    # Cheeks & smile
    canvas.create_oval(80, 72, 94, 79, fill="#e8a795", outline="")
    canvas.create_oval(146, 72, 160, 79, fill="#e8a795", outline="")
    canvas.create_arc(107, 66, 133, 84, start=200, extent=140, style="arc", outline="#1a5c41", width=max(1, px(2 * scale)))
    # Rounded laptop screen centered at x=120
    laptop_id = _draw_rounded_rect(canvas, 68, 112, 172, 164, 10, fill="#1e2227", outline=laptop_edge, width=max(1, px(2 * scale)))
    canvas.create_line(58, 168, 182, 168, width=max(2, px(4 * scale)), fill=laptop_edge, capstyle="round")
    canvas.create_text(38, 56, text="✦", fill=PY_GOLD, font=(FONT, max(11, round(19 * scale))))
    canvas.create_text(202, 64, text="✧", fill=PY_BLUE, font=(FONT, max(10, round(17 * scale))))

    # Uniformly scale mascot artwork, then add & center crisp prompt inside laptop & center whole scene in canvas
    factor = DPI_SCALE * scale
    canvas.scale("all", 0, 0, factor, factor)
    lb = canvas.bbox(laptop_id)
    if lb:
        lcx, lcy = (lb[0] + lb[2]) / 2.0, (lb[1] + lb[3]) / 2.0
    else:
        lcx, lcy = 120 * factor, 138 * factor
    prompt_id = canvas.create_text(
        lcx, lcy, text=">_", fill="#4ec9b0",
        font=(CODE_FONT, max(11, round(19 * scale)), "bold"), anchor="center",
    )
    _center_canvas_bbox(canvas, prompt_id, lcx, lcy, center_x=True, center_y=True)

    tw = int(float(canvas.cget("width") or 0))
    th = int(float(canvas.cget("height") or 0))
    ab = canvas.bbox("all")
    if ab and tw > 20 and th > 20:
        dx = (tw / 2.0) - ((ab[0] + ab[2]) / 2.0)
        dy = (th / 2.0) - ((ab[1] + ab[3]) / 2.0)
        canvas.move("all", dx, dy)


class CodeStepApp(tk.Tk):
    _DRAFT_KEYS = {
        "python": ("code", "stdin", "sample"),
        "rust": ("rustCode", "rustStdin", "rustSample"),
    }

    def __init__(self, data_dir=None, hidden=False):
        super().__init__()
        global DPI_SCALE
        DPI_SCALE = self.winfo_fpixels("1i") / 96
        if hidden:
            self.withdraw()
        self.title("코드스텝 · Python & Rust 코딩 학습 스튜디오")
        self.configure(bg=BG)
        width = min(px(1440), self.winfo_screenwidth() - px(60))
        height = min(px(880), self.winfo_screenheight() - px(90))
        self.geometry(f"{max(px(980), width)}x{max(px(660), height)}")
        self.minsize(px(980), px(660))
        self._icon_photos = []
        self._win_hicons = []
        self._apply_window_icons()
        if not hidden:
            self.bind("<Map>", lambda _: self._sync_win32_taskbar_icons(), add="+")
        self.option_add("*Font", (FONT, 10))
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Green.Horizontal.TProgressbar", background=GREEN, troughcolor="#dce6df", bordercolor="#dce6df", lightcolor=GREEN, darkcolor=GREEN)
        style.configure("Py.Horizontal.TProgressbar", background=PY_BLUE, troughcolor="#d5e2ec", bordercolor="#d5e2ec", lightcolor=PY_BLUE, darkcolor=PY_BLUE)
        style.configure("Rust.Horizontal.TProgressbar", background=RUST_ORANGE, troughcolor="#ebd7d0", bordercolor="#ebd7d0", lightcolor=RUST_ORANGE, darkcolor=RUST_ORANGE)
        style.configure(
            "TScrollbar",
            background="#cad6ce",
            troughcolor=BG,
            bordercolor=BG,
            lightcolor="#cad6ce",
            darkcolor="#cad6ce",
            arrowcolor="#74887c",
            borderwidth=0,
            relief="flat",
            width=px(10),
        )
        for s_name in ("Dark.Vertical.TScrollbar", "Dark.Horizontal.TScrollbar"):
            style.configure(
                s_name,
                background="#3a424c",
                troughcolor=CODE_BG,
                bordercolor=CODE_BG,
                lightcolor="#3a424c",
                darkcolor="#3a424c",
                arrowcolor="#8a939e",
                borderwidth=0,
                relief="flat",
                width=px(9),
            )
            style.map(s_name, background=[("active", "#4d5764"), ("!active", "#363d46")])
        self.store = ProgressStore(data_dir)
        self.runtime = discover_python_runtime(self.progress["settings"].get("pythonPath", ""))
        self.rust_runtime = discover_rust_runtime(self.progress["settings"].get("rustPath", ""))
        self.editors = discover_editors()
        self.workspace = WorkspaceManager(
            self.store.folder,
            self.progress["settings"].get("workspaceDir", ""),
            isolated=data_dir is not None,
        )
        saved_lang = self.progress["settings"].get("activeLang", "python")
        self.lang_filter = saved_lang if saved_lang in ("python", "rust") else "python"
        self.setup_lang = self.lang_filter
        self.setup_status = None
        self.route = self.lang_filter
        self.level_filter = "all"
        self.review_lang_filter = "all"
        initial_next = next_lesson(self.progress, self.lang_filter)
        self.expanded = {initial_next["unitId"]}
        self.session = None
        self.lesson_overlay = None
        self.controls = {}
        self.tasks = {}
        self.results = queue.Queue()
        self.task_id = 0
        self.closing = False
        self.play_running = False
        self.play_result = None
        self.play_task_dir = None
        self.play_script_path = None
        self.play_result_frame = None
        self.play_sync_label = None
        self.console = None
        self.repl_entry = None
        self.repl_history = []
        self.repl_cursor = 0
        self.repl_transcript = []
        self.repl_running = False
        self.editor = None
        self.lesson_editor = None
        self.lesson_result_frame = None
        self.lesson_feedback_frame = None
        self.lesson_sync_label = None
        self.lesson_hint_frame = None
        self.lesson_ref_frame = None
        self.lesson_concept_ex_frame = None
        self.watch_state = None
        self.sync_write_job = None
        self.draft_job = None
        self.toast_job = None
        self.resize_job = None
        self.poll_job = None
        self.watch_job = None
        self.home_two_cols = None
        self.play_two_cols = None
        self.lesson_two_cols = None
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)
        self._shell()
        self.update_idletasks()
        self.navigate(self.route)
        self.bind_all("<MouseWheel>", self._wheel, add=True)
        self.bind("<KeyPress>", self._key, add=True)
        self.bind("<Control-Return>", self._handle_ctrl_enter, add=True)
        self.bind("<Control-KP_Enter>", self._handle_ctrl_enter, add=True)
        self.bind("<Configure>", self._on_configure, add=True)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.poll_job = self.after(80, self._poll_results)
        self.watch_job = self.after(500, self._watch_workspace)
        if self.store.warning:
            self.after(200, lambda: self.toast(self.store.warning))

    @property
    def progress(self):
        return self.store.progress

    def _shell(self):
        self.sidebar = tk.Frame(self, bg=WHITE, width=px(192), padx=px(12), pady=px(14), highlightbackground=LINE, highlightthickness=px(1))
        self.sidebar.grid(row=0, column=0, rowspan=3, sticky="ns")
        self.sidebar.grid_propagate(False)
        self.sidebar.pack_propagate(False)
        brand = tk.Frame(self.sidebar, bg=WHITE)
        brand.pack(fill="x", pady=px((2, 4)))
        _draw_brand_emblem(brand).pack(side="left")
        label(brand, " 코드스텝", 15, INK, True).pack(side="left", padx=px((4, 0)))
        label(self.sidebar, "PYTHON & RUST STUDIO", 8, MUTED, True).pack(anchor="w", padx=px(2), pady=px((2, 14)))
        label(self.sidebar, "메뉴", 8, "#7e9186", True).pack(anchor="w", padx=px(8), pady=px((0, 6)))
        self.nav_buttons = {}
        for route, glyph, text in ROUTES:
            item = NavPill(self.sidebar, route, glyph, text, lambda name=route: self.navigate(name))
            item.pack(fill="x", pady=px(2))
            self.nav_buttons[route] = item
        bottom = tk.Frame(self.sidebar, bg=WHITE)
        bottom.pack(side="bottom", fill="x")
        note = card(bottom, PY_BLUE_PALE, 11, border="#cfe0ef", radius=12)
        note.pack(fill="x", pady=px((0, 8)))
        label(note, "실제 컴파일·실행 연동", 9, PY_BLUE, True).pack(anchor="w")
        label(note, "Python IDLE · rustc\nVS Code 저장 자동 인식", 8, MUTED).pack(anchor="w", pady=px((3, 0)))
        self.runtime_badge = label(bottom, "", 8, MUTED, wraplength=px(164))
        self.runtime_badge.pack(anchor="w")
        self._refresh_runtime_badge()
        label(bottom, "CODESTEP · DESKTOP 3.0", 7, "#82948a").pack(anchor="w", pady=px((4, 0)))

        top = tk.Frame(self, bg=WHITE, padx=px(20), pady=px(10), highlightbackground=LINE, highlightthickness=px(1))
        top.grid(row=0, column=1, sticky="ew")
        self.page_label = label(top, "학습하기  /  코드스텝 스튜디오", 10, INK, True)
        self.page_label.pack(side="left")
        pills = tk.Frame(top, bg=WHITE)
        pills.pack(side="right")
        self.stat_streak = pill(pills, "", PY_BLUE, PY_BLUE_PALE, border="#cfe0ef", size=9, padx=10, pady=4)
        self.stat_streak.pack(side="left", padx=px((0, 6)))
        self.stat_xp = pill(pills, "", GREEN, PALE, border="#bce0ce", size=9, padx=10, pady=4)
        self.stat_xp.pack(side="left", padx=px((0, 6)))
        self.stat_hearts = pill(pills, "♥ 5", "#b85c50", "#faece9", border="#f0cdc6", size=9, padx=10, pady=4)
        self.stat_hearts.pack(side="left")

        self.scroll = ScrollArea(self)
        self.scroll.grid(row=1, column=1, sticky="nsew")
        self.status = label(self, "한 줄의 코드, 한 걸음의 성장.", 9, MUTED, padx=px(20), pady=px(5), bg=WHITE)
        self.status.grid(row=2, column=1, sticky="ew")

    def _refresh_runtime_badge(self):
        self.setup_status = None
        if hasattr(self, "runtime_badge") and self.runtime_badge.winfo_exists():
            py_state = "시스템" if self.runtime["available"] else "내장"
            rs_state = "rustc" if self.rust_runtime["available"] else "미설치"
            self.runtime_badge.configure(
                text=f"● Python({py_state}) · Rust({rs_state})",
                fg=GREEN if (self.runtime["available"] or self.rust_runtime["available"]) else "#967832",
            )

    def _play_lang(self):
        return "rust" if self.progress["settings"].get("playgroundLang") == "rust" else "python"

    def _lesson_lang(self, question=None, lesson=None):
        if question and question.get("lang") in LANG_META:
            return question["lang"]
        if lesson and lesson.get("lang") in LANG_META:
            return lesson["lang"]
        return "python"

    def _wheel(self, event):
        if isinstance(event.widget, tk.Listbox):
            return
        if isinstance(event.widget, tk.Text):
            if event.widget.cget("state") != "disabled":
                return
            first, last = event.widget.yview()
            steps = -int(event.delta / 120) if abs(event.delta) >= 120 else (-1 if event.delta > 0 else 1)
            if (first > 0.0 or last < 1.0) and ((steps < 0 and first > 0.0) or (steps > 0 and last < 1.0)):
                event.widget.yview_scroll(steps * 2, "units")
                return "break"
        scroll = getattr(self, "lesson_scroll", None) if self.session else self.scroll
        if scroll and scroll.winfo_exists():
            if abs(event.delta) >= 120:
                step = int(-event.delta / 120)
            elif event.delta != 0:
                step = -1 if event.delta > 0 else 1
            else:
                step = 0
            if step:
                scroll.canvas.yview_scroll(step, "units")

    def _make_two_cols(self, parent, two_cols, left_weight=11, right_weight=10, gap=14):
        wrap = tk.Frame(parent, bg=parent.cget("bg"))
        wrap.pack(fill="both", expand=True)
        left = tk.Frame(wrap, bg=wrap.cget("bg"))
        right = tk.Frame(wrap, bg=wrap.cget("bg"))
        if two_cols:
            wrap.columnconfigure(0, weight=left_weight, uniform="split_pane")
            wrap.columnconfigure(1, weight=right_weight, uniform="split_pane")
            wrap.rowconfigure(0, weight=1)
            left.grid(row=0, column=0, sticky="nsew", padx=px((0, gap)))
            right.grid(row=0, column=1, sticky="nsew", padx=px((gap, 0)))
        else:
            wrap.columnconfigure(0, weight=1)
            left.grid(row=0, column=0, sticky="nsew")
            right.grid(row=1, column=0, sticky="nsew", pady=px((16, 0)))
        return wrap, left, right

    def _on_configure(self, event):
        if event.widget is not self:
            return
        two_cols = event.width >= px(1080)
        changed = False
        if self.session:
            if not self.session.get("running") and self.lesson_two_cols is not None and two_cols != self.lesson_two_cols:
                changed = True
        elif self.route in ("python", "rust") and self.home_two_cols is not None and two_cols != self.home_two_cols:
            changed = True
        elif self.route == "playground" and self.play_two_cols is not None and two_cols != self.play_two_cols:
            changed = True
        if changed:
            if self.resize_job:
                self.after_cancel(self.resize_job)
            self.resize_job = self.after(150, self._reflow_layout)

    def _reflow_layout(self):
        self.resize_job = None
        if self.session:
            if not self.session.get("running"):
                if self.lesson_editor and self.lesson_editor.winfo_exists():
                    self.session["code"] = self.lesson_editor.get()
                position = self.lesson_scroll.canvas.yview()[0] if getattr(self, "lesson_scroll", None) else 0
                self.render_lesson()
                self.update_idletasks()
                if getattr(self, "lesson_scroll", None):
                    self.lesson_scroll.canvas.yview_moveto(position)
            return
        if self.route in ("python", "rust", "playground"):
            position = self.scroll.canvas.yview()[0]
            self.navigate(self.route)
            self.update_idletasks()
            self.scroll.canvas.yview_moveto(position)

    def _key(self, event):
        if not self.session or self.session.get("done") or self.session["index"] < 0:
            return
        if isinstance(self.focus_get(), (tk.Text, tk.Entry)):
            return
        question = self.current_question()
        opts = self.session.get("options") or question.get("options") or []
        if event.char in ("1", "2", "3", "4") and len(opts) >= int(event.char) and not self.session.get("feedback", {}).get("correct"):
            self.choose(opts[int(event.char) - 1])

    def _handle_ctrl_enter(self, _=None):
        session = self.session
        if session:
            if session.get("done"):
                self.close_lesson()
            elif session["index"] < 0:
                self.next_question()
            elif session.get("running"):
                return "break"
            elif session["feedback"].get("correct"):
                self.next_question()
            else:
                check = self.controls.get("check")
                if check and check.winfo_exists() and str(check.cget("state")) != "disabled":
                    self.check_answer()
            return "break"
        if self.route == "playground":
            self.run_playground()
            return "break"
        return None

    def toast(self, text):
        self.status.configure(text=text, fg=GREEN)
        if self.toast_job:
            self.after_cancel(self.toast_job)
        self.toast_job = self.after(6000, lambda: self.status.configure(text="한 줄의 코드, 한 걸음의 성장.", fg=MUTED) if self.status.winfo_exists() else None)

    def save(self):
        try:
            self.store.save()
        except OSError:
            self.toast("학습 기록을 저장하지 못했어요. 설정에서 기록을 내보내 보관해 주세요.")

    def _heading(self, title, subtitle):
        label(self.content, title, 18, INK, True).pack(anchor="w")
        label(self.content, subtitle, 10, MUTED, wraplength=px(980)).pack(anchor="w", pady=px((3, 12)))

    def navigate(self, route):
        if self.session:
            return
        if route == "learn":
            route = self.lang_filter if self.lang_filter in ("python", "rust") else "python"
        if self.route == "playground":
            self._capture_draft()
        self._cancel_sync_write()
        self.watch_state = None
        if route in ("python", "rust"):
            if route == "rust":
                self._refresh_rust_if_missing()
            if self.lang_filter != route:
                self.lang_filter = route
                self.level_filter = "all"
                self.progress["settings"]["activeLang"] = route
                self.expanded.add(next_lesson(self.progress, route)["unitId"])
                self.save()
            elif not any(u["id"] in self.expanded for u in UNITS if u.get("lang", "python") == route):
                self.expanded.add(next_lesson(self.progress, route)["unitId"])
        self.route = route
        self.editor = None
        self.console = None
        self.repl_entry = None
        self.play_result_frame = None
        self.play_sync_label = None
        self.controls = {}
        self.unit_rows = {}
        for widget in self.scroll.inner.winfo_children():
            widget.destroy()
        self.content = tk.Frame(self.scroll.inner, bg=BG, padx=px(20), pady=px(16))
        self.content.pack(fill="both", expand=True)
        for name, widget in self.nav_buttons.items():
            widget.set_active(route == name)
        title = next(title for name, _, title in ROUTES if name == route)
        self.page_label.configure(text=f"{title}   /   코드스텝 스튜디오")
        self.stat_streak.set_text(f"연속 {streak(self.progress)}일")
        self.stat_xp.set_text(f"⚡ {self.progress['xp']:,} XP")
        self.stat_hearts.set_text("♥ 5")
        {"setup": self.setup_page, "python": self.home, "rust": self.home, "review": self.review_page,
         "playground": self.playground, "achievements": self.achievements, "settings": self.settings}[route]()
        self.scroll.canvas.yview_moveto(0)

    def home(self):
        active_lang = "rust" if self.route == "rust" else "python"
        meta = LANG_META[active_lang]
        if active_lang == "rust":
            self._heading("Rust 학습 여정", "소유권·빌림·패턴 매칭부터 실제 rustc 컴파일까지 단계별로 익혀요.")
            hero_bg, hero_border, pb_trough = RUST_PALE, "#eed1c8", "#ebd7d0"
            track_label, cta_kind = "RUST TRACK", "rust"
            rt_pill = self.rust_runtime["label"]
            rt_bg = GREEN if self.rust_runtime["available"] else "#967832"
        else:
            self._heading("Python 학습 여정", "실제 Python 3 · IDLE · VS Code와 연동해 입문부터 기출 실전까지 배워요.")
            hero_bg, hero_border, pb_trough = PY_BLUE_PALE, "#c8dce9", "#d5e2ec"
            track_label, cta_kind = "PYTHON TRACK", "py"
            rt_pill = self.runtime["label"]
            rt_bg = GREEN if self.runtime["available"] else "#967832"

        hero = card(self.content, hero_bg, 16, border=hero_border, radius=16)
        hero.pack(fill="x", pady=px((0, 14)))
        mascot = tk.Canvas(hero, width=px(180), height=px(144), bg=hero_bg, highlightthickness=0, bd=0)
        mascot.pack(side="right", padx=px((12, 4)))
        draw_mascot(mascot, theme=active_lang, scale=0.65)
        badge_row = tk.Frame(hero, bg=hero_bg)
        badge_row.pack(anchor="w", pady=px((0, 7)))
        pill(badge_row, track_label, WHITE, meta["accent"], size=8, padx=9, pady=3).pack(side="left", padx=px((0, 6)))
        pill(badge_row, f"{meta['name']} ({Path(meta['filename']).suffix})", meta["accent"], WHITE, border=hero_border, size=8, padx=8, pady=3).pack(side="left", padx=px((0, 6)))
        pill(badge_row, rt_pill, WHITE, rt_bg, size=8, padx=8, pady=3).pack(side="left")

        scoped_lessons = [l for l in LESSONS if l.get("lang", "python") == active_lang]
        count = sum(1 for l in scoped_lessons if l["id"] in self.progress["completed"])
        total_lessons = len(scoped_lessons)
        pct = round((count / total_lessons) * 100) if total_lessons else 0
        hero_title = (
            f"{meta['name']}의 첫걸음, 함께 시작해요."
            if not count
            else f"{meta['name']} 트랙을 모두 완주했어요!"
            if count >= total_lessons and total_lessons
            else f"{meta['name']} 실력이 차곡차곡 쌓이고 있어요."
        )
        first_steps = (
            "처음이어도 괜찮아요. Python은 이 프로그램 안에 들어 있어서 따로 설치할 것 없이 지금 바로 시작할 수 있어요. "
            "아래 '첫 레슨 시작하기'를 누르면 개념 → 예제 → 문제 순서로 한 걸음씩 안내해요."
            if active_lang == "python"
            else "처음이어도 괜찮아요. 개념·빈칸·순서 문제는 지금 바로 풀 수 있고, 직접 코드를 실행하는 실기 문제는 "
                 "[준비] 탭에서 Rust를 설치한 뒤 풀 수 있어요. Python을 먼저 배우고 오면 훨씬 쉬워요."
        )
        hero_desc = (
            first_steps
            if not count
            else f"{meta['name']} 트랙 {total_lessons}개 레슨을 모두 완료했어요 (100%). 아래 레슨이나 [연습장]에서 자유롭게 복습해 보세요!"
            if count >= total_lessons and total_lessons
            else f"{meta['name']} 트랙 {total_lessons}개 중 {count}개 레슨 완료 ({pct}%). 멋진 한 걸음이에요!"
        )
        label(hero, hero_title, 17, INK, True).pack(anchor="w")
        label(hero, hero_desc, 9, MUTED, wraplength=px(640)).pack(anchor="w", pady=px((4, 8)))
        hero_bar = tk.Frame(hero, bg=hero_bg)
        hero_bar.pack(fill="x", pady=px((0, 11)))
        RoundedProgressBar(hero_bar, fill=meta["accent"], trough=pb_trough, maximum=max(1, total_lessons), value=count, length=260, height=9).pack(side="left")
        label(hero_bar, f"  {pct}%", 9, meta["accent"], True).pack(side="left")
        target_next = next_lesson(self.progress, active_lang)
        cta_label = (
            "첫 레슨 시작하기  →"
            if not count
            else f"{target_next['title']} 다시 풀기  →"
            if count >= total_lessons and total_lessons
            else "이어서 학습하기  →"
        )
        self.controls["start"] = button(hero, cta_label, lambda lid=target_next["id"]: self.start_lesson(lid), kind=cta_kind, pill=True, padx=px(16), pady=px(7))
        self.controls["start"].pack(anchor="w")

        columns = tk.Frame(self.content, bg=BG)
        columns.pack(fill="x")
        columns.columnconfigure(0, weight=1)
        left = tk.Frame(columns, bg=BG)
        left.grid(row=0, column=0, sticky="nsew")
        two_cols = self.winfo_width() >= px(1080)
        self.home_two_cols = two_cols
        if two_cols:
            right = tk.Frame(columns, bg=BG, width=px(236))
            right.grid(row=0, column=1, sticky="ne", padx=px((16, 0)))
            self._daily_panel(right)
        section = tk.Frame(left, bg=BG)
        section.pack(fill="x", pady=px((0, 6)))
        label(section, f"◈  {meta['name']} 커리큘럼", 13, INK, True).pack(side="left")
        unlock_on = self.progress["settings"].get("unlockAll", False)
        button(
            section,
            "● 자유 열기 ON" if unlock_on else "○ 자유 열기 OFF",
            self._toggle_quick_unlock,
            "secondary" if unlock_on else "ghost",
            pill=True,
            padx=px(10),
            pady=px(4),
            font=(FONT, 8, "bold" if unlock_on else "normal"),
        ).pack(side="right")
        label(section, f"{count} / {total_lessons} 레슨 완료  ·  ", 9, MUTED, True).pack(side="right")

        lang_units = [u for u in UNITS if u.get("lang", "python") == active_lang]
        filter_bar = tk.Frame(left, bg=BG)
        filter_bar.pack(fill="x", pady=px((0, 8)))
        for lvl_key, lvl_label in LEVELS:
            tier_count = len(lang_units) if lvl_key == "all" else sum(1 for u in lang_units if u.get("level", "intro") == lvl_key)
            if lvl_key != "all" and tier_count == 0:
                continue
            selected = self.level_filter == lvl_key
            button(
                filter_bar,
                f"{lvl_label} {tier_count}",
                lambda lk=lvl_key: self._set_level_filter(lk),
                cta_kind if selected else "ghost",
                pill=True,
                padx=px(10),
                pady=px(4),
                font=(FONT, 8, "bold" if selected else "normal"),
            ).pack(side="left", padx=px((0, 5)))

        if active_lang == "rust" and not self.rust_runtime["available"]:
            rust_note = card(left, RUST_PALE, 11, border="#eed1c8", radius=12)
            rust_note.pack(fill="x", pady=px((0, 8)))
            button(rust_note, "준비 탭에서 터미널 설치 →", lambda: self.open_setup("rust"), "rust", pill=True, padx=px(10), pady=px(4), font=(FONT, 8, "bold")).pack(side="right", padx=px((8, 0)))
            label(rust_note, "Rust 개념·빈칸·순서 문제(1~3번)는 rustc 없이도 바로 학습할 수 있어요. 4번 실기·연습장 실행은 로컬 rustc 설치 후 동작해요.", 9, RUST_ORANGE, wraplength=px(520)).pack(anchor="w")

        visible_units = [u for u in lang_units if self.level_filter == "all" or u.get("level", "intro") == self.level_filter]
        unit_nums = {u["id"]: idx for idx, u in enumerate(lang_units, 1)}
        tier_colors = {"intro": GREEN, "beginner": "#2f7a68", "intermediate": "#306998", "advanced": "#7b4397", "exam": "#b45309"}
        for unit in visible_units:
            active = unit["id"] == target_next["unitId"]
            is_midterm_unit = unit.get("kind") == "midterm"
            card_border = meta["accent"] if active else "#e5c88e" if is_midterm_unit else LINE
            box = card(left, WHITE, padding=8, border=card_border, radius=14)
            box.pack(fill="x", pady=px((0, 8)))
            unit_done = sum(1 for l in unit["lessons"] if l["id"] in self.progress["completed"])
            header_bg = hero_bg if active else "#fffaf0" if is_midterm_unit else WHITE
            header = RoundedFrame(box, bg=header_bg, padx=12, pady=8, border="", radius=10, outer_bg=WHITE)
            header.pack(fill="x")
            pill(
                header,
                f"{unit_nums[unit['id']]:02d}",
                WHITE if active else "#8a5314" if is_midterm_unit else MUTED,
                meta["accent"] if active else "#fef0d1" if is_midterm_unit else "#eef2ef",
                size=11,
                padx=9,
                pady=4,
                radius=9,
            ).pack(side="left", padx=px((0, 10)))
            text = tk.Frame(header, bg=header_bg)
            text.pack(side="left", fill="x", expand=True)
            title_row = tk.Frame(text, bg=header_bg)
            title_row.pack(anchor="w")
            label(title_row, unit["title"], 11, INK, True, bg=header_bg).pack(side="left")
            pill(title_row, meta["name"], WHITE, meta["accent"], size=8, padx=7, pady=2).pack(side="left", padx=px((6, 0)))
            pill(title_row, unit.get("levelTitle", "입문"), WHITE, tier_colors.get(unit.get("level", "intro"), PY_BLUE), size=8, padx=7, pady=2).pack(side="left", padx=px((4, 0)))
            if is_midterm_unit:
                pill(title_row, "⚑ 중간 시험", "#8a5314", "#fef0d1", border="#ebd096", size=8, padx=7, pady=2).pack(side="left", padx=px((4, 0)))
            label(text, unit["description"], 8, MUTED, bg=header_bg, wraplength=px(440)).pack(anchor="w", pady=px((2, 0)))
            right_hdr = tk.Frame(header, bg=header_bg)
            right_hdr.pack(side="right")
            label(right_hdr, f"{unit_done}/{len(unit['lessons'])}", 9, GREEN if unit_done == len(unit["lessons"]) else MUTED, True, bg=header_bg).pack(side="left", padx=px((0, 8)))
            toggle_btn = button(right_hdr, "접기 ▴" if unit["id"] in self.expanded else "펼치기 ▾", lambda uid=unit["id"]: self.toggle_unit(uid), "ghost", pill=True, padx=px(9), pady=px(3), font=(FONT, 8))
            toggle_btn.pack(side="left")
            path_wrap = tk.Frame(box, bg=WHITE)
            self.unit_rows[unit["id"]] = (path_wrap, toggle_btn, unit, meta)
            if unit["id"] in self.expanded:
                self._populate_unit_path(path_wrap, unit, meta)
                path_wrap.pack(fill="x")
        if not two_cols:
            bottom_panel = tk.Frame(columns, bg=BG)
            bottom_panel.grid(row=1, column=0, sticky="ew", pady=px((12, 0)))
            self._daily_panel(bottom_panel)

    def _populate_unit_path(self, path_wrap, unit, meta):
        for child in path_wrap.winfo_children():
            child.destroy()
        path = tk.Frame(path_wrap, bg=WHITE, padx=px(8), pady=px(10))
        path.pack(fill="x")
        for i, lesson in enumerate(unit["lessons"]):
            path.columnconfigure(i, weight=1, uniform="lesson")
            stop = tk.Frame(path, bg=WHITE)
            stop.grid(row=0, column=i, sticky="nsew", padx=px(4))
            done = lesson["id"] in self.progress["completed"]
            unlocked = is_unlocked(self.progress, lesson["id"])
            is_mid = lesson.get("kind") == "midterm" or unit.get("kind") == "midterm"
            state_kind = "done" if done else "current" if unlocked else "locked"
            LessonNode(stop, state_kind, meta["accent"], lambda lid=lesson["id"]: self.start_lesson(lid), midterm=is_mid).pack(pady=px((0, 6)))
            title_wrap = px(320 if len(unit["lessons"]) == 1 else 145)
            label(stop, lesson["title"], 9, INK if unlocked else MUTED, True, anchor="center", wraplength=title_wrap).pack(fill="x")
            q_cnt = len(lesson.get("questions") or [])
            repeat_xp = 10 if is_mid else 5
            sub_txt = f"다시 풀기 · +{repeat_xp} XP" if done else f"{'중간 시험 · ' if is_mid else ''}{lesson.get('minutes', 4)}분 · {q_cnt}문제"
            label(stop, sub_txt, 8, GREEN if done else "#8a5314" if is_mid and unlocked else MUTED, anchor="center").pack(fill="x", pady=px((2, 0)))

    def toggle_unit(self, unit_id):
        self.expanded.symmetric_difference_update({unit_id})
        row = self.unit_rows.get(unit_id)
        if not row:
            self.navigate(self.route)
            return
        path_wrap, toggle_btn, unit, meta = row
        if not path_wrap.winfo_exists():
            self.navigate(self.route)
            return
        expanded = unit_id in self.expanded
        if toggle_btn.winfo_exists():
            toggle_btn.configure(text="접기 ▴" if expanded else "펼치기 ▾")
        if expanded:
            self._populate_unit_path(path_wrap, unit, meta)
            path_wrap.pack(fill="x")
            self.after(25, lambda w=path_wrap: self.scroll.ensure_visible(w) if self.scroll and self.scroll.winfo_exists() and w.winfo_exists() and not self.session else None)
        else:
            for child in path_wrap.winfo_children():
                child.destroy()
            path_wrap.pack_forget()

    def _refresh_rust_if_missing(self):
        if not self.rust_runtime.get("available"):
            self.rust_runtime = discover_rust_runtime(self.progress["settings"].get("rustPath", ""), refresh=True)
            self._refresh_runtime_badge()
        return self.rust_runtime

    def _set_lang_filter(self, lang_key):
        target_route = "rust" if lang_key == "rust" else "python"
        self.navigate(target_route)

    def _set_level_filter(self, level):
        self.level_filter = level
        active_lang = "rust" if self.route == "rust" else "python"
        if level != "all":
            tier_units = [u["id"] for u in UNITS if u.get("lang", "python") == active_lang and u.get("level", "intro") == level]
            if tier_units and not any(uid in self.expanded for uid in tier_units):
                self.expanded.add(tier_units[0])
        self.navigate(active_lang)

    def _toggle_quick_unlock(self):
        self.progress["settings"]["unlockAll"] = not self.progress["settings"].get("unlockAll", False)
        self.save()
        self.navigate(self.route if self.route in ("python", "rust") else self.lang_filter)

    def _daily_panel(self, parent):
        today = activity_today(self.progress)
        goal = self.progress["settings"]["goal"]
        panel = card(parent, padding=14, radius=14)
        panel.pack(fill="x", pady=px((0, 10)))
        label(panel, "오늘의 목표", 11, INK, True).pack(anchor="w")
        label(panel, f"{today['xp']} / {goal} XP", 17, GREEN, True).pack(anchor="w", pady=px((6, 6)))
        RoundedProgressBar(panel, fill=GREEN, trough="#dce6df", maximum=goal, value=min(goal, today["xp"]), length=180, height=8).pack(fill="x")
        label(panel, "목표 달성! 정말 잘했어요." if today["xp"] >= goal else f"목표까지 {goal-today['xp']} XP 남았어요.", 8, MUTED).pack(anchor="w", pady=px((6, 10)))
        week = tk.Frame(panel, bg=WHITE)
        week.pack(fill="x")
        dot_sz = px(20)
        for i in range(7):
            week.columnconfigure(i, weight=1, uniform="weekday")
            day = date.today() - timedelta(days=6 - i)
            studied = self.progress["activity"].get(day.isoformat(), {}).get("xp", 0) > 0
            column = tk.Frame(week, bg=WHITE)
            column.grid(row=0, column=i, sticky="ew")
            label(column, "월화수목금토일"[day.weekday()], 8, MUTED, anchor="center").pack(fill="x")
            dc = tk.Canvas(column, width=dot_sz, height=dot_sz, bg=WHITE, highlightthickness=0, bd=0)
            dc.pack(pady=px((3, 0)))
            pad = px(3)
            if studied:
                dc.create_oval(pad, pad, dot_sz - pad, dot_sz - pad, fill=GREEN, outline="")
                cx, cy = dot_sz / 2.0, dot_sz / 2.0
                s = px(3.2)
                dc.create_line(cx - s, cy, cx - s * 0.2, cy + s * 0.75, cx + s, cy - s * 0.7, fill=WHITE, width=max(1, px(1.8)), capstyle="round", joinstyle="round")
            else:
                dc.create_oval(pad, pad, dot_sz - pad, dot_sz - pad, fill="#f7faf8", outline="#c8d6ce", width=max(1, px(1.3)))
        panel = card(parent, padding=14, radius=14)
        panel.pack(fill="x", pady=px((0, 10)))
        label(panel, "오늘의 미션", 11, INK, True).pack(anchor="w", pady=px((0, 6)))
        for title, value, target in [("레슨 하나 완료하기", today["lessons"], 1), (f"{goal} XP 모으기", today["xp"], goal), ("오답 하나 복습하기", today["reviews"], 1)]:
            label(panel, ("✓  " if value >= target else "○  ") + title, 9, GREEN if value >= target else MUTED).pack(anchor="w", pady=px(3))
        panel = card(parent, PY_BLUE_PALE, 13, border="#cfe0ef", radius=14)
        panel.pack(fill="x")
        label(panel, ">_  코드 실행 연습장", 10, PY_BLUE, True).pack(anchor="w")
        label(panel, "Python(.py · >>> REPL)과\nRust(.rs · rustc)를 바로 실행해요.", 8, MUTED).pack(anchor="w", pady=px((5, 5)))
        label(panel, str(self.workspace.root), 8, INK, wraplength=px(195)).pack(anchor="w")
        button(panel, "코드 연습장 열기 →", lambda: self.navigate("playground"), "primary", pill=True, font=(FONT, 9, "bold"), padx=px(12), pady=px(6)).pack(fill="x", pady=px((8, 0)))

    def _set_review_lang_filter(self, lang_key):
        self.review_lang_filter = lang_key if lang_key in ("all", "python", "rust") else "all"
        self.navigate("review")

    def review_page(self):
        self._heading("실수도, 성장의 한 걸음", "Python · Rust 오답을 언어별로 골라 다시 풀고 기억을 단단하게 만들어요.")
        all_mistakes = [q for q in QUESTIONS if q["id"] in self.progress["mistakes"]]
        tab_bar = tk.Frame(self.content, bg=BG)
        tab_bar.pack(fill="x", pady=px((0, 10)))
        for lkey, llabel, active_kind in [("all", "전체 오답", "primary"), ("python", "Python", "py"), ("rust", "Rust", "rust")]:
            lcount = len(all_mistakes) if lkey == "all" else sum(1 for q in all_mistakes if q.get("lang", "python") == lkey)
            selected = self.review_lang_filter == lkey
            button(
                tab_bar,
                f"{llabel} ({lcount})",
                lambda k=lkey: self._set_review_lang_filter(k),
                active_kind if selected else "ghost",
                pill=True,
                padx=px(12),
                pady=px(5),
                font=(FONT, 9, "bold" if selected else "normal"),
            ).pack(side="left", padx=px((0, 6)))

        active_lang = None if self.review_lang_filter == "all" else self.review_lang_filter
        mistakes = sorted(
            (q for q in all_mistakes if not active_lang or q.get("lang", "python") == active_lang),
            key=lambda q: -self.progress["mistakes"].get(q["id"], {}).get("count", 1),
        )
        if not mistakes:
            empty = card(self.content, padding=24, radius=16)
            empty.pack(fill="x")
            canvas = tk.Canvas(empty, width=px(184), height=px(144), bg=WHITE, highlightthickness=0, bd=0)
            canvas.pack()
            draw_mascot(canvas, scale=0.72)
            empty_title = "아직 오답이 없어요" if not active_lang else f"{LANG_META[active_lang]['name']} 오답이 없어요"
            label(empty, empty_title, 15, INK, True, anchor="center").pack(fill="x", pady=px((8, 8)))
            label(empty, "레슨에서 틀린 문제를 여기에 모아 둘게요.\n처음부터 다 알 필요는 없어요. 함께 배워 가요.", 10, MUTED, anchor="center", justify="center").pack(fill="x")
            start_lang = active_lang or self.lang_filter
            button(empty, f"{LANG_META[start_lang]['name']} 학습 시작  →", lambda l=start_lang: self.start_lesson(next_lesson(self.progress, l)["id"]), kind="py" if start_lang == "python" else "rust", pill=True, padx=px(16), pady=px(7)).pack(pady=px((14, 0)))
            return
        intro = card(self.content, PALE, 14, border="#c4dfd0", radius=14)
        intro.pack(fill="x", pady=px((0, 12)))
        button(intro, "전체 복습하기  →", lambda l=self.review_lang_filter: self.start_review(lang=l), pill=True, padx=px(14), pady=px(6)).pack(side="right", padx=px((12, 0)))
        label(intro, f"{len(mistakes)}개 문제가 복습을 기다려요", 12, INK, True).pack(anchor="w")
        label(intro, "하트가 줄지 않아요. 해결한 문제마다 +3 XP!", 9, MUTED).pack(anchor="w", pady=px((4, 0)))
        for question in mistakes:
            q_lang = question.get("lang", "python")
            q_meta = LANG_META.get(q_lang, LANG_META["python"])
            box = card(self.content, padding=13, radius=13)
            box.pack(fill="x", pady=px((0, 7)))
            button(box, "다시 풀기", lambda qid=question["id"]: self.start_review(qid), "secondary", pill=True, padx=px(12), pady=px(5)).pack(side="right", padx=px((12, 0)))
            meta_row = tk.Frame(box, bg=WHITE)
            meta_row.pack(anchor="w")
            miss_count = self.progress["mistakes"].get(question["id"], {}).get("count", 1)
            pill(meta_row, q_meta["name"], WHITE, q_meta["accent"], size=8, padx=8, pady=2).pack(side="left", padx=px((0, 6)))
            label(meta_row, f"{question['lessonTitle']} · {TYPE_NAMES[question['type']]} · 오답 {miss_count}회", 9, MUTED).pack(side="left")
            label(box, question["prompt"], 10, INK, True, wraplength=px(620)).pack(anchor="w", pady=px((5, 0)))

    def _build_external_bridge_bar(self, parent, script_path: Path, task_dir: Path, on_reset=None, lang="python"):
        meta = LANG_META.get(lang, LANG_META["python"])
        rt = self.rust_runtime if lang == "rust" else self.runtime
        bridge = card(parent, meta["pale"], 12, border=meta["border"], radius=14)
        bridge.pack(fill="x", pady=px((0, 8)))
        header = tk.Frame(bridge, bg=meta["pale"])
        header.pack(fill="x")
        label(header, f"실제 {meta['name']} 프로그램 연동", 9, meta["accent"], True).pack(side="left")
        pill(header, "● " + rt["label"], WHITE, GREEN if rt["available"] else "#967832", size=8, padx=8, pady=2).pack(side="right")

        editor_hint = "IDLE / VS Code 저장 시 자동 인식" if lang == "python" else "VS Code / 외부 편집기 저장 시 자동 인식"
        sync_lbl = label(bridge, f"● 실시간 감시 중 — {editor_hint}", 8, GREEN, wraplength=px(430))
        sync_lbl.pack(anchor="w", pady=px((4, 1)))
        label(bridge, f"파일: {script_path}", 8, MUTED, wraplength=px(430)).pack(anchor="w", pady=px((0, 7)))

        actions = tk.Frame(bridge, bg=meta["pale"])
        actions.pack(fill="x")
        launch_buttons = []
        if lang == "python":
            launch_buttons.append(
                ("Python IDLE로 열기", lambda: self._run_launcher(launch_idle(script_path, task_dir, self.runtime)),
                 "primary" if self.runtime["hasIdle"] else "ghost")
            )
        if self.editors.get("vscode"):
            launch_buttons.append(
                ("VS Code로 열기", lambda: self._run_launcher(launch_vscode(script_path, task_dir, self.editors["vscode"])),
                 "primary" if lang == "rust" else "secondary")
            )
        launch_buttons.extend([
            ("메모장으로 열기", lambda: self._run_launcher(launch_default_editor(script_path)), "secondary"),
            (
                "터미널 실행",
                lambda: self._run_launcher(
                    launch_rust_terminal(script_path, task_dir, self.rust_runtime)
                    if lang == "rust"
                    else launch_terminal(script_path, task_dir, self.runtime)
                ),
                "ghost",
            ),
            ("폴더 열기", lambda: self._run_launcher(launch_folder(task_dir)), "ghost"),
        ])
        if on_reset:
            launch_buttons.append(("파일 초기화", on_reset, "ghost"))

        cols = 3
        for idx, (text, cmd, kind) in enumerate(launch_buttons):
            r, c = divmod(idx, cols)
            actions.columnconfigure(c, weight=1, uniform="bridge_btn")
            button(actions, text, cmd, kind, radius=9, padx=px(6), pady=px(4), font=(FONT, 8, "bold" if kind != "ghost" else "normal")).grid(
                row=r, column=c, sticky="ew", padx=px((0, 5 if c < cols - 1 else 0)), pady=px((0, 4))
            )
        return sync_lbl

    def _run_launcher(self, outcome):
        _, message = outcome
        self.toast(message)

    def _render_deliverable_list(self, parent, deliverables):
        if not deliverables:
            label(parent, "생성된 결과 파일이 아직 없어요. 코드를 실행해 결과 파일을 만들면 여기에 자동으로 표시돼요.", 9, MUTED, wraplength=px(430)).pack(anchor="w")
            return
        for item in deliverables:
            row = card(parent, "#f4faf7" if item["isOutput"] else SURFACE, 11, border="#cde4d7" if item["isOutput"] else LINE)
            row.pack(fill="x", pady=px((6, 0)))
            top = tk.Frame(row, bg=row.cget("bg"))
            top.pack(fill="x")
            tag = "★ 실기 결과물" if item["isOutput"] else "입력 데이터"
            label(top, f"{item['name']}   [{tag}]", 10, GREEN if item["isOutput"] else MUTED, True).pack(side="left")
            label(top, f"{item['size']:,} bytes · {item['modified']}", 8, MUTED).pack(side="right")
            if item["preview"]:
                preview = item["preview"].strip()
                if len(preview) > 500:
                    preview = preview[:500] + "\n..."
                code_block(row, preview, height=min(8, max(1, preview.count("\n") + 1))).pack(fill="x", pady=px((6, 0)))

    def _activate_watch(self, mode, task_dir: Path, script_path: Path, fixtures=None, question=None):
        text = read_text_safe(script_path)
        deliverables = scan_deliverables(task_dir, script_name=script_path.name, fixtures=fixtures)
        self.watch_state = {
            "mode": mode,
            "dir": Path(task_dir),
            "script": Path(script_path),
            "fixtures": fixtures or {},
            "question": question,
            "last_disk_digest": text_digest(text),
            "last_script_sig": self._file_sig(script_path),
            "last_deliverable_sig": tuple((d["name"], d["size"], d["mtime"]) for d in deliverables),
        }

    @staticmethod
    def _file_sig(path: Path):
        try:
            st = path.stat()
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    def _cancel_sync_write(self):
        if self.sync_write_job:
            self.after_cancel(self.sync_write_job)
            self.sync_write_job = None

    def _schedule_disk_sync(self, script_path: Path, value: str, update_draft=False):
        self._cancel_sync_write()
        self.sync_write_job = self.after(250, lambda p=script_path, v=value, d=update_draft: self._flush_disk_sync(p, v, d))

    def _flush_disk_sync(self, script_path: Path, value: str, update_draft=False):
        self._cancel_sync_write()
        try:
            write_text_safe(script_path, value)
            if self.watch_state and self.watch_state["script"] == Path(script_path):
                self.watch_state["last_disk_digest"] = text_digest(value)
                self.watch_state["last_script_sig"] = self._file_sig(script_path)
        except OSError:
            pass
        if update_draft:
            lang = "rust" if Path(script_path).suffix.lower() == ".rs" else "python"
            code_key, _, _ = self._DRAFT_KEYS[lang]
            self.store.draft[code_key] = value
            self._save_draft()

    def _watch_workspace(self):
        if self.closing:
            return
        try:
            state = self.watch_state
            if state and not self.sync_write_job:
                script_path = state["script"]
                task_dir = state["dir"]
                sig = self._file_sig(script_path)
                script_changed = False
                if sig != state["last_script_sig"] and script_path.is_file():
                    new_text = read_text_safe(script_path)
                    digest = text_digest(new_text)
                    state["last_script_sig"] = sig
                    if digest != state["last_disk_digest"]:
                        state["last_disk_digest"] = digest
                        script_changed = True
                        self._handle_external_script_change(state["mode"], new_text)

                deliverables = scan_deliverables(task_dir, script_name=script_path.name, fixtures=state["fixtures"])
                deliv_sig = tuple((d["name"], d["size"], d["mtime"]) for d in deliverables)
                deliv_changed = deliv_sig != state["last_deliverable_sig"]
                if deliv_changed:
                    state["last_deliverable_sig"] = deliv_sig
                    self._handle_external_deliverable_change(state["mode"], deliverables)

                if (script_changed or deliv_changed) and state["mode"] == "lesson":
                    session = self.session
                    if session and self.progress["settings"].get("autoVerify", True):
                        if not session["running"] and not session["feedback"].get("correct"):
                            self._run_lesson_verification(isolated=True, explicit=False)
        finally:
            if not self.closing:
                self.watch_job = self.after(500, self._watch_workspace)

    def _handle_external_script_change(self, mode, new_text):
        now_str = time.strftime("%H:%M:%S")
        if mode == "playground" and self.route == "playground" and self.editor and self.editor.winfo_exists():
            lang = self._play_lang()
            code_key, _, _ = self._DRAFT_KEYS[lang]
            self.editor.set_silent(new_text)
            self.store.draft[code_key] = new_text[:32000]
            self._save_draft()
            if self.play_sync_label and self.play_sync_label.winfo_exists():
                self.play_sync_label.configure(text=f"● 외부 파일 변경 감지됨 ({now_str}) — {LANG_META[lang]['practice']} 동기화 완료")
        elif mode == "lesson" and self.session and self.lesson_editor and self.lesson_editor.winfo_exists():
            self.lesson_editor.set_silent(new_text)
            self.session["code"] = new_text
            msg = f"● 외부 파일 저장 감지됨 ({now_str}) — 자동 확인 중..."
            self.session["syncStatus"] = msg
            if self.lesson_sync_label and self.lesson_sync_label.winfo_exists():
                self.lesson_sync_label.configure(text=msg)

    def _handle_external_deliverable_change(self, mode, deliverables):
        if mode == "playground" and self.route == "playground" and self.play_result_frame and self.play_result_frame.winfo_exists():
            self._render_playground_results()
        elif mode == "lesson" and self.session and self.lesson_result_frame and self.lesson_result_frame.winfo_exists():
            if not self.session["running"]:
                self._render_lesson_result_area(external_deliverables=deliverables)

    def _switch_playground_lang(self, lang):
        if self.play_running or lang not in LANG_META or lang == self._play_lang():
            return
        if lang == "rust":
            self._refresh_rust_if_missing()
        self._capture_draft()
        self.progress["settings"]["playgroundLang"] = lang
        self.save()
        self.play_result = None
        self.repl_transcript = []
        self.navigate("playground")

    def playground(self):
        play_lang = self._play_lang()
        meta = LANG_META[play_lang]
        code_key, stdin_key, sample_key = self._DRAFT_KEYS[play_lang]
        subtitle = (
            "왼쪽에서 Python 코드를 작성하고 오른쪽 실제 파이썬 터미널(>>>)에서 바로 실행·대화할 수 있어요."
            if play_lang == "python"
            else "왼쪽에서 Rust 코드를 작성하고 오른쪽 터미널에서 rustc로 컴파일·실행할 수 있어요."
        )
        self._heading("생각을 코드로 바꾸는 곳", subtitle)

        lang_row = tk.Frame(self.content, bg=BG)
        lang_row.pack(fill="x", pady=px((0, 8)))
        for key, caption, kind in [("python", "Python (.py)  ·  대화형 터미널", "py"), ("rust", "Rust (.rs)  ·  rustc 실행", "rust")]:
            selected = play_lang == key
            button(
                lang_row,
                caption,
                lambda k=key: self._switch_playground_lang(k),
                kind if selected else "ghost",
                radius=11,
                padx=px(14),
                pady=px(6),
                font=(FONT, 9, "bold" if selected else "normal"),
            ).pack(side="left", padx=px((0, 6)))

        task_dir = self.workspace.playground_dir()
        script_path = task_dir / meta["practice"]
        if not script_path.exists():
            self.workspace.prepare_workspace(task_dir, meta["practice"], self.store.draft[code_key])
        else:
            self.store.draft[code_key] = read_text_safe(script_path)[:32000]
        self.play_task_dir = task_dir
        self.play_script_path = script_path

        lang_samples = [s for s in SAMPLES if s.get("lang", "python") == play_lang]
        tabs = tk.Frame(self.content, bg=BG)
        tabs.pack(fill="x", pady=px((0, 10)))
        chip_builders = [
            (
                lambda row_p, item=sample: button(
                    row_p,
                    item["title"],
                    lambda s=item: self.select_sample(s),
                    "secondary" if self.store.draft[sample_key] == item["id"] else "ghost",
                    pill=True,
                    padx=px(11),
                    pady=px(4),
                    font=(FONT, 8, "bold" if self.store.draft[sample_key] == item["id"] else "normal"),
                )
            )
            for sample in lang_samples
        ]
        _pack_chip_flow(tabs, chip_builders, gap_x=6, gap_y=5, max_width=940, bg=BG)

        self.play_two_cols = self.winfo_width() >= px(1080)
        _, left_pane, right_pane = self._make_two_cols(self.content, self.play_two_cols, left_weight=11, right_weight=10)

        shell = create_code_shell(left_pane, f"{script_path.name}  ·  {meta['name']}", ("코드 복사", self.copy_code))
        shell.pack(fill="x")
        self.editor = CodeEditor(shell, self.store.draft[code_key], self.draft_changed, self.run_playground, height=13, lang=play_lang, bordered=False)
        self.editor.pack(fill="x")
        actions = tk.Frame(left_pane, bg=BG)
        actions.pack(fill="x", pady=px((8, 8)))
        self.controls["run"] = button(actions, "실행 중…" if self.play_running else "▶  실행하기", self.run_playground, pill=True, padx=px(16), pady=px(6))
        self.controls["run"].pack(side="right")
        if self.play_running:
            self.controls["run"].configure(state="disabled")
        label(actions, f"Ctrl + Enter 실행   ·   Tab 들여쓰기   ·   {meta['practice']} 자동 동기화", 8, MUTED, wraplength=px(360)).pack(side="left")
        input_box = card(left_pane, padding=11, radius=13)
        input_box.pack(fill="x")
        label(input_box, "표준 입력(stdin)  ·  프로그램 실행 시 읽을 값을 한 줄씩 적어 주세요.", 8, MUTED).pack(anchor="w", pady=px((0, 5)))
        stdin_wrap = RoundedFrame(input_box, bg="#f6f9f7", padx=10, pady=6, border="#d6e2db", radius=10, outer_bg=WHITE)
        stdin_wrap.pack(fill="x")
        self.stdin = tk.Text(
            stdin_wrap, height=2, font=(CODE_FONT, 10), bg="#f6f9f7", fg=INK,
            relief="flat", bd=0, highlightthickness=0, padx=px(2), pady=px(1),
        )
        self.stdin.pack(fill="x")
        self.stdin.bind("<FocusIn>", lambda _, w=stdin_wrap: w.set_colors(border="#5aa47f"), add=True)
        self.stdin.bind("<FocusOut>", lambda _, w=stdin_wrap: w.set_colors(border="#d6e2db"), add=True)
        self.stdin.insert("1.0", self.store.draft[stdin_key])
        self.stdin.edit_modified(False)
        self.stdin.bind("<<Modified>>", self._stdin_changed)

        self.play_result_frame = tk.Frame(right_pane, bg=BG)
        self.play_result_frame.pack(fill="x")
        self._render_playground_results()
        bridge_wrap = tk.Frame(right_pane, bg=BG)
        bridge_wrap.pack(fill="x", pady=px((8, 0)))
        self.play_sync_label = self._build_external_bridge_bar(bridge_wrap, script_path, task_dir, lang=play_lang)
        self._activate_watch("playground", task_dir, script_path)

    def _build_playground_terminal_entries(self):
        play_lang = self._play_lang()
        if play_lang == "rust":
            entries = [
                ("dim", f"Rust ({self.rust_runtime['label']}) on Windows\n"),
                ("dim", f"작업 폴더: {self.play_task_dir}\n\n"),
            ]
            if self.play_result:
                entries.append(("prompt", "PS> "))
                entries.append(("cmd", "rustc --edition 2021 practice.rs && practice.exe\n"))
                if self.play_result.get("output"):
                    entries.append(("stdout", self.play_result["output"]))
                    if not self.play_result["output"].endswith("\n"):
                        entries.append(("stdout", "\n"))
                if self.play_result.get("error"):
                    entries.append(("stderr", self.play_result["error"]))
                    if not self.play_result["error"].endswith("\n"):
                        entries.append(("stderr", "\n"))
                if not self.play_result.get("output") and not self.play_result.get("error"):
                    entries.append(("dim", "(출력 없이 정상 종료됨)\n"))
                engine = "rustc 미설치" if self.play_result.get("missingCompiler") else "로컬 rustc"
                status_tag = "ok" if self.play_result.get("ok") else "stderr"
                status_word = "완료" if self.play_result.get("ok") else "컴파일·실행 오류"
                entries.append((status_tag, f"[{status_word} · {engine} · {self.play_result.get('elapsed', 0)} ms]\n"))
            else:
                entries.append(("dim", "'▶ 실행하기'를 누르면 practice.rs를 rustc로 컴파일해 바로 실행해요.\n"))
                if not self.rust_runtime["available"]:
                    entries.append(("stderr", "\n현재 PC에서 rustc.exe를 찾지 못했어요. 설정에서 rustc 경로를 지정하거나 winget install Rustlang.Rustup으로 설치해 주세요.\n"))
            return entries

        py_ver = self.runtime.get("version") or sys.version.split()[0]
        entries = [
            ("dim", f"Python {py_ver} ({self.runtime['label']}) on Windows\n"),
            ("dim", f"작업 폴더: {self.play_task_dir}\n\n"),
        ]
        if self.play_result:
            entries.append(("prompt", "PS> "))
            entries.append(("cmd", "python -X utf8 practice.py\n"))
            if self.play_result.get("output"):
                entries.append(("stdout", self.play_result["output"]))
                if not self.play_result["output"].endswith("\n"):
                    entries.append(("stdout", "\n"))
            if self.play_result.get("error"):
                entries.append(("stderr", self.play_result["error"]))
                if not self.play_result["error"].endswith("\n"):
                    entries.append(("stderr", "\n"))
            if not self.play_result.get("output") and not self.play_result.get("error"):
                entries.append(("dim", "(출력 없이 정상 종료됨)\n"))
            engine = "시스템 Python" if self.play_result.get("usedSystemPython") else "내장 Python"
            status_tag = "ok" if self.play_result.get("ok") else "stderr"
            status_word = "완료" if self.play_result.get("ok") else "오류 종료"
            entries.append((status_tag, f"[{status_word} · {engine} · {self.play_result.get('elapsed', 0)} ms]\n\n"))
        elif not self.repl_transcript:
            entries.append(("dim", "'실행하기'를 누르거나 아래 >>> 프롬프트에 파이썬 코드를 직접 입력해 보세요.\n"))
            entries.append(("dim", "예: 1 + 2, name = '파이썬', print(name), clear(화면 지우기)\n"))

        for item in self.repl_transcript:
            entries.append(item)
        return entries

    def _render_playground_results(self, focus_repl=False):
        if not self.play_result_frame or not self.play_result_frame.winfo_exists():
            return
        for child in self.play_result_frame.winfo_children():
            child.destroy()

        play_lang = self._play_lang()
        entries = self._build_playground_terminal_entries()
        line_count = sum(text.count("\n") for _, text in entries) + 2
        if play_lang == "rust":
            rs_ver = self.rust_runtime.get("version") or "rustc"
            title = f"Rust ({rs_ver}) · 컴파일 실행 터미널"
            hdr_actions = [("화면 지우기", self.clear_output)]
            if not self.rust_runtime["available"]:
                hdr_actions = [("준비 탭에서 Rust 설치 →", lambda: self.open_setup("rust"))] + hdr_actions
        else:
            py_ver = self.runtime.get("version") or sys.version.split()[0]
            title = f"Python {py_ver} · 실제 터미널 (CMD 스타일)"
            hdr_actions = [("세션 초기화", self._reset_repl_session), ("화면 지우기", self.clear_output)]

        shell, console = create_terminal_box(
            self.play_result_frame,
            title,
            entries,
            height=max(6, min(11, line_count)),
            header_actions=hdr_actions,
        )
        shell.pack(fill="x", pady=px((0, 8)))
        self.console = console
        self.repl_entry = None

        if play_lang == "python":
            # Interactive >>> Python prompt capsule inside the dark terminal shell
            prompt_shell = RoundedFrame(shell, bg="#14181d", padx=10, pady=5, border="#272e37", radius=9, outer_bg=TERM_BG)
            prompt_shell.pack(fill="x", padx=px(6), pady=px((2, 6)))
            tk.Label(prompt_shell, text=">>>", bg="#14181d", fg=TERM_PROMPT, font=(CODE_FONT, 10, "bold")).pack(side="left", padx=px((0, 6)))
            entry = tk.Entry(
                prompt_shell,
                bg="#14181d",
                fg=TERM_FG,
                insertbackground=TERM_FG,
                selectbackground=CODE_SELECT,
                font=(CODE_FONT, 10),
                relief="flat",
                bd=0,
                highlightthickness=0,
            )
            entry.pack(side="left", fill="x", expand=True)
            entry.bind("<Return>", lambda _: self._submit_repl())
            entry.bind("<Up>", lambda _: self._repl_history_nav(-1))
            entry.bind("<Down>", lambda _: self._repl_history_nav(1))
            if self.repl_running:
                entry.configure(state="disabled")
            self.repl_entry = entry
            run_btn = button(prompt_shell, "입력 ↵", self._submit_repl, "dark", pill=True, padx=px(11), pady=px(3), font=(FONT, 8, "bold"))
            run_btn.pack(side="right", padx=px((8, 0)))
            if self.repl_running:
                run_btn.configure(state="disabled")
            if focus_repl and not self.repl_running:
                entry.focus_set()

        if self.play_task_dir:
            deliv_card = card(self.play_result_frame, padding=15, radius=13)
            deliv_card.pack(fill="x")
            d_head = tk.Frame(deliv_card, bg=WHITE)
            d_head.pack(fill="x", pady=px((0, 8)))
            label(d_head, "작업 폴더 내 결과 파일 (실기 결과물)", 11, INK, True).pack(side="left")
            button(d_head, "결과 비우기", self._clear_playground_deliverables, "ghost", pill=True, padx=px(11), pady=px(4), font=(FONT, 9)).pack(side="right", padx=px((6, 0)))
            button(d_head, "새로고침", self._render_playground_results, "ghost", pill=True, padx=px(11), pady=px(4), font=(FONT, 9)).pack(side="right")
            deliverables = scan_deliverables(self.play_task_dir, script_name=LANG_META[play_lang]["practice"])
            self._render_deliverable_list(deliv_card, deliverables)

    def _clear_playground_deliverables(self):
        if not self.play_task_dir:
            return
        play_lang = self._play_lang()
        script_name = LANG_META[play_lang]["practice"]
        stem = Path(script_name).stem
        # Both languages share this folder. The other language's practice file is hidden from the
        # result list, so removing it here would silently delete the learner's code.
        keep = {script_name, f"{stem}.exe", f"{stem}.pdb"} | {meta["practice"] for meta in LANG_META.values()}
        removed = 0
        for item in Path(self.play_task_dir).iterdir():
            if item.is_file() and item.name not in keep:
                try:
                    item.unlink()
                    removed += 1
                except OSError:
                    pass
        self._render_playground_results()
        self.toast(f"결과 파일 {removed}개를 정리했어요." if removed else "정리할 결과 파일이 없어요.")

    def _repl_history_nav(self, delta):
        if not self.repl_history or not self.repl_entry or not self.repl_entry.winfo_exists():
            return "break"
        self.repl_cursor = max(0, min(len(self.repl_history), self.repl_cursor + delta))
        self.repl_entry.delete(0, "end")
        if self.repl_cursor < len(self.repl_history):
            self.repl_entry.insert(0, self.repl_history[self.repl_cursor])
        return "break"

    def _reset_repl_session(self):
        self.repl_history = []
        self.repl_cursor = 0
        self.repl_transcript = [("dim", "[대화형 Python 세션이 초기화되었어요]\n")]
        self._render_playground_results(focus_repl=True)

    def _submit_repl(self):
        if self.repl_running or self.route != "playground" or not self.repl_entry or not self.repl_entry.winfo_exists():
            return "break"
        cmd = self.repl_entry.get()
        stripped = cmd.strip()
        if not stripped:
            self.repl_transcript.append(("prompt", ">>> \n"))
            self._render_playground_results(focus_repl=True)
            return "break"
        if stripped in ("clear", "cls"):
            self.play_result = None
            self.repl_transcript = []
            self._render_playground_results(focus_repl=True)
            return "break"
        if stripped.endswith(":"):
            # This prompt takes one line, so a block header alone can only end in a confusing SyntaxError.
            self.repl_transcript.extend([
                ("prompt", ">>> "),
                ("cmd", cmd + "\n"),
                ("stderr", "':'으로 끝나는 if / for / while / def 같은 코드는 다음 줄(들여쓴 내용)이 함께 있어야 해요.\n"
                           "이 입력창은 한 줄만 실행하니, 왼쪽 편집기에 여러 줄로 적은 뒤 '▶ 실행하기'를 눌러 주세요.\n"),
            ])
            self._render_playground_results(focus_repl=True)
            return "break"
        self.repl_running = True
        self.repl_entry.configure(state="disabled")
        python_path = self.runtime.get("path") if self.runtime.get("available") else None
        history_snapshot = list(self.repl_history)
        work_dir = self.play_task_dir or self.workspace.playground_dir()
        self.submit_task(
            lambda: run_repl_command(cmd, work_dir, history=history_snapshot, python_path=python_path),
            lambda result, command_text=cmd: self._repl_finished(command_text, result),
        )
        return "break"

    def _repl_finished(self, cmd, result):
        self.repl_running = False
        self.repl_transcript.append(("prompt", ">>> "))
        self.repl_transcript.append(("cmd", cmd + "\n"))
        if result.get("committed"):
            self.repl_history.append(cmd)
            self.repl_cursor = len(self.repl_history)
        if result.get("output"):
            out = result["output"]
            if not out.endswith("\n"):
                out += "\n"
            self.repl_transcript.append(("stdout", out))
        if result.get("error"):
            err = result["error"]
            if not err.endswith("\n"):
                err += "\n"
            self.repl_transcript.append(("stderr", err))
        if len(self.repl_transcript) > 160:
            self.repl_transcript = self.repl_transcript[-160:]
        if self.route == "playground" and not self.session:
            self._render_playground_results(focus_repl=True)
            if self.watch_state and self.watch_state["mode"] == "playground":
                deliverables = scan_deliverables(self.play_task_dir, script_name="practice.py")
                self.watch_state["last_deliverable_sig"] = tuple((d["name"], d["size"], d["mtime"]) for d in deliverables)

    def _stdin_changed(self, _):
        if self.stdin.edit_modified():
            self.stdin.edit_modified(False)
            self._capture_draft()

    def draft_changed(self, value):
        code_key, _, _ = self._DRAFT_KEYS[self._play_lang()]
        self.store.draft[code_key] = value
        if self.play_script_path:
            self._schedule_disk_sync(self.play_script_path, value, update_draft=True)
            return
        if self.draft_job:
            self.after_cancel(self.draft_job)
        self.draft_job = self.after(400, self._save_draft)

    def _save_draft(self):
        self.draft_job = None
        try:
            self.store.save_draft()
        except OSError:
            self.toast("코드 초안을 저장하지 못했어요. 필요한 코드는 복사해 보관해 주세요.")

    def _capture_draft(self):
        if self.editor and self.editor.winfo_exists():
            play_lang = self._play_lang()
            code_key, stdin_key, _ = self._DRAFT_KEYS[play_lang]
            code_val = self.editor.get()
            self.store.draft[code_key] = code_val
            if self.play_script_path:
                self._flush_disk_sync(self.play_script_path, code_val, update_draft=False)
            if hasattr(self, "stdin") and self.stdin.winfo_exists():
                self.store.draft[stdin_key] = self.stdin.get("1.0", "end-1c")
            self._save_draft()

    def select_sample(self, sample):
        if self.play_running:
            return
        self._capture_draft()
        sample_lang = sample.get("lang", self._play_lang())
        code_key, stdin_key, sample_key = self._DRAFT_KEYS[sample_lang]
        previous = next((s["code"] for s in SAMPLES if s["id"] == self.store.draft[sample_key]), "")
        if self.store.draft[code_key] != previous and not messagebox.askyesno("예제 불러오기", "작성한 코드가 예제로 바뀌어요. 필요한 코드는 먼저 복사해 주세요.\n예제를 불러올까요?", parent=self):
            return
        self.progress["settings"]["playgroundLang"] = sample_lang
        self.store.draft[code_key] = sample["code"]
        self.store.draft[stdin_key] = sample.get("stdin", "")
        self.store.draft[sample_key] = sample["id"]
        if self.play_script_path and self.play_script_path.name == LANG_META[sample_lang]["practice"]:
            self._flush_disk_sync(self.play_script_path, sample["code"], update_draft=False)
        else:
            task_dir = self.workspace.playground_dir()
            self.workspace.prepare_workspace(task_dir, LANG_META[sample_lang]["practice"], sample["code"])
        self._save_draft()
        self.play_result = None
        self.repl_transcript = []
        self.navigate("playground")

    def copy_code(self):
        self.clipboard_clear()
        self.clipboard_append(self.editor.get())
        self.toast("코드를 복사했어요.")

    def clear_output(self):
        self.play_result = None
        self.repl_transcript = []
        self._render_playground_results(focus_repl=(self._play_lang() == "python"))

    def run_playground(self):
        if self.play_running or self.route != "playground":
            return
        self._capture_draft()
        play_lang = self._play_lang()
        _, stdin_key, _ = self._DRAFT_KEYS[play_lang]
        stdin_val = self.store.draft[stdin_key]
        self.play_running = True
        if self.controls.get("run") and self.controls["run"].winfo_exists():
            self.controls["run"].configure(text="실행 중…", state="disabled")
        if play_lang == "rust":
            custom_rust = self.progress["settings"].get("rustPath", "")
            current_rt = dict(self.rust_runtime)

            def _run_rust_task():
                rt = current_rt
                if not rt.get("available"):
                    rt = discover_rust_runtime(custom_rust, refresh=True)
                rust_path = rt.get("path") if rt.get("available") else None
                res = run_rust_script(self.play_script_path, self.play_task_dir, stdin=stdin_val, rust_path=rust_path)
                res["_discoveredRuntime"] = rt
                return res

            self.submit_task(_run_rust_task, self._play_finished)
        else:
            python_path = self.runtime.get("path") if self.runtime.get("available") else None
            self.submit_task(
                lambda: run_workspace_script(self.play_script_path, self.play_task_dir, stdin=stdin_val, python_path=python_path),
                self._play_finished,
            )

    def _play_finished(self, result):
        discovered = result.pop("_discoveredRuntime", None) if isinstance(result, dict) else None
        if discovered and discovered.get("available") and not self.rust_runtime.get("available"):
            self.rust_runtime = discovered
            self._refresh_runtime_badge()
        self.play_running = False
        self.play_result = result
        if self.route == "playground" and not self.session:
            if self.controls.get("run") and self.controls["run"].winfo_exists():
                self.controls["run"].configure(text="▶  실행하기", state="normal")
            self._render_playground_results()
            if self.watch_state and self.watch_state["mode"] == "playground":
                script_name = LANG_META[self._play_lang()]["practice"]
                deliverables = scan_deliverables(self.play_task_dir, script_name=script_name)
                self.watch_state["last_deliverable_sig"] = tuple((d["name"], d["size"], d["mtime"]) for d in deliverables)

    def achievements(self):
        self._heading("차곡차곡 쌓인 나의 성장", "작은 성취들이 모여, 어제보다 한 걸음 더 나아갔어요.")
        earned = badges(self.progress)
        stats = tk.Frame(self.content, bg=BG)
        stats.pack(fill="x", pady=px((0, 12)))
        stat_cards = [
            (f"{self.progress['xp']:,} XP", "모은 경험치", PY_BLUE),
            (f"{streak(self.progress)}일", "연속 학습", GREEN),
            (f"{len(self.progress['completed'])} / {len(LESSONS)}", "완료한 레슨", PY_BLUE),
            (f"{sum(b[3] for b in earned)} / {len(earned)}", "획득한 배지", PY_GOLD),
        ]
        for i, (value, title, accent) in enumerate(stat_cards):
            stats.columnconfigure(i, weight=1, uniform="stat")
            panel = card(stats, padding=13, radius=13)
            panel.grid(row=0, column=i, sticky="ew", padx=px((0 if i == 0 else 5, 5 if i < 3 else 0)))
            bar_c = tk.Canvas(panel, width=px(36), height=px(5), bg=WHITE, highlightthickness=0, bd=0)
            bar_c.pack(anchor="w", pady=px((0, 7)))
            _draw_rounded_rect(bar_c, 0, 0, px(36) - 1, px(5) - 1, px(2.5), fill=accent, outline="")
            label(panel, value, 16, accent, True).pack(anchor="w")
            label(panel, title, 8, MUTED).pack(anchor="w", pady=px((3, 0)))
        level = card(self.content, PALE, 14, border="#c4dfd0", radius=14)
        level.pack(fill="x", pady=px((0, 12)))
        number = self.progress["xp"] // 100 + 1
        label(level, f"LEVEL {number}  ·  꾸준히 성장하는 코드스텝 탐험가", 11, GREEN, True).pack(anchor="w")
        RoundedProgressBar(level, fill=GREEN, trough="#cfe5d8", maximum=100, value=self.progress["xp"] % 100, length=400, height=9).pack(fill="x", pady=px((7, 6)))
        label(level, f"다음 레벨까지 {100-self.progress['xp'] % 100} XP", 8, MUTED).pack(anchor="w")

        tracks = tk.Frame(self.content, bg=BG)
        tracks.pack(fill="x", pady=px((0, 14)))
        for col_idx, (lkey, _) in enumerate(LANGS):
            tracks.columnconfigure(col_idx, weight=1, uniform="track_prog")
            t_meta = LANG_META[lkey]
            t_lessons = [l for l in LESSONS if l.get("lang", "python") == lkey]
            t_done = sum(1 for l in t_lessons if l["id"] in self.progress["completed"])
            t_pct = round((t_done / len(t_lessons)) * 100) if t_lessons else 0
            t_card = card(tracks, WHITE, 13, border=t_meta["border"], radius=14)
            t_card.grid(row=0, column=col_idx, sticky="ew", padx=px((0 if col_idx == 0 else 5, 5 if col_idx == 0 else 0)))
            t_head = tk.Frame(t_card, bg=WHITE)
            t_head.pack(fill="x", pady=px((0, 7)))
            label(t_head, f"{t_meta['name']} 트랙", 11, t_meta["accent"], True).pack(side="left")
            button(t_head, f"{t_meta['name']} 학습 →", lambda k=lkey: self.navigate(k), "py" if lkey == "python" else "rust", pill=True, padx=px(10), pady=px(4), font=(FONT, 8, "bold")).pack(side="right")
            trough = "#d5e2ec" if lkey == "python" else "#ebd7d0"
            RoundedProgressBar(t_card, fill=t_meta["accent"], trough=trough, maximum=max(1, len(t_lessons)), value=t_done, length=320, height=9).pack(fill="x", pady=px((0, 6)))
            label(t_card, f"{t_done} / {len(t_lessons)} 레슨 완료 ({t_pct}%)", 8, MUTED).pack(anchor="w")
        label(self.content, "☆  나의 배지 컬렉션", 12, INK, True).pack(anchor="w", pady=px((0, 10)))
        grid = tk.Frame(self.content, bg=BG)
        grid.pack(fill="x")
        for i, (title, description, glyph, unlocked) in enumerate(earned):
            grid.columnconfigure(i % 4, weight=1, uniform="badge")
            bg_c = "#f2f8f4" if unlocked else WHITE
            panel = card(grid, bg_c, 12, border="#c4dfd0" if unlocked else LINE, radius=14)
            panel.grid(row=i // 4, column=i % 4, sticky="nsew", padx=px(5), pady=px(5))
            _draw_badge_medallion(panel, glyph, unlocked, bg=bg_c).pack(pady=px((2, 6)))
            label(panel, title, 9, INK, True, anchor="center", bg=bg_c).pack(fill="x")
            label(panel, description, 8, MUTED, anchor="center", justify="center", wraplength=px(160), bg=bg_c).pack(fill="x", pady=px((4, 8)))
            pill_wrap = tk.Frame(panel, bg=bg_c)
            pill_wrap.pack()
            pill(
                pill_wrap,
                "✓ 획득 완료" if unlocked else "도전 중",
                GREEN if unlocked else MUTED,
                "#e1f3ea" if unlocked else "#eff3f1",
                border="#bde2cf" if unlocked else "#dce4df",
                size=8,
                padx=9,
                pady=2,
            ).pack()

    def open_setup(self, lang=None):
        if lang in ("python", "rust"):
            self.setup_lang = lang
        self.navigate("setup")

    def _set_setup_lang(self, lang):
        self.setup_lang = lang if lang in ("python", "rust") else "python"
        self.navigate("setup")

    def _refresh_setup_status(self, refresh_toolchains=False, notify=False):
        if refresh_toolchains:
            self.runtime = discover_python_runtime(self.progress["settings"].get("pythonPath", ""), refresh=True)
            self.rust_runtime = discover_rust_runtime(self.progress["settings"].get("rustPath", ""), refresh=True)
            self.editors = discover_editors(refresh=True)
            self._refresh_runtime_badge()
        self.setup_status = discover_setup_status(self.runtime, self.rust_runtime, self.editors)
        if notify:
            self.navigate("setup")
            self.toast("Python · Rust 개발 환경 설치 상태를 다시 확인했어요.")

    def _copy_command(self, command, label_name=""):
        self.clipboard_clear()
        self.clipboard_append(command)
        self.toast(f"{label_name or '설치'} 명령을 클립보드에 복사했어요.")

    def _run_setup_installer(self, steps, title="코드스텝 개발 환경 설치"):
        code_cli = (self.setup_status or {}).get("codeCli", "")
        ok, msg = launch_installer_terminal(steps, title=title, code_cli=code_cli)
        if ok:
            self.toast(msg)
        else:
            messagebox.showwarning("설치 터미널 실행", msg, parent=self)

    def setup_page(self):
        if self.setup_status is None:
            self._refresh_setup_status(refresh_toolchains=False)
        status = self.setup_status
        catalog = get_setup_catalog(status)
        lang = self.setup_lang if self.setup_lang in ("python", "rust") else "python"
        items = catalog[lang]
        py_items, rs_items = catalog["python"], catalog["rust"]
        py_done = sum(1 for item in py_items if item["installed"] is True)
        rs_done = sum(1 for item in rs_items if item["installed"] is True)
        meta = LANG_META[lang]

        self._heading(
            "학습 · 실행 환경 준비",
            "Python과 Rust 실습에 필요한 프로그램을 설명하고, 버튼 클릭 한 번으로 터미널 설치를 실행해요.",
        )

        tab_bar = tk.Frame(self.content, bg=BG)
        tab_bar.pack(fill="x", pady=px((0, 10)))
        self.controls["setupLang"] = {}
        for lkey, title_txt, kind_active in [
            ("python", f"Python ({py_done}/{len(py_items)})", "py"),
            ("rust", f"Rust ({rs_done}/{len(rs_items)})", "rust"),
        ]:
            selected = lang == lkey
            btn = button(
                tab_bar,
                title_txt,
                lambda k=lkey: self._set_setup_lang(k),
                kind_active if selected else "ghost",
                pill=True,
                padx=px(13),
                pady=px(5),
                font=(FONT, 9, "bold" if selected else "normal"),
            )
            btn.pack(side="left", padx=px((0, 6)))
            self.controls["setupLang"][lkey] = btn

        missing_steps = [item["step"] for item in items if item["installed"] is not True]
        batch_btn = button(
            tab_bar,
            f"미설치 {meta['name']} 항목 한 번에 설치 ({len(missing_steps)}개) ▶" if missing_steps else f"✓ {meta['name']} 권장 항목 모두 준비됨",
            lambda st=missing_steps, m=meta: self._run_setup_installer(st, title=f"{m['name']} 개발 환경 일괄 설치"),
            ("py" if lang == "python" else "rust") if missing_steps else "secondary",
            pill=True,
            padx=px(13),
            pady=px(5),
            font=(FONT, 9, "bold"),
        )
        batch_btn.pack(side="right")
        if not missing_steps:
            batch_btn.configure(state="disabled")
        self.controls["setupBatch"] = batch_btn

        button(
            tab_bar,
            "↻ 설치 상태 다시 확인",
            lambda: self._refresh_setup_status(refresh_toolchains=True, notify=True),
            "ghost",
            pill=True,
            padx=px(11),
            pady=px(5),
            font=(FONT, 9, "bold"),
        ).pack(side="right", padx=px((0, 6)))

        summary_bg = PY_BLUE_PALE if lang == "python" else RUST_PALE
        summary_border = "#c8dce9" if lang == "python" else "#eed1c8"
        summary = card(self.content, summary_bg, 13, border=summary_border, radius=14)
        summary.pack(fill="x", pady=px((0, 10)))
        pill_row = tk.Frame(summary, bg=summary_bg)
        pill_row.pack(anchor="w", pady=px((0, 7)))
        if lang == "python":
            pill(pill_row, "PYTHON 환경 안내", WHITE, PY_BLUE, size=8, padx=9, pady=3).pack(side="left", padx=px((0, 6)))
            pill(pill_row, "✓ 내장 Python 바로 학습 가능", GREEN, PALE, border="#bde2cf", size=8, padx=9, pady=3).pack(side="left", padx=px((0, 6)))
            pill(pill_row, f"시스템 Python: {'연동됨' if status['python'].get('available') else '미설치'}", INK, WHITE, border=summary_border, size=8, padx=9, pady=3).pack(side="left")
            summary_body = (
                "코드스텝 앱 안에 Python 3 인터프리터가 내장되어 있어 입문~기출 문제와 연습장을 설치 없이 바로 풀 수 있어요.\n"
                "아래 프로그램을 추가로 설치하면 실제 IDLE 편집기, Windows 터미널 실행, VS Code 저장 자동 채점까지 함께 연동됩니다."
            )
        else:
            pill(pill_row, "RUST 환경 안내", WHITE, RUST_ORANGE, size=8, padx=9, pady=3).pack(side="left", padx=px((0, 6)))
            pill(
                pill_row,
                f"rustc: {'설치됨' if status['rust'].get('available') else '미설치'}",
                GREEN if status['rust'].get('available') else "#b85c50",
                WHITE,
                border=summary_border,
                size=8,
                padx=9,
                pady=3,
            ).pack(side="left", padx=px((0, 6)))
            pill(
                pill_row,
                f"MSVC 링커: {'설치됨' if status.get('msvc') else '미설치'}",
                GREEN if status.get('msvc') else "#b85c50",
                WHITE,
                border=summary_border,
                size=8,
                padx=9,
                pady=3,
            ).pack(side="left")
            summary_body = (
                "Rust 개념·객관식 문제는 지금 바로 풀 수 있고, 직접 Rust 코드를 작성해 컴파일·실행하려면\n"
                "1) Microsoft C++ Build Tools(MSVC 링커)와 2) Rust 도구 모음(rustup · rustc · cargo)을 순서대로 설치해야 해요."
            )
        fit_wrap(label(summary, summary_body, 9, INK, wraplength=px(780))).pack(anchor="w")

        self.controls["setupInstall"] = {}
        for item in items:
            installed = item["installed"]
            is_ok = installed is True
            is_unknown = installed is None
            border = "#b8dccb" if is_ok else "#e7dba8" if is_unknown else LINE
            box = card(self.content, WHITE, 13, border=border, radius=14)
            box.pack(fill="x", pady=px((0, 8)))

            top_row = tk.Frame(box, bg=WHITE)
            top_row.pack(fill="x")
            # Pack buttons on the right BEFORE title so long titles wrap rather than clipping buttons
            btn_row = tk.Frame(top_row, bg=WHITE)
            btn_row.pack(side="right", padx=px((10, 0)))
            vscode_ready = bool((status or {}).get("codeCli")) or any(it.get("id") == "vscode" and it.get("installed") is True for it in items)

            def run_item(it=item, vr=vscode_ready):
                if it.get("requiresVscode") and not vr:
                    messagebox.showinfo(
                        "VS Code 선행 설치 필요",
                        "VS Code가 먼저 설치되어 있어야 확장 프로그램을 연결할 수 있어요.\n위의 'Visual Studio Code' 항목을 먼저 설치해 주세요.",
                        parent=self,
                    )
                    return
                self._run_setup_installer([it["step"]], title=it["title"])

            install_btn = button(
                btn_row,
                "터미널로 재설치/업데이트" if is_ok else "터미널로 바로 설치 ▶",
                run_item,
                "ghost" if is_ok else ("py" if lang == "python" else "rust"),
                pill=True,
                padx=px(12),
                pady=px(4),
                font=(FONT, 9, "bold"),
            )
            install_btn.pack(side="left", padx=px((0, 5)))
            self.controls["setupInstall"][item["id"]] = install_btn
            button(
                btn_row,
                "명령 복사",
                lambda c=item["command"], t=item["title"]: self._copy_command(c, t),
                "ghost",
                pill=True,
                padx=px(10),
                pady=px(4),
                font=(FONT, 9, "bold"),
            ).pack(side="left")

            left_hdr = tk.Frame(top_row, bg=WHITE)
            left_hdr.pack(side="left", fill="x", expand=True)
            role_bg = RUST_PALE if item["required"] else PY_BLUE_PALE
            role_fg = RUST_ORANGE if item["required"] else PY_BLUE
            pill(left_hdr, item["badge"], role_fg, role_bg, size=8, padx=8, pady=2).pack(side="left", padx=px((0, 5)))
            st_txt = "✓ 설치됨" if is_ok else "확인 필요" if is_unknown else "○ 미설치"
            st_bg = PALE if is_ok else "#fbf5df" if is_unknown else "#fbede7"
            st_fg = GREEN if is_ok else "#7c6c3c" if is_unknown else "#b85c50"
            pill(left_hdr, st_txt, st_fg, st_bg, size=8, padx=8, pady=2).pack(side="left", padx=px((0, 8)))
            label(left_hdr, item["title"], 11, INK, True, wraplength=px(430)).pack(side="left")

            label(box, f"현재 상태: {item['statusText']}", 9, GREEN if is_ok else MUTED, True if is_ok else False).pack(anchor="w", pady=px((6, 2)))
            fit_wrap(label(box, item["detail"], 9, INK, wraplength=px(760))).pack(anchor="w", pady=px((0, 7)))
            code_block(box, item["command"], wrap_chars=74).pack(fill="x")

        tip = card(self.content, SURFACE, 12, border=LINE, radius=14)
        tip.pack(fill="x", pady=px((2, 0)))
        button(tip, "설정에서 경로 직접 지정 →", lambda: self.navigate("settings"), "ghost", pill=True, padx=px(11), pady=px(4)).pack(side="right", padx=px((8, 0)))
        button(tip, f"{meta['name']} 학습으로 이동 →", lambda l=lang: self.navigate(l), "py" if lang == "python" else "rust", pill=True, padx=px(12), pady=px(4)).pack(side="right")
        label(tip, "설치 터미널 실행 안내", 10, INK, True).pack(anchor="w")
        label(tip, "터미널 창에서 설치 진행 및 관리자 권한 확인을 마친 뒤, 위 [↻ 설치 상태 다시 확인] 버튼을 누르면 즉시 반영돼요.", 9, MUTED, wraplength=px(540)).pack(anchor="w", pady=px((2, 0)))

    def settings(self):
        self._heading("나에게 맞는 학습 리듬", "외부 Python · Rust 실행 환경과 학습 설정을 관리해요.")
        panel = card(self.content, padding=15, radius=14)
        panel.pack(fill="x", pady=px((0, 10)))
        label(panel, "외부 Python · Rust 프로그램 연동", 12, INK, True).pack(anchor="w")

        rt_text = f"Python 연결: {self.runtime['label']}" + (f"  ({self.runtime['path']})" if self.runtime["available"] else "  (내장 기본 실행기)")
        fit_wrap(label(panel, rt_text, 9, GREEN if self.runtime["available"] else MUTED, wraplength=px(760))).pack(anchor="w", pady=px((6, 6)))
        rt_row = tk.Frame(panel, bg=WHITE)
        rt_row.pack(fill="x", pady=px((0, 8)))
        button(rt_row, "Python 경로 지정", self.choose_python_path, "secondary", pill=True, padx=px(11), pady=px(4)).pack(side="left", padx=px((0, 6)))
        button(rt_row, "자동 재검색", self.reset_python_path, "ghost", pill=True, padx=px(11), pady=px(4)).pack(side="left", padx=px((0, 6)))
        button(rt_row, "준비 탭에서 설치/확인 →", lambda: self.open_setup("python"), "ghost", pill=True, padx=px(11), pady=px(4)).pack(side="left")

        rs_text = f"Rust(rustc) 연결: {self.rust_runtime['label']}" + (
            f"  ({self.rust_runtime['path']})"
            if self.rust_runtime["available"]
            else "\n(PC에 rustc.exe가 없어요. 설치 명령: winget install Rustlang.Rustup  또는  https://rustup.rs)"
        )
        fit_wrap(label(panel, rs_text, 9, GREEN if self.rust_runtime["available"] else RUST_ORANGE, wraplength=px(760))).pack(anchor="w", pady=px((2, 6)))
        rs_row = tk.Frame(panel, bg=WHITE)
        rs_row.pack(fill="x", pady=px((0, 10)))
        button(rs_row, "rustc.exe 경로 지정", self.choose_rust_path, "secondary", pill=True, padx=px(11), pady=px(4)).pack(side="left", padx=px((0, 6)))
        button(rs_row, "Rust 자동 재검색", self.reset_rust_path, "ghost", pill=True, padx=px(11), pady=px(4)).pack(side="left", padx=px((0, 6)))
        button(rs_row, "설치 명령 복사", self._copy_rustup_cmd, "ghost", pill=True, padx=px(11), pady=px(4)).pack(side="left", padx=px((0, 6)))
        button(rs_row, "준비 탭에서 터미널 설치 →", lambda: self.open_setup("rust"), "rust", pill=True, padx=px(11), pady=px(4)).pack(side="left")

        fit_wrap(label(panel, f"실습 작업 폴더: {self.workspace.root}", 9, INK, wraplength=px(760))).pack(anchor="w", pady=px((2, 6)))
        ws_row = tk.Frame(panel, bg=WHITE)
        ws_row.pack(fill="x", pady=px((0, 8)))
        button(ws_row, "작업 폴더 변경", self.choose_workspace_dir, "secondary", pill=True, padx=px(11), pady=px(4)).pack(side="left", padx=px((0, 6)))
        button(ws_row, "작업 폴더 열기", lambda: self._run_launcher(launch_folder(self.workspace.root)), "ghost", pill=True, padx=px(11), pady=px(4)).pack(side="left", padx=px((0, 6)))
        if self.progress["settings"].get("workspaceDir"):
            button(ws_row, "기본 폴더로 되돌리기", self.reset_workspace_dir, "ghost", pill=True, padx=px(11), pady=px(4)).pack(side="left")

        self.auto_verify_var = tk.BooleanVar(value=self.progress["settings"].get("autoVerify", True))
        tk.Checkbutton(panel, text="외부 편집기(IDLE/VS Code)에서 저장 시 자동 인식 및 미리보기 채점",
                       variable=self.auto_verify_var, command=self.toggle_auto_verify,
                       bg=WHITE, fg=INK, activebackground=WHITE, font=(FONT, 9, "bold"), selectcolor=WHITE).pack(anchor="w", pady=px((2, 2)))
        self.unlock_all_var = tk.BooleanVar(value=self.progress["settings"].get("unlockAll", False))
        tk.Checkbutton(panel, text="모든 레슨 자유 열기 (Python 입문~고급·기출 및 Rust 레슨 바로 열기)",
                       variable=self.unlock_all_var, command=self.toggle_unlock_all,
                       bg=WHITE, fg=INK, activebackground=WHITE, font=(FONT, 9, "bold"), selectcolor=WHITE).pack(anchor="w")

        panel = card(self.content, padding=15, radius=14)
        panel.pack(fill="x", pady=px((0, 10)))
        label(panel, "하루 목표", 12, INK, True).pack(anchor="w")
        label(panel, "새 레슨 완료 20 XP, 모두 첫 시도에 맞히면 추가 5 XP를 받아요.", 9, MUTED).pack(anchor="w", pady=px((4, 10)))
        choices = tk.Frame(panel, bg=WHITE)
        choices.pack(fill="x")
        for i, (goal, title) in enumerate([(10, "가볍게 시작"), (20, "꾸준히 한 걸음"), (40, "조금 더 도전")]):
            choices.columnconfigure(i, weight=1)
            button(choices, f"{goal} XP · {title}", lambda n=goal: self.set_goal(n), "primary" if goal == self.progress["settings"]["goal"] else "ghost", radius=11, pady=px(8)).grid(row=0, column=i, sticky="ew", padx=px(4))
        panel = card(self.content, padding=14, radius=14)
        panel.pack(fill="x", pady=px((0, 10)))
        self.sound_var = tk.BooleanVar(value=self.progress["settings"]["sound"])
        tk.Checkbutton(panel, text="학습 효과음", variable=self.sound_var, command=self.toggle_sound, bg=WHITE, fg=INK, activebackground=WHITE, font=(FONT, 10, "bold"), selectcolor=WHITE).pack(anchor="w")
        label(panel, "정답과 오답 시 부드러운 차임벨 효과음이 재생돼요.", 9, MUTED).pack(anchor="w", pady=px((3, 0)))
        panel = card(self.content, padding=15, radius=14)
        panel.pack(fill="x", pady=px((0, 10)))
        label(panel, "학습 기록 보관하기", 12, INK, True).pack(anchor="w")
        fit_wrap(label(panel, "학습 기록은 PC에 자동 저장돼요. 백업 파일로 보관하거나 이전 기록을 불러올 수 있어요.", 9, MUTED, wraplength=px(760))).pack(anchor="w", pady=px((4, 10)))
        row = tk.Frame(panel, bg=WHITE)
        row.pack(fill="x")
        button(row, "기록 내보내기", self.export_progress, "secondary", pill=True, padx=px(13), pady=px(5)).pack(side="left", padx=px((0, 8)))
        button(row, "기록 불러오기", self.import_progress, "secondary", pill=True, padx=px(13), pady=px(5)).pack(side="left")
        fit_wrap(label(panel, "이전 브라우저 버전에서 내보낸 JSON 기록도 불러올 수 있어요. 개인정보를 수집하지 않으며, 외부로 전송하지 않아요.", 8, MUTED, wraplength=px(760))).pack(anchor="w", pady=px((8, 0)))
        panel = card(self.content, "#faf4f0", 14, border="#ebd5c9", radius=14)
        panel.pack(fill="x")
        label(panel, "처음부터 다시 시작하기", 11, "#9c725a", True).pack(anchor="w")
        fit_wrap(label(panel, "현재 기록을 자동으로 백업한 뒤 진도와 경험치를 초기화해요. 코드 초안은 유지돼요.", 9, MUTED, wraplength=px(740))).pack(anchor="w", pady=px((4, 8)))
        button(panel, "학습 기록 초기화", self.reset_progress, "ghost", pill=True, padx=px(13), pady=px(5)).pack(anchor="w")

    def choose_python_path(self):
        path = filedialog.askopenfilename(parent=self, title="python.exe 선택", filetypes=[("Python 실행 파일", "python*.exe"), ("모든 실행 파일", "*.exe")])
        if not path:
            return
        probed = discover_python_runtime(path, refresh=True)
        if not probed["available"]:
            messagebox.showerror("Python 확인 실패", "선택한 파일이 실행 가능한 Python 인터프리터가 아니에요.", parent=self)
            return
        self.progress["settings"]["pythonPath"] = str(Path(path))
        self.runtime = probed
        self._refresh_runtime_badge()
        self.save()
        self.navigate("settings")
        self.toast(f"연동 Python을 변경했어요: {self.runtime['label']}")

    def reset_python_path(self):
        self.progress["settings"]["pythonPath"] = ""
        self.runtime = discover_python_runtime("", refresh=True)
        self.editors = discover_editors(refresh=True)
        self._refresh_runtime_badge()
        self.save()
        self.navigate("settings")
        self.toast(f"Python 감지를 새로고침했어요: {self.runtime['label']}")

    def choose_rust_path(self):
        path = filedialog.askopenfilename(parent=self, title="rustc.exe 선택", filetypes=[("Rust 컴파일러", "rustc*.exe"), ("모든 실행 파일", "*.exe")])
        if not path:
            return
        probed = discover_rust_runtime(path, refresh=True)
        if not probed["available"]:
            messagebox.showerror("Rust 확인 실패", "선택한 파일이 실행 가능한 rustc 컴파일러가 아니에요.", parent=self)
            return
        self.progress["settings"]["rustPath"] = str(Path(path))
        self.rust_runtime = probed
        self._refresh_runtime_badge()
        self.save()
        self.navigate("settings")
        self.toast(f"연동 Rust를 변경했어요: {self.rust_runtime['label']}")

    def reset_rust_path(self):
        self.progress["settings"]["rustPath"] = ""
        self.rust_runtime = discover_rust_runtime("", refresh=True)
        self._refresh_runtime_badge()
        self.save()
        self.navigate("settings")
        self.toast(f"Rust 감지를 새로고침했어요: {self.rust_runtime['label']}")

    def _copy_rustup_cmd(self):
        self.clipboard_clear()
        self.clipboard_append("winget install Rustlang.Rustup")
        self.toast("Rust 설치 명령(winget install Rustlang.Rustup)을 복사했어요.")

    def choose_workspace_dir(self):
        folder = filedialog.askdirectory(parent=self, title="실습 작업 폴더 선택")
        if not folder:
            return
        self.progress["settings"]["workspaceDir"] = folder
        self.workspace.set_custom_dir(folder)
        self.save()
        self.navigate("settings")
        self.toast(f"실습 폴더를 {self.workspace.root}로 변경했어요.")

    def reset_workspace_dir(self):
        self.progress["settings"]["workspaceDir"] = ""
        self.workspace.set_custom_dir("")
        self.save()
        self.navigate("settings")
        self.toast(f"기본 실습 폴더({self.workspace.root})로 되돌렸어요.")

    def toggle_auto_verify(self):
        self.progress["settings"]["autoVerify"] = self.auto_verify_var.get()
        self.save()
        self.toast("외부 파일 저장 시 자동 인식 설정을 저장했어요.")

    def toggle_unlock_all(self):
        self.progress["settings"]["unlockAll"] = self.unlock_all_var.get()
        self.save()
        self.toast("레슨 열기 설정을 저장했어요.")

    def set_goal(self, value):
        self.progress["settings"]["goal"] = value
        self.save()
        self.navigate("settings")
        self.toast("하루 목표를 저장했어요.")

    def toggle_sound(self):
        self.progress["settings"]["sound"] = self.sound_var.get()
        self.save()
        self.play_sound(True)

    def export_progress(self):
        path = filedialog.asksaveasfilename(parent=self, title="학습 기록 내보내기", defaultextension=".json", initialfile=f"codestep-progress-{date.today()}.json", filetypes=[("코드스텝 기록", "*.json")])
        if path:
            try:
                self.store.export(path)
                self.toast("학습 기록을 파일로 보관했어요.")
            except OSError:
                messagebox.showerror("저장 실패", "파일을 저장하지 못했어요. 다른 위치를 선택해 주세요.", parent=self)

    def import_progress(self):
        path = filedialog.askopenfilename(parent=self, title="학습 기록 불러오기", filetypes=[("코드스텝 기록", "*.json")])
        if not path:
            return
        try:
            restored = self.store.read_import(path)
            if messagebox.askyesno("기록 불러오기", f"{len(restored['completed'])}개 레슨, {restored['xp']} XP의 기록으로 바꿀까요?\n현재 기록은 자동으로 백업해요.", parent=self):
                self.store.export(self.store.folder / "progress-before-import.json")
                self.store.progress = restored
                self.runtime = discover_python_runtime(self.progress["settings"].get("pythonPath", ""), refresh=True)
                self.rust_runtime = discover_rust_runtime(self.progress["settings"].get("rustPath", ""), refresh=True)
                saved_lang = self.progress["settings"].get("activeLang", "python")
                self.lang_filter = saved_lang if saved_lang in ("python", "rust") else "python"
                self.workspace.set_custom_dir(self.progress["settings"].get("workspaceDir", ""))
                self._refresh_runtime_badge()
                self.save()
                self.expanded = {next_lesson(self.progress, self.lang_filter)["unitId"]}
                self.navigate("settings")
                self.toast("학습 기록을 불러왔어요.")
        except (OSError, ValueError):
            messagebox.showerror("불러오기 실패", "올바른 코드스텝 기록 파일인지 확인해 주세요. 파일은 1 MB 이하여야 해요.", parent=self)

    def reset_progress(self):
        if messagebox.askyesno("기록 초기화", "진도, 경험치, 오답, 배지를 초기화할까요?\n이전 기록은 PC에 자동으로 백업해요.", parent=self):
            try:
                self.store.reset()
                self.runtime = discover_python_runtime("", refresh=True)
                self.rust_runtime = discover_rust_runtime("", refresh=True)
                self.lang_filter = "python"
                self.review_lang_filter = "all"
                self.workspace.set_custom_dir("")
                self._refresh_runtime_badge()
                self.expanded = {UNITS[0]["id"]}
                self.navigate("settings")
                self.toast("첫걸음부터 다시 시작해요. 이전 기록은 백업했어요.")
            except OSError:
                messagebox.showerror("초기화 실패", "기록을 백업하지 못해 초기화를 중단했어요.", parent=self)

    def start_lesson(self, lesson_id):
        if self.session:
            return
        if not is_unlocked(self.progress, lesson_id):
            if hasattr(self, "toast"):
                self.toast("이전 레슨을 먼저 완료하거나, 설정에서 '모든 레슨 자유 열기'를 켜 주세요.")
            return
        self._capture_draft()
        lesson = LESSON_BY_ID[lesson_id]
        self._start_session("lesson", list(lesson["questions"]), lesson)

    def start_review(self, question_id=None, lang="all"):
        if self.session:
            return
        ids = [question_id] if question_id else list(self.progress["mistakes"])
        questions = [
            QUESTION_BY_ID[key]
            for key in ids
            if key in self.progress["mistakes"]
            and key in QUESTION_BY_ID
            and (question_id or lang == "all" or QUESTION_BY_ID[key].get("lang", "python") == lang)
        ]
        if questions:
            self._start_session("review", questions)

    def skip_review_question(self):
        session = self.session
        if not session or session.get("done") or session["mode"] != "review":
            return
        if session["index"] + 1 < len(session["queue"]):
            session["index"] += 1
            self.initialize_question()
            self.render_lesson()
        else:
            self.close_lesson()

    def _start_session(self, mode, questions, lesson=None):
        self.watch_state = None
        self.session = {"mode": mode, "lesson": lesson, "queue": questions,
                        "index": -1 if lesson else 0, "missed": set(), "resolved": set(),
                        "hearts": 5, "started": time.monotonic(), "earned": 0, "done": False,
                        "initialBadges": {name for name, _, _, unlocked in badges(self.progress) if unlocked}}
        self.lesson_overlay = tk.Frame(self, bg=BG)
        self.lesson_overlay.place(x=0, y=0, relwidth=1, relheight=1)
        self.lesson_overlay.lift()
        self.initialize_question()
        self.render_lesson()

    def current_question(self):
        return self.session["queue"][self.session["index"]]

    def initialize_question(self):
        session = self.session
        question = self.current_question() if session["index"] >= 0 else {}
        lang = self._lesson_lang(question, session.get("lesson"))
        meta = LANG_META[lang]
        bank = list(range(len(question.get("tokens", []))))
        random.shuffle(bank)
        options = list(question.get("options", []))
        if len(options) > 1:
            random.shuffle(options)
        code = question.get("starter", "")
        task_dir = None
        script_path = None
        if question.get("type") == "code":
            task_dir, script_path, code = self.workspace.prepare_workspace(
                self.workspace.task_dir(question["id"]),
                meta["filename"],
                question.get("starter", ""),
                fixtures=question.get("fixtures"),
            )
        auto_verify = self.progress["settings"].get("autoVerify", True)
        sync_status = (
            f"● 실시간 감시 중 — 외부 편집기에서 {meta['filename']} 저장 시 자동 인식해요"
            if auto_verify
            else f"● 파일 감시 중 (수동 채점 모드) — 저장 시 코드가 반영되며 아래 '정답 확인'으로 채점해요"
        )
        session.update(
            selected=None, options=options, order=[], bank=bank, code=code, typed="",
            taskDir=task_dir, scriptPath=script_path,
            feedback={}, result=None, hint=False, revealed=False, running=False,
            exampleIdx=0, conceptOpen=False,
            syncStatus=sync_status,
        )

    def render_lesson(self):
        session = self.session
        if not session:
            return
        self._cancel_sync_write()
        for child in self.lesson_overlay.winfo_children():
            child.destroy()
        self.lesson_editor = None
        self.lesson_result_frame = None
        self.lesson_feedback_frame = None
        self.lesson_sync_label = None
        self.lesson_hint_frame = None
        self.lesson_ref_frame = None
        self.lesson_concept_ex_frame = None
        self.controls = {}
        self.lesson_overlay.columnconfigure(0, weight=1)
        self.lesson_overlay.rowconfigure(1, weight=1)
        top = tk.Frame(self.lesson_overlay, bg=WHITE, padx=px(22), pady=px(10))
        top.grid(row=0, column=0, sticky="ew")
        button(top, "✕  닫기", self.request_exit_lesson, "ghost", pill=True, padx=px(12), pady=px(4)).pack(side="left")
        total = len(session["queue"])
        title = session["lesson"]["title"] if session["lesson"] else "오답 복습"
        label(top, f"  {title}", 11, INK, True).pack(side="left", padx=px((8, 16)))
        hearts = ("♥ " * session["hearts"]).strip() or "∞  자유 연습"
        self.controls["hearts"] = pill(top, hearts if session["mode"] == "lesson" else "↻  다시 한 걸음", "#b85c50", "#faece9", border="#f0cdc6", size=10, padx=11, pady=4)
        self.controls["hearts"].pack(side="right")
        bar = RoundedProgressBar(top, fill=GREEN, trough="#dce6df", maximum=total,
                                 value=total if session["done"] else max(0, session["index"]), length=190, height=9)
        bar.pack(side="right", padx=px(14))
        self.lesson_scroll = ScrollArea(self.lesson_overlay)
        self.lesson_scroll.grid(row=1, column=0, sticky="nsew")
        self.lesson_scroll.inner.columnconfigure(0, weight=1)
        body = tk.Frame(self.lesson_scroll.inner, bg=BG, padx=px(20), pady=px(12))
        body.grid(row=0, column=0, sticky="nsew")
        footer = tk.Frame(self.lesson_overlay, bg=WHITE, padx=px(24), pady=px(10),
                          highlightbackground=LINE, highlightthickness=px(1))
        footer.grid(row=2, column=0, sticky="ew")
        self.controls["footer"] = footer
        self.lesson_two_cols = self.winfo_width() >= px(1080)
        if session["done"]:
            self.watch_state = None
            center = tk.Frame(body, bg=BG)
            center.pack(fill="x", padx=px(120 if self.lesson_two_cols else 0))
            self._completion_page(center, footer)
            return
        if session["index"] < 0:
            self.watch_state = None
            self._concept_page(body, footer)
            return

        _, left_pane, right_pane = self._make_two_cols(body, self.lesson_two_cols, left_weight=11, right_weight=10, gap=14)
        wrap_w = px(560 if self.lesson_two_cols else 720)
        question = self.current_question()
        lang = self._lesson_lang(question, session.get("lesson"))
        meta = LANG_META[lang]
        q_type_label = meta["code_type"] if question["type"] == "code" else TYPE_NAMES[question["type"]]
        q_hdr = tk.Frame(left_pane, bg=BG)
        q_hdr.pack(anchor="w")
        is_mid = (session.get("lesson") or {}).get("kind") == "midterm"
        q_prefix = "중간 시험" if is_mid else "문제"
        pill(
            q_hdr,
            f"{q_prefix} {session['index'] + 1} / {total}  ·  {meta['name']} · {q_type_label}",
            "#8a5314" if is_mid else GREEN,
            "#fef0d1" if is_mid else PALE,
            border="#ebd096" if is_mid else "#bde2cf",
            size=9,
            padx=10,
            pady=3,
        ).pack(side="left")
        fit_wrap(label(left_pane, question["prompt"], 14, INK, True, wraplength=wrap_w)).pack(anchor="w", pady=px((6, 8)))
        if question.get("code") and question["type"] != "code":
            snippet = question["code"].replace("___", str(session["selected"])) if question["type"] == "fill" and session["selected"] is not None else question["code"]
            # Tracing needs the whole program on screen, so written-output questions are never cut off.
            full_height = len(snippet.splitlines()) if question["type"] == "output" else None
            fill_box = code_block(left_pane, snippet, True, height=full_height, lang=lang)
            fill_box.pack(fill="x", pady=px((0, 8)))
            if question["type"] == "fill":
                self.controls["fill_code"] = (fill_box, question["code"])
        locked = session["running"] or session["feedback"].get("correct")
        if question["type"] in ("choice", "fill"):
            self.watch_state = None
            self._answer_choices(left_pane, question, locked)
            self.lesson_ref_frame = tk.Frame(right_pane, bg=BG)
            self.lesson_ref_frame.pack(fill="x")
            self._render_lesson_reference_pane(question)
        elif question["type"] == "order":
            self.watch_state = None
            self._answer_order(left_pane, question, locked)
            self.lesson_ref_frame = tk.Frame(right_pane, bg=BG)
            self.lesson_ref_frame.pack(fill="x")
            self._render_lesson_reference_pane(question)
        elif question["type"] == "output":
            self.watch_state = None
            self._answer_output(left_pane, question, locked)
            self.lesson_ref_frame = tk.Frame(right_pane, bg=BG)
            self.lesson_ref_frame.pack(fill="x")
            self._render_lesson_reference_pane(question)
        else:
            self._answer_code(left_pane, question, locked, right_pane)
            self._activate_watch(
                "lesson",
                session["taskDir"],
                session["scriptPath"],
                fixtures=question.get("fixtures"),
                question=question,
            )

        self.lesson_hint_frame = tk.Frame(left_pane, bg=BG)
        self.lesson_hint_frame.pack(fill="x")
        self._render_lesson_hint_and_feedback(question)

        if question["type"] in ("choice", "fill"):
            ready = session["selected"] is not None
        elif question["type"] == "order":
            ready = len(session["order"]) == len(question["tokens"])
        elif question["type"] == "output":
            ready = bool(session["typed"].strip())
        else:
            ready = True
        self.controls["footer_hint"] = label(footer, "하트가 없어도 계속 연습할 수 있어요." if session["hearts"] == 0 else "천천히 생각해도 괜찮아요.", 9, MUTED)
        self.controls["footer_hint"].pack(side="left")
        check = button(footer, "정답 확인", self.check_answer, pill=True, padx=px(18), pady=px(7), min_width=220)
        check.pack(side="right")
        skip = button(footer, "건너뛰기 →", self.skip_review_question, "ghost", pill=True, padx=px(12), pady=px(7))
        self.controls["check"] = check
        self.controls["skip"] = skip
        self._sync_review_skip_button()
        self._update_check_button(ready)

    def _lesson_examples(self, lesson):
        examples = lesson.get("examples") or []
        if examples:
            return examples
        return [{"title": f"{lesson['title']} 기본 예제", "code": lesson.get("example", ""), "output": "", "note": ""}]

    def _render_example_tabs(self, parent, examples, active_idx, target, bg=BG, padx_btn=10, pady_btn=4, pady_wrap=(0, 6),
                             show_all_btn=False, max_width=None):
        """Example navigator: '예제 3 / 15', previous/next, and numbered buttons that wrap onto more rows.

        Lessons have 15-20 examples, so one row of '예제 N' buttons would run off the panel.
        """
        total = len(examples)
        if total <= 1 and not show_all_btn:
            return
        wrap = tk.Frame(parent, bg=bg)
        wrap.pack(fill="x", pady=px(pady_wrap))
        head = tk.Frame(wrap, bg=bg)
        head.pack(fill="x", pady=px((0, 4)))
        current = "전체" if active_idx == -1 else f"{active_idx + 1} / {total}"
        label(head, f"예제 {current}", 9, MUTED, True, bg=bg).pack(side="left")
        style = dict(pill=True, padx=px(padx_btn), pady=px(pady_btn), font=(FONT, 8, "bold"))
        if show_all_btn and total > 1:
            button(head, "전체 보기", lambda t=target: self._select_lesson_example(-1, t),
                   "secondary" if active_idx == -1 else "ghost", **style).pack(side="right")
        next_btn = button(head, "다음 ▶", lambda t=target: self._select_lesson_example(0 if active_idx < 0 else min(total - 1, active_idx + 1), t),
                          "ghost", **style)
        next_btn.pack(side="right", padx=px((0, 5)))
        prev_btn = button(head, "◀ 이전", lambda t=target: self._select_lesson_example(max(0, active_idx - 1), t), "ghost", **style)
        prev_btn.pack(side="right", padx=px((0, 5)))
        if active_idx <= 0:
            prev_btn.configure(state="disabled")
        if active_idx == total - 1:
            next_btn.configure(state="disabled")
        builders = [
            (lambda row, i=idx: button(row, str(i + 1), lambda i=i, t=target: self._select_lesson_example(i, t),
                                       "secondary" if i == active_idx else "ghost", pill=True, padx=px(8), pady=px(pady_btn),
                                       font=(FONT, 8, "bold"), min_width=28))
            for idx in range(total)
        ]
        _pack_chip_flow(wrap, builders, gap_x=5, gap_y=4, max_width=max_width or (520 if self.lesson_two_cols else 680), bg=bg)

    def _copy_snippet(self, code):
        self.clipboard_clear()
        self.clipboard_append(code)
        self.toast("예제 코드를 복사했어요. 연습장이나 IDLE에 붙여 넣어 보세요.")

    def _render_example_card(self, parent, ex, wrap_w, title_prefix="", pad_bottom=8, lang="python"):
        meta = LANG_META.get(lang, LANG_META["python"])
        title = f"{title_prefix}{ex.get('title', '예제')}"
        shell = create_code_shell(
            parent,
            f"{meta['example']}  ·  {title}",
            right_action=("복사", lambda code=ex.get("code", ""): self._copy_snippet(code)),
        )
        shell.pack(fill="x", pady=px((0, 4 if ex.get("note") else pad_bottom)))
        lines = ex.get("code", "").splitlines() or [""]
        widget = tk.Text(
            shell,
            height=max(2, min(11, len(lines) + 1)),
            wrap="word",
            bg=CODE_BG,
            fg=CODE_FG,
            font=(CODE_FONT, 10),
            relief="flat",
            bd=0,
            padx=px(2),
            pady=0,
            spacing1=2,
            spacing3=2,
            selectbackground=CODE_SELECT,
            highlightthickness=0,
            cursor="xterm",
        )
        widget.insert("1.0", ex.get("code", ""))
        configure_code_tags(widget)
        apply_code_syntax(widget, ex.get("code", ""), lang)
        widget.configure(state="disabled")
        line_cnt = int(widget.index("end-1c").split(".")[0])
        box_h = int(str(widget.cget("height") or 11))
        if line_cnt > box_h or (box_h >= 10 and any(len(ln) > 62 for ln in widget.get("1.0", "end-1c").splitlines())):
            bar_kw = {"style": "Dark.Vertical.TScrollbar"} if str(widget.cget("bg")).lower() == CODE_BG.lower() else {}
            vbar = ttk.Scrollbar(widget.master, orient="vertical", command=widget.yview, **bar_kw)
            widget.configure(yscrollcommand=vbar.set)
            vbar.pack(side="right", fill="y", padx=px((4, 0)))
            widget.pack(side="left", fill="x", expand=True)
        else:
            widget.pack(fill="x")
        if ex.get("output"):
            out_bar = RoundedFrame(shell, bg="#14181d", padx=10, pady=6, border="#272e37", radius=9, outer_bg=CODE_BG)
            out_bar.pack(fill="x", pady=px((6, 0)))
            tk.Label(out_bar, text="▶ 실행 출력", bg="#14181d", fg=TERM_PROMPT, font=(FONT, 8, "bold")).pack(anchor="w")
            tk.Label(
                out_bar, text=ex["output"], bg="#14181d", fg=TERM_FG, font=(CODE_FONT, 9),
                justify="left", anchor="w", wraplength=max(px(260), wrap_w - px(48)),
            ).pack(anchor="w", pady=px((2, 0)))
        if ex.get("note"):
            note_card = card(parent, "#f7faf9", 9, border="#dce6e1", radius=11)
            note_card.pack(fill="x", pady=px((0, pad_bottom)))
            fit_wrap(label(note_card, ex["note"], 8, MUTED, wraplength=max(px(280), wrap_w - px(32)))).pack(anchor="w")

    def _render_steps_cards(self, parent, lesson, wrap_w, compact=False):
        steps = lesson.get("steps") or []
        if not steps:
            return
        header_row = tk.Frame(parent, bg=BG)
        header_row.pack(fill="x", pady=px((8 if not compact else 5, 4)))
        label(header_row, "단계별 학습 가이드", 11 if not compact else 10, PY_BLUE, True).pack(side="left")
        label(header_row, f"총 {len(steps)}단계", 8, MUTED).pack(side="right")
        for item in steps:
            sc = card(parent, WHITE, padding=10 if not compact else 9, radius=12)
            sc.pack(fill="x", pady=px((0, 6 if not compact else 5)))
            title_row = tk.Frame(sc, bg=WHITE)
            title_row.pack(fill="x")
            badge_num = item.get("step", "")
            badge_bg = PY_BLUE_PALE if badge_num else PALE
            badge_fg = PY_BLUE if badge_num else GREEN
            pill(title_row, item.get("title", "단계 안내"), badge_fg, badge_bg, size=8 if compact else 9, padx=9, pady=2).pack(side="left")
            body_wrap = max(px(260), wrap_w - px(28 if compact else 32))
            fit_wrap(label(sc, item.get("summary", ""), 9, INK, wraplength=body_wrap)).pack(anchor="w", pady=px((5, 0)))
            if item.get("tip"):
                fit_wrap(label(sc, f"TIP · {item['tip']}", 8, "#7c6c3c", wraplength=body_wrap)).pack(anchor="w", pady=px((2, 0)))

    def _render_pitfalls(self, parent, lesson, wrap_w, compact=False, bg=BG):
        """'자주 하는 실수': wrong code, the message the app really shows for it, the fix and why."""
        items = (lesson or {}).get("pitfalls") or []
        if not items:
            return
        lang = self._lesson_lang(lesson=lesson)
        header = tk.Frame(parent, bg=bg)
        header.pack(fill="x", pady=px((10 if not compact else 8, 4)))
        label(header, "자주 하는 실수", 11 if not compact else 10, "#b85c50", True, bg=bg).pack(side="left")
        label(header, f"{len(items)}가지 · 미리 알면 덜 막혀요", 8, MUTED, bg=bg).pack(side="right")
        for number, item in enumerate(items, 1):
            box = card(parent, WHITE, padding=10 if not compact else 9, border="#efd3cc", radius=12)
            box.pack(fill="x", pady=px((0, 6)))
            fit_wrap(label(box, f"{number}. {item.get('title', '')}", 10 if not compact else 9, INK, True, wraplength=wrap_w)).pack(anchor="w")
            label(box, "✕  이렇게 쓰면", 8, "#b85c50", True).pack(anchor="w", pady=px((6, 2)))
            code_block(box, item.get("wrong", ""), True, lang=lang).pack(fill="x")
            if item.get("message") or "wrongOutput" in item:
                is_error = bool(item.get("message"))
                caption = "화면에 나오는 오류" if is_error else "오류는 없지만 결과가 기대와 달라요 · 실제 출력"
                label(box, caption, 8, MUTED, True).pack(anchor="w", pady=px((6, 2)))
                shown = item.get("message") if is_error else (item.get("wrongOutput") or "(아무것도 출력되지 않아요)")
                out = RoundedFrame(box, bg="#fdf2ef" if is_error else SURFACE, padx=10, pady=6,
                                   border="#efd3cc" if is_error else LINE, radius=9, outer_bg=WHITE)
                out.pack(fill="x")
                fit_wrap(tk.Label(out, text=shown, bg=out.cget("bg"), fg="#9b3d31" if is_error else INK,
                                  font=(CODE_FONT, 9), justify="left", anchor="w", wraplength=wrap_w)).pack(anchor="w")
            label(box, "✓  이렇게 고쳐요", 8, GREEN, True).pack(anchor="w", pady=px((6, 2)))
            code_block(box, item.get("fix", ""), True, lang=lang).pack(fill="x")
            fix_output = item.get("fixOutput", "")
            if fix_output and not compact:
                lines = fix_output.splitlines()
                preview = "\n".join(lines[:3]) + ("\n..." if len(lines) > 3 else "")
                tk.Label(box, text="▶ " + preview.replace("\n", "\n   "), bg=WHITE, fg=GREEN, font=(CODE_FONT, 9),
                         justify="left", anchor="w").pack(anchor="w", pady=px((3, 0)))
            fit_wrap(label(box, item.get("why", ""), 9, INK, wraplength=wrap_w)).pack(anchor="w", pady=px((6, 0)))

    @staticmethod
    def _matching_pitfall(lesson, error_text):
        """The lesson's '자주 하는 실수' item that produced the same error, if any."""
        error_text = (error_text or "").strip()
        if not lesson or not error_text:
            return None
        first = re.sub(r"^\d+번째 줄: ", "", error_text.splitlines()[0])
        for item in lesson.get("pitfalls") or []:
            message, expect = item.get("message") or "", item.get("expect", "")
            if not message:
                continue
            if lesson.get("lang") == "rust":
                code_match = re.search(r"error\[(E\d{4})\]", message)
                if (code_match and f"error[{code_match.group(1)}]" in error_text) or (not expect.startswith("E") and expect in error_text):
                    return item
                continue
            theirs = re.sub(r"^\d+번째 줄: ", "", message.splitlines()[0])
            if first[:30] == theirs[:30] or (expect and first.startswith(expect + ":")):
                return item
        return None

    def _render_lesson_reference_pane(self, question):
        """Right-side step-by-step concept & multi-example panel for choice/fill/order questions."""
        if not self.lesson_ref_frame or not self.lesson_ref_frame.winfo_exists():
            return
        for child in self.lesson_ref_frame.winfo_children():
            child.destroy()
        parent = self.lesson_ref_frame
        lesson = self.session.get("lesson") or LESSON_BY_ID.get(question.get("lessonId"))
        lang = self._lesson_lang(question, lesson)
        meta = LANG_META[lang]
        wrap_w = px(540 if self.lesson_two_cols else 680)
        if lesson:
            examples = self._lesson_examples(lesson)
            idx = max(0, min(self.session.get("exampleIdx", 0), len(examples) - 1))
            self._render_example_tabs(parent, examples, idx, "ref")
            self._render_example_card(parent, examples[idx], wrap_w, pad_bottom=6, lang=lang)
            steps = lesson.get("steps") or []
            if steps:
                steps_box = card(parent, padding=10)
                steps_box.pack(fill="x", pady=px((0, 8)))
                label(steps_box, "핵심 단계 요약", 9, meta["accent"], True).pack(anchor="w", pady=px((0, 4)))
                for st in steps:
                    fit_wrap(label(steps_box, f"· {st['title']} — {st['summary']}", 8, INK, wraplength=wrap_w - px(28))).pack(anchor="w", pady=px(1))
                    if st.get("tip"):
                        fit_wrap(label(steps_box, f"   TIP · {st['tip']}", 8, "#7c6c3c", wraplength=wrap_w - px(28))).pack(anchor="w", pady=px((0, 2)))
            else:
                info = card(parent, padding=10)
                info.pack(fill="x", pady=px((0, 8)))
                label(info, "핵심 개념 요약", 10, meta["accent"], True).pack(anchor="w")
                fit_wrap(label(info, lesson["body"], 9, INK, wraplength=wrap_w - px(28))).pack(anchor="w", pady=px((4, 0)))
        ver_str = self.rust_runtime.get("version") or "rustc" if lang == "rust" else self.runtime.get("version") or sys.version.split()[0]
        if question["type"] == "order":
            tip_line = f"· 조각 클릭: 순서 추가   · 위 조각 클릭: 되돌리기\n· Ctrl+Enter: 정답 확인/이동 · 마지막은 {meta['filename']} 실기 문제!"
        elif question["type"] == "output":
            tip_line = "· 실행하지 말고 손으로 따라가 결과를 적어요\n· Ctrl+Enter: 채점/이동 · 줄바꿈·따옴표까지 똑같이!"
        elif question["type"] == "code":
            tip_line = f"· Tab: 공백 4칸   · Ctrl+Enter: 실행·검증\n· {meta['filename']} 저장 시 앱이 변경을 즉시 인식해요!"
        else:
            tip_line = f"· 숫자 키 1~4: 보기 선택   · Ctrl+Enter: 채점/이동\n· 마지막은 실제 {meta['name']}({meta['filename']}) 실기 문제!"
        tip_entries = [
            ("dim", f"{meta['name']} {ver_str} · 학습 가이드\n"),
            ("prompt", "TIP> "),
            ("cmd", "단축키 안내\n"),
            ("stdout", tip_line + "\n"),
        ]
        shell, _ = create_terminal_box(parent, f"{meta['name']} 터미널 안내", tip_entries, height=4)
        shell.pack(fill="x")

    def _ensure_feedback_visible(self):
        session = self.session
        scroll = getattr(self, "lesson_scroll", None)
        ui = self.controls.get("hint_ui") if session else None
        if not scroll or not scroll.winfo_exists() or not ui:
            return
        slot = ui.get("feedback_slot")
        if slot and slot.winfo_exists() and slot.winfo_manager():
            scroll.ensure_visible(slot)

    def _sync_review_skip_button(self):
        session = self.session
        skip = self.controls.get("skip")
        if not session or not skip or not skip.winfo_exists():
            return
        should_show = (
            session["mode"] == "review"
            and not session["feedback"].get("correct")
            and (len(session["queue"]) > 1 or session["feedback"].get("missingCompiler"))
        )
        if should_show:
            if not skip.winfo_manager():
                skip.pack(side="right", padx=px((0, 6)))
        elif skip.winfo_manager():
            skip.pack_forget()

    def _render_lesson_hint_and_feedback(self, question):
        if not self.lesson_hint_frame or not self.lesson_hint_frame.winfo_exists():
            return
        session = self.session
        wrap_w = px(540 if self.lesson_two_cols else 690)
        lesson = session.get("lesson") or LESSON_BY_ID.get(question.get("lessonId"))
        lang = self._lesson_lang(question, lesson)
        meta = LANG_META[lang]

        ui = self.controls.get("hint_ui")
        if not ui or not ui["bar"].winfo_exists():
            for child in self.lesson_hint_frame.winfo_children():
                child.destroy()
            self.lesson_hint_frame.columnconfigure(0, weight=1)
            hint_bar = tk.Frame(self.lesson_hint_frame, bg=BG)
            hint_bar.grid(row=0, column=0, sticky="ew", pady=px((8, 0)))
            hint_btn = button(hint_bar, "◉  힌트 보기", self.toggle_hint,
                              "ghost", pill=True, padx=px(11), pady=px(4), font=(FONT, 9, "bold"))
            hint_btn.pack(side="left")
            concept_btn = button(hint_bar, "▤  개념·예제 다시 보기", self.toggle_concept,
                                 "ghost", pill=True, padx=px(11), pady=px(4), font=(FONT, 9, "bold"))
            reveal_btn = button(hint_bar, "예시 답안 보기", self.reveal_solution,
                                "secondary", pill=True, padx=px(11), pady=px(4), font=(FONT, 9, "bold"))
            hint_slot = tk.Frame(self.lesson_hint_frame, bg=BG)
            concept_slot = tk.Frame(self.lesson_hint_frame, bg=BG)
            solution_slot = tk.Frame(self.lesson_hint_frame, bg=BG)
            feedback_slot = tk.Frame(self.lesson_hint_frame, bg=BG)
            ui = {
                "bar": hint_bar,
                "hint_btn": hint_btn,
                "concept_btn": concept_btn,
                "reveal_btn": reveal_btn,
                "hint_slot": hint_slot,
                "concept_slot": concept_slot,
                "solution_slot": solution_slot,
                "feedback_slot": feedback_slot,
                "hint_state": None,
                "concept_state": None,
                "sol_state": None,
                "fb_sig": None,
            }
            self.controls["hint_ui"] = ui

        ui["hint_btn"].configure(text="힌트 접기" if session["hint"] else "◉  힌트 보기")
        if lesson:
            ui["concept_btn"].configure(text="▤  개념·예제 접기" if session.get("conceptOpen") else "▤  개념·예제 다시 보기")
            if not ui["concept_btn"].winfo_manager():
                ui["concept_btn"].pack(side="left", padx=px((6, 0)))
        elif ui["concept_btn"].winfo_manager():
            ui["concept_btn"].pack_forget()

        written = question["type"] == "output"
        show_reveal = bool(session["feedback"] and not session["feedback"].get("correct") and question["type"] in ("code", "output"))
        if show_reveal:
            ui["reveal_btn"].configure(text="정답 출력 보기" if written else "예시 답안 보기")
            if not ui["reveal_btn"].winfo_manager():
                ui["reveal_btn"].pack(side="left", padx=px(6))
        elif ui["reveal_btn"].winfo_manager():
            ui["reveal_btn"].pack_forget()

        hint_state = (bool(session["hint"]), question["id"])
        if hint_state != ui["hint_state"]:
            ui["hint_state"] = hint_state
            for c in ui["hint_slot"].winfo_children():
                c.destroy()
            if session["hint"]:
                hint = card(ui["hint_slot"], "#fbf5df", 11, border="#e7dba8", radius=12)
                hint.pack(fill="x")
                hint_text = question.get("hint") or "개념·예제 다시 보기에서 핵심 단계와 예제를 먼저 확인해 보세요."
                label(hint, "단계별 힌트", 9, "#7c6c3c", True).pack(anchor="w")
                fit_wrap(label(hint, hint_text, 9, "#7c6c3c", wraplength=wrap_w)).pack(anchor="w", pady=px((2, 0)))
                ui["hint_slot"].grid(row=1, column=0, sticky="ew", pady=px((7, 0)))
            else:
                ui["hint_slot"].grid_remove()

        concept_state = (bool(lesson and session.get("conceptOpen")), int(session.get("exampleIdx", 0)), question["id"])
        if concept_state != ui["concept_state"]:
            ui["concept_state"] = concept_state
            for c in ui["concept_slot"].winfo_children():
                c.destroy()
            if lesson and session.get("conceptOpen"):
                ref_card = card(ui["concept_slot"], "#f6f9fc", 11, border=meta["border"], radius=13)
                ref_card.pack(fill="x")
                label(ref_card, f"{lesson['title']} — 단계별 복습 & 예제", 10, meta["accent"], True).pack(anchor="w")
                examples = self._lesson_examples(lesson)
                idx = max(0, min(session.get("exampleIdx", 0), len(examples) - 1))
                holder = tk.Frame(ref_card, bg="#f6f9fc")
                holder.pack(fill="x", pady=px((5, 0)))
                for step in (lesson.get("steps") or []):
                    fit_wrap(label(holder, f"· {step['title']}: {step['summary']}", 9, INK, wraplength=wrap_w - px(20))).pack(anchor="w", pady=px(1))
                    if step.get("tip"):
                        fit_wrap(label(holder, f"   TIP · {step['tip']}", 8, "#7c6c3c", wraplength=wrap_w - px(20))).pack(anchor="w", pady=px((0, 2)))
                self._render_example_tabs(holder, examples, idx, "code", bg="#f6f9fc", padx_btn=9, pady_btn=3, pady_wrap=(5, 4),
                                          max_width=490 if self.lesson_two_cols else 650)
                self._render_example_card(holder, examples[idx], wrap_w - px(20), pad_bottom=0, lang=lang)
                self._render_pitfalls(holder, lesson, wrap_w - px(20), compact=True, bg="#f6f9fc")
                ui["concept_slot"].grid(row=2, column=0, sticky="ew", pady=px((7, 0)))
            else:
                ui["concept_slot"].grid_remove()

        sol_state = (bool(session["revealed"]), question["id"])
        if sol_state != ui["sol_state"]:
            ui["sol_state"] = sol_state
            for c in ui["solution_slot"].winfo_children():
                c.destroy()
            if session["revealed"]:
                sol_hdr = tk.Frame(ui["solution_slot"], bg=BG)
                sol_hdr.pack(fill="x", pady=px((0, 2)))
                shown_answer = question["answer"] if written else question["solution"]
                label(sol_hdr, "💡 정답 출력" if written else "💡 예시 답안", 9, meta["accent"], True).pack(side="left")
                button(
                    sol_hdr,
                    "답안 복사",
                    lambda s=shown_answer: (self.clipboard_clear(), self.clipboard_append(s), self.toast("답안을 클립보드에 복사했어요.")),
                    "ghost",
                    pill=True,
                    padx=px(9),
                    pady=px(2),
                    font=(FONT, 8, "bold"),
                ).pack(side="right")
                code_block(ui["solution_slot"], shown_answer, True, lang=lang).pack(fill="x")
                ui["solution_slot"].grid(row=3, column=0, sticky="ew", pady=px((7, 0)))
            else:
                ui["solution_slot"].grid_remove()

        result = session.get("result") if question["type"] == "code" else None
        feedback = session["feedback"]
        has_fb_box = bool(feedback or (result and result.get("checks")))
        fb_sig = (
            has_fb_box,
            tuple(sorted((k, str(v)) for k, v in feedback.items())) if feedback else (),
            result.get("runtimeMode") if result else None,
            result.get("elapsed") if result else None,
            result.get("ok") if result else None,
            result.get("passed") if result else None,
            result.get("missingCompiler") if result else None,
            result.get("error") if result else None,
            tuple((bool(c.get("ok")), c.get("label"), c.get("detail")) for c in (result.get("checks") or [])) if result else (),
        )
        prev_had_fb = bool(ui["fb_sig"] and ui["fb_sig"][0])
        if fb_sig != ui["fb_sig"]:
            ui["fb_sig"] = fb_sig
            for c in ui["feedback_slot"].winfo_children():
                c.destroy()
            if has_fb_box:
                is_ok = feedback.get("correct") if feedback else bool(result and result.get("passed"))
                is_missing_rs = bool(feedback and feedback.get("missingCompiler"))
                box_bg = PALE if feedback and is_ok else "#fbf5df" if is_missing_rs else "#fbede7" if feedback else WHITE
                box_border = "#b8dccb" if feedback and is_ok else "#e7dba8" if is_missing_rs else "#e8c4b9" if feedback else LINE
                box = card(ui["feedback_slot"], box_bg, 12, border=box_border, radius=13)
                box.pack(fill="x")
                if feedback:
                    if is_missing_rs:
                        title = "⚠  로컬 Rust 컴파일러(rustc)가 아직 설치되지 않았어요"
                        title_fg = "#8b6414"
                    elif is_ok:
                        title = "✓  정답 판정: 잘했어요! (Ctrl+Enter로 다음으로)"
                        title_fg = GREEN
                    else:
                        title = "✕  정답 판정: 한 번 더 생각해 볼까요?"
                        title_fg = "#b85c50"
                    label(box, title, 10, title_fg, True).pack(anchor="w")
                    fit_wrap(label(box, feedback["message"], 9, INK, wraplength=wrap_w)).pack(anchor="w", pady=px((4, 0)))
                    if result and result.get("missingCompiler"):
                        rs_act = tk.Frame(box, bg=box_bg)
                        rs_act.pack(anchor="w", pady=px((6, 0)))
                        button(rs_act, "Rust 설치 명령 복사 (winget install Rustlang.Rustup)", self._copy_rustup_cmd, "secondary", pill=True, padx=px(10), pady=px(4), font=(FONT, 9, "bold")).pack(side="left", padx=px((0, 6)))
                        button(rs_act, "준비 탭에서 터미널 설치 →", lambda: (self.close_lesson(), self.open_setup("rust")), "rust", pill=True, padx=px(10), pady=px(4), font=(FONT, 9, "bold")).pack(side="left")
                else:
                    mode_map = {"rustc": "로컬 rustc", "missing-rustc": "rustc 미설치", "system": "시스템 Python"}
                    mode_label = mode_map.get(result.get("runtimeMode"), "내장 기본 실행기")
                    label(box, f"●  실시간 자동 검증 ({mode_label} · {result.get('elapsed', 0)} ms)", 9, meta["accent"], True).pack(anchor="w")
                    if result.get("error") and not result.get("ok"):
                        first_err = next((ln.strip() for ln in result["error"].splitlines() if ln.strip()), "")[:120]
                        if first_err:
                            fit_wrap(label(box, f"오류 요약: {first_err}", 8, "#b85c50", wraplength=wrap_w)).pack(anchor="w", pady=px((3, 0)))
                if result and result.get("checks"):
                    checks_wrap = tk.Frame(box, bg=box_bg)
                    checks_wrap.pack(fill="x", pady=px((5, 0)))
                    for item in result["checks"]:
                        mark = "✓" if item["ok"] else "✕"
                        color = GREEN if item["ok"] else "#b85c50"
                        fit_wrap(label(checks_wrap, f"{mark}  {item['label']}: {item['detail']}", 9, color, wraplength=wrap_w)).pack(anchor="w", pady=px(1))
                ui["feedback_slot"].grid(row=4, column=0, sticky="ew", pady=px((8, 0)))
                if not prev_had_fb:
                    self.after(25, self._ensure_feedback_visible)
            else:
                ui["feedback_slot"].grid_remove()

    def _update_check_button(self, ready=True):
        session = self.session
        check = self.controls.get("check")
        if not session or not check or not check.winfo_exists():
            return
        question = self.current_question()
        correct = session["feedback"].get("correct")
        if correct:
            caption = "다음으로 (Ctrl+Enter)  →"
            cmd = self.next_question
        elif session["running"]:
            caption = "실행 중…"
            cmd = self.check_answer
        elif question["type"] == "code":
            caption = "실행하고 채점 (Ctrl+Enter)"
            cmd = self.check_answer
        else:
            caption = "정답 확인"
            cmd = self.check_answer
        check.configure(text=caption, command=cmd, state="disabled" if (session["running"] or not ready) else "normal")
        if self.controls.get("footer_hint") and self.controls["footer_hint"].winfo_exists():
            if correct:
                hint_text = "정답입니다! Ctrl + Enter를 누르면 다음으로 넘어가요."
            elif session["hearts"] == 0:
                hint_text = "하트가 없어도 계속 연습할 수 있어요."
            else:
                hint_text = "천천히 생각해도 괜찮아요."
            if self.controls["footer_hint"].cget("text") != hint_text:
                self.controls["footer_hint"].configure(text=hint_text)

    def _render_concept_examples(self):
        if not self.lesson_concept_ex_frame or not self.lesson_concept_ex_frame.winfo_exists():
            return
        for child in self.lesson_concept_ex_frame.winfo_children():
            child.destroy()
        lesson = self.session["lesson"]
        lang = self._lesson_lang(lesson=lesson)
        wrap_w = px(560 if self.lesson_two_cols else 680)
        examples = self._lesson_examples(lesson)
        idx = self.session.get("exampleIdx", 0)
        if idx != -1:
            idx = max(0, min(idx, len(examples) - 1))
        self._render_example_tabs(self.lesson_concept_ex_frame, examples, idx, "concept", show_all_btn=True)
        if idx == -1:
            for num, ex in enumerate(examples, start=1):
                self._render_example_card(self.lesson_concept_ex_frame, ex, wrap_w, title_prefix=f"예제 {num} · ", pad_bottom=6, lang=lang)
        else:
            self._render_example_card(self.lesson_concept_ex_frame, examples[idx], wrap_w, title_prefix=f"예제 {idx + 1} · ", pad_bottom=6, lang=lang)

    def _concept_page(self, body, footer):
        lesson = self.session["lesson"]
        lang = self._lesson_lang(lesson=lesson)
        meta = LANG_META[lang]
        _, left_pane, right_pane = self._make_two_cols(body, self.lesson_two_cols, left_weight=11, right_weight=10)
        wrap_w = px(560 if self.lesson_two_cols else 680)
        badge_hdr = tk.Frame(left_pane, bg=BG)
        badge_hdr.pack(anchor="w")
        lang_units = [u["id"] for u in UNITS if u.get("lang", "python") == lang]
        unit_num = (lang_units.index(lesson["unitId"]) + 1) if lesson.get("unitId") in lang_units else lesson["unitNumber"]
        is_mid = lesson.get("kind") == "midterm"
        badge_text = f"{meta['name']}  ·  {lesson.get('levelTitle', '입문')}  ·  UNIT {unit_num:02d}  ·  {lesson['unitTitle']}"
        if is_mid:
            badge_text += "  ·  ⚑ 중간 시험"
        pill(
            badge_hdr,
            badge_text,
            "#8a5314" if is_mid else meta["accent"],
            "#fef0d1" if is_mid else meta["pale"],
            border="#ebd096" if is_mid else meta["border"],
            size=9,
            padx=10,
            pady=3,
        ).pack(side="left")
        fit_wrap(label(left_pane, lesson["title"], 18, INK, True, wraplength=wrap_w)).pack(anchor="w", pady=px((7, 3)))
        fit_wrap(label(left_pane, lesson["subtitle"], 10, MUTED, wraplength=wrap_w)).pack(anchor="w", pady=px((0, 8)))
        panel = card(left_pane, padding=13, radius=13)
        panel.pack(fill="x")
        label(panel, "시험 범위 핵심 정리" if is_mid else "먼저, 핵심부터 가볍게", 11, INK, True).pack(anchor="w")
        fit_wrap(label(panel, lesson["body"], 9, INK, wraplength=wrap_w - px(28))).pack(anchor="w", pady=px((5, 1)))
        self._render_steps_cards(left_pane, lesson, wrap_w, compact=True)
        fit_wrap(label(left_pane, f"고르기 → 빈칸 → 순서 맞추기 → 실제 {meta['name']} 실기 순서로 차근차근 익혀요.", 9, MUTED, wraplength=wrap_w)).pack(anchor="w", pady=px((4, 0)))

        examples = self._lesson_examples(lesson)
        label(right_pane, f"단계별 실행 예제 ({len(examples)}가지)", 10, meta["accent"], True).pack(anchor="w", pady=px((0, 5)))
        self.lesson_concept_ex_frame = tk.Frame(right_pane, bg=BG)
        self.lesson_concept_ex_frame.pack(fill="x")
        self._render_concept_examples()
        self._render_pitfalls(right_pane, lesson, wrap_w)
        bridge_note = card(right_pane, meta["pale"], 11, border=meta["border"], radius=13)
        bridge_note.pack(fill="x", pady=px((4, 0)))
        label(bridge_note, f">_  실제 {meta['name']} 프로그램 연동 학습", 10, meta["accent"], True).pack(anchor="w")
        fit_wrap(label(bridge_note, "문제를 푸는 중에도 '▤ 개념·예제 다시 보기' 버튼으로 언제든 위 예제를 다시 펼쳐 볼 수 있어요.", 9, MUTED, wraplength=wrap_w - px(28))).pack(anchor="w", pady=px((3, 0)))

        q_cnt = len(lesson.get("questions") or [])
        base_xp = 40 if is_mid else 20
        label(footer, f"{q_cnt}문제  ·  약 {lesson.get('minutes', 4)}분  ·  완료하면 +{base_xp} XP", 9, MUTED).pack(side="left")
        start = button(footer, "문제 풀기 (Ctrl+Enter)  →", self.next_question, pill=True, padx=px(18), pady=px(7))
        start.pack(side="right")
        self.controls["check"] = start

    def _answer_output(self, body, question, locked):
        """The exam's own format: read the program, work out the result by hand and write it down."""
        label(body, "실행 결과 쓰기 (줄바꿈·띄어쓰기·따옴표까지 그대로)", 9, MUTED, True).pack(anchor="w", pady=px((2, 4)))
        shell = RoundedFrame(body, bg=WHITE, padx=12, pady=8, border=LINE, radius=11)
        shell.pack(fill="x")
        box = tk.Text(shell, height=6, wrap="none", bg=WHITE, fg=INK, insertbackground=INK, font=(CODE_FONT, 11),
                      relief="flat", bd=0, padx=0, pady=0, spacing1=2, spacing3=2, highlightthickness=0, undo=True)
        box.pack(fill="x")
        box.insert("1.0", self.session["typed"])
        box.bind("<KeyRelease>", self._sync_output_answer)
        box.bind("<<Paste>>", lambda _e: self.after_idle(self._sync_output_answer))
        for sequence in ("<Control-Return>", "<Control-KP_Enter>"):
            box.bind(sequence, self._handle_ctrl_enter)
        self.controls["output_box"] = box
        if locked:
            box.configure(state="disabled")
        else:
            self.after_idle(lambda: box.winfo_exists() and box.focus_set())

    def _sync_output_answer(self, _=None):
        session = self.session
        box = self.controls.get("output_box")
        if not session or not box or not box.winfo_exists():
            return
        session["typed"] = box.get("1.0", "end-1c")
        if not session["feedback"].get("correct"):
            self._update_check_button(bool(session["typed"].strip()))

    def _answer_choices(self, body, question, locked):
        self.controls["choices"] = {}
        wrap_w = px(510 if self.lesson_two_cols else 680)
        for index, option in enumerate(self.session.get("options") or question["options"]):
            item = button(
                body,
                option,
                lambda answer=option: self.choose(answer),
                "ghost",
                badge=str(index + 1),
                anchor="w",
                radius=12,
                padx=px(12),
                pady=px(9),
                font=(FONT, 9, "bold"),
                wraplength=wrap_w,
            )
            item.pack(fill="x", pady=px(3))
            self.controls["choices"][option] = item
        self._sync_choice_buttons(locked)
        label(body, "숫자 키 1–4로 선택   ·   Ctrl + Enter로 정답 확인 및 다음으로", 9, MUTED).pack(anchor="w", pady=px((5, 0)))

    def _sync_choice_buttons(self, locked=False):
        session = self.session
        choices = self.controls.get("choices") or {}
        if not session or not choices:
            return
        fb_correct = session.get("feedback", {}).get("correct")
        state_val = "disabled" if locked else "normal"
        for option, item in choices.items():
            if not item.winfo_exists():
                continue
            chosen = session["selected"] == option
            wrong_checked = chosen and (fb_correct is False)
            dis_fg = GREEN if chosen else MUTED
            if wrong_checked:
                item.configure(
                    kind="ghost",
                    bg="#fdf2ef",
                    highlightbackground="#b85c50",
                    highlightthickness=px(2),
                    disabledbackground="#fdf2ef",
                    disabledforeground=dis_fg,
                    state=state_val,
                )
            elif chosen:
                item.configure(
                    kind="secondary",
                    bg=PALE,
                    highlightbackground=GREEN,
                    highlightthickness=px(2),
                    disabledbackground=PALE,
                    disabledforeground=dis_fg,
                    state=state_val,
                )
            else:
                item.configure(
                    kind="ghost",
                    bg=WHITE,
                    highlightbackground="#d7e3dc",
                    highlightthickness=1,
                    disabledbackground="#f4f7f5",
                    disabledforeground=dis_fg,
                    state=state_val,
                )

    def _answer_order(self, body, question, locked):
        lang = self._lesson_lang(question, self.session.get("lesson"))
        meta = LANG_META[lang]
        tokens = question["tokens"]
        preview_box = code_block(body, f"{meta['comment']} 아래 조각을 눌러 코드를 만들어 보세요.", True, lang=lang)
        preview_box.pack(fill="x", pady=px((0, 8)))
        self.controls["order_preview"] = preview_box
        selection = tk.Frame(body, bg=BG)
        selection.pack(fill="x")
        self.controls["order_selection"] = selection
        label(body, "코드 조각  ·  선택한 조각을 다시 누르면 돌아가요.", 9, MUTED).pack(anchor="w", pady=px((10, 5)))
        tok_wrap = px(260 if self.lesson_two_cols else 320)
        max_row_w = 560 if self.lesson_two_cols else 700
        bank = tk.Frame(body, bg=BG)
        bank.pack(fill="x")
        bank_builders = [
            lambda row_p, idx=token_index: button(
                row_p,
                tokens[idx],
                lambda index=idx: self.add_token(index),
                "ghost",
                pill=True,
                padx=px(11),
                pady=px(5),
                font=(FONT, 9, "bold"),
                wraplength=tok_wrap,
            )
            for token_index in self.session["bank"]
        ]
        built_tokens = _pack_chip_flow(bank, bank_builders, gap_x=6, gap_y=5, max_width=max_row_w, bg=BG)
        self.controls["tokens"] = {
            token_index: built_tokens[pos] for pos, token_index in enumerate(self.session["bank"])
        }
        self._sync_order_ui(question, locked)

    def _sync_order_ui(self, question, locked=False):
        session = self.session
        if not session:
            return
        lang = self._lesson_lang(question, session.get("lesson"))
        meta = LANG_META[lang]
        tokens = question["tokens"]
        selected = session["order"]
        preview = question.get("separator", "").join(tokens[index] for index in selected)
        preview_box = self.controls.get("order_preview")
        if preview_box and preview_box.winfo_exists():
            preview_box.set_text(preview or f"{meta['comment']} 아래 조각을 눌러 코드를 만들어 보세요.", adjust_height=True)
        selection = self.controls.get("order_selection")
        if selection and selection.winfo_exists():
            for c in selection.winfo_children():
                c.destroy()
            if selected:
                tok_wrap = px(260 if self.lesson_two_cols else 320)
                max_row_w = 560 if self.lesson_two_cols else 700
                sel_builders = []
                for position, token_index in enumerate(selected):
                    def make_sel(row_p, pos=position, txt=tokens[token_index] + "  ×"):
                        it = button(row_p, txt, lambda place=pos: self.remove_token(place),
                                    "secondary", pill=True, padx=px(11), pady=px(5), font=(FONT, 9, "bold"), wraplength=tok_wrap)
                        if locked:
                            it.configure(state="disabled")
                        return it
                    sel_builders.append(make_sel)
                _pack_chip_flow(selection, sel_builders, gap_x=6, gap_y=5, max_width=max_row_w, bg=BG)
            else:
                label(selection, "아래 코드 조각을 눌러 순서대로 조립하세요.", 8, MUTED).pack(anchor="w", pady=px(5))
        for idx, btn in (self.controls.get("tokens") or {}).items():
            if btn.winfo_exists():
                btn.configure(state="disabled" if (locked or idx in selected) else "normal")

    @staticmethod
    def _rust_sample_value(value, mode="auto", as_arg=True):
        if mode == "mut_string":
            return f"&mut String::from({json.dumps(str(value), ensure_ascii=False)})"
        if mode == "empty_i32_slice":
            return "&[]"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, str):
            return json.dumps(value, ensure_ascii=False)
        if isinstance(value, list):
            inner = ", ".join(CodeStepApp._rust_sample_value(v, as_arg=False) for v in value)
            return f"&[{inner}]" if as_arg else f"[{inner}]"
        return str(value)

    @staticmethod
    def _format_check_sample(item, lang="python"):
        if lang == "rust":
            modes = item.get("argModes") or []
            parts = [
                CodeStepApp._rust_sample_value(arg, modes[idx] if idx < len(modes) else "auto", as_arg=True)
                for idx, arg in enumerate(item.get("args", []))
            ]
            call_txt = f"{item['name']}({', '.join(parts)})"
            expected_txt = item.get("expectedDebug") or CodeStepApp._rust_sample_value(item.get("expected"), as_arg=False)
            return f"{call_txt}  ->  {expected_txt}"
        kwargs = item.get("kwargs") or {}
        if item.get("className"):
            init_txt = ", ".join(repr(a) for a in item.get("initArgs", []))
            m_parts = [repr(a) for a in item.get("methodArgs", [])]
            m_parts.extend(f"{k}={v!r}" for k, v in kwargs.items())
            call_txt = f"{item['className']}({init_txt}).{item.get('method', '')}({', '.join(m_parts)})"
        else:
            parts = [repr(a) for a in item.get("args", [])]
            parts.extend(f"{k}={v!r}" for k, v in kwargs.items())
            call_txt = f"{item['name']}({', '.join(parts)})"
            if item.get("isGenerator"):
                call_txt = f"list({call_txt})"
        return f"{call_txt}  ->  {item.get('expected')!r}"

    def _answer_code(self, body, question, locked, terminal_parent):
        session = self.session
        lang = self._lesson_lang(question, session.get("lesson"))
        meta = LANG_META[lang]
        wrap_w = px(540 if self.lesson_two_cols else 720)
        target = card(body, padding=11, radius=13)
        target.pack(fill="x", pady=px((0, 8)))
        label(target, "목표 출력 및 실기 조건", 9, GREEN, True).pack(anchor="w")
        if question.get("expected"):
            code_block(target, question["expected"].rstrip("\n"), height=min(4, max(1, len(question["expected"].splitlines())))).pack(fill="x", pady=px((5, 0)))
        hints = []
        raw_stdin = (question.get("stdin") or "").rstrip("\n")
        multiline_stdin = bool(raw_stdin and "\n" in raw_stdin)
        if raw_stdin and not multiline_stdin:
            hints.append(f"준비된 입력값(stdin): {raw_stdin}")
        if question.get("fixtures"):
            hints.append("준비된 입력 파일: " + ", ".join(question["fixtures"].keys()))
        if question.get("functionChecks"):
            names = sorted({(item["className"] + "." + item.get("method", "") + "()" if item.get("className") else item["name"] + "()") for item in question["functionChecks"]})
            hints.append("자동 함수 검사: " + ", ".join(names))
        if question.get("fileChecks"):
            files = [item["path"] for item in question["fileChecks"]]
            hints.append("생성할 결과 파일: " + ", ".join(files))
        if hints:
            fit_wrap(label(target, "   ·   ".join(hints), 9, MUTED, wraplength=wrap_w)).pack(anchor="w", pady=px((5, 0)))
        if multiline_stdin:
            label(target, "준비된 표준 입력(stdin) · 한 줄씩 차례로 전달", 8, meta["accent"], True).pack(anchor="w", pady=px((5, 2)))
            code_block(target, raw_stdin, height=min(4, max(1, len(raw_stdin.splitlines())))).pack(fill="x")
        if question.get("functionChecks"):
            samples_txt = "\n".join(self._format_check_sample(item, lang=lang) for item in question["functionChecks"][:2])
            label(target, "함수 입출력 예시 (다른 입력값도 함께 검사해요)", 8, meta["accent"], True).pack(anchor="w", pady=px((5, 2)))
            code_block(target, samples_txt, height=min(3, len(question["functionChecks"][:2])), lang=lang).pack(fill="x")
        if question.get("fixtures"):
            for fname, fcontent in question["fixtures"].items():
                preview = fcontent.rstrip("\n")
                label(target, f"입력 파일 미리보기 · {fname}", 8, meta["accent"], True).pack(anchor="w", pady=px((5, 2)))
                code_block(target, preview, height=min(5, max(1, len(preview.splitlines())))).pack(fill="x")

        shell = create_code_shell(body, f"{meta['filename']}  ·  내 정답 코드")
        shell.pack(fill="x")
        self.lesson_editor = CodeEditor(shell, session["code"], self._lesson_code_changed, self._handle_ctrl_enter, height=9, lang=lang, bordered=False)
        self.lesson_editor.pack(fill="x")
        if locked:
            self.lesson_editor.text.configure(state="disabled")
        fit_wrap(label(body, f"외부 편집기(VS Code 등) 저장도 자동 인식   ·   Tab 들여쓰기   ·   Ctrl+Enter 채점 / 정답 시 다음으로", 8, MUTED, wraplength=wrap_w)).pack(anchor="w", pady=px((5, 0)))

        self.lesson_result_frame = tk.Frame(terminal_parent, bg=BG)
        self.lesson_result_frame.pack(fill="x")
        deliverables = scan_deliverables(session["taskDir"], script_name=meta["filename"], fixtures=question.get("fixtures"))
        self._render_lesson_result_area(external_deliverables=deliverables)

        bridge_wrap = tk.Frame(terminal_parent, bg=BG)
        bridge_wrap.pack(fill="x", pady=px((8, 0)))
        self.lesson_sync_label = self._build_external_bridge_bar(
            bridge_wrap, session["scriptPath"], session["taskDir"], on_reset=self._reset_lesson_file, lang=lang
        )
        if session.get("syncStatus") and self.lesson_sync_label:
            self.lesson_sync_label.configure(text=session["syncStatus"])

    def _render_lesson_result_area(self, external_deliverables=None):
        if not self.lesson_result_frame or not self.lesson_result_frame.winfo_exists():
            return
        for child in self.lesson_result_frame.winfo_children():
            child.destroy()
        session = self.session
        if not session:
            return
        question = self.current_question()
        lang = self._lesson_lang(question, session.get("lesson"))
        meta = LANG_META[lang]
        result = session.get("result")
        ver_str = self.rust_runtime.get("version") or "rustc" if lang == "rust" else self.runtime.get("version") or sys.version.split()[0]
        cmd_line = f"rustc --edition 2021 {meta['filename']} && main.exe\n" if lang == "rust" else "python -X utf8 main.py\n"
        if result:
            mode_map = {"rustc": "로컬 rustc", "missing-rustc": "rustc 미설치", "system": "시스템 Python"}
            mode_label = mode_map.get(result.get("runtimeMode"), "내장 Python")
            term_title = f"실행 터미널 · {mode_label} ({result.get('elapsed', 0)} ms)"
            term_entries = [
                ("dim", f"{meta['name']} {ver_str} · {session['taskDir']}\n"),
                ("prompt", "PS> "),
                ("cmd", cmd_line),
            ]
            if result.get("output"):
                out = result["output"]
                if not out.endswith("\n"):
                    out += "\n"
                term_entries.append(("stdout", out))
            if result.get("error") and not result.get("ok"):
                err = result["error"]
                if not err.endswith("\n"):
                    err += "\n"
                term_entries.append(("stderr", err))
            if not result.get("output") and (result.get("ok") or not result.get("error")):
                term_entries.append(("dim", "(출력 없음)\n"))
            status_tag = "ok" if result.get("ok") else "stderr"
            status_text = "정상 종료" if result.get("ok") else "오류 종료"
            term_entries.append((status_tag, f"[{status_text} · {result.get('elapsed', 0)} ms]\n"))
        else:
            rt_label = self.rust_runtime["label"] if lang == "rust" else self.runtime["label"]
            term_title = f"{meta['name']} {ver_str} · 실제 터미널 (대기 중)"
            term_entries = [
                ("dim", f"{meta['name']} {ver_str} ({rt_label})\n"),
                ("dim", f"작업 폴더: {session['taskDir']}\n\n"),
                ("prompt", "PS> "),
                ("cmd", cmd_line),
                ("dim", f"왼쪽에서 코드를 작성하거나 외부 편집기에서 저장한 뒤\n'실행하고 채점 (Ctrl+Enter)'을 누르면 실행 결과가 여기에 출력돼요.\n"),
            ]
        line_count = sum(text.count("\n") for _, text in term_entries) + 1
        shell, _ = create_terminal_box(
            self.lesson_result_frame,
            term_title,
            term_entries,
            height=max(6, min(11, line_count)),
        )
        shell.pack(fill="x")

        deliverables = result.get("deliverables") if result and result.get("deliverables") is not None else external_deliverables
        if deliverables:
            deliv_box = card(self.lesson_result_frame, WHITE, 10)
            deliv_box.pack(fill="x", pady=px((7, 0)))
            label(deliv_box, "인식된 작업 폴더 파일 (실기 결과물)", 9, INK, True).pack(anchor="w", pady=px((0, 3)))
            self._render_deliverable_list(deliv_box, deliverables)

    def _reset_lesson_file(self):
        session = self.session
        if not session or session["running"] or session["feedback"].get("correct"):
            return
        question = self.current_question()
        lang = self._lesson_lang(question, session.get("lesson"))
        fname = LANG_META[lang]["filename"]
        if not messagebox.askyesno("파일 초기화", f"현재 실습 파일({fname})과 입력 파일을 처음 코드로 되돌릴까요?", parent=self):
            return
        _, _, code = self.workspace.prepare_workspace(
            session["taskDir"], fname, question.get("starter", ""),
            fixtures=question.get("fixtures"), reset_code=True,
        )
        session["code"] = code
        session["result"] = None
        if self.lesson_editor and self.lesson_editor.winfo_exists():
            self.lesson_editor.set_silent(code)
        self._activate_watch("lesson", session["taskDir"], session["scriptPath"], fixtures=question.get("fixtures"), question=question)
        self._render_lesson_result_area(external_deliverables=scan_deliverables(session["taskDir"], fname, question.get("fixtures")))
        self.toast("실습 파일을 초기 코드로 되돌렸어요.")

    def _lesson_code_changed(self, value):
        if self.session and self.session.get("scriptPath"):
            self.session["code"] = value
            self._schedule_disk_sync(self.session["scriptPath"], value, update_draft=False)

    def _sync_fill_snippet(self, question):
        fill_info = self.controls.get("fill_code")
        if not fill_info or question.get("type") != "fill":
            return
        fill_box, raw_code = fill_info
        if fill_box.winfo_exists():
            sel = self.session["selected"]
            snippet = raw_code.replace("___", str(sel)) if sel is not None else raw_code
            fill_box.set_text(snippet)

    def choose(self, answer):
        session = self.session
        if not session or session["running"] or session["feedback"].get("correct"):
            return
        question = self.current_question()
        if answer not in question.get("options", []):
            return
        session["selected"] = answer
        if session["feedback"] and not session["feedback"].get("correct"):
            session["feedback"] = {}
            self._render_lesson_hint_and_feedback(question)
        self._sync_fill_snippet(question)
        self._sync_choice_buttons(locked=False)
        self._update_check_button(True)

    def _after_order_changed(self):
        session = self.session
        question = self.current_question()
        if session["feedback"] and not session["feedback"].get("correct"):
            session["feedback"] = {}
            self._render_lesson_hint_and_feedback(question)
        self._sync_order_ui(question, locked=False)
        self._update_check_button(len(session["order"]) == len(question["tokens"]))

    def add_token(self, index):
        session = self.session
        if not session or session["running"] or session["feedback"].get("correct") or index in session["order"]:
            return
        session["order"].append(index)
        self._after_order_changed()

    def remove_token(self, position):
        session = self.session
        if not session or session["running"] or session["feedback"].get("correct"):
            return
        session["order"].pop(position)
        self._after_order_changed()

    def toggle_hint(self):
        self.session["hint"] = not self.session["hint"]
        if self.lesson_hint_frame:
            self._render_lesson_hint_and_feedback(self.current_question())

    def toggle_concept(self):
        self.session["conceptOpen"] = not self.session.get("conceptOpen")
        self._render_lesson_hint_and_feedback(self.current_question())

    def _select_lesson_example(self, index, target="ref"):
        if not self.session:
            return
        self.session["exampleIdx"] = index
        if target == "concept" or self.session.get("index", 0) < 0:
            self._render_concept_examples()
            return
        question = self.current_question()
        if target == "code":
            self._render_lesson_hint_and_feedback(question)
        else:
            self._render_lesson_reference_pane(question)

    def reveal_solution(self):
        self.session["revealed"] = True
        if self.lesson_hint_frame:
            self._render_lesson_hint_and_feedback(self.current_question())

    def _run_lesson_verification(self, isolated=False, explicit=True):
        session = self.session
        if not session or session["done"] or session["index"] < 0 or session["running"] or session["feedback"].get("correct"):
            return
        question = self.current_question()
        if self.lesson_editor and self.lesson_editor.winfo_exists():
            session["code"] = self.lesson_editor.get()
            if not isolated:
                self._flush_disk_sync(session["scriptPath"], session["code"], update_draft=False)
        session["running"] = True
        self._update_check_button(True)
        task_dir = session["taskDir"]
        script_path = session["scriptPath"]
        expected_index = session["index"]
        lang = self._lesson_lang(question, session.get("lesson"))
        custom_rust = self.progress["settings"].get("rustPath", "")
        runtime = dict(self.rust_runtime if lang == "rust" else self.runtime)

        def work():
            rt = runtime
            if lang == "rust" and not rt.get("available"):
                rt = discover_rust_runtime(custom_rust, refresh=True)
            res = verify_workspace_question(task_dir, script_path, question, rt, isolated=isolated)
            if lang == "rust":
                res["_discoveredRuntime"] = rt
            return res

        def finished(result):
            discovered = result.pop("_discoveredRuntime", None) if isinstance(result, dict) else None
            if discovered and discovered.get("available") and not self.rust_runtime.get("available"):
                self.rust_runtime = discovered
                self._refresh_runtime_badge()
            if self.session is not session or session["index"] != expected_index:
                return
            session["running"] = False
            session["result"] = result
            passed = bool(result.get("passed"))
            if passed:
                session["syncStatus"] = "✓ 외부/실습 코드 및 실기 결과물 인식 완료!"
                if self.lesson_sync_label and self.lesson_sync_label.winfo_exists():
                    self.lesson_sync_label.configure(text=session["syncStatus"])
                self._render_lesson_result_area()
                self.grade_answer(True, result.get("summary") or question["explanation"])
                return
            if explicit:
                self._render_lesson_result_area()
                if result.get("missingCompiler"):
                    session["syncStatus"] = "⚠ rustc 미설치 — [준비] 탭에서 설치 후 다시 확인해 주세요 (하트 차감 없음)"
                    session["feedback"] = {
                        "correct": False,
                        "missingCompiler": True,
                        "message": result.get("summary") or "PC에 rustc.exe가 아직 없어 컴파일을 건너뛰었어요. 하트와 오답 기록에는 반영되지 않아요.",
                    }
                    if self.lesson_sync_label and self.lesson_sync_label.winfo_exists():
                        self.lesson_sync_label.configure(text=session["syncStatus"])
                    self._render_lesson_hint_and_feedback(question)
                    self._sync_review_skip_button()
                    self._update_check_button(True)
                    return
                message = result.get("summary") or "실행 결과를 다시 확인해 주세요."
                lesson = session.get("lesson") or LESSON_BY_ID.get(question.get("lessonId"))
                pitfall = self._matching_pitfall(lesson, result.get("error"))
                if pitfall:
                    message += (f"\n\n도움말: 이 레슨의 '자주 하는 실수 · {pitfall['title']}'과 같은 실수예요. "
                                "'▤ 개념·예제 다시 보기'를 누르면 고치는 법을 바로 볼 수 있어요.")
                self.grade_answer(False, message)
            else:
                session["feedback"] = {}
                session["syncStatus"] = "● 저장 감지됨 — 아직 조건을 모두 만족하지 않았어요 (하트 차감 없음)"
                if self.lesson_sync_label and self.lesson_sync_label.winfo_exists():
                    self.lesson_sync_label.configure(text=session["syncStatus"])
                self._render_lesson_result_area()
                self._render_lesson_hint_and_feedback(question)
                self._update_check_button(True)

        self.submit_task(work, finished)

    def check_answer(self):
        session = self.session
        if not session or session["done"] or session["index"] < 0 or session["running"] or session["feedback"].get("correct"):
            return
        question = self.current_question()
        if question["type"] == "code":
            self._run_lesson_verification(isolated=False, explicit=True)
            return
        if question["type"] == "order":
            if len(session["order"]) != len(question["tokens"]):
                return
            correct = [question["tokens"][index] for index in session["order"]] == question["answer"]
        elif question["type"] == "output":
            self._sync_output_answer()
            if not session["typed"].strip():
                return
            line = compare_written_output(session["typed"], question["answer"])
            if line is not None:
                self.grade_answer(False, f"{line}번째 줄이 달라요. 변수 값을 종이에 적으면서 코드를 한 줄씩 다시 따라가 보세요. "
                                         "리스트의 대괄호, 문자열의 따옴표, 값 사이의 띄어쓰기도 실제 출력과 똑같아야 해요.")
                return
            correct = True
        else:
            if session["selected"] is None:
                return
            correct = session["selected"] == question["answer"]
        msg = (
            question["explanation"]
            if correct
            else "아쉬워요! 위 '◉ 힌트 보기' 또는 '▤ 개념·예제 다시 보기'를 참고해 다시 골라 보세요."
        )
        self.grade_answer(correct, msg)

    def grade_answer(self, correct, message):
        session = self.session
        question = self.current_question()
        question_id = question["id"]
        if correct:
            if question_id not in session["resolved"]:
                session["resolved"].add(question_id)
                if session["mode"] == "review" and question_id in self.progress["mistakes"]:
                    del self.progress["mistakes"][question_id]
                    self.progress["reviewCount"] += 1
                    add_activity(self.progress, 3, "reviews")
                    session["earned"] += 3
                    self.save()
        else:
            session["missed"].add(question_id)
            if session["mode"] == "lesson":
                session["hearts"] = max(0, session["hearts"] - 1)
            previous = self.progress["mistakes"].get(question_id, {})
            self.progress["mistakes"][question_id] = {"count": previous.get("count", 0) + 1, "date": date.today().isoformat()}
            self.save()
        session["feedback"] = {"correct": correct, "message": message}
        self.play_sound(correct)
        if question["type"] == "code":
            if correct and self.lesson_editor and self.lesson_editor.winfo_exists():
                self.lesson_editor.text.configure(state="disabled")
        elif question["type"] == "order":
            self._sync_order_ui(question, locked=bool(correct))
        elif question["type"] == "output":
            box = self.controls.get("output_box")
            if correct and box and box.winfo_exists():
                box.configure(state="disabled")
        else:
            self._sync_choice_buttons(locked=bool(correct))
        if session["mode"] == "lesson" and self.controls.get("hearts") and self.controls["hearts"].winfo_exists():
            hearts = ("♥ " * session["hearts"]).strip() or "∞  자유 연습"
            self.controls["hearts"].configure(text=hearts)
        self._render_lesson_hint_and_feedback(question)
        self._sync_review_skip_button()
        self._update_check_button(True)

    def next_question(self):
        session = self.session
        if not session or session["done"] or (session["index"] >= 0 and not session["feedback"].get("correct")):
            return
        self._cancel_sync_write()
        session["index"] += 1
        if session["index"] == len(session["queue"]):
            session["done"] = True
            session["accuracy"] = round(100 * (len(session["queue"]) - len(session["missed"])) / len(session["queue"]))
            session["seconds"] = max(1, round(time.monotonic() - session["started"]))
            if session["mode"] == "lesson":
                session["earned"] += finish_lesson(self.progress, session["lesson"]["id"], session["accuracy"])
                target_lang = session["lesson"].get("lang", self.lang_filter)
                self.expanded = {next_lesson(self.progress, target_lang)["unitId"]}
                self.save()
        else:
            self.initialize_question()
        self.render_lesson()

    def _completion_page(self, body, footer):
        session = self.session
        mascot = tk.Canvas(body, width=px(184), height=px(144), bg=BG, highlightthickness=0, bd=0)
        mascot.pack(pady=px((0, 6)))
        draw_mascot(mascot, scale=0.72)
        label(body, "오늘도 한 걸음 성장했어요!", 19, INK, True, anchor="center").pack(fill="x")
        label(body, "다시 풀어 보니 더 단단해졌어요." if session["mode"] == "review" else "작은 한 걸음이 쌓여 실력이 돼요.", 10, MUTED, anchor="center").pack(fill="x", pady=px((6, 14)))
        stats = tk.Frame(body, bg=BG)
        stats.pack(fill="x")
        for index, (value, name) in enumerate([(f"+{session['earned']} XP", "획득 경험치"), (f"{session['accuracy']}%", "첫 시도 정답률"), (f"{session['seconds'] // 60:02d}:{session['seconds'] % 60:02d}", "학습 시간")]):
            stats.columnconfigure(index, weight=1, uniform="comp_stat")
            box = card(stats, padding=15, radius=14)
            box.grid(row=0, column=index, sticky="ew", padx=px(5))
            label(box, value, 18, GREEN, True, anchor="center").pack(fill="x")
            label(box, name, 9, MUTED, anchor="center").pack(fill="x", pady=px((4, 0)))
        new_badges = [name for name, _, _, unlocked in badges(self.progress) if unlocked and name not in session["initialBadges"]]
        if new_badges:
            label(body, "☆  새 배지: " + ", ".join(new_badges), 10, GREEN, True, anchor="center", wraplength=px(700)).pack(fill="x", pady=px((12, 0)))
        if session["missed"] and session["mode"] == "lesson":
            label(body, f"틀렸던 {len(session['missed'])}문제는 오답 노트에서 다시 만나요.", 9, MUTED, anchor="center").pack(fill="x", pady=px((10, 0)))
        label(footer, f"연속 {streak(self.progress)}일 학습  ·  오늘 {activity_today(self.progress)['xp']} XP", 9, GREEN, True).pack(side="left")
        done = button(footer, "학습 여정으로 (Ctrl+Enter)  →", self.close_lesson, pill=True, padx=px(18), pady=px(7))
        done.pack(side="right")
        self.controls["check"] = done

    def request_exit_lesson(self):
        if self.session["done"] or self.session["index"] < 0 or messagebox.askyesno("레슨 닫기", "이번 레슨을 나갈까요?\n이미 기록된 오답과 복습 경험치는 유지돼요.", parent=self):
            self.close_lesson()

    def _flush_pending_lesson_code(self):
        """Write code typed in the last moment before leaving, instead of dropping the delayed save."""
        session = self.session
        if (self.sync_write_job and session and session.get("scriptPath")
                and self.lesson_editor and self.lesson_editor.winfo_exists()):
            self._flush_disk_sync(session["scriptPath"], self.lesson_editor.get(), update_draft=False)

    def close_lesson(self):
        self._flush_pending_lesson_code()
        self._cancel_sync_write()
        self.watch_state = None
        self.session = None
        if self.lesson_overlay:
            self.lesson_overlay.destroy()
        self.lesson_overlay = None
        self.lesson_editor = None
        self.lesson_result_frame = None
        self.lesson_feedback_frame = None
        self.lesson_sync_label = None
        self.lesson_hint_frame = None
        self.lesson_concept_ex_frame = None
        self.lesson_scroll = None
        self.navigate(self.route)

    def submit_task(self, fn, callback):
        self.task_id += 1
        task_id = self.task_id

        def execute():
            try:
                result = fn()
            except Exception:
                result = {"ok": False, "passed": False, "output": "", "error": "코드를 실행하지 못했어요. 다시 시도해 주세요."}
            self.results.put((task_id, result))

        thread = threading.Thread(target=execute, daemon=False)
        self.tasks[task_id] = (thread, callback)
        thread.start()

    def _poll_results(self):
        while True:
            try:
                task_id, result = self.results.get_nowait()
            except queue.Empty:
                break
            item = self.tasks.pop(task_id, None)
            if item and not self.closing:
                item[1](result)
        if self.closing and not self.tasks:
            self.destroy()
            return
        self.poll_job = self.after(80, self._poll_results)

    def play_sound(self, correct):
        if self.progress["settings"]["sound"]:
            try:
                import winsound
                # winsound cannot play from memory asynchronously (it raises RuntimeError), so the
                # chime is played from a small file. Async keeps the window responsive.
                winsound.PlaySound(str(_chime_file(correct, self.store.folder)),
                                   winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
            except (ImportError, RuntimeError, OSError):
                pass

    def _resolve_assets_dir(self):
        candidates = []
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "assets")
        candidates.append(Path(__file__).resolve().parent / "assets")
        return next((path for path in candidates if path.is_dir()), candidates[-1])

    def _apply_window_icons(self):
        assets_dir = self._resolve_assets_dir()
        icon_file = assets_dir / "codestep.ico"
        if icon_file.exists():
            try:
                self.iconbitmap(default=str(icon_file))
            except tk.TclError:
                self.iconbitmap(str(icon_file))
        photos = []
        for size in (256, 64, 48, 32):
            png_path = assets_dir / f"codestep_{size}.png"
            if png_path.exists():
                try:
                    photos.append(tk.PhotoImage(master=self, file=str(png_path)))
                except tk.TclError:
                    pass
        if photos:
            self._icon_photos = photos
            try:
                self.iconphoto(True, *photos)
            except tk.TclError:
                pass
        self._sync_win32_taskbar_icons()

    def _sync_win32_taskbar_icons(self):
        if sys.platform != "win32":
            return
        icon_file = self._resolve_assets_dir() / "codestep.ico"
        if not icon_file.exists():
            return
        try:
            import ctypes
            import ctypes.wintypes as wintypes

            shell32 = ctypes.windll.shell32
            user32 = ctypes.windll.user32
            try:
                shell32.SetCurrentProcessExplicitAppUserModelID("CodeStep.Desktop.3")
            except (AttributeError, OSError):
                pass
            self.update_idletasks()
            wm_frame = self.wm_frame()
            hwnd = int(wm_frame, 16) if wm_frame and wm_frame != "0x0" else self.winfo_id()
            if not hwnd:
                return

            user32.LoadImageW.restype = wintypes.HANDLE
            user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
                                          ctypes.c_int, ctypes.c_int, wintypes.UINT]
            user32.DestroyIcon.argtypes = [wintypes.HICON]
            user32.SendMessageW.restype = ctypes.c_void_p
            user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, ctypes.c_void_p]
            set_class_ptr = getattr(user32, "SetClassLongPtrW", user32.SetClassLongW)
            set_class_ptr.restype = ctypes.c_void_p
            set_class_ptr.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]

            sm_cx, sm_cy = max(16, user32.GetSystemMetrics(49)), max(16, user32.GetSystemMetrics(50))
            bg_cx, bg_cy = max(32, user32.GetSystemMetrics(11)), max(32, user32.GetSystemMetrics(12))
            if self._win_hicons and getattr(self, "_win_icon_hwnd", None) == hwnd:
                h_small, h_big = self._win_hicons
            else:
                h_small = user32.LoadImageW(None, str(icon_file), 1, sm_cx, sm_cy, 0x0010)
                h_big = user32.LoadImageW(None, str(icon_file), 1, bg_cx, bg_cy, 0x0010)
                if not h_small or not h_big:
                    return
                for old in self._win_hicons:
                    user32.DestroyIcon(old)
                self._win_hicons = [h_small, h_big]
                self._win_icon_hwnd = hwnd

            user32.SendMessageW(hwnd, 0x0080, 0, h_small)  # WM_SETICON ICON_SMALL
            user32.SendMessageW(hwnd, 0x0080, 1, h_big)    # WM_SETICON ICON_BIG
            set_class_ptr(hwnd, -34, h_small)              # GCLP_HICONSM
            set_class_ptr(hwnd, -14, h_big)                # GCLP_HICON
        except (AttributeError, OSError, tk.TclError, ValueError):
            pass

    def close(self):
        self._flush_pending_lesson_code()
        self._capture_draft()
        self.save()
        self.closing = True
        for job in (self.watch_job, self.resize_job, self.sync_write_job, self.draft_job):
            if job:
                try:
                    self.after_cancel(job)
                except tk.TclError:
                    pass
        if self.tasks:
            self.withdraw()
        else:
            self.destroy()

    def destroy(self):
        if sys.platform == "win32" and getattr(self, "_win_hicons", None):
            try:
                import ctypes
                import ctypes.wintypes as wintypes

                user32 = ctypes.windll.user32
                user32.DestroyIcon.argtypes = [wintypes.HICON]
                for handle in self._win_hicons:
                    user32.DestroyIcon(handle)
                self._win_hicons = []
            except (AttributeError, OSError):
                pass
        super().destroy()


PyStepApp = CodeStepApp
