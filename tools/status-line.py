#!/usr/bin/env python3
"""Claude Code status line — modular Python port of statusline.sh.

Reads the status JSON on stdin and prints up to three ANSI-colored lines.
Layout is driven by SEGMENTS (on/off), LAYOUT (template), and BUILDERS
(key -> builder(data, avail)). The packer is the authority on show/hide;
builders auto-deprioritize to fit. See the "HOW TO CUSTOMIZE" block near the
bottom. Stdlib only. The .sh original is kept as a fallback.
"""

import json
import math
import os
import re
import subprocess
import sys
import time
import unicodedata
from collections import namedtuple
from datetime import datetime

# ═══ CONFIG — edit freely ════════════════════════════════════════════════════
# Per-segment on/off. Set False to hide a segment entirely (its builder is then
# never called). Invariant: keep "path" True so the identity line always emits.
SEGMENTS = {
    # identity line
    "path": True, "branch": True, "dirty": True, "todo": True,
    # model row
    "model": True, "time_ago": True, "clock": True, "effort": True,
    "lines": True, "cost": False, "total_time": True, "api_time": True,
    # diagnostics row
    "dimensions": True, "context": True, "chat_size": True,
    "memory": True, "rate_limits": True,
}

# Identity-line tuning.
PATH_MAX_LEN = 20       # ~-collapsed path longer than this collapses to its basename
CONTEXT_BAR_CELLS = 10  # context bar width; ▌ half-cells give 5% resolution

# Packing: reserve a few cols so emoji-width miscounts don't wrap the line.
RIGHT_MARGIN = 4
SEP = " | "

# ═══ Palette ════════════════════════════════════════════════════════════════
RESET = "\033[0m"
GREY = "\033[90m"
BG_LIGHTGRAY = "\033[47m"
WHITE = "\033[1;97m"
CYAN = "\033[1;36m"
GREEN = "\033[1;32m"
ORANGE = "\033[38;5;208m"
RED = "\033[1;31m"
YELLOW = "\033[1;33m"
MAGENTA = "\033[1;35m"
BLUE = "\033[1;34m"

# Bold variants for the high-severity context bands (orange and up). Kept
# separate so the base colors stay reusable elsewhere without forcing bold
# (e.g. effort xhigh uses plain ORANGE).
ORANGE_BOLD = "\033[1;38;5;208m"
MAGENTA_DARK_BOLD = "\033[1;38;5;90m"  # dark/gothic — top context band (>=50%)

# ═══ Color ramps (ceil, color) — first ceil the pct is below wins ════════════
INF = float("inf")
CONTEXT_RAMP = [
    (10, WHITE), (15, CYAN), (20, BLUE), (25, GREEN),
    (30, YELLOW), (40, ORANGE_BOLD), (50, RED), (INF, MAGENTA_DARK_BOLD),
]
RATE_RAMP = [(50, GREEN), (80, YELLOW), (INF, RED)]


def pick_color(pct, ramp):
    """Return the color for the first ceil that pct is strictly below."""
    for ceil, color in ramp:
        if pct < ceil:
            return color
    return ramp[-1][1]


# ═══ Display width ═══════════════════════════════════════════════════════════
_ANSI_RE = re.compile(r"\033\[[0-9;]*m")
# BMP symbols we render that terminals draw 2 cells wide (east_asian_width
# misclassifies these as narrow). Add a codepoint here if a new wide BMP glyph
# is introduced in a segment.
_WIDE_BMP = {0x23F0, 0x23F8, 0x26A1}  # ⏰ ⏸ ⚡


def char_width(ch):
    """Display cells for one char: 0 (combining/zero-width), 1, or 2 (wide)."""
    if unicodedata.combining(ch):
        return 0
    o = ord(ch)
    if o >= 0x1F300:                                  # emoji / pictographs (SMP)
        return 2
    if o in _WIDE_BMP:
        return 2
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 2
    return 1


def visible_width(s):
    """Terminal display width of s, ignoring ANSI SGR escapes."""
    return sum(char_width(c) for c in _ANSI_RE.sub("", s))


def _first_fitting(variants, avail):
    """Return the first (richest) truthy variant whose display width fits avail.

    None if none fit. Builders pass their variants rich-first so the widest
    affordable detail level wins; returning None is a builder self-hiding."""
    for v in variants:
        if v and visible_width(v) <= avail:
            return v
    return None


# ═══ Formatters ══════════════════════════════════════════════════════════════
def fmt_number(n):
    """Thousands separators: 1234567 -> '1,234,567'."""
    return f"{int(n):,}"


def fmt_time_ms(ms):
    """Human-readable duration from milliseconds (matches statusline.sh)."""
    ms = int(ms)
    if ms < 1000:
        return f"{ms}ms"
    if ms < 60_000:
        return f"{ms // 1000}s"
    if ms < 3_600_000:
        return f"{ms // 60_000}m {(ms % 60_000) // 1000}s"
    return f"{ms // 3_600_000}h {(ms % 3_600_000) // 60_000}m"


def fmt_tokens(n):
    """200000 -> '200K', 1000000 -> '1M'."""
    n = int(n)
    if n >= 1_000_000:
        return f"{n // 1_000_000}M"
    if n >= 1000:
        return f"{n // 1000}K"
    return str(n)


def fmt_ago(secs):
    """Seconds since last activity as an 'ago' string."""
    secs = int(secs)
    if secs <= 0:
        return "just now"
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m {secs % 60}s ago"
    return f"{secs // 3600}h {(secs % 3600) // 60}m ago"


def fmt_bytes(n):
    """IEC byte size matching `numfmt --to=iec --suffix=B`: ceiling rounding,
    one decimal only when the scaled value is < 10."""
    n = int(n)
    if n < 1024:
        return f"{n}B"
    units = ["B", "KB", "MB", "GB", "TB"]
    v = float(n)
    i = 0
    while v >= 1024 and i < len(units) - 1:
        v /= 1024
        i += 1
    if v < 10:
        return f"{math.ceil(v * 10) / 10:.1f}{units[i]}"
    return f"{math.ceil(v)}{units[i]}"


# ═══ Rate-limit helpers ══════════════════════════════════════════════════════
_NUM_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "fifteen": 15,
    "twenty": 20, "thirty": 30, "sixty": 60,
}
_UNIT_ABBR = {
    "hour": "h", "hours": "h", "day": "d", "days": "d",
    "week": "w", "weeks": "w", "month": "mo", "months": "mo",
}


def rate_key_label(key):
    """five_hour -> '5h', thirty_day -> '30d'. Unknown words pass through."""
    num, _, unit = key.partition("_")
    num = _NUM_WORDS.get(num, num)
    unit = _UNIT_ABBR.get(unit, unit)
    return f"{num}{unit}"


def rate_color(pct):
    return pick_color(float(pct), RATE_RAMP)


# ═══ Segment builders ════════════════════════════════════════════════════════
# Contract: every builder is seg_x(data, avail) -> str | None.
#   avail = display cells available to this segment at its position.
#   Return None when there is no data, OR when even the smallest variant does
#   not fit avail (the builder self-deprioritizes). Otherwise return the richest
#   variant that fits, via _first_fitting([rich, ..., minimal], avail).
# The packer (pack_line) supplies avail and owns the final keep/skip decision.
# To add a segment: write seg_x(data, avail), add it to BUILDERS, list its key
# in a LAYOUT line, add a SEGMENTS flag. See the HOW TO CUSTOMIZE block below.

# fill count = intensity (1..5); auto reuses medium's 2-bar fill, ultracode max's 5.
_EFFORT_BARS = {
    "low":       (CYAN,    f"{CYAN}▁{GREY}▃▄▆█"),
    "medium":    (BLUE,    f"{BLUE}▁▃{GREY}▄▆█"),
    "auto":      (GREEN,   f"{GREEN}▁▃{GREY}▄▆█"),
    "high":      (YELLOW,  f"{YELLOW}▁▃▄{GREY}▆█"),
    "xhigh":     (ORANGE,  f"{ORANGE}▁▃▄▆{GREY}█"),
    "max":       (RED,     f"{RED}▁▃▄▆█"),
    "ultracode": (MAGENTA, f"{MAGENTA}▁▃▄▆█"),
}


def _display_dir(work_dir, home):
    shown = work_dir
    if home and work_dir.startswith(home):
        shown = "~" + work_dir[len(home):]
    if len(shown) <= PATH_MAX_LEN:
        return shown
    return os.path.basename(work_dir.rstrip("/")) or shown


def _dirty_mark(dirty):
    if dirty == "untracked":
        return f"{RED}✗{RESET}"
    if dirty == "modified":
        return f"{YELLOW}~{RESET}"
    return ""


# ── identity line ────────────────────────────────────────────────────────────
def seg_path(data, avail):
    return f"{BLUE}{_display_dir(data['work_dir'], data['home'])}{RESET}"  # floor


def seg_branch(data, avail):
    branch = data.get("branch")
    if not branch:
        return None
    icon = "🌳" if data.get("is_worktree") else "🌿"
    return _first_fitting([f"{GREY}[{icon} {branch}]{RESET}"], avail)


def seg_dirty(data, avail):
    mark = _dirty_mark(data.get("dirty", "clean"))
    return _first_fitting([mark], avail) if mark else None


def seg_todo(data, avail):
    state, text = data.get("todo_state"), data.get("todo_text")
    if not text:
        return None
    limit = avail - 4                      # room for icon + space + ellipsis
    if limit < 6:                          # too cramped to be useful -> hide
        return None
    if len(text) > limit:
        text = text[:limit - 1] + "…"
    if state == "in_progress":
        return f"📝 {YELLOW}{text}{RESET}"
    if state == "pending":
        return f"⏸  {GREY}{text}{RESET}"
    return None


# ── model row ────────────────────────────────────────────────────────────────
def seg_model(data, avail):
    name = data.get("model_name") or data.get("model_id")
    if not name:
        return None
    return _first_fitting([f"{CYAN}{name}{RESET}"], avail)


def seg_time_ago(data, avail):
    ago = data.get("ago")
    if not ago:
        return None
    return _first_fitting([f"{WHITE}{ago}{RESET}"], avail)


def seg_clock(data, avail):
    return _first_fitting([f"⏰{data['clock']}"], avail)


def seg_effort(data, avail):
    effort = data.get("effort", "")
    if not effort:
        return None
    color, bar = _EFFORT_BARS.get(effort.lower(), ("", f"{GREY}▁▃▄▆█"))
    full = f"🧠 {bar}{RESET} {color}{effort}{RESET}"
    compact = f"🧠 {bar}{RESET}"
    return _first_fitting([full, compact], avail)


def seg_lines(data, avail):
    s = (f"📃{BG_LIGHTGRAY}{GREEN}+{fmt_number(data['added'])}{RESET}"
         f"/{BG_LIGHTGRAY}{RED}-{fmt_number(data['removed'])}{RESET}")
    return _first_fitting([s], avail)


def seg_cost(data, avail):
    return _first_fitting([f"🪙${float(data['cost']):.3f}"], avail)


def seg_total_time(data, avail):
    return _first_fitting([f"💬{fmt_time_ms(data['total_ms'])}"], avail)


def seg_api_time(data, avail):
    return _first_fitting([f"📡{fmt_time_ms(data['api_ms'])}"], avail)


# ── diagnostics row ──────────────────────────────────────────────────────────
def seg_dimensions(data, avail):
    mark = "?" if data.get("dim_assumed") else ""
    return _first_fitting([f"{data['cols']}×{data['lines']}{mark}"], avail)


def seg_context(data, avail):
    pct = int(data["context_pct"])
    color = pick_color(pct, CONTEXT_RAMP)
    pct_only = f"📊 {color}{pct}%{RESET}"
    # Measure in half-cells (5% each) and round up, so any pct > 0 shows >= ▌.
    halves = 0 if pct <= 0 else min(2 * CONTEXT_BAR_CELLS, math.ceil(pct / 5))
    full_n, half = divmod(halves, 2)
    bar_f = "█" * full_n + ("▌" if half else "")
    bar_e = "░" * (CONTEXT_BAR_CELLS - full_n - half)
    bar = f"{color}{bar_f}{GREY}{bar_e}{RESET}"
    mid = f"📊 {bar} {color}{pct}%{RESET}"
    full = f"📊 {bar} {color}{pct}% of {fmt_tokens(data['context_max'])}{RESET}"
    return _first_fitting([full, mid, pct_only], avail) or pct_only  # floor


def seg_chat_size(data, avail):
    n = data.get("chat_bytes")
    if n is None:
        return None
    return _first_fitting([f"💾 {fmt_bytes(n)}"], avail)


def seg_memory(data, avail):
    n = data.get("mem_bytes")
    if n is None:
        return None
    return _first_fitting([f"🧮 {fmt_bytes(n)}"], avail)


def _reset_suffix(reset, detail):
    """Reset stamp at the requested detail: 'long' | 'short' | 'none'.
    Pure formatting of resets_at in local time — never compared against the
    clock, so a wrong system time or a timezone change can't change what shows."""
    if reset is None or detail == "none":
        return ""
    dt = datetime.fromtimestamp(reset)
    if detail == "long":
        return f" (↺ {dt.strftime('%b %d %H:%M')})"   # e.g. Jun 07 14:10
    return f" (↺ {dt.strftime('%m-%d %H:%M')})"        # e.g. 06-07 14:10


def _rate_str(rate_limits, detail):
    # Show every bucket that reports a percentage. Visibility never depends on
    # the clock — the reset stamp is shown only when there's room (via detail),
    # so timezone shifts / clock skew can't make a bucket vanish.
    parts = []
    for key in sorted(rate_limits):
        info = rate_limits[key] or {}
        pct = info.get("used_percentage")
        if pct is None:
            continue
        reset = info.get("resets_at")
        if reset is not None:
            reset = int(reset)
        color = rate_color(pct)
        suffix = _reset_suffix(reset, detail)
        parts.append(f"{rate_key_label(key)}: {color}{round(float(pct))}%{RESET}{suffix}")
    return "⚡ " + " | ".join(parts) if parts else None


def seg_rate_limits(data, avail):
    rate_limits = data.get("rate_limits")
    if not rate_limits:
        return None
    return _first_fitting([_rate_str(rate_limits, "long"),
                           _rate_str(rate_limits, "short"),
                           _rate_str(rate_limits, "none")], avail)


# ═══ Segment registry — key -> builder(data, avail) ══════════════════════════
BUILDERS = {
    "path": seg_path, "branch": seg_branch, "dirty": seg_dirty, "todo": seg_todo,
    "model": seg_model, "time_ago": seg_time_ago, "clock": seg_clock,
    "effort": seg_effort, "lines": seg_lines, "cost": seg_cost,
    "total_time": seg_total_time, "api_time": seg_api_time,
    "dimensions": seg_dimensions, "context": seg_context,
    "chat_size": seg_chat_size, "memory": seg_memory,
    "rate_limits": seg_rate_limits,
}

# ═══ Layout template — edit to reorder / move / re-line segments ═════════════
# One Line per row. `segments` lists keys LEFT->RIGHT; leftmost = highest
# priority (kept first when space is tight). `min_rows` gates the whole row by
# terminal height. Reorder = move a key within a list; move between rows = cut
# and paste a key; hide = flip its SEGMENTS flag.
Line = namedtuple("Line", "min_rows segments")
LAYOUT = [
    Line(0,  ["path", "branch", "dirty", "todo"]),
    Line(20, ["model", "time_ago", "clock", "effort", "lines",
              "cost", "total_time", "api_time"]),
    Line(30, ["dimensions", "context", "chat_size", "memory", "rate_limits"]),
]
PINNED = {"path", "context"}   # always rendered even if they overflow the budget


# ═══ Extractors ═══════════════════════════════════════════════════════════════
def terminal_size(env):
    """Resolve (cols, lines, assumed). Priority: STATUSLINE_* > COLUMNS/LINES >
    stty via /dev/tty. If none available, assume a wide panel and flag it."""
    def _int(*keys):
        for k in keys:
            v = env.get(k)
            if v and str(v).isdigit() and int(v) > 0:
                return int(v)
        return None

    cols = _int("STATUSLINE_COLS", "COLUMNS")
    lines = _int("STATUSLINE_LINES", "LINES")
    if cols is None or lines is None:
        try:
            with open("/dev/tty") as tty:
                out = subprocess.run(["stty", "size"], stdin=tty,
                                     capture_output=True, text=True, timeout=1).stdout.split()
            if len(out) == 2:
                lines = lines or int(out[0])
                cols = cols or int(out[1])
        except Exception:
            pass
    assumed = False
    if cols is None:
        cols, assumed = 200, True
    if lines is None:
        lines, assumed = 40, True
    return cols, lines, assumed


def git_info(work_dir):
    """Return (branch, dirty, is_worktree).

    dirty in {clean, untracked, modified}. is_worktree is True when work_dir sits
    in a linked worktree (git-dir != git-common-dir), False in the main repo or
    outside any repo."""
    def _git(*args):
        return subprocess.run(["git", "-C", work_dir, *args],
                              capture_output=True, text=True).stdout

    branch = _git("branch", "--show-current").strip()
    status = _git("status", "--porcelain")
    if any(ln.startswith(("??", "A", "D")) or ln.startswith(" D")
           for ln in status.splitlines()):
        dirty = "untracked"
    elif status.strip():
        dirty = "modified"
    else:
        dirty = "clean"
    # One extra git call: in a linked worktree git-dir and git-common-dir differ.
    gd = _git("rev-parse", "--git-dir", "--git-common-dir").split()
    is_worktree = len(gd) == 2 and gd[0] != gd[1]
    return branch, dirty, is_worktree


def proc_rss_bytes():
    """Resident memory of the parent `claude` process, in bytes. None if /proc
    is unavailable. Walk up the parent chain in case a shell wraps us."""
    pid = os.getppid()
    for _ in range(4):
        try:
            comm = open(f"/proc/{pid}/comm").read().strip()
        except OSError:
            return None
        if comm == "claude":
            break
        try:
            ppid = int(open(f"/proc/{pid}/stat").read().split()[3])
        except (OSError, IndexError, ValueError):
            return None
        if ppid in (0, pid):
            break
        pid = ppid
    try:
        for line in open(f"/proc/{pid}/status"):
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except OSError:
        return None
    return None


def transcript_bytes(path):
    if not path or not os.path.isfile(path):
        return None
    try:
        return os.path.getsize(path)
    except OSError:
        return None


def _iter_tool_uses(line_obj, names):
    # In real transcripts message.content is a list of blocks for tool turns but
    # a plain string for text turns — only iterate when it is a list of dicts.
    content = (line_obj.get("message") or {}).get("content")
    if not isinstance(content, list):
        return
    for item in content:
        if isinstance(item, dict) and item.get("type") == "tool_use" and item.get("name") in names:
            yield item


def current_todo(path):
    """Return (state, text) for the active TODO, or (None, None).

    Prefer the managed-tasks API (TaskCreate/TaskUpdate), projecting events in
    order; fall back to the latest TodoWrite snapshot."""
    if not path or not os.path.isfile(path):
        return None, None

    tasks = []
    try:
        with open(path) as fh:
            todo_snapshots = []
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(obj, dict):
                    continue
                for tu in _iter_tool_uses(obj, ("TaskCreate", "TaskUpdate")):
                    inp = tu.get("input", {})
                    if tu["name"] == "TaskCreate":
                        tasks.append({
                            "id": len(tasks) + 1,
                            "subject": inp.get("subject", ""),
                            "activeForm": inp.get("activeForm") or inp.get("subject", ""),
                            "status": "pending",
                        })
                    else:
                        tid = str(inp.get("taskId"))
                        for t in tasks:
                            if str(t["id"]) == tid and inp.get("status"):
                                t["status"] = inp["status"]
                for tu in _iter_tool_uses(obj, ("TodoWrite",)):
                    todo_snapshots.append(tu.get("input", {}).get("todos", []))
    except OSError:
        return None, None

    if tasks:
        in_prog = [t for t in tasks if t["status"] == "in_progress"]
        if in_prog:
            return "in_progress", in_prog[-1]["activeForm"]
        pending = [t for t in tasks if t["status"] == "pending"]
        if pending:
            return "pending", pending[0]["subject"]
        return None, None

    if todo_snapshots:
        todos = todo_snapshots[-1]
        in_prog = [t for t in todos if t.get("status") == "in_progress"]
        if in_prog:
            return "in_progress", in_prog[0].get("activeForm", "")
        pending = [t for t in todos if t.get("status") == "pending"]
        if pending:
            return "pending", pending[0].get("content", "")
    return None, None


# ═══ Packing + render ════════════════════════════════════════════════════════
def pack_line(keys, data, cols):
    """Best-fit pack enabled segments into cols - RIGHT_MARGIN.

    For each key (left->right), compute the space available at this position
    (budget - used - separator), ask the builder for content sized to it, and
    keep it if it is non-empty and fits — else skip it and keep trying the rest.
    Pinned segments are always kept. Order is priority: leftmost survive."""
    budget = cols - RIGHT_MARGIN
    sep_w = visible_width(SEP)
    kept, used = [], 0
    for key in keys:
        if not SEGMENTS.get(key, False):       # flag gate: not built => no compute
            continue
        sep = sep_w if kept else 0
        avail = budget - used - sep
        s = BUILDERS[key](data, max(avail, 0))
        if not s:
            continue
        if key in PINNED or visible_width(s) <= avail:
            kept.append(s)
            used += visible_width(s) + sep
    return SEP.join(kept)


def render(data, cols, lines):
    """Render up to len(LAYOUT) lines, gated by terminal height and width."""
    out = []
    for ln in LAYOUT:
        if lines < ln.min_rows:
            continue
        packed = pack_line(ln.segments, data, cols)
        if packed:
            out.append(packed)
    return out


# ═══ HOW TO CUSTOMIZE ════════════════════════════════════════════════════════
# Three knobs at the top of the file drive everything:
#
#   SEGMENTS  — on/off flag per segment. False hides it everywhere and its
#               builder is never called (saves compute). Keep "path" True.
#   LAYOUT    — the template: a list of Line(min_rows, [segment keys]). Key order
#               in each list is LEFT->RIGHT priority; leftmost survive when the
#               terminal is narrow. min_rows gates the whole row by terminal rows.
#   BUILDERS  — maps each segment key to its builder(data, avail) function.
#
# How show/hide is decided: the packer (pack_line) is the authority. It offers
# each builder the space available at its spot (avail) and keeps the result only
# if it is non-empty and fits; otherwise it skips it and tries the next. A
# builder cooperates by auto-deprioritizing itself — returning a compact variant
# for a small avail, or None when even its smallest variant will not fit.
# PINNED segments ("path", "context") are kept even if they overflow.
#
# Available segments (key -> what it shows):
#   path         working dir (~-collapsed; basename if long)     [pinned]
#   branch       git branch with 🌿 (repo) / 🌳 (worktree) icon
#   dirty        ✗ untracked / ~ modified marker
#   todo         active TODO / task (truncated to fit)
#   model        model display name
#   time_ago     time since last transcript activity
#   clock        ⏰ wall clock HH:MM
#   effort       🧠 effort ramp bar (+ level word when room)
#   lines        📃 +added/-removed line counts
#   cost         🪙 session cost in USD (off by default)
#   total_time   💬 total session duration
#   api_time     📡 total API duration
#   dimensions   terminal COLS×ROWS
#   context      📊 context-window usage bar + percent           [pinned]
#   chat_size    💾 transcript file size
#   memory       🧮 claude process RSS
#   rate_limits  ⚡ rate-limit buckets (+ reset times when room)
#
# Common edits:
#   * Toggle a segment:       flip its SEGMENTS[...] value.
#   * Reorder within a line:  move its key within that Line's list.
#   * Move to another line:   cut its key from one Line list, paste into another.
#   * Re-enable a removed one: ensure (a) SEGMENTS[key] is True, (b) the key is
#                             in some LAYOUT line, and (c) the key is in BUILDERS.
#                             All three are required for it to show.
#   * Add a NEW segment:
#       1. Write a builder:  def seg_foo(data, avail):
#              if no_data: return None
#              return _first_fitting([rich_form, compact_form], avail)
#          (return None to hide; read what you need from `data`; let the builder
#          auto-deprioritize via _first_fitting on the avail it is offered).
#       2. Register it:      add  "foo": seg_foo  to BUILDERS.
#       3. Place it:         add  "foo"  to a LAYOUT line where you want it.
#       4. Flag it:          add  "foo": True  to SEGMENTS.
#       5. Test it:          add a case in tests/test_status_line.py.


# ═══ Entry point ══════════════════════════════════════════════════════════════
def build_data(raw, env):
    model = raw.get("model") or {}
    cost = raw.get("cost") or {}
    ctx = raw.get("context_window") or {}
    workspace = raw.get("workspace") or {}
    work_dir = workspace.get("current_dir") or "."
    transcript = raw.get("transcript_path") or ""

    cols, lines, assumed = terminal_size(env)
    branch, dirty, is_worktree = git_info(work_dir)

    ago = ""
    if transcript and os.path.isfile(transcript):
        ago = fmt_ago(int(time.time()) - int(os.path.getmtime(transcript)))

    effort = (raw.get("effort") or {}).get("level") or env.get("CLAUDE_EFFORT", "")
    todo_state, todo_text = current_todo(transcript)

    data = {
        "model_name": model.get("display_name", ""),
        "model_id": model.get("id", "unknown"),
        "effort": effort,
        "work_dir": work_dir,
        "home": env.get("HOME", ""),
        "branch": branch, "dirty": dirty, "is_worktree": is_worktree,
        "clock": time.strftime("%H:%M"), "ago": ago,
        "added": cost.get("total_lines_added", 0),
        "removed": cost.get("total_lines_removed", 0),
        "cost": cost.get("total_cost_usd", 0),
        "total_ms": cost.get("total_duration_ms", 0),
        "api_ms": cost.get("total_api_duration_ms", 0),
        "context_pct": int(ctx.get("used_percentage", 0)),
        "context_max": ctx.get("context_window_size", 0),
        "chat_bytes": transcript_bytes(transcript),
        "mem_bytes": proc_rss_bytes(),
        "rate_limits": raw.get("rate_limits") or {},
        "todo_state": todo_state, "todo_text": todo_text,
        "dim_assumed": assumed,
        "cols": cols, "lines": lines,
    }
    return data, cols, lines


def main():
    try:
        raw = json.load(sys.stdin)
    except (ValueError, OSError):
        raw = {}
    data, cols, lines = build_data(raw, os.environ)
    print("\n".join(render(data, cols, lines)))


if __name__ == "__main__":
    main()
