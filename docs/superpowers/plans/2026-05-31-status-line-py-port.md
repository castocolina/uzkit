# Status Line Python Port — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port `~/.claude/statusline.sh` to a modular, dependency-free Python script at `~/.claude/plugins/uz-kit/status-line.py`, with per-segment on/off flags and color ramps declared at the top, built test-first.

**Architecture:** Single executable file. A `CONFIG` block at the top (segment flags, width tiers, color ramps). Pure helpers (formatters, `pick_color`) are unit-tested in isolation. Data extractors (`git`, `/proc`, transcript) and segment builders return strings; a `render()` function assembles up to 3 lines honoring flags + responsive width/height tiers. `main()` reads the status JSON from stdin and prints. The `.sh` stays untouched as a fallback; `settings.json` is repointed to the `.py` only at the end after side-by-side parity is confirmed.

**CONFIG invariant:** `SEGMENTS["path"]` must remain `True` (default). `render()` always emits at least the identity line regardless of other flags, matching the bash original's unconditional first `echo`. If all other segments are `False`, `render()` still returns a one-element list containing the path/dir string.

**Tech Stack:** Python 3.12 stdlib only (`json`, `os`, `sys`, `subprocess`, `time`, `math`, `datetime`, `importlib` for tests, `unittest`). No third-party deps — mirrors the zero-dependency bash original.

---

## File Structure

- Create: `~/.claude/plugins/uz-kit/status-line.py` — the whole status line (CONFIG → palette → ramps → helpers → extractors → builders → render → main).
- Create: `~/.claude/plugins/uz-kit/tests/test_status_line.py` — `unittest` suite; loads the hyphenated module via `importlib.util.spec_from_file_location`.
- Modify (final task only): `~/.claude/settings.json:128-131` — repoint `statusLine.command` to the Python script.
- Untouched: `~/.claude/statusline.sh` — kept as the rollback baseline.

**Module layout inside `status-line.py` (top → bottom):**

1. `CONFIG` — `SEGMENTS` (bool per segment), `TIERS` (min cols per segment), row gates `LINE1_MIN_LINES` / `LINE2_MIN_LINES`.
2. Palette — ANSI constants (`RESET`, `GREY`, `WHITE`, `CYAN`, `BLUE`, `GREEN`, `YELLOW`, `ORANGE`, `RED`, `MAGENTA`, `BG_LIGHTGRAY`).
3. Ramps — `CONTEXT_RAMP`, `RATE_RAMP`, `INF = float('inf')`.
4. Pure helpers — `pick_color`, `fmt_number`, `fmt_time_ms`, `fmt_tokens`, `fmt_ago`, `fmt_bytes`, `rate_key_label`, `rate_color`.
5. Extractors — `terminal_size`, `git_info`, `proc_rss_bytes`, `transcript_bytes`, `current_todo`.
6. Builders — `seg_*` functions returning `str | None`.
7. `render(data, cols, lines)` → list of output lines.
8. `main()`.

**Color ramp (per user spec):** `<10` white · `10–14` cyan · `15–19` blue · `20–24` green · `25–29` yellow · `30–39` orange · `40–49` red · `≥50` magenta. Rule: first ceil the pct is strictly below wins; exact boundary falls into the higher band. This is a deliberate user-requested replacement for the bash original's 5-band ramp (`<20` white · `<30` cyan · `<40` green · `<60` orange · `≥60` red); the parity check in Task 9 validates segment presence/order only — context color is an intentional delta.

---

### Task 1: Test harness + `pick_color` ramp

**Files:**
- Create: `~/.claude/plugins/uz-kit/status-line.py`
- Test: `~/.claude/plugins/uz-kit/tests/test_status_line.py`

- [ ] **Step 1: Write the failing test**

`tests/test_status_line.py`:

```python
import importlib.util
import os
import re
import unittest

_HERE = os.path.dirname(__file__)
_MODULE_PATH = os.path.join(_HERE, "..", "status-line.py")


def load_module():
    spec = importlib.util.spec_from_file_location("status_line", _MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sl = load_module()

ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def strip(s):
    return ANSI_RE.sub("", s)


class TestPickColor(unittest.TestCase):
    def test_context_ramp_bands(self):
        cases = [
            (5, sl.WHITE), (9, sl.WHITE),
            (10, sl.CYAN), (14, sl.CYAN),
            (15, sl.BLUE), (19, sl.BLUE),
            (20, sl.GREEN), (24, sl.GREEN),
            (25, sl.YELLOW), (29, sl.YELLOW),
            (30, sl.ORANGE), (39, sl.ORANGE),
            (40, sl.RED), (49, sl.RED),
            (50, sl.MAGENTA), (99, sl.MAGENTA),
        ]
        for pct, expected in cases:
            self.assertEqual(sl.pick_color(pct, sl.CONTEXT_RAMP), expected, f"pct={pct}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/.claude/plugins/uz-kit && python3 tests/test_status_line.py`
Expected: FAIL — `FileNotFoundError` / `ModuleNotFoundError` because `status-line.py` does not exist yet.

- [ ] **Step 3: Write minimal implementation**

Create `status-line.py`:

```python
#!/usr/bin/env python3
"""Claude Code status line — modular Python port of statusline.sh.

Reads the status JSON on stdin and prints up to three ANSI-colored lines.
Stdlib only. The .sh original is kept as a fallback.
"""

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

# ═══ Color ramps (ceil, color) — first ceil the pct is below wins ════════════
INF = float("inf")
CONTEXT_RAMP = [
    (10, WHITE), (15, CYAN), (20, BLUE), (25, GREEN),
    (30, YELLOW), (40, ORANGE), (50, RED), (INF, MAGENTA),
]
RATE_RAMP = [(50, GREEN), (80, YELLOW), (INF, RED)]


def pick_color(pct, ramp):
    """Return the color for the first ceil that pct is strictly below."""
    for ceil, color in ramp:
        if pct < ceil:
            return color
    return ramp[-1][1]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/.claude/plugins/uz-kit && python3 tests/test_status_line.py`
Expected: PASS (`test_context_ramp_bands ... ok`).

- [ ] **Step 5: Commit**

```bash
cd ~/.claude/plugins/uz-kit
git add status-line.py tests/test_status_line.py
git commit -m "feat(status-line): palette, color ramps, pick_color (TDD)"
```

---

### Task 2: Numeric & time formatters

**Files:**
- Modify: `~/.claude/plugins/uz-kit/status-line.py`
- Test: `~/.claude/plugins/uz-kit/tests/test_status_line.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_status_line.py` (before the `if __name__` block):

```python
class TestFormatters(unittest.TestCase):
    def test_fmt_number(self):
        self.assertEqual(sl.fmt_number(1234567), "1,234,567")
        self.assertEqual(sl.fmt_number(120), "120")
        self.assertEqual(sl.fmt_number(0), "0")

    def test_fmt_time_ms(self):
        self.assertEqual(sl.fmt_time_ms(500), "500ms")
        self.assertEqual(sl.fmt_time_ms(5000), "5s")
        self.assertEqual(sl.fmt_time_ms(65000), "1m 5s")
        self.assertEqual(sl.fmt_time_ms(3700000), "1h 1m")

    def test_fmt_tokens(self):
        self.assertEqual(sl.fmt_tokens(1000000), "1M")
        self.assertEqual(sl.fmt_tokens(200000), "200K")
        self.assertEqual(sl.fmt_tokens(500), "500")

    def test_fmt_ago(self):
        self.assertEqual(sl.fmt_ago(0), "just now")
        self.assertEqual(sl.fmt_ago(30), "30s ago")
        self.assertEqual(sl.fmt_ago(90), "1m 30s ago")
        self.assertEqual(sl.fmt_ago(3700), "1h 1m ago")

    def test_fmt_bytes(self):
        self.assertEqual(sl.fmt_bytes(999), "999B")
        self.assertEqual(sl.fmt_bytes(1024), "1.0KB")
        self.assertEqual(sl.fmt_bytes(1536), "1.5KB")
        self.assertEqual(sl.fmt_bytes(134417), "132KB")
        self.assertEqual(sl.fmt_bytes(305152), "298KB")
        self.assertEqual(sl.fmt_bytes(999999), "977KB")
        self.assertEqual(sl.fmt_bytes(448000000), "428MB")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/.claude/plugins/uz-kit && python3 tests/test_status_line.py`
Expected: FAIL — `AttributeError: module 'status_line' has no attribute 'fmt_number'`.

- [ ] **Step 3: Write minimal implementation**

Append to `status-line.py` after `pick_color`:

```python
import math

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/.claude/plugins/uz-kit && python3 tests/test_status_line.py`
Expected: PASS (all `TestFormatters` cases ok).

- [ ] **Step 5: Commit**

```bash
cd ~/.claude/plugins/uz-kit
git add status-line.py tests/test_status_line.py
git commit -m "feat(status-line): numeric/time/byte formatters (TDD)"
```

---

### Task 3: Rate-limit label + color

**Files:**
- Modify: `~/.claude/plugins/uz-kit/status-line.py`
- Test: `~/.claude/plugins/uz-kit/tests/test_status_line.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_status_line.py`:

```python
class TestRateHelpers(unittest.TestCase):
    def test_rate_key_label(self):
        self.assertEqual(sl.rate_key_label("five_hour"), "5h")
        self.assertEqual(sl.rate_key_label("seven_day"), "7d")
        self.assertEqual(sl.rate_key_label("thirty_day"), "30d")
        self.assertEqual(sl.rate_key_label("one_week"), "1w")

    def test_rate_color(self):
        self.assertEqual(sl.rate_color(23.4), sl.GREEN)
        self.assertEqual(sl.rate_color(50), sl.YELLOW)
        self.assertEqual(sl.rate_color(80), sl.RED)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/.claude/plugins/uz-kit && python3 tests/test_status_line.py`
Expected: FAIL — `AttributeError: module 'status_line' has no attribute 'rate_key_label'`.

- [ ] **Step 3: Write minimal implementation**

Append to `status-line.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/.claude/plugins/uz-kit && python3 tests/test_status_line.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd ~/.claude/plugins/uz-kit
git add status-line.py tests/test_status_line.py
git commit -m "feat(status-line): rate-limit label + color helpers (TDD)"
```

---

### Task 4: CONFIG block + segment builders for the model row

**Files:**
- Modify: `~/.claude/plugins/uz-kit/status-line.py`
- Test: `~/.claude/plugins/uz-kit/tests/test_status_line.py`

Builders take already-extracted primitives and return a styled `str` (or `None` when there is nothing to show). Tests strip ANSI to assert on text.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_status_line.py`:

```python
class TestModelBuilders(unittest.TestCase):
    def test_seg_model_prefers_display_name(self):
        self.assertEqual(strip(sl.seg_model("Opus 4.8", "claude-opus-4-8")), "Opus 4.8")
        self.assertEqual(strip(sl.seg_model("", "claude-opus-4-8")), "claude-opus-4-8")

    def test_seg_clock(self):
        self.assertEqual(strip(sl.seg_clock("09:41")), "⏰09:41")

    def test_seg_cost(self):
        self.assertEqual(strip(sl.seg_cost(0.42)), "🪙$0.420")

    def test_seg_lines(self):
        self.assertEqual(strip(sl.seg_lines(120, 30)), "📃+120/-30")

    def test_seg_effort_levels(self):
        self.assertEqual(strip(sl.seg_effort("medium")), "🧠 ▁▃▄▆█ medium")
        self.assertIsNone(sl.seg_effort(""))

    def test_config_has_all_segments(self):
        for key in ("model", "time_ago", "clock", "effort", "lines",
                    "cost", "context", "chat_size", "memory",
                    "rate_limits", "dimensions"):
            self.assertIn(key, sl.SEGMENTS)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/.claude/plugins/uz-kit && python3 tests/test_status_line.py`
Expected: FAIL — `AttributeError: module 'status_line' has no attribute 'SEGMENTS'`.

- [ ] **Step 3: Write minimal implementation**

Insert the CONFIG block at the very TOP of `status-line.py` (immediately after the module docstring, before the palette):

```python
# ═══ CONFIG — edit freely ════════════════════════════════════════════════════
# Per-segment on/off. Set False to hide a segment entirely.
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

# Minimum terminal width (cols) for a segment to appear. Absent key => always.
# Note: "cost" keeps a tier entry (65) even though SEGMENTS["cost"] is False by
# default, so flipping the flag on later picks up the right threshold with no
# other change. While the flag is off, this entry is intentionally inert.
TIERS = {
    "branch": 65,
    "cost": 65, "effort": 90, "lines": 90, "total_time": 120, "api_time": 120,
    "dimensions": 80, "chat_size": 80, "memory": 80, "rate_limits": 80,
}

# Whole-row height gates (terminal lines).
LINE1_MIN_LINES = 20   # model row
LINE2_MIN_LINES = 30   # diagnostics row
DIAG_MIN_COLS = 50     # below this, diagnostics row collapses to "📊 NN%"
```

Append the builders after the rate helpers:

```python
# ═══ Segment builders (return styled str, or None to omit) ═══════════════════
_EFFORT_BARS = {
    "low":    (CYAN,    f"{CYAN}▁{GREY}▃▄▆█"),
    "medium": (GREEN,   f"{GREEN}▁▃{GREY}▄▆█"),
    "high":   (YELLOW,  f"{YELLOW}▁▃▄{GREY}▆█"),
    "xhigh":  (RED,     f"{RED}▁▃▄▆{GREY}█"),
    "max":    (MAGENTA, f"{MAGENTA}▁▃▄▆█"),
}


def seg_model(display_name, model_id):
    name = display_name or model_id
    return f"{CYAN}{name}{RESET}"


def seg_time_ago(ago_text):
    return f"{WHITE}{ago_text}{RESET}" if ago_text else None


def seg_clock(hhmm):
    return f"⏰{hhmm}"


def seg_effort(effort):
    if not effort:
        return None
    color, bar = _EFFORT_BARS.get(effort.lower(), ("", f"{GREY}▁▃▄▆█"))
    return f"🧠 {bar}{RESET} {color}{effort}{RESET}"


def seg_lines(added, removed):
    return (f"📃{BG_LIGHTGRAY}{GREEN}+{fmt_number(added)}{RESET}"
            f"/{BG_LIGHTGRAY}{RED}-{fmt_number(removed)}{RESET}")


def seg_cost(cost_usd):
    return f"🪙${float(cost_usd):.3f}"


def seg_total_time(ms):
    return f"💬{fmt_time_ms(ms)}"


def seg_api_time(ms):
    return f"📡{fmt_time_ms(ms)}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/.claude/plugins/uz-kit && python3 tests/test_status_line.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd ~/.claude/plugins/uz-kit
git add status-line.py tests/test_status_line.py
git commit -m "feat(status-line): CONFIG block + model-row builders (TDD)"
```

---

### Task 5: Context, dimensions, chat-size, memory, rate-limit builders

**Files:**
- Modify: `~/.claude/plugins/uz-kit/status-line.py`
- Test: `~/.claude/plugins/uz-kit/tests/test_status_line.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_status_line.py`:

```python
class TestDiagBuilders(unittest.TestCase):
    def test_seg_context_bar_and_label(self):
        out = strip(sl.seg_context(12, 1_000_000))
        self.assertEqual(out, "📊 █░░░░░░░░░ 12% of 1M")

    def test_seg_context_color_follows_ramp(self):
        self.assertIn(sl.WHITE, sl.seg_context(5, 1_000_000))
        self.assertIn(sl.MAGENTA, sl.seg_context(70, 1_000_000))

    def test_seg_dimensions(self):
        self.assertEqual(strip(sl.seg_dimensions(267, 58, False)), "267×58")
        self.assertEqual(strip(sl.seg_dimensions(200, 40, True)), "200×40?")

    def test_seg_chat_and_memory(self):
        self.assertEqual(strip(sl.seg_chat_size(305152)), "💾 298KB")
        self.assertIsNone(sl.seg_chat_size(None))
        self.assertEqual(strip(sl.seg_memory(448000000)), "🧮 428MB")
        self.assertIsNone(sl.seg_memory(None))

    def test_seg_rate_limits(self):
        rl = {"five_hour": {"used_percentage": 23.4, "resets_at": None}}
        out = strip(sl.seg_rate_limits(rl))
        self.assertTrue(out.startswith("⚡ 5h: 23%"))
        self.assertIsNone(sl.seg_rate_limits({}))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/.claude/plugins/uz-kit && python3 tests/test_status_line.py`
Expected: FAIL — `AttributeError: ... 'seg_context'`.

- [ ] **Step 3: Write minimal implementation**

Append to `status-line.py`:

```python
from datetime import datetime


def seg_context(pct, ctx_max):
    pct = int(pct)
    filled = pct // 10
    bar_f = "█" * filled
    bar_e = "░" * (10 - filled)
    color = pick_color(pct, CONTEXT_RAMP)
    return (f"📊 {color}{bar_f}{GREY}{bar_e}{RESET} "
            f"{color}{pct}% of {fmt_tokens(ctx_max)}{RESET}")


def seg_dimensions(cols, lines, assumed):
    return f"{cols}×{lines}{'?' if assumed else ''}"


def seg_chat_size(num_bytes):
    if num_bytes is None:
        return None
    return f"💾 {fmt_bytes(num_bytes)}"


def seg_memory(num_bytes):
    if num_bytes is None:
        return None
    return f"🧮 {fmt_bytes(num_bytes)}"


def seg_rate_limits(rate_limits):
    if not rate_limits:
        return None
    parts = []
    for key in sorted(rate_limits):
        info = rate_limits[key] or {}
        pct = info.get("used_percentage")
        if pct is None:
            continue
        color = rate_color(pct)
        label = rate_key_label(key)
        reset = info.get("resets_at")
        suffix = ""
        if reset:
            suffix = f" (↺ {datetime.fromtimestamp(int(reset)).strftime('%H:%M')})"
        parts.append(f"{label}: {color}{round(float(pct))}%{RESET}{suffix}")
    if not parts:
        return None
    return "⚡ " + " | ".join(parts)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/.claude/plugins/uz-kit && python3 tests/test_status_line.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd ~/.claude/plugins/uz-kit
git add status-line.py tests/test_status_line.py
git commit -m "feat(status-line): diagnostics-row builders (TDD)"
```

---

### Task 6: Extractors — terminal size, git, /proc memory, transcript size, TODO

**Files:**
- Modify: `~/.claude/plugins/uz-kit/status-line.py`
- Test: `~/.claude/plugins/uz-kit/tests/test_status_line.py`

These touch the environment, so tests use `tmp_path`-style temp files and env patching for the parts that are deterministic (terminal size, transcript size, TODO reconstruction). `git_info` and `proc_rss_bytes` are smoke-tested for "does not crash, returns expected type".

- [ ] **Step 1: Write the failing test**

Append to `tests/test_status_line.py`:

```python
import json
import tempfile


class TestExtractors(unittest.TestCase):
    def test_terminal_size_from_env_override(self):
        cols, lines, assumed = sl.terminal_size({"STATUSLINE_COLS": "120", "STATUSLINE_LINES": "40"})
        self.assertEqual((cols, lines, assumed), (120, 40, False))

    def test_terminal_size_fallback_is_assumed(self):
        # env={} suppresses env-var lookup but NOT /dev/tty: in a real terminal
        # stty returns the actual size with assumed=False. Assert only on the
        # contract (positive dims), not the specific fallback constant.
        cols, lines, assumed = sl.terminal_size({})
        self.assertGreater(cols, 0)
        self.assertGreater(lines, 0)

    def test_transcript_bytes(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write("x" * 1000)
            path = f.name
        self.assertEqual(sl.transcript_bytes(path), 1000)
        self.assertIsNone(sl.transcript_bytes(None))
        self.assertIsNone(sl.transcript_bytes("/no/such/file"))

    def test_current_todo_taskcreate(self):
        lines = [
            {"message": {"content": [
                {"type": "tool_use", "name": "TaskCreate",
                 "input": {"subject": "Build X", "activeForm": "Building X"}}]}},
            {"message": {"content": [
                {"type": "tool_use", "name": "TaskUpdate",
                 "input": {"taskId": 1, "status": "in_progress"}}]}},
        ]
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            for ln in lines:
                f.write(json.dumps(ln) + "\n")
            path = f.name
        state, text = sl.current_todo(path)
        self.assertEqual(state, "in_progress")
        self.assertEqual(text, "Building X")

    def test_current_todo_none_when_empty(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            f.write('{"message":{"content":[]}}\n')
            path = f.name
        self.assertEqual(sl.current_todo(path), (None, None))

    def test_proc_rss_and_git_smoke(self):
        rss = sl.proc_rss_bytes()
        self.assertTrue(rss is None or isinstance(rss, int))
        branch, dirty = sl.git_info(os.getcwd())
        self.assertIsInstance(branch, str)
        self.assertIn(dirty, ("clean", "untracked", "modified"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/.claude/plugins/uz-kit && python3 tests/test_status_line.py`
Expected: FAIL — `AttributeError: ... 'terminal_size'`.

- [ ] **Step 3: Write minimal implementation**

Append to `status-line.py`:

```python
import os
import subprocess


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
    """Return (branch, dirty) where dirty in {clean, untracked, modified}."""
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
    return branch, dirty


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
    for item in (line_obj.get("message", {}).get("content") or []):
        if item.get("type") == "tool_use" and item.get("name") in names:
            yield item


def current_todo(path):
    """Return (state, text) for the active TODO, or (None, None).

    Prefer the managed-tasks API (TaskCreate/TaskUpdate), projecting events in
    order; fall back to the latest TodoWrite snapshot."""
    import json
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/.claude/plugins/uz-kit && python3 tests/test_status_line.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd ~/.claude/plugins/uz-kit
git add status-line.py tests/test_status_line.py
git commit -m "feat(status-line): env/git/proc/transcript/todo extractors (TDD)"
```

---

### Task 7: `render()` — assemble lines honoring flags + tiers, and the TODO/path/identity builders

**Files:**
- Modify: `~/.claude/plugins/uz-kit/status-line.py`
- Test: `~/.claude/plugins/uz-kit/tests/test_status_line.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_status_line.py`:

```python
class TestRender(unittest.TestCase):
    def _data(self, **over):
        d = {
            "model_name": "Opus 4.8", "model_id": "claude-opus-4-8",
            "effort": "medium", "work_dir": "/home/u/.claude", "home": "/home/u",
            "branch": "master", "dirty": "modified",
            "clock": "09:41", "ago": "5s ago",
            "added": 0, "removed": 0, "cost": 0.0, "total_ms": 0, "api_ms": 0,
            "context_pct": 12, "context_max": 1_000_000,
            "chat_bytes": 305152, "mem_bytes": 448000000,
            "rate_limits": {}, "todo_state": None, "todo_text": None,
        }
        d.update(over)
        return d

    def test_diag_row_order_and_segments(self):
        lines = sl.render(self._data(), cols=267, lines=58)
        diag = strip(lines[-1])
        # screen dims | context | chat | memory  (rate absent here)
        self.assertEqual(diag, "267×58 | 📊 █░░░░░░░░░ 12% of 1M | 💾 298KB | 🧮 428MB")

    def test_narrow_collapses_diag(self):
        lines = sl.render(self._data(), cols=40, lines=58)
        self.assertEqual(strip(lines[-1]), "📊 12%")

    def test_flag_off_hides_segment(self):
        saved = sl.SEGMENTS["memory"]
        sl.SEGMENTS["memory"] = False
        try:
            diag = strip(sl.render(self._data(), cols=267, lines=58)[-1])
            self.assertNotIn("🧮", diag)
        finally:
            sl.SEGMENTS["memory"] = saved

    def test_short_terminal_drops_diag_row(self):
        lines = sl.render(self._data(), cols=267, lines=24)  # < LINE2_MIN_LINES
        self.assertTrue(all("🧮" not in strip(l) for l in lines))

    def test_identity_line_path_and_branch(self):
        ident = strip(sl.render(self._data(), cols=267, lines=58)[0])
        self.assertIn("~/.claude", ident)
        self.assertIn("master", ident)

    def test_all_segments_off_still_emits_identity(self):
        """render() must always emit ≥1 line (matches bash which always prints the identity line)."""
        saved = dict(sl.SEGMENTS)
        for k in sl.SEGMENTS:
            sl.SEGMENTS[k] = False
        sl.SEGMENTS["path"] = True   # path flag must stay True per CONFIG invariant
        try:
            result = sl.render(self._data(), cols=267, lines=58)
            self.assertGreaterEqual(len(result), 1)
            self.assertTrue(any(strip(l) for l in result), "output must not be all blank")
        finally:
            sl.SEGMENTS.update(saved)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/.claude/plugins/uz-kit && python3 tests/test_status_line.py`
Expected: FAIL — `AttributeError: ... 'render'`.

- [ ] **Step 3: Write minimal implementation**

Append to `status-line.py`:

```python
# ═══ Identity-line helpers ════════════════════════════════════════════════════
def _display_dir(work_dir, home):
    shown = work_dir
    if home and work_dir.startswith(home):
        shown = "~" + work_dir[len(home):]
    if len(shown) > 20:
        project = os.path.basename(work_dir.rstrip("/")) or work_dir
        return "~/…/" + project if shown.startswith("~") else "…/" + project
    return shown


def _dirty_mark(dirty):
    if dirty == "untracked":
        return f" {RED}✗{RESET}"
    if dirty == "modified":
        return f" {YELLOW}~{RESET}"
    return ""


def _todo_seg(state, text, cols):
    if not text:
        return None
    limit = max(20, min(80, cols - 50))
    if len(text) > limit:
        text = text[:limit - 1] + "…"
    if state == "in_progress":
        return f"📝 {YELLOW}{text}{RESET}"
    if state == "pending":
        return f"⏸  {GREY}{text}{RESET}"
    return None


def _enabled(key, cols):
    """A segment shows when its flag is on AND the width tier permits it."""
    return SEGMENTS.get(key, False) and cols >= TIERS.get(key, 0)


def _join(parts):
    return " | ".join(p for p in parts if p)


def render(data, cols, lines):
    out = []

    # ── Identity line (always) ──────────────────────────────────────────────
    ident = ""
    if SEGMENTS.get("path", True):
        ident = f"{BLUE}{_display_dir(data['work_dir'], data['home'])}{RESET}"
    if _enabled("branch", cols) and data.get("branch"):
        ident += f" {GREY}[🌿 {data['branch']}]{RESET}"
    if SEGMENTS.get("dirty", True):
        ident += _dirty_mark(data.get("dirty", "clean"))
    todo = _todo_seg(data.get("todo_state"), data.get("todo_text"), cols) \
        if SEGMENTS.get("todo", True) else None
    if todo:
        ident += f" | {todo}"
    out.append(ident)

    # ── Model row (lines >= LINE1_MIN_LINES) ────────────────────────────────
    if lines >= LINE1_MIN_LINES:
        row = []
        if _enabled("model", cols):
            row.append(seg_model(data["model_name"], data["model_id"]))
        if _enabled("time_ago", cols):
            row.append(seg_time_ago(data.get("ago")))
        if _enabled("clock", cols):
            row.append(seg_clock(data["clock"]))
        if _enabled("effort", cols):
            row.append(seg_effort(data.get("effort", "")))
        if _enabled("lines", cols):
            row.append(seg_lines(data["added"], data["removed"]))
        if _enabled("cost", cols):
            row.append(seg_cost(data["cost"]))
        if _enabled("total_time", cols):
            row.append(seg_total_time(data["total_ms"]))
        if _enabled("api_time", cols):
            row.append(seg_api_time(data["api_ms"]))
        line = _join(row)
        if line:
            out.append(line)

    # ── Diagnostics row (lines >= LINE2_MIN_LINES) ──────────────────────────
    if lines >= LINE2_MIN_LINES:
        if cols >= DIAG_MIN_COLS:
            row = []
            if _enabled("dimensions", cols):
                row.append(seg_dimensions(cols, lines, data.get("dim_assumed", False)))
            if SEGMENTS.get("context", True):
                row.append(seg_context(data["context_pct"], data["context_max"]))
            if _enabled("chat_size", cols):
                row.append(seg_chat_size(data.get("chat_bytes")))
            if _enabled("memory", cols):
                row.append(seg_memory(data.get("mem_bytes")))
            if _enabled("rate_limits", cols):
                row.append(seg_rate_limits(data.get("rate_limits")))
            line = _join(row)
            if line:
                out.append(line)
        elif SEGMENTS.get("context", True):
            color = pick_color(int(data["context_pct"]), CONTEXT_RAMP)
            out.append(f"📊 {color}{data['context_pct']}%{RESET}")

    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ~/.claude/plugins/uz-kit && python3 tests/test_status_line.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd ~/.claude/plugins/uz-kit
git add status-line.py tests/test_status_line.py
git commit -m "feat(status-line): render() with flags + responsive tiers (TDD)"
```

---

### Task 8: `main()` (stdin → render → stdout) + integration test

**Files:**
- Modify: `~/.claude/plugins/uz-kit/status-line.py`
- Test: `~/.claude/plugins/uz-kit/tests/test_status_line.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_status_line.py`:

```python
import subprocess as _sp


class TestMainIntegration(unittest.TestCase):
    def test_end_to_end_stdin(self):
        payload = {
            "model": {"display_name": "Opus 4.8", "id": "claude-opus-4-8"},
            "workspace": {"current_dir": os.getcwd()},
            "context_window": {"used_percentage": 12, "context_window_size": 1_000_000},
        }
        proc = _sp.run(
            ["python3", _MODULE_PATH],
            input=json.dumps(payload),
            capture_output=True, text=True,
            env={**os.environ, "STATUSLINE_COLS": "267", "STATUSLINE_LINES": "58"},
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = ANSI_RE.sub("", proc.stdout)
        self.assertIn("Opus 4.8", out)
        self.assertIn("267×58", out)
        self.assertIn("12% of 1M", out)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/.claude/plugins/uz-kit && python3 tests/test_status_line.py`
Expected: FAIL — script prints nothing / errors (no `main`, no `__main__` entry).

- [ ] **Step 3: Write minimal implementation**

Append to `status-line.py`:

```python
import sys
import json
import time


def build_data(raw, env):
    model = raw.get("model") or {}
    cost = raw.get("cost") or {}
    ctx = raw.get("context_window") or {}
    workspace = raw.get("workspace") or {}
    work_dir = workspace.get("current_dir") or "."
    transcript = raw.get("transcript_path") or ""

    cols, lines, assumed = terminal_size(env)
    branch, dirty = git_info(work_dir)

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
        "branch": branch, "dirty": dirty,
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
```

- [ ] **Step 4: Run the full suite**

Run: `cd ~/.claude/plugins/uz-kit && python3 tests/test_status_line.py`
Expected: PASS — every test class green.

- [ ] **Step 5: Hoist stdlib imports + commit**

Before committing, move all stdlib imports to the top of `status-line.py` (immediately after the module docstring, before the `CONFIG` block). The incremental tasks appended `import math`, `from datetime import datetime`, `import os`, `import subprocess`, `import sys`, `import json`, and `import time` mid-file, which violates PEP 8 and triggers flake8 E402. Also remove the redundant local `import json` inside `current_todo()` — it is already at module level after this hoist. The final top-of-file import block should be:

```python
import json
import math
import os
import subprocess
import sys
import time
from datetime import datetime
```

Then commit:

```bash
cd ~/.claude/plugins/uz-kit
chmod +x status-line.py
git add status-line.py tests/test_status_line.py
git commit -m "feat(status-line): main() entrypoint + integration test (TDD)"
```

---

### Task 9: Side-by-side parity check, then repoint settings.json

**Files:**
- Modify: `~/.claude/settings.json:128-131`

- [ ] **Step 1: Mechanical parity check at multiple widths**

Run (strips ANSI, normalises the known intentional deltas, then diffs `.sh` vs `.py` — exits non-zero on unexpected mismatch):

```bash
cd ~/.claude
TP=$(ls -t projects/*/*.jsonl | head -1)
JSON="{\"model\":{\"display_name\":\"Opus 4.8\",\"id\":\"claude-opus-4-8\"},\"workspace\":{\"current_dir\":\"$PWD\"},\"transcript_path\":\"$PWD/$TP\",\"context_window\":{\"used_percentage\":12,\"context_window_size\":1000000},\"effort\":{\"level\":\"medium\"},\"cost\":{\"total_cost_usd\":0.42,\"total_lines_added\":120,\"total_lines_removed\":30,\"total_duration_ms\":650000,\"total_api_duration_ms\":120000}}"
strip_ansi() { sed 's/\x1b\[[0-9;]*m//g'; }
# Known intentional deltas (both are expected — not regressions):
#   1. cost segment: OFF by default in .py (SEGMENTS["cost"]=False). The bash
#      original shows cost at cols>=65. The `grep -v '\$'` filter below
#      deliberately masks this delta so it does not fail the check.
#   2. context color: .py uses the user-specified 8-band ramp; .sh uses the old
#      5-band ramp. This check compares segment presence/order only (plain text
#      after ANSI stripping), NOT color codes — the color delta is expected.
# Prerequisite: grep -P (PCRE / GNU grep) must be available. On systems where
# grep -P is absent, replace grep -oP with: grep -oE '[[:print:]]+' (less precise).
PASS=true
for W in 267 120 90 65 40; do
  SH_OUT=$(echo "$JSON" | STATUSLINE_COLS=$W STATUSLINE_LINES=58 bash statusline.sh | strip_ansi)
  PY_OUT=$(echo "$JSON" | STATUSLINE_COLS=$W STATUSLINE_LINES=58 python3 plugins/uz-kit/status-line.py | strip_ansi)
  # Extract segment labels (emoji + text tokens) for order comparison, ignoring cost.
  SH_SEG=$(echo "$SH_OUT" | grep -oP '[\x{1F300}-\x{1FFFF}][^\|]+' | grep -v '\$' | tr -d ' ')
  PY_SEG=$(echo "$PY_OUT" | grep -oP '[\x{1F300}-\x{1FFFF}][^\|]+' | grep -v '\$' | tr -d ' ')
  if [ "$SH_SEG" != "$PY_SEG" ]; then
    echo "MISMATCH at cols=$W"
    echo "  sh: $SH_SEG"
    echo "  py: $PY_SEG"
    PASS=false
  else
    echo "OK cols=$W"
  fi
done
$PASS || { echo "Parity check FAILED — do not repoint settings.json"; exit 1; }
echo "Parity check PASSED"
```

Expected: Every width prints `OK cols=N`; script exits 0. If any width prints `MISMATCH`, stop, investigate, and fix before proceeding to Step 2.

- [ ] **Step 2: Repoint settings.json**

Edit `~/.claude/settings.json` `statusLine` block (currently lines 128-131):

```json
  "statusLine": {
    "type": "command",
    "command": "python3 ~/.claude/plugins/uz-kit/status-line.py"
  },
```

- [ ] **Step 3: Verify in a live render**

Run: `echo "$JSON" | STATUSLINE_COLS=267 STATUSLINE_LINES=58 python3 ~/.claude/plugins/uz-kit/status-line.py`
Expected: Three lines render without traceback; identity + model + diagnostics rows present.

- [ ] **Step 4: Commit the settings change**

```bash
cd ~/.claude
git add settings.json
git commit -m "chore: point statusLine at uz-kit/status-line.py (bash kept as fallback)"
```

- [ ] **Step 5: Rollback (if needed)**

If the Python version fails silently after cutover, revert `settings.json` to the bash original with this exact command — no project context required:

```bash
cd ~/.claude
sed -i 's|"command": "python3 ~/.claude/plugins/uz-kit/status-line.py"|"command": "~/.claude/statusline.sh"|' settings.json
git add settings.json
git commit -m "revert: restore statusLine to statusline.sh fallback"
```

Or use `git revert HEAD` if the settings commit was already pushed.

---

## Self-Review

**Spec coverage:**
- Modular, functions, file at `uz-kit/status-line.py` → Tasks 1-8. ✓
- Flags per option defined at top (`SEGMENTS`) → Task 4. ✓
- Per-segment one-by-one toggles (model/time/effort/…) → `SEGMENTS` keys cover every segment; `render()` gates each on its flag → Tasks 4, 7. ✓
- pct ramp `<10 white, >10 cyan, >15 blue, >20 green, >25 yellow, >30 orange, >40 red, >50 magenta` → `CONTEXT_RAMP` + Task 1 tests. ✓
- Don't edit the `.sh` → only `settings.json` is modified (Task 9). ✓
- Responsive tiers + flags combined (chosen in design) → `TIERS` + `_enabled()` → Task 7. ✓
- Last-line order `dims | context | chat | memory | rate` → Task 7 test `test_diag_row_order_and_segments`. ✓
- TDD throughout → every task is test-first. ✓

**Placeholder scan:** No TBD/TODO/"handle edge cases" — every code step contains complete, runnable code. ✓

**Type consistency:** `current_todo` returns `(state, text)` and is consumed as such in `build_data`; `seg_*` builders return `str | None` and are filtered by `_join`; `proc_rss_bytes`/`transcript_bytes` return `int | None` consumed by `seg_memory`/`seg_chat_size` which accept `None`. Builder names match between definition (Tasks 4-5) and use (Task 7). ✓

**Known intentional deltas from the `.sh`:** decimal separator in the rare `<10 KB` byte case uses `.` instead of the locale comma `numfmt` emits (no impact for live MB/100s-of-KB values); `cost` defaults OFF (`SEGMENTS["cost"]=False`) — the bash original shows cost at cols≥65, so the Task 9 parity script's `grep -v '\$'` filter deliberately masks this known delta to prevent false failures; the context color ramp is the user-specified 8-band one (replaces the old 5-band ramp: `<20` white/`<30` cyan/`<40` green/`<60` orange/`≥60` red) — the Task 9 parity check compares segment presence/order only after ANSI stripping, so this color change does not affect the check result. `STATUSLINE_COLS=0` / `STATUSLINE_LINES=0` are treated as absent (fall through to stty/assumed), matching the `.sh` behavior of `[ -z "$TERM_COLS" ]` treating a falsy value as unset.
