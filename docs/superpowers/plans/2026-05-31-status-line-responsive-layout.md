# Status Line Responsive Layout Engine — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the status line's hardcoded per-segment width thresholds with a declarative 3-line template plus a real width-aware best-fit packer; each segment builder cooperates by auto-deprioritizing itself (compact form or hide) for the space it is offered. Also harden rate-limit rendering against stale buckets.

**Architecture:** Two responsibilities, clearly split.
- **Orchestrator** (`render` → `pack_line`) is the authority. It walks each line's segment keys left→right, computes the display width *available at that position* (`budget − used − separator`), asks the builder for content at that width, and decides: `None`/empty → drop; fits → keep; doesn't fit → skip and keep trying the rest (best-fit). A `PINNED` set forces a segment to stay even if it overflows.
- **Builders** cooperate. Each is `seg_x(data, avail) -> str | None`: it returns `None` when it has no data, otherwise the richest of its internal *variants* (rich → compact) that fits `avail`, via `_first_fitting`; if even its smallest variant doesn't fit, it returns `None` (self-deprioritizes). Two "floor" builders (`path`, `context`) never return `None` — they fall back to a minimal form and are pinned.

This removes the old `TIERS` table and the scattered `cols < N` hide-thresholds: "too narrow" now means "not enough `avail` here," decided by the orchestrator, with builders shrinking themselves to help.

**Tech Stack:** Python 3 stdlib only (`re`, `unicodedata`, `collections.namedtuple`). Tests via `unittest` (`tests/test_status_line.py`), module loaded with `importlib` as `sl`.

---

## Context for the implementer

> **On-disk state (read before implementing):** The current `status-line.py` already contains most of this plan's architecture — `char_width`/`visible_width`/`_first_fitting`, the full `seg_*(data, avail)` builders, `BUILDERS`, `LAYOUT`, `PINNED`, `pack_line`, and `render` are all present. The old `TIERS`/`_enabled`/`LINE*_MIN_LINES` code is already gone. **The remaining work is: Task 4 (rate-limit staleness with `now`-injection and the 7d long-date tier), updating the two known-failing tests (see Task 2 Step 1a and Task 5 Step 1a below), and Task 5's documentation assertions.** Tasks 1–3 serve as the spec-of-record for review and should be verified, not re-implemented from scratch.

- Single source file: `/home/user-zero/.claude/plugins/uz-kit/status-line.py`. Read it fully before starting.
- Tests: `/home/user-zero/.claude/plugins/uz-kit/tests/test_status_line.py`. The module loads as `sl` via `load_module()`; `strip(s)` removes ANSI for assertions. **Run from the `uz-kit` root**: `python3 tests/test_status_line.py -v`.
- **Do NOT touch** `statusline.sh` — production fallback. Only `status-line.py` and the test file change.
- Builders move to the uniform `seg_x(data, avail)` contract, registered in a `BUILDERS` dict so the packer can call any segment by key.
- Prior round's features stay (inside builders): effort levels `low/medium/auto/high/xhigh/max/ultracode`, half-bar context, path→basename collapse, worktree icon 🌿/🌳.
- `data` is the dict from `build_data()`. This plan adds `"cols"`, `"lines"` (so `seg_dimensions` can render terminal size as content, distinct from `avail`) and `"now"` (epoch seconds, so `seg_rate_limits` can judge bucket staleness; injectable for tests).

### Final API (type contract — keep names consistent across tasks)

```python
def char_width(ch) -> int                      # 0, 1, or 2
def visible_width(s) -> int                    # display cells, ANSI-stripped
def _first_fitting(variants, avail) -> str | None   # richest variant that fits, else None

# builders (ALL share this signature; `avail` = display cells available here)
def seg_path(data, avail) -> str               # floor: never None
def seg_branch(data, avail) -> str | None
def seg_dirty(data, avail) -> str | None
def seg_todo(data, avail) -> str | None
def seg_model(data, avail) -> str | None
def seg_time_ago(data, avail) -> str | None
def seg_clock(data, avail) -> str | None
def seg_effort(data, avail) -> str | None      # variants: [full, bar-only]
def seg_lines(data, avail) -> str | None
def seg_cost(data, avail) -> str | None
def seg_total_time(data, avail) -> str | None
def seg_api_time(data, avail) -> str | None
def seg_dimensions(data, avail) -> str | None
def seg_context(data, avail) -> str            # floor: never None; variants [full, mid, pct]
def seg_chat_size(data, avail) -> str | None
def seg_memory(data, avail) -> str | None
def seg_rate_limits(data, avail) -> str | None # drops stale buckets; variants [with-reset, no-reset]

BUILDERS: dict[str, Callable]                  # key -> builder
Line = namedtuple("Line", "min_rows segments")
LAYOUT: list[Line]
PINNED: set[str]                               # {"path", "context"}
# Note: seg_cost is wired through LAYOUT and BUILDERS but SEGMENTS["cost"] = False
# by default — it is present and callable but never rendered unless toggled on.
RIGHT_MARGIN: int                              # 4
SEP: str                                       # " | "

def pack_line(keys, data, cols) -> str
def render(data, cols, lines) -> list[str]
```

### Who decides show/hide

| concern | owner |
|---|---|
| Is there content at all? (`None` for no data) | builder |
| Detail level for the offered space (full/compact) | builder, via `_first_fitting(variants, avail)` |
| Self-hide rather than show cramped | builder, via `_first_fitting` returning `None` |
| How much space is available here (`avail`) | orchestrator (`pack_line`) |
| Skip `None`/empty; count separators; best-fit | orchestrator |
| Force-keep despite overflow (`path`, `context`) | orchestrator (`PINNED`) |
| Line placement, left→right priority, row gate | template (`LAYOUT`) |

---

## Task 1: Display-width measurement + variant fitting

**Files:** Modify `status-line.py` (add `char_width`, `visible_width`, `_first_fitting`; `import re`, `import unicodedata`). Test `tests/test_status_line.py`.

- [ ] **Step 1: Write failing tests** — `TestVisibleWidth` (ascii=len; ANSI zero-width; SMP emoji `📊📝🧠💬📡💾🧮🌿🌳📃` width 2; `⏰⏸⚡` width 2; box `▁▃▄▆█▌░` width 1; `✗~↺` width 1; combining `é` width 1; `"📊 12%"` width 6) and `TestFirstFitting` (richest-that-fits; first when all fit; None when none fit; skips falsy variants).
- [ ] **Step 2: Run, verify fail** — `python3 tests/test_status_line.py -v` → `AttributeError: ... 'visible_width'`.
- [ ] **Step 3: Implement** — after `pick_color`:

```python
import re
import unicodedata

_ANSI_RE = re.compile(r"\033\[[0-9;]*m")
_WIDE_BMP = {0x23F0, 0x23F8, 0x26A1}  # ⏰ ⏸ ⚡ (BMP symbols drawn 2 cells wide)


def char_width(ch):
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
    return sum(char_width(c) for c in _ANSI_RE.sub("", s))


def _first_fitting(variants, avail):
    """First (richest) truthy variant whose display width fits avail, else None."""
    for v in variants:
        if v and visible_width(v) <= avail:
            return v
    return None
```

- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** — `git commit -m "feat(statusline): display-width measurement + variant fitting"`.

---

## Task 2: Cooperative segment builders + BUILDERS registry

**Files:** Modify `status-line.py` (rewrite the builders section; add `BUILDERS`; delete old `TIERS`/`DIAG_MIN_COLS`). Test `tests/test_status_line.py`.

- [ ] **Step 1: Add `_data(**over)` test factory** (full data dict incl. `"cols":200,"lines":50,"now":<future-safe>`) and failing `TestCooperativeBuilders`. **Also fix the known-failing rate-limit test (Step 1a).**
  - **Step 1a (known-failing test fix):** `TestCooperativeBuilders.test_rate_limits_drops_reset_then_hides` currently uses `"resets_at": 0`, which after Task 4 will be treated as a stale bucket (dropped). Update this test to use a *future* `resets_at` so it remains valid post-Task-4:
    ```python
    def test_rate_limits_drops_reset_then_hides(self):
        rl = {"five_hour": {"used_percentage": 42, "resets_at": 9_999_999_999}}
        self.assertIn("↺", strip(sl.seg_rate_limits(_data(rate_limits=rl), 200)))
        narrow = strip(sl.seg_rate_limits(_data(rate_limits=rl), 12))
        self.assertNotIn("↺", narrow)
        self.assertIn("5h", narrow)
        self.assertIsNone(sl.seg_rate_limits(_data(rate_limits={}), 200))
    ```
  - branch: content at avail 50, `None` at avail 5, `None` when no branch; worktree icon 🌳 vs 🌿.
  - effort: word present at avail 30, absent (bar only) at avail 10, `None` at avail 5, `None` when empty; all 7 levels render full at avail 30.
  - context: `of 1M` at 200, no `of 1M` but has `█` at 18, exactly `📊 12%` at 8, never `None` at 2.
  - dimensions: `120×40` at 200, `None` at 3.
  - chat/memory: present at 200, `None` at 3, `None` when bytes None.
  - todo: truncates/hides by avail.
  - path never None; registry has all keys callable.
- [ ] **Step 2: Run, verify fail** (new signatures / `BUILDERS` absent).
- [ ] **Step 3: Delete `TIERS` and `DIAG_MIN_COLS`** from CONFIG (keep `PATH_MAX_LEN`, `CONTEXT_BAR_CELLS`).
- [ ] **Step 4: Implement builders** — every builder is `seg_x(data, avail)` returning `_first_fitting([rich, …, minimal], avail)` (or `None` for no-data; floor for `path`/`context`). Key forms:
  - `seg_effort`: `full = "🧠 {bar}{RESET} {color}{effort}{RESET}"`, `compact = "🧠 {bar}{RESET}"`.
  - `seg_context`: variants `[full="📊 {bar} {pct}% of {max}", mid="📊 {bar} {pct}%", pct_only="📊 {pct}%"]`, `or pct_only` floor.
  - `seg_branch`/`seg_dirty`/`seg_model`/`seg_time_ago`/`seg_clock`/`seg_lines`/`seg_cost`/`seg_total_time`/`seg_api_time`/`seg_dimensions`/`seg_chat_size`/`seg_memory`: single-variant `_first_fitting([form], avail)` with `None` for no-data.
  - `seg_todo`: truncate text to `avail - 4`; `None` if `avail - 4 < 6`.
  - Register all in `BUILDERS = {...}`.
- [ ] **Step 5: Remove duplicate `_display_dir`/`_dirty_mark`/`_todo_seg` from old identity-helpers section** (now provided by builders).
- [ ] **Step 6: Run, verify `TestCooperativeBuilders` passes** (old-signature tests fixed in Task 3).
- [ ] **Step 7: Commit** — `feat(statusline): cooperative (data, avail) builders + registry`.

---

## Task 3: Best-fit packer, declarative LAYOUT, new render()

**Files:** Modify `status-line.py` (`RIGHT_MARGIN`, `SEP`, `Line`, `LAYOUT`, `PINNED`, `pack_line`, `render`; add `"cols"`/`"lines"` to `build_data`; delete `_enabled`, `_join`, `LINE1_MIN_LINES`, `LINE2_MIN_LINES`). Test file.

- [ ] **Step 1: Fix old-signature tests** (`seg_model(_data(),200)`, `seg_effort(_data(effort="high"),200)`, `seg_context(_data(context_pct=12),200)`, `seg_todo(_data(...),cols)`, `seg_dimensions(_data(cols=C,lines=R,dim_assumed=A),200)`). Add `TestPackLine` (keeps fitting; best-fit skips overflow keeps smaller; flag-off not built; pinned path present when narrow; pinned context present when narrow; respects `RIGHT_MARGIN`) and `TestRenderLayout` (3 lines tall+wide; row gating 10→1, 25→2; identity never empty; `PINNED` contains path+context).
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement:**

```python
RIGHT_MARGIN = 4
SEP = " | "

Line = namedtuple("Line", "min_rows segments")
LAYOUT = [
    Line(0,  ["path", "branch", "dirty", "todo"]),
    Line(20, ["model", "time_ago", "clock", "effort", "lines",
              "cost", "total_time", "api_time"]),
    Line(30, ["dimensions", "context", "chat_size", "memory", "rate_limits"]),
]
PINNED = {"path", "context"}


def pack_line(keys, data, cols):
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
    out = []
    for ln in LAYOUT:
        if lines < ln.min_rows:
            continue
        packed = pack_line(ln.segments, data, cols)
        if packed:
            out.append(packed)
    return out
```

Add `"cols": cols, "lines": lines,` to the `build_data` dict. Delete `_enabled`, `_join`, `LINE1_MIN_LINES`, `LINE2_MIN_LINES`.

- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Live smoke** — wide (cols=200) → 3 full lines; narrow (cols=55) → segments drop right-to-left, effort bar-only, context compacts, identity+context never disappear, no wrap.
- [ ] **Step 6: Commit** — `feat(statusline): width-aware best-fit packer + declarative LAYOUT`.

---

## Task 4: Rate-limit staleness hardening

**Why:** Live output showed `5h: 107% (↺ 14:10)` at ~16:40 — an impossible percent and a reset already in the past. The script is stateless; this is a stale `rate_limits` bucket from the upstream payload that we render anyway. Rules:
- **a bucket whose `resets_at` is in the past is stale → drop it;**
- render the reset only when it is in the future;
- **same-day resets show time only (`↺ 14:10`); future-day resets (e.g. the 7d/weekly bucket) include the date, in a long form when there is room (`↺ Jun 07 14:10`), degrading to a short numeric form (`↺ 06-07 14:10`), then to no suffix when cramped.**

**Files:** Modify `status-line.py` (`_rate_str`/`seg_rate_limits`; add `"now"` to `build_data`). Test file.

- [ ] **Step 1: Write failing tests** (`TestRateLimits`). Before writing these tests, add `"now": 1_000_000` to the `_data` factory's base dict so the `now=NOW` overrides in these tests work correctly (the key must exist in the base dict for `update()` to be a no-op when not overridden, and for `seg_rate_limits` to call `data.get("now", 0)` correctly):

```python
NOW = 1_000_000  # fixed epoch for deterministic tests; matches _data factory default


def test_future_reset_shown_and_stale_dropped(self):
    rl = {"five_hour": {"used_percentage": 42, "resets_at": NOW + 3600},
          "seven_day": {"used_percentage": 107, "resets_at": NOW - 60}}  # stale
    out = strip(sl.seg_rate_limits(_data(rate_limits=rl, now=NOW), 200))
    self.assertIn("5h: 42%", out)
    self.assertIn("↺", out)            # future reset shown
    self.assertNotIn("7d", out)        # stale bucket dropped
    self.assertNotIn("107%", out)

def test_all_stale_returns_none(self):
    rl = {"five_hour": {"used_percentage": 50, "resets_at": NOW - 1}}
    self.assertIsNone(sl.seg_rate_limits(_data(rate_limits=rl, now=NOW), 200))

def test_no_resets_at_is_kept_without_suffix(self):
    rl = {"five_hour": {"used_percentage": 30}}  # cannot judge staleness -> keep
    out = strip(sl.seg_rate_limits(_data(rate_limits=rl, now=NOW), 200))
    self.assertIn("5h: 30%", out)
    self.assertNotIn("↺", out)

def test_reset_drops_to_no_suffix_when_narrow(self):
    rl = {"five_hour": {"used_percentage": 42, "resets_at": NOW + 3600}}
    narrow = strip(sl.seg_rate_limits(_data(rate_limits=rl, now=NOW), 12))
    self.assertNotIn("↺", narrow)
    self.assertIn("5h", narrow)

def test_far_future_bucket_shows_long_date_when_room(self):
    rl = {"seven_day": {"used_percentage": 30, "resets_at": NOW + 7 * 86400}}
    wide = strip(sl.seg_rate_limits(_data(rate_limits=rl, now=NOW), 200))
    self.assertRegex(wide, r"↺ [A-Z][a-z]{2} \d\d")   # e.g. "↺ Jan 19"
```

- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement:**

```python
def _reset_suffix(reset, now, detail):
    """Reset stamp at the requested detail: 'long' | 'short' | 'none'.
    Same-day resets show time only; future-day resets include the date."""
    if reset is None or detail == "none":
        return ""
    dt = datetime.fromtimestamp(reset)
    if dt.date() == datetime.fromtimestamp(now).date():
        return f" (↺ {dt.strftime('%H:%M')})"
    if detail == "long":
        return f" (↺ {dt.strftime('%b %d %H:%M')})"   # e.g. Jun 07 14:10
    return f" (↺ {dt.strftime('%m-%d %H:%M')})"        # e.g. 06-07 14:10


def _rate_str(rate_limits, now, detail):
    parts = []
    for key in sorted(rate_limits):
        info = rate_limits[key] or {}
        pct = info.get("used_percentage")
        if pct is None:
            continue
        reset = info.get("resets_at")
        if reset is not None:
            reset = int(reset)
            if reset <= now:                 # bucket already reset => stale, skip
                continue
        color = rate_color(pct)
        suffix = _reset_suffix(reset, now, detail)
        parts.append(f"{rate_key_label(key)}: {color}{round(float(pct))}%{RESET}{suffix}")
    return "⚡ " + " | ".join(parts) if parts else None


def seg_rate_limits(data, avail):
    rate_limits = data.get("rate_limits")
    if not rate_limits:
        return None
    now = data.get("now", 0)
    return _first_fitting([_rate_str(rate_limits, now, "long"),
                           _rate_str(rate_limits, now, "short"),
                           _rate_str(rate_limits, now, "none")], avail)
```

Add `"now": int(time.time()),` to the `build_data` dict.

- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** — `fix(statusline): drop stale rate-limit buckets (past resets_at)`.

---

## Task 5: In-file documentation block (how to adjust/extend)

**Files:** Modify `status-line.py` (module docstring + `# ═══ HOW TO CUSTOMIZE` block before `# ═══ Entry point`). Test file.

- [ ] **Step 1: Failing `TestDocumentation`** — source contains all 16 segment keys and the phrases `HOW TO CUSTOMIZE`, `Add a NEW segment`, `Reorder`, `Re-enable`, `auto-deprioritize`. **Also fix the known-failing doc test (Step 1a).**
  - **Step 1a (known-failing test fix):** `TestDocumentation.test_has_customization_guide` currently asserts `"add a NEW segment"` (lowercase `a`), but the source uses `"Add a NEW segment"` (uppercase `A`). Update the assertion to match the source exactly:
    ```python
    for phrase in ("HOW TO CUSTOMIZE", "Add a NEW segment",
                   "Reorder", "Re-enable", "auto-deprioritize"):
    ```
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Add the block** — three knobs (SEGMENTS/LAYOUT/BUILDERS), the show/hide ownership rule (packer authority; builders auto-deprioritize; PINNED path+context), a key→description catalog of all 16 segments, and Common edits (Toggle / Reorder / Move / Re-enable / Add a NEW segment with the `seg_foo(data, avail)` + `_first_fitting` recipe + register/place/flag/test steps). Expand the module docstring to name the three knobs.
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** — `docs(statusline): in-file customization guide + segment catalog`.

---

## Task 6: Final verification and branch finish

- [ ] **Step 1: Full suite** — `python3 tests/test_status_line.py -v` → `OK`.
- [ ] **Step 2: Live renders** at cols 40/55/80/120/200 (and a rate-limit payload with one future + one past bucket) — confirm no wrap, right-to-left dropping, effort/context compaction, identity+context always present, stale bucket gone.
- [ ] **Step 3: Finish the branch** — Announce and use superpowers:finishing-a-development-branch (verify tests, detect env, present options, execute). Note the branch also carries the prior round's features (effort levels, half-bar context, path collapse, worktree icon).

---

## Self-Review (plan author)

- Orchestrator owns fit/drop → Task 3 `pack_line`. ✓
- Builders auto-deprioritize via `_first_fitting` variants / `None` → Tasks 2, 4. ✓
- Uniform `seg_x(data, avail)` + registry → Task 2. ✓
- Real width incl. emoji/ANSI; never `len()` for width; `RIGHT_MARGIN=4` → Tasks 1, 3. ✓
- Declarative `LAYOUT`; reorder/move by editing one list → Task 3. ✓
- `path`+`context` never disappear → `PINNED` + floor returns → Tasks 2, 3. ✓
- Rate-limit staleness (past `resets_at` dropped; date prefix off-day) → Task 4. ✓
- Removes `TIERS`/`DIAG_MIN_COLS`/`_enabled`/`LINE*_MIN_LINES` → Tasks 2, 3. ✓
- Docs catalog + toggle/reorder/move/re-enable/extend → Task 5. ✓
- Prior round's features preserved inside builders → Task 2. ✓
- Type consistency: all builders `(data, avail)`; `data` gains `cols`/`lines` (Task 3) and `now` (Task 4) before use; `_first_fitting`, `pack_line`, `render` signatures stable. ✓
