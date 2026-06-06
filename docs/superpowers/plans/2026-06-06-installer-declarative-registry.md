# Declarative Installer Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse the uz-kit installer's two duplicated tool tables (`[[cli_tool]]` + `[[ai_tool]]`) and 16 hand-written `install_*` functions into ONE declarative `[[tool]]` registry driven by a small set of generic install strategies, plus add version/date autodiscovery and an outdated-`sync` command — net deletion of ~40% of the install-stack code.

**Architecture:** A single `Tool` dataclass loaded from `tools/installer/registry.toml`. Each row declares a `kind` (`pkg|cargo|node|curl|github-release|marketplace|launcher|custom`); a strategy function per kind performs the install, driven entirely by row data (URLs, asset templates, version sources, bin dirs, wiring commands). The 3 genuinely irregular installers (gh apt-repo, sublime, ast-bro) survive behind a `kind="custom"` escape hatch that names a Python function. One `ensure_on_path()` function manages every PATH/bin concern. A `sync` flow compares the installed version against an autodiscovered latest version+date.

**Tech Stack:** Python ≥3.11 (stdlib `tomllib`, `urllib`, `dataclasses`), `rich` (via uv PEP-723 header), `unittest`. No new dependencies. npm/pip remain banned (Node via volta/pnpm, Python via uv).

---

## Scope & decisions (from brainstorming)

- **Unify** `[[cli_tool]]` + `[[ai_tool]]` → one `[[tool]]` table + one engine.
- **Minimal escape hatch**: generic strategies cover ~13 tools; `kind="custom"` keeps only `gh`, `sublime`, `ast-bro`.
- **Best-effort sync**: only tools with a `[tool.version]` block; latest version **and release date**; others reported `skip`/`unknown`, never fatal.
- **Default gentle-ai wiring** = `gentle-ai install --agent claude-code,opencode --scope global` (NO `pi`; editable in TOML). _Override here if you want a different agent set or `--scope workspace`._
- **Folder**: engine modules move to `tools/installer/` and drop the leading underscore; `tools/setup.py` stays as the thin entrypoint.
- **Execution isolation**: run this plan in an isolated worktree (REQUIRED SUB-SKILL: superpowers:using-git-worktrees at execution time).

## File Structure (target)

```
tools/
  setup.py                 # thin wizard entrypoint (rewritten to use installer.engine)
  install-dev-tools.sh     # bootstrap (unchanged)
  status-line.py           # unrelated (unchanged)
  installer/
    __init__.py            # empty (marks the package dir; imports stay flat via sys.path)
    registry.toml          # moved from tools/registry.toml, migrated to [[tool]]
    ui.py                  # moved verbatim from tools/_ui.py
    model.py               # Tool dataclass + load_tools()  (replaces Tool+AITool+loaders)
    paths.py               # ensure_on_path(), detect_os(), detect_arch(), github/crates version
    strategies.py          # one fn per kind (pkg/cargo/node/curl/github-release/marketplace/launcher)
    custom.py              # escape hatch: install_gh, install_subl, install_ast_bro
    engine.py              # check/status/audit/order+drag/install_all/sync
    register.py            # moved verbatim from tools/_register.py (import fix only)
    shell.py               # moved verbatim from tools/_shell.py (import fix only)
tests/
  test_setup.py            # updated import paths + new tests
```

**Deleted at the end:** `tools/_cli_tools.py`, `tools/_ai_tools.py`, `tools/_register.py`, `tools/_shell.py`, `tools/_ui.py`, `tools/registry.toml`.

## Conventions used by strategies

Asset/URL templates expand these placeholders via `str.format`:
- `{ver}` — autodiscovered version (no leading `v`)
- `{os}` — `"Linux"` / `"Darwin"` token the tool expects (declared per row as `os_token`, default `"Linux"`)
- `{arch.deb}` `{arch.go}` `{arch.suffix}` `{arch.machine}` — from `detect_arch()` + `platform.machine()`

`[tool.version].latest` source syntax: `github:owner/repo` | `crates:name` | `json:URL#dotted.key`.

---

## Phase 0 — Worktree + package skeleton (no behavior change)

### Task 0: Create the installer package and move ui.py

**Files:**
- Create: `tools/installer/__init__.py`
- Create: `tools/installer/ui.py` (from `tools/_ui.py`)
- Modify: `tests/test_setup.py` (import path bootstrap)

- [ ] **Step 1: Create the worktree** (execution-time; skip if your harness already isolated you)

```bash
# REQUIRED SUB-SKILL: superpowers:using-git-worktrees
git worktree add .worktrees/installer-registry -b feat/installer-registry
cd .worktrees/installer-registry
```

- [ ] **Step 2: Create the package dir + move ui.py verbatim**

```bash
mkdir -p tools/installer
: > tools/installer/__init__.py
git mv tools/_ui.py tools/installer/ui.py
```

- [ ] **Step 3: Point the test bootstrap at both locations**

In `tests/test_setup.py`, replace the `_TOOLS` sys.path insert block (currently lines ~10-12) with:

```python
_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.join(_HERE, "..", "tools")
_INSTALLER = os.path.join(_TOOLS, "installer")
sys.path.insert(0, _INSTALLER)
sys.path.insert(0, _TOOLS)
```

- [ ] **Step 4: Run the suite to confirm nothing imports `_ui` anymore**

Run: `python3 -m unittest discover -s tests -p 'test_*.py' 2>&1 | tail -3`
Expected: FAIL — `_cli_tools`/`_ai_tools`/`_register`/`_shell` still `from _ui import ...`.

- [ ] **Step 5: Fix the `_ui` import in the still-present old modules**

In each of `tools/_cli_tools.py`, `tools/_ai_tools.py`, `tools/_register.py`, `tools/_shell.py`, and `tools/setup.py`, change `from _ui import` → `from ui import`. (They resolve via the `_INSTALLER` path now on `sys.path`. `setup.py` adds `installer/` to its own `sys.path` — see Step 6.)

- [ ] **Step 6: Make setup.py see the installer package**

In `tools/setup.py`, after the existing `sys.path.insert(0, str(Path(__file__).resolve().parent))` line, add:

```python
sys.path.insert(0, str(Path(__file__).resolve().parent / "installer"))
```

- [ ] **Step 7: Run the suite — green again**

Run: `python3 -m unittest discover -s tests -p 'test_*.py' 2>&1 | tail -3`
Expected: `OK` (same count as before, 113).

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor(installer): create tools/installer package, move ui.py"
```

---

## Phase 1 — Unified model + migrated registry

### Task 1: The unified `Tool` dataclass + loader

**Files:**
- Create: `tools/installer/model.py`
- Test: `tests/test_setup.py`

- [ ] **Step 1: Write the failing test** (append a new class to `tests/test_setup.py`)

```python
import model as mdl  # noqa: E402  (add near the other installer imports)

class ModelTests(unittest.TestCase):
    def test_minimal_row_defaults(self):
        t = mdl.Tool(id="rg", name="ripgrep", kind="pkg", category="search")
        self.assertEqual(t.cmd, "rg")          # cmd defaults to id
        self.assertEqual(t.priority, "P3")
        self.assertEqual(t.requires, [])
        self.assertEqual(t.pkg, {})

    def test_loader_parses_kinds_and_version_block(self):
        import tempfile, pathlib
        toml = (
            '[[tool]]\n'
            'id="lazygit"\nkind="github-release"\ncategory="git"\npriority="P2"\n'
            'repo="jesseduffield/lazygit"\nasset="lazygit_{ver}_Linux_{arch.suffix}.tar.gz"\n'
            'member="lazygit"\nbin_dir="~/.local/bin"\n'
            '[tool.version]\n'
            'latest="github:jesseduffield/lazygit"\n'
            'installed_cmd="lazygit --version"\ninstalled_re="version=(\\\\S+)"\n'
        )
        p = pathlib.Path(tempfile.mkdtemp()) / "r.toml"
        p.write_text(toml)
        tools = mdl.load_tools(p)
        self.assertEqual(len(tools), 1)
        t = tools[0]
        self.assertEqual(t.kind, "github-release")
        self.assertEqual(t.cmd, "lazygit")
        self.assertEqual(t.repo, "jesseduffield/lazygit")
        self.assertEqual(t.version_latest, "github:jesseduffield/lazygit")
        self.assertEqual(t.version_re, r"version=(\S+)")
```

- [ ] **Step 2: Run it (red)**

Run: `python3 -m unittest tests.test_setup.ModelTests -v 2>&1 | tail -5`
Expected: FAIL — `ModuleNotFoundError: No module named 'model'`.

- [ ] **Step 3: Implement `tools/installer/model.py`**

```python
"""The single declarative tool model + loader for the uz-kit installer."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

KINDS = {"pkg", "cargo", "node", "curl", "github-release", "marketplace", "launcher", "custom"}


@dataclass
class Tool:
    id: str
    name: str
    kind: str
    category: str
    priority: str = "P3"
    cmd: str = ""                                   # binary on PATH; defaults to id
    requires: list[str] = field(default_factory=list)
    bin_dir: str = ""                               # dir the binary lands in (ensured on PATH)
    notes: str = ""
    # pkg
    pkg: dict = field(default_factory=dict)         # {debian, arch, brew}
    alias_cmd: str = ""
    # cargo
    crate: str = ""
    # node
    npm_pkg: str = ""
    # curl
    url: str = ""
    shell: str = "sh"
    brew: str = ""                                  # macOS override (e.g. sst/tap/opencode)
    # github-release
    repo: str = ""
    asset: str = ""
    member: str = ""                                # file in archive; defaults to cmd
    raw: bool = False                               # download asset directly as the binary
    os_token: str = "Linux"                         # {os} placeholder value
    # marketplace
    marketplace: str = ""
    marketplace_ref: str = ""
    plugins: list[str] = field(default_factory=list)
    # launcher
    bootstrap_curl: str = ""
    bootstrap_brew: str = ""
    wiring: str = ""
    update: str = ""
    verify: str = ""
    wired_marker: str = ""
    interactive: bool = False
    # custom
    fn: str = ""
    # version / sync
    version_latest: str = ""                        # github:owner/repo | crates:name | json:URL#key
    version_cmd: str = ""
    version_re: str = ""

    def __post_init__(self) -> None:
        if not self.cmd:
            self.cmd = self.id
        if not self.member:
            self.member = self.cmd


def load_tools(manifest_path: str | Path) -> list[Tool]:
    with open(manifest_path, "rb") as fh:
        data = tomllib.load(fh)
    tools: list[Tool] = []
    for row in data.get("tool", []):
        ver = row.get("version", {})
        tools.append(Tool(
            id=row["id"], name=row["name"], kind=row["kind"], category=row["category"],
            priority=row.get("priority", "P3"), cmd=row.get("cmd", ""),
            requires=list(row.get("requires", [])), bin_dir=row.get("bin_dir", ""),
            notes=row.get("notes", ""),
            pkg=dict(row.get("pkg", {})), alias_cmd=row.get("alias_cmd", ""),
            crate=row.get("crate", ""), npm_pkg=row.get("npm_pkg", ""),
            url=row.get("url", ""), shell=row.get("shell", "sh"), brew=row.get("brew", ""),
            repo=row.get("repo", ""), asset=row.get("asset", ""), member=row.get("member", ""),
            raw=bool(row.get("raw", False)), os_token=row.get("os_token", "Linux"),
            marketplace=row.get("marketplace", ""), marketplace_ref=row.get("marketplace_ref", ""),
            plugins=list(row.get("plugins", [])),
            bootstrap_curl=row.get("bootstrap_curl", ""), bootstrap_brew=row.get("bootstrap_brew", ""),
            wiring=row.get("wiring", ""), update=row.get("update", ""), verify=row.get("verify", ""),
            wired_marker=row.get("wired_marker", ""), interactive=bool(row.get("interactive", False)),
            fn=row.get("fn", ""),
            version_latest=ver.get("latest", ""), version_cmd=ver.get("installed_cmd", ""),
            version_re=ver.get("installed_re", ""),
        ))
    return tools


def categories(tools: list[Tool]) -> list[str]:
    """Distinct categories in manifest order (stable, de-duplicated)."""
    seen: list[str] = []
    for t in tools:
        if t.category not in seen:
            seen.append(t.category)
    return seen
```

- [ ] **Step 4: Run it (green)**

Run: `python3 -m unittest tests.test_setup.ModelTests -v 2>&1 | tail -5`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add tools/installer/model.py tests/test_setup.py
git commit -m "feat(installer): unified Tool dataclass + load_tools()"
```

### Task 2: Migrate `registry.toml` to the unified `[[tool]]` schema

**Files:**
- Create: `tools/installer/registry.toml` (from `tools/registry.toml`, rewritten)
- Test: `tests/test_setup.py`

- [ ] **Step 1: Write the failing manifest test** (append to `tests/test_setup.py`)

```python
MANIFEST = os.path.join(_INSTALLER, "registry.toml")   # update the module-level MANIFEST constant

class UnifiedManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tools = mdl.load_tools(MANIFEST)

    def test_loads_and_ids_unique(self):
        ids = [t.id for t in self.tools]
        self.assertGreater(len(ids), 25)
        self.assertEqual(len(ids), len(set(ids)), "duplicate tool ids")

    def test_every_kind_is_known(self):
        for t in self.tools:
            self.assertIn(t.kind, mdl.KINDS, f"{t.id}: bad kind {t.kind}")

    def test_kind_required_fields(self):
        for t in self.tools:
            if t.kind == "pkg":
                self.assertTrue(t.pkg.get("debian") or t.pkg.get("arch") or t.pkg.get("brew"), t.id)
            if t.kind == "cargo":
                self.assertTrue(t.crate, t.id)
            if t.kind == "node":
                self.assertTrue(t.npm_pkg, t.id)
            if t.kind == "curl":
                self.assertTrue(t.url or t.brew, t.id)
            if t.kind == "github-release":
                self.assertTrue(t.repo and t.asset, t.id)
            if t.kind == "marketplace":
                self.assertTrue(t.marketplace and t.marketplace_ref, t.id)
            if t.kind == "launcher":
                self.assertTrue(t.bootstrap_curl or t.bootstrap_brew or t.cmd, t.id)
            if t.kind == "custom":
                self.assertTrue(t.fn, t.id)

    def test_requires_reference_real_ids(self):
        ids = {t.id for t in self.tools}
        for t in self.tools:
            for dep in t.requires:
                self.assertIn(dep, ids, f"{t.id} requires unknown {dep}")

    def test_ai_launchers_present(self):
        ids = {t.id for t in self.tools}
        self.assertTrue({"gentle-ai", "gsd", "superpowers", "agent-toolkit"} <= ids)

    def test_gentle_ai_wiring_excludes_pi(self):
        g = next(t for t in self.tools if t.id == "gentle-ai")
        self.assertIn("--agent", g.wiring)
        self.assertNotIn("pi", g.wiring.split("--agent")[1].split("--")[0])
```

- [ ] **Step 2: Run it (red)**

Run: `python3 -m unittest tests.test_setup.UnifiedManifestTests -v 2>&1 | tail -8`
Expected: FAIL — `registry.toml` not found at the new path.

- [ ] **Step 3: Write `tools/installer/registry.toml`**

Translate every existing `[[cli_tool]]`/`[[ai_tool]]` row into a `[[tool]]` row. Mapping rules:
- `cmd`→`id` (and keep `cmd` only when the binary name differs from the id, e.g. `id="pyright"`, `cmd="pyright-langserver"`).
- `method="pkg"`→`kind="pkg"`; `method="cargo"`→`kind="cargo"` (`cargo_crate`→`crate`); `method="npm"`→`kind="node"`.
- `method="custom"` curl-installers (uv, volta, opencode, pi) → `kind="curl"` with `url=`/`shell=`/`brew=` (opencode: `url="curl -fsSL https://opencode.ai/install | bash"` simplified to `url="https://opencode.ai/install"`, `shell="bash"`, `brew="sst/tap/opencode"`; pi: `url="https://pi.dev/install.sh"`, `shell="sh"`, `requires=["volta"]`; uv: `url="https://astral.sh/uv/install.sh"`; volta: `url="https://get.volta.sh"`, `shell="bash"`, `bin_dir="~/.volta/bin"`).
- pnpm/node stay `kind="custom"` (they call `volta install` subcommands) → `fn="install_pnpm"` / `fn="install_node"` (ported in Task 4), OR model them as a new tiny `node-toolchain` — **keep as `custom` to avoid schema growth**.
- github-release family (yq, lazygit, gron, eza) → `kind="github-release"`:
  - `yq`: `repo="mikefarah/yq"`, `asset="yq_linux_{arch.deb}"`, `raw=true`, `bin_dir="~/.local/bin"`.
  - `lazygit`: `repo="jesseduffield/lazygit"`, `asset="lazygit_{ver}_Linux_{arch.suffix}.tar.gz"`, `member="lazygit"`.
  - `gron`: `repo="tomnomnom/gron"`, `asset="gron-linux-{arch.go}-{ver}.tgz"`, `member="gron"`.
  - `eza`: `repo="eza-community/eza"`, `asset="eza_{arch.machine}-unknown-linux-musl.tar.gz"`, `member="eza"`, plus `pkg={arch="eza",brew="eza"}` so the pkg path is tried first on arch/mac (see strategy note in Task 2 Step 4).
- `gh`, `sublime`, `ast-bro` → `kind="custom"` with `fn="install_gh"`/`install_subl"`/`install_ast_bro"`.
- `[[ai_tool]]` marketplace rows (superpowers, agent-toolkit) → `kind="marketplace"` (carry `marketplace`, `marketplace_ref`, `plugins`).
- gsd → `kind="launcher"`, `cmd="npx"`, `wiring="npx @opengsd/gsd-core@latest"`, `interactive=true`.
- gentle-ai → `kind="launcher"` with `bootstrap_curl`/`bootstrap_brew`, `wiring="gentle-ai install --agent claude-code,opencode --scope global"`, `update="gentle-ai update"`, `verify="gentle-ai doctor"`, `wired_marker="~/.gentle-ai/state.json"`, `interactive=true`.
- Add `[tool.version]` blocks for the github-release tools (lazygit/gron/eza/yq) and for tools with a clean `--version`:
  - lazygit: `latest="github:jesseduffield/lazygit"`, `installed_cmd="lazygit --version"`, `installed_re="version=(\\S+)"`.
  - eza: `latest="github:eza-community/eza"`, `installed_cmd="eza --version"`, `installed_re="v([0-9.]+)"`.
  - gron: `latest="github:tomnomnom/gron"`, `installed_cmd="gron --version"`, `installed_re="version (\\S+)"`.
  - yq: `latest="github:mikefarah/yq"`, `installed_cmd="yq --version"`, `installed_re="v([0-9.]+)"`.

Preserve `category`, `priority`, `requires`, `alias_cmd`, and `notes` verbatim from the old rows. Keep the existing `requires=["volta"]` edges (pnpm, node, mmdc, pyright, pi, codegraph).

- [ ] **Step 4: Run the unified manifest tests (green)**

Run: `python3 -m unittest tests.test_setup.UnifiedManifestTests -v 2>&1 | tail -8`
Expected: PASS (6 tests).

- [ ] **Step 5: Delete the old registry and commit**

```bash
git rm tools/registry.toml
git add tools/installer/registry.toml tests/test_setup.py
git commit -m "feat(installer): migrate registry to unified [[tool]] schema"
```

---

## Phase 2 — Paths + generic strategies

### Task 3: `paths.py` — the single PATH/bin + arch + version-source helpers

**Files:**
- Create: `tools/installer/paths.py`
- Test: `tests/test_setup.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_setup.py`)

```python
import paths as pth  # noqa: E402

class PathsTests(unittest.TestCase):
    def test_ensure_on_path_creates_and_prepends(self):
        import tempfile, pathlib
        d = pathlib.Path(tempfile.mkdtemp()) / "newbin"
        old = os.environ["PATH"]
        self.addCleanup(lambda: os.environ.__setitem__("PATH", old))
        pth.ensure_on_path(d)
        self.assertTrue(d.is_dir())
        self.assertTrue(os.environ["PATH"].startswith(str(d) + os.pathsep))

    def test_ensure_on_path_is_idempotent(self):
        import tempfile, pathlib
        d = pathlib.Path(tempfile.mkdtemp())
        old = os.environ["PATH"]
        self.addCleanup(lambda: os.environ.__setitem__("PATH", old))
        pth.ensure_on_path(d)
        pth.ensure_on_path(d)
        self.assertEqual(os.environ["PATH"].count(str(d)), 1)

    def test_render_asset_template(self):
        arch = {"deb": "amd64", "go": "amd64", "suffix": "x86_64"}
        out = pth.render_asset("lazygit_{ver}_{os}_{arch.suffix}.tar.gz",
                               ver="0.45.0", os_token="Linux", arch=arch, machine="x86_64")
        self.assertEqual(out, "lazygit_0.45.0_Linux_x86_64.tar.gz")
```

- [ ] **Step 2: Run it (red)**

Run: `python3 -m unittest tests.test_setup.PathsTests -v 2>&1 | tail -5`
Expected: FAIL — `No module named 'paths'`.

- [ ] **Step 3: Implement `tools/installer/paths.py`** (move `detect_os`/`detect_arch`/`github_latest_version` from `_cli_tools.py` here, add `ensure_on_path`, `render_asset`, `latest_version`)

```python
"""OS/arch detection, PATH management, and version-source resolution."""
from __future__ import annotations

import json
import os
import platform
import shutil
import urllib.request
from pathlib import Path
from types import SimpleNamespace

from ui import die, info, warn


def detect_os() -> str:
    """Returns 'debian' | 'arch' | 'macos'. Exits if no supported PM found."""
    if shutil.which("apt-get"):
        info("Detected: Debian/Ubuntu (apt)")
        return "debian"
    if shutil.which("pacman"):
        info("Detected: Arch Linux (pacman)")
        return "arch"
    if shutil.which("brew"):
        info("Detected: macOS (Homebrew)")
        return "macos"
    die("No supported package manager found (apt-get, pacman, brew)")
    return ""  # unreachable


def detect_arch() -> dict[str, str]:
    machine = platform.machine()
    mapping = {
        "x86_64":  {"deb": "amd64", "go": "amd64", "suffix": "x86_64"},
        "aarch64": {"deb": "arm64", "go": "arm64", "suffix": "arm64"},
        "armv7l":  {"deb": "armhf", "go": "arm",   "suffix": "armv6"},
    }
    return mapping.get(machine, {"deb": machine, "go": machine, "suffix": machine})


def ensure_on_path(directory: Path) -> None:
    """THE single PATH/bin helper: make the dir exist and sit first on PATH (idempotent)."""
    directory = Path(directory).expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    d = str(directory)
    if d not in os.environ.get("PATH", "").split(os.pathsep):
        os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")


def render_asset(template: str, *, ver: str, os_token: str, arch: dict, machine: str) -> str:
    return template.format(ver=ver, os=os_token,
                           arch=SimpleNamespace(machine=machine, **arch))


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def github_latest_version(repo: str) -> str:
    """Version string without leading 'v' ('' on failure)."""
    v, _ = _github_latest(repo)
    return v


def _github_latest(repo: str) -> tuple[str, str]:
    try:
        data = _get_json(f"https://api.github.com/repos/{repo}/releases/latest")
        return data.get("tag_name", "").lstrip("v"), (data.get("published_at", "") or "")[:10]
    except Exception:
        warn(f"Could not fetch latest version for {repo} (rate-limited or network error)")
        return "", ""


def _crates_latest(name: str) -> tuple[str, str]:
    try:
        data = _get_json(f"https://crates.io/api/v1/crates/{name}")
        ver = data.get("crate", {}).get("newest_version", "")
        date = ""
        for v in data.get("versions", []):
            if v.get("num") == ver:
                date = (v.get("created_at", "") or "")[:10]
                break
        return ver, date
    except Exception:
        warn(f"Could not fetch crates.io version for {name}")
        return "", ""


def _json_latest(spec: str) -> tuple[str, str]:
    """spec = 'URL#dotted.key' — fetch URL, walk dotted key for the version. No date."""
    url, _, key = spec.partition("#")
    try:
        data = _get_json(url)
        for part in key.split("."):
            data = data[part]
        return str(data).lstrip("v"), ""
    except Exception:
        warn(f"Could not fetch json version for {spec}")
        return "", ""


def latest_version(source: str) -> tuple[str, str]:
    """Resolve a [tool.version].latest source to (version, 'YYYY-MM-DD'|'')."""
    scheme, _, rest = source.partition(":")
    if scheme == "github":
        return _github_latest(rest)
    if scheme == "crates":
        return _crates_latest(rest)
    if scheme == "json":
        return _json_latest(rest)
    return "", ""
```

- [ ] **Step 4: Run it (green)**

Run: `python3 -m unittest tests.test_setup.PathsTests -v 2>&1 | tail -5`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add tools/installer/paths.py tests/test_setup.py
git commit -m "feat(installer): paths.py — ensure_on_path, arch, version sources (+date)"
```

### Task 4: `custom.py` — port the 3 irregular installers + node toolchain

**Files:**
- Create: `tools/installer/custom.py`
- Test: `tests/test_setup.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_setup.py`)

```python
import custom as cst  # noqa: E402

class CustomFnTests(unittest.TestCase):
    def test_every_custom_row_has_a_fn(self):
        for t in mdl.load_tools(MANIFEST):
            if t.kind == "custom":
                self.assertTrue(hasattr(cst, t.fn), f"missing {t.fn} for {t.id}")
```

- [ ] **Step 2: Run it (red)**

Run: `python3 -m unittest tests.test_setup.CustomFnTests -v 2>&1 | tail -5`
Expected: FAIL — `No module named 'custom'`.

- [ ] **Step 3: Implement `tools/installer/custom.py`**

Move these functions **verbatim** from `tools/_cli_tools.py` into `custom.py`, changing only their imports (`from ui import ...`, `from paths import ensure_on_path`) and replacing any `local_bin = Path.home()/".local"/"bin"; local_bin.mkdir(...)` with `ensure_on_path(Path.home()/".local"/"bin")`:
- `install_gh` (`_cli_tools.py:360-380`)
- `install_subl` (`_cli_tools.py:477-538`)
- `install_ast_bro` (`_cli_tools.py:464-474`)
- `install_pnpm` (`_cli_tools.py:348-352`)
- `install_node` (`_cli_tools.py:354-358`)

Each keeps the signature `def install_<name>(tool, os_name, arch) -> None` (add an unused `tool` param so the dispatcher can call every custom fn uniformly; update the 2 node fns to the 3-arg signature).

Helper they share (define at top of `custom.py`):

```python
import subprocess
from pathlib import Path
from ui import ok, warn, info
from paths import ensure_on_path

def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)
```

- [ ] **Step 4: Run it (green)**

Run: `python3 -m unittest tests.test_setup.CustomFnTests -v 2>&1 | tail -5`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/installer/custom.py tests/test_setup.py
git commit -m "feat(installer): custom.py escape hatch (gh, sublime, ast-bro, pnpm, node)"
```

### Task 5: `strategies.py` — one function per generic kind

**Files:**
- Create: `tools/installer/strategies.py`
- Test: `tests/test_setup.py`

- [ ] **Step 1: Write the failing tests** (append to `tests/test_setup.py`)

```python
import strategies as strat  # noqa: E402

class StrategyTests(unittest.TestCase):
    def test_dispatch_covers_every_kind(self):
        for t in mdl.load_tools(MANIFEST):
            self.assertIn(t.kind, strat.STRATEGIES, f"no strategy for kind {t.kind}")

    def test_curl_builds_installer_command(self):
        calls = []
        strat._run = lambda c: calls.append(c)          # capture
        t = mdl.Tool(id="uv", name="uv", kind="curl", category="pkg-mgr",
                     url="https://astral.sh/uv/install.sh", shell="sh", bin_dir="~/.local/bin")
        strat.install_curl(t, "debian", {})
        self.assertTrue(any("astral.sh/uv/install.sh" in " ".join(c) for c in calls))

    def test_github_release_raw_downloads_binary(self):
        calls = []
        strat._run = lambda c: calls.append(c)
        strat._latest = lambda repo: ("4.0.0", "2026-01-01")
        t = mdl.Tool(id="yq", name="yq", kind="github-release", category="data",
                     repo="mikefarah/yq", asset="yq_linux_{arch.deb}", raw=True,
                     bin_dir="~/.local/bin")
        strat.install_github_release(t, "debian", {"deb": "amd64", "go": "amd64", "suffix": "x86_64"})
        joined = " ".join(" ".join(c) for c in calls)
        self.assertIn("yq_linux_amd64", joined)

    def test_node_uses_volta_or_pnpm_never_npm(self):
        calls = []
        strat._run = lambda c: calls.append(c)
        strat._cmd_ok = lambda c: c[0] == "volta"       # only volta "works"
        t = mdl.Tool(id="pyright", cmd="pyright-langserver", name="pyright", kind="node",
                     category="lsp", npm_pkg="pyright")
        strat.install_node(t, "debian", {})
        self.assertEqual(calls, [["volta", "install", "pyright"]])

    def test_node_raises_when_no_volta_or_pnpm(self):
        strat._run = lambda c: None
        strat._cmd_ok = lambda c: False
        t = mdl.Tool(id="x", name="x", kind="node", category="lsp", npm_pkg="x")
        with self.assertRaises(RuntimeError) as e:
            strat.install_node(t, "debian", {})
        self.assertIn("npm", str(e.exception).lower())
```

- [ ] **Step 2: Run it (red)**

Run: `python3 -m unittest tests.test_setup.StrategyTests -v 2>&1 | tail -8`
Expected: FAIL — `No module named 'strategies'`.

- [ ] **Step 3: Implement `tools/installer/strategies.py`**

```python
"""One install strategy per Tool.kind, driven entirely by registry data.

Generic kinds live here; the irregular long tail is in custom.py. npm/pip are
banned: node packages go through volta then pnpm, never bare npm.
"""
from __future__ import annotations

import platform
import shutil
import subprocess
from pathlib import Path

import custom
from model import Tool
from paths import ensure_on_path, github_latest_version, render_asset
from ui import info, ok, warn

_latest = github_latest_version          # indirection so tests can stub


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def _cmd_ok(args: list[str]) -> bool:
    try:
        return subprocess.run(args, capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _bin(tool: Tool) -> Path:
    return Path(tool.bin_dir).expanduser() if tool.bin_dir else (Path.home() / ".local" / "bin")


# ── pkg / cargo / node ───────────────────────────────────────────────────────────

def install_pkg(tool: Tool, os_name: str, arch: dict) -> None:
    name = {"debian": tool.pkg.get("debian"), "arch": tool.pkg.get("arch"),
            "macos": tool.pkg.get("brew")}.get(os_name)
    if not name:
        raise RuntimeError(f"{tool.id}: no package name for {os_name}")
    if os_name == "debian":
        _run(["sudo", "apt-get", "install", "-y", name])
    elif os_name == "arch":
        _run(["sudo", "pacman", "-S", "--noconfirm", "--needed", name])
    else:
        _run(["brew", "install", name])


def install_cargo(tool: Tool, os_name: str, arch: dict) -> None:
    if os_name == "arch" and tool.pkg.get("arch"):
        _run(["sudo", "pacman", "-S", "--noconfirm", "--needed", tool.pkg["arch"]])
    elif os_name == "macos" and tool.pkg.get("brew"):
        _run(["brew", "install", tool.pkg["brew"]])
    else:
        _run(["cargo", "install", tool.crate, "--quiet"])


def install_node(tool: Tool, os_name: str, arch: dict) -> None:
    if _cmd_ok(["volta", "--version"]):
        _run(["volta", "install", tool.npm_pkg])
    elif _cmd_ok(["pnpm", "--version"]):
        _ensure_pnpm_global_bin()
        _run(["pnpm", "add", "-g", tool.npm_pkg])
    else:
        raise RuntimeError(
            "No working volta or pnpm found — cannot install node package "
            "(bare npm is intentionally not used). Install volta first.")


def _ensure_pnpm_global_bin() -> None:
    import os
    home = os.environ.get("PNPM_HOME") or str(Path.home() / ".local" / "share" / "pnpm")
    Path(home).mkdir(parents=True, exist_ok=True)
    os.environ["PNPM_HOME"] = home
    ensure_on_path(Path(home))
    subprocess.run(["pnpm", "config", "set", "global-bin-dir", home],
                   capture_output=True, timeout=10)


# ── curl installer ────────────────────────────────────────────────────────────────

def install_curl(tool: Tool, os_name: str, arch: dict) -> None:
    if os_name == "macos" and tool.brew and shutil.which("brew"):
        _run(["brew", "install", tool.brew])
    else:
        _run(["sh", "-c", f"curl -fsSL '{tool.url}' | {tool.shell}"])
    if tool.bin_dir:
        ensure_on_path(_bin(tool))
    ensure_on_path(Path.home() / ".local" / "bin")


# ── github release ────────────────────────────────────────────────────────────────

def install_github_release(tool: Tool, os_name: str, arch: dict) -> None:
    # Prefer a distro/brew package when declared (eza on arch/mac), else download.
    if os_name in ("arch", "macos") and (tool.pkg.get("arch") or tool.pkg.get("brew")):
        return install_pkg(tool, os_name, arch)
    ver, _date = _latest(tool.repo) if "{ver}" in tool.asset else ("", "")
    if "{ver}" in tool.asset and not ver:
        raise RuntimeError(f"{tool.id}: could not determine latest version")
    asset = render_asset(tool.asset, ver=ver, os_token=tool.os_token,
                         arch=arch, machine=platform.machine())
    url = f"https://github.com/{tool.repo}/releases/download/v{ver}/{asset}" if ver \
        else f"https://github.com/{tool.repo}/releases/latest/download/{asset}"
    dest_dir = _bin(tool)
    ensure_on_path(dest_dir)
    if tool.raw:
        target = dest_dir / tool.cmd
        _run(["sh", "-c", f"curl -fsSLo '{target}' '{url}'"])
        target.chmod(0o755)
    else:
        _run(["sh", "-c", f"curl -fsSL '{url}' | tar -xz -C '{dest_dir}' '{tool.member}'"])
        (dest_dir / tool.member).chmod(0o755)


# ── marketplace / launcher ────────────────────────────────────────────────────────

def install_marketplace(tool: Tool, os_name: str, arch: dict) -> None:
    if not shutil.which("claude"):
        warn("claude CLI not on PATH — skipping marketplace tool.")
        return
    _run(["claude", "plugin", "marketplace", "add", tool.marketplace_ref])
    for plugin in tool.plugins:
        _run(["claude", "plugin", "install", f"{plugin}@{tool.marketplace}"])
    if not tool.plugins:
        info(f"Marketplace '{tool.marketplace}' added — enable plugins via /plugin in Claude.")


def install_launcher(tool: Tool, os_name: str, arch: dict) -> None:
    if tool.cmd != "npx" and not shutil.which(tool.cmd):
        boot = tool.bootstrap_brew if (os_name == "macos" and tool.bootstrap_brew) else tool.bootstrap_curl
        if not boot:
            raise RuntimeError(f"{tool.id}: no bootstrap for this OS")
        _run(["sh", "-c", boot])
        ensure_on_path(Path.home() / ".local" / "bin")
    cmd = (tool.wiring or tool.cmd).split()
    (subprocess.run if tool.interactive else _run)(cmd)


def install_custom(tool: Tool, os_name: str, arch: dict) -> None:
    fn = getattr(custom, tool.fn, None)
    if fn is None:
        raise RuntimeError(f"{tool.id}: no custom fn {tool.fn}")
    fn(tool, os_name, arch)


STRATEGIES = {
    "pkg": install_pkg, "cargo": install_cargo, "node": install_node,
    "curl": install_curl, "github-release": install_github_release,
    "marketplace": install_marketplace, "launcher": install_launcher,
    "custom": install_custom,
}
```

- [ ] **Step 4: Run it (green)**

Run: `python3 -m unittest tests.test_setup.StrategyTests -v 2>&1 | tail -8`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add tools/installer/strategies.py tests/test_setup.py
git commit -m "feat(installer): strategies.py — generic per-kind install dispatch"
```

---

## Phase 3 — Engine (status, audit, order+drag, install, sync)

### Task 6: `engine.py` — status + check + alias + ordering with dependency drag-in

**Files:**
- Create: `tools/installer/engine.py`
- Test: `tests/test_setup.py`

- [ ] **Step 1: Write the failing tests** (append to `tests/test_setup.py`)

```python
import engine as eng  # noqa: E402

class EngineStatusTests(unittest.TestCase):
    def _bin(self, name, body):
        import tempfile, pathlib
        d = tempfile.mkdtemp(); self.addCleanup(__import__("shutil").rmtree, d)
        p = pathlib.Path(d) / name; p.write_text("#!/bin/sh\n" + body); p.chmod(0o755)
        old = os.environ["PATH"]; os.environ["PATH"] = d + os.pathsep + old
        self.addCleanup(lambda: os.environ.__setitem__("PATH", old)); return name

    def test_missing_binary(self):
        t = mdl.Tool(id="nope-xyz", name="x", kind="pkg", category="extras")
        self.assertEqual(eng.status(t, "debian"), "missing")

    def test_installed_binary(self):
        n = self._bin("fakeok", 'echo 1.2.3\nexit 0\n')
        t = mdl.Tool(id=n, name="x", kind="curl", category="extras")
        self.assertEqual(eng.status(t, "debian"), "installed")

    def test_broken_volta_shim_is_missing(self):
        n = self._bin("fakepnpm", 'echo \'Volta error: Could not find executable "fakepnpm"\' >&2\nexit 1\n')
        t = mdl.Tool(id=n, name="x", kind="custom", category="pkg-mgr", fn="install_pnpm")
        self.assertEqual(eng.status(t, "debian"), "missing")

    def test_launcher_unwired_when_marker_absent(self):
        t = mdl.Tool(id="x", name="x", kind="launcher", cmd="sh",
                     wired_marker="/nonexistent/marker")
        self.assertEqual(eng.status(t, "debian"), "unwired")

    def test_npx_launcher_unknown(self):
        t = mdl.Tool(id="gsd", name="gsd", kind="launcher", cmd="npx")
        self.assertEqual(eng.status(t, "debian"), "unknown")

class EngineOrderTests(unittest.TestCase):
    def _t(self, i, req=None):
        return mdl.Tool(id=i, name=i, kind="pkg", category="x", requires=req or [])

    def test_topo_order(self):
        a = self._t("pyright", ["volta"]); v = self._t("volta")
        out = [t.id for t in eng.order_for_install([a, v])]
        self.assertLess(out.index("volta"), out.index("pyright"))

    def test_drag_in_missing_dependency(self):
        # selecting pyright drags in its missing requires from the full catalogue
        catalogue = [self._t("pyright", ["volta"]), self._t("volta")]
        selected = [catalogue[0]]
        dragged = eng.with_required(selected, catalogue, lambda t: t.id != "volta")  # volta missing
        ids = {t.id for t in dragged}
        self.assertEqual(ids, {"pyright", "volta"})

    def test_drag_in_skips_already_installed_dep(self):
        catalogue = [self._t("pyright", ["volta"]), self._t("volta")]
        selected = [catalogue[0]]
        dragged = eng.with_required(selected, catalogue, lambda t: True)  # all installed
        self.assertEqual({t.id for t in dragged}, {"pyright"})
```

- [ ] **Step 2: Run it (red)**

Run: `python3 -m unittest tests.test_setup.EngineStatusTests tests.test_setup.EngineOrderTests -v 2>&1 | tail -8`
Expected: FAIL — `No module named 'engine'`.

- [ ] **Step 3: Implement `tools/installer/engine.py`** (status/check/alias/order + drag-in + install_all)

```python
"""The installer engine: audit, ordering, install, and sync — model + strategies only."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Callable

from model import Tool
from strategies import STRATEGIES
from ui import console, info, ok, warn


# ── status / check ────────────────────────────────────────────────────────────────

def _is_broken_volta_shim(stderr: str) -> bool:
    s = stderr.lower()
    return "volta" in s and "could not find executable" in s


def check(tool: Tool, os_name: str) -> tuple[str, str]:
    """Returns (status, installed_version_string)."""
    if shutil.which(tool.cmd):
        try:
            r = subprocess.run([tool.cmd, "--version"], capture_output=True, text=True, timeout=5)
            if r.returncode != 0 and _is_broken_volta_shim(r.stderr or ""):
                return "missing", ""
            out = (r.stdout or r.stderr or "")
            return "installed", (out.splitlines()[0][:40] if out else "")
        except Exception:
            return "installed", ""
    if tool.alias_cmd and os_name == "debian" and shutil.which(tool.alias_cmd):
        return "alias_needed", ""
    return "missing", ""


def status(tool: Tool, os_name: str) -> str:
    """'installed' | 'unwired' | 'missing' | 'alias_needed' | 'unknown'."""
    if tool.kind == "marketplace":
        from register import marketplace_enabled  # reuse settings.json reader (Task 8)
        return "installed" if marketplace_enabled(tool) else "missing"
    if tool.kind == "launcher":
        if tool.cmd == "npx":
            return "unknown"
        if not shutil.which(tool.cmd):
            return "missing"
        if tool.wired_marker and not Path(tool.wired_marker).expanduser().exists():
            return "unwired"
        return "installed"
    return check(tool, os_name)[0]


# ── ordering + dependency drag-in ──────────────────────────────────────────────────

def with_required(selected: list[Tool], catalogue: list[Tool],
                  is_installed: Callable[[Tool], bool]) -> list[Tool]:
    """Expand `selected` with any required tools that are not installed (transitive)."""
    by_id = {t.id: t for t in catalogue}
    out: dict[str, Tool] = {t.id: t for t in selected}
    queue = list(selected)
    while queue:
        t = queue.pop()
        for dep in t.requires:
            d = by_id.get(dep)
            if d and d.id not in out and not is_installed(d):
                out[d.id] = d
                queue.append(d)
    return list(out.values())


def order_for_install(tools: list[Tool]) -> list[Tool]:
    """Stable topological sort so each tool's requires install first (cycle-safe)."""
    by_id = {t.id: t for t in tools}
    ordered: list[Tool] = []
    placed: set[str] = set()
    visiting: set[str] = set()

    def visit(t: Tool) -> None:
        if t.id in placed or t.id in visiting:
            return
        visiting.add(t.id)
        for dep in t.requires:
            if dep in by_id:
                visit(by_id[dep])
        visiting.discard(t.id)
        placed.add(t.id)
        ordered.append(t)

    for t in tools:
        visit(t)
    return ordered


# ── install ────────────────────────────────────────────────────────────────────────

def install(tool: Tool, os_name: str, arch: dict) -> None:
    info(f"Installing {tool.name}...")
    STRATEGIES[tool.kind](tool, os_name, arch)
    if tool.alias_cmd and os_name == "debian":
        _create_alias(tool.cmd, tool.alias_cmd)
    ok(f"{tool.name} ready")


def _create_alias(cmd: str, alias_cmd: str) -> None:
    local_bin = Path.home() / ".local" / "bin"
    local_bin.mkdir(parents=True, exist_ok=True)
    src = shutil.which(alias_cmd)
    if not src:
        warn(f"{alias_cmd} not found — cannot alias {cmd}")
        return
    link = local_bin / cmd
    if link.exists() or link.is_symlink():
        link.unlink()
    link.symlink_to(src)
    ok(f"{cmd} alias -> {src}")


def install_all(tools: list[Tool], os_name: str, arch: dict) -> list[str]:
    """Install dependency-ordered; returns ids that failed (soft-warned)."""
    failed: list[str] = []
    for tool in order_for_install(tools):
        try:
            install(tool, os_name, arch)
        except (subprocess.CalledProcessError, OSError, RuntimeError) as exc:
            warn(f"Failed to install {tool.name}: {exc}")
            failed.append(tool.id)
    return failed
```

> Note: `status()` imports `marketplace_enabled` from `register.py` — add that helper in Task 8 by moving the existing `_enabled_plugins`/`_marketplace_enabled` logic out of `_ai_tools.py` into `register.py` as a public `marketplace_enabled(tool)`. Until Task 8, the marketplace branch is only exercised by the live wizard, not the unit tests above.

- [ ] **Step 4: Run it (green)**

Run: `python3 -m unittest tests.test_setup.EngineStatusTests tests.test_setup.EngineOrderTests -v 2>&1 | tail -8`
Expected: PASS (8 tests). (Marketplace branch not hit by these tests.)

- [ ] **Step 5: Commit**

```bash
git add tools/installer/engine.py tests/test_setup.py
git commit -m "feat(installer): engine.py — status, alias, topo-order + dependency drag-in"
```

### Task 7: `sync` — installed vs latest version + release date

**Files:**
- Modify: `tools/installer/engine.py`
- Test: `tests/test_setup.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_setup.py`)

```python
class SyncTests(unittest.TestCase):
    def test_sync_row_outdated(self):
        eng_latest = eng.paths_latest_version
        try:
            eng.paths_latest_version = lambda src: ("0.45.0", "2026-05-20")
            t = mdl.Tool(id="lazygit", name="lazygit", kind="github-release", category="git",
                         version_latest="github:jesseduffield/lazygit",
                         version_cmd="true", version_re=r"(0\.44\.1)")
            # stub installed-version probe
            eng._installed_version = lambda tool: "0.44.1"
            row = eng.sync_row(t)
            self.assertEqual(row["latest"], "0.45.0")
            self.assertEqual(row["latest_date"], "2026-05-20")
            self.assertEqual(row["state"], "outdated")
        finally:
            eng.paths_latest_version = eng_latest

    def test_sync_row_skips_without_version_block(self):
        t = mdl.Tool(id="bat", name="bat", kind="pkg", category="nav")
        self.assertEqual(eng.sync_row(t)["state"], "skip")

    def test_sync_row_ok_when_equal(self):
        eng.paths_latest_version = lambda src: ("0.20.1", "2026-04-11")
        eng._installed_version = lambda tool: "0.20.1"
        t = mdl.Tool(id="eza", name="eza", kind="github-release", category="nav",
                     version_latest="github:eza-community/eza",
                     version_cmd="true", version_re=r"(0\.20\.1)")
        self.assertEqual(eng.sync_row(t)["state"], "ok")
```

- [ ] **Step 2: Run it (red)**

Run: `python3 -m unittest tests.test_setup.SyncTests -v 2>&1 | tail -5`
Expected: FAIL — `AttributeError: module 'engine' has no attribute 'sync_row'`.

- [ ] **Step 3: Implement sync in `tools/installer/engine.py`** (append)

```python
import re as _re
from paths import latest_version as paths_latest_version   # module-level so tests can stub


def _installed_version(tool: Tool) -> str:
    if not tool.version_cmd:
        return ""
    try:
        r = subprocess.run(tool.version_cmd.split(), capture_output=True, text=True, timeout=5)
        text = (r.stdout or r.stderr or "")
    except (OSError, subprocess.SubprocessError):
        return ""
    if tool.version_re:
        m = _re.search(tool.version_re, text)
        return m.group(1) if m else ""
    return text.splitlines()[0].strip() if text else ""


def sync_row(tool: Tool) -> dict:
    """One row of the sync report: id, installed, latest, latest_date, state."""
    if not tool.version_latest:
        return {"id": tool.id, "state": "skip"}
    if not shutil.which(tool.cmd):
        return {"id": tool.id, "state": "missing", "latest": "", "latest_date": ""}
    latest, date = paths_latest_version(tool.version_latest)
    installed = _installed_version(tool)
    if not latest:
        state = "unknown"
    elif installed and installed == latest:
        state = "ok"
    elif installed:
        state = "outdated"
    else:
        state = "unknown"
    return {"id": tool.id, "installed": installed, "latest": latest,
            "latest_date": date, "state": state}


def sync(tools: list[Tool]) -> list[dict]:
    """Report version state for every tool that declares a [tool.version] block."""
    rows = [sync_row(t) for t in tools]
    from rich.table import Table
    table = Table(title="Version sync", show_header=True, header_style="bold cyan")
    for col in ("Tool", "Installed", "Latest", "Released", "State"):
        table.add_column(col)
    style = {"ok": "green", "outdated": "yellow", "missing": "red",
             "unknown": "dim", "skip": "dim"}
    for r in rows:
        if r["state"] == "skip":
            continue
        table.add_row(r["id"], r.get("installed", ""), r.get("latest", ""),
                      r.get("latest_date", ""), f"[{style[r['state']]}]{r['state']}[/]")
    console.print(table)
    return rows
```

- [ ] **Step 4: Run it (green)**

Run: `python3 -m unittest tests.test_setup.SyncTests -v 2>&1 | tail -5`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add tools/installer/engine.py tests/test_setup.py
git commit -m "feat(installer): sync — installed vs latest version + release date"
```

---

## Phase 4 — Wire the wizard, move register/shell, delete the old stack

### Task 8: Move register.py + shell.py; expose `marketplace_enabled`

**Files:**
- Create: `tools/installer/register.py` (from `tools/_register.py`)
- Create: `tools/installer/shell.py` (from `tools/_shell.py`)
- Modify: `tools/installer/register.py` (add `marketplace_enabled`)
- Test: `tests/test_setup.py`

- [ ] **Step 1: git mv both modules**

```bash
git mv tools/_register.py tools/installer/register.py
git mv tools/_shell.py tools/installer/shell.py
```

- [ ] **Step 2: Add the marketplace-status reader to `register.py`** (move from `_ai_tools.py:72-83`, make public)

```python
import json
SETTINGS = Path.home() / ".claude" / "settings.json"

def _enabled_plugins() -> dict:
    try:
        return json.loads(SETTINGS.read_text()).get("enabledPlugins", {})
    except (OSError, ValueError):
        return {}

def marketplace_enabled(tool) -> bool:
    ep = _enabled_plugins()
    if tool.plugins:
        return any(ep.get(f"{p}@{tool.marketplace}") for p in tool.plugins)
    return any(k.endswith(f"@{tool.marketplace}") and v for k, v in ep.items())
```

- [ ] **Step 3: Update the test imports** — the existing `import _register as reg` / `import _shell as sh` lines become `import register as reg` / `import shell as sh`.

- [ ] **Step 4: Run register + shell + engine status tests**

Run: `python3 -m unittest tests.test_setup.RegisterCodexTests tests.test_setup.RegisterClaudeTests tests.test_setup.ShellGuardTests tests.test_setup.EngineStatusTests -v 2>&1 | tail -4`
Expected: PASS (status' marketplace branch now resolves `register.marketplace_enabled`).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(installer): move register.py + shell.py; expose marketplace_enabled"
```

### Task 9: Rewrite `setup.py` onto the engine; derive PATH reminder from bin_dirs

**Files:**
- Modify: `tools/setup.py`
- Test: `tests/test_setup.py`

- [ ] **Step 1: Write the failing test for the data-driven PATH reminder** (append to `tests/test_setup.py`)

```python
class PathReminderFromRegistryTests(unittest.TestCase):
    def test_bin_dirs_collected_from_registry(self):
        import setup as wiz
        tools = mdl.load_tools(MANIFEST)
        dirs = wiz.bin_dirs(tools)
        self.assertIn(str(__import__("pathlib").Path("~/.local/bin").expanduser()), dirs)
        # volta tool declares ~/.volta/bin
        self.assertTrue(any(".volta" in d for d in dirs))
```

- [ ] **Step 2: Run it (red)**

Run: `python3 -m unittest tests.test_setup.PathReminderFromRegistryTests -v 2>&1 | tail -5`
Expected: FAIL — `module 'setup' has no attribute 'bin_dirs'`.

- [ ] **Step 3: Rewrite `tools/setup.py`** to import from the installer package and drive everything through `engine`. Key shape (full file):

```python
# /// script
# requires-python = ">=3.11"
# dependencies = ["rich>=13"]
# ///
# setup.py — uz-kit setup wizard (entrypoint). Data lives in installer/registry.toml.
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE / "installer"))

import engine as eng                       # noqa: E402
import model as mdl                        # noqa: E402
import paths as pth                        # noqa: E402
import register as reg                     # noqa: E402
import shell as sh                         # noqa: E402
from ui import console, info, ok, warn, header  # noqa: E402

MANIFEST = _HERE / "installer" / "registry.toml"


def bin_dirs(tools: list[mdl.Tool]) -> list[str]:
    """Distinct, expanded bin dirs declared across the registry (+ the default)."""
    dirs = {str((Path.home() / ".local" / "bin"))}
    for t in tools:
        if t.bin_dir:
            dirs.add(str(Path(t.bin_dir).expanduser()))
    return sorted(dirs)


def path_reminder(tools: list[mdl.Tool]) -> None:
    import os
    cur = os.environ.get("PATH", "")
    rc = _rc_text()
    missing = [d for d in bin_dirs(tools)
               if Path(d).is_dir() and d not in cur and d not in rc
               and d.replace(str(Path.home()), "$HOME") not in rc]
    console.rule("[bold cyan]PATH[/bold cyan]")
    if not missing:
        ok("PATH already configured — nothing to add.")
        return
    console.print("\n[bold]Add to ~/.bashrc or ~/.zshrc:[/bold]")
    for d in missing:
        console.print(f'  export PATH="{d.replace(str(Path.home()), "$HOME")}:$PATH"')


def _rc_text() -> str:
    home = Path.home()
    out = ""
    for rc in (".bashrc", ".zshrc", ".profile", ".zprofile", ".bash_profile"):
        try:
            out += (home / rc).read_text()
        except OSError:
            pass
    return out


# --- flows: run_install(categories?), run_ai(select?), run_sync(), run_register(), run_shell() ---
# (Compose the existing menu using eng.status / eng.with_required / eng.order_for_install /
#  eng.install_all / eng.sync / reg.sync_claude / reg.sync_codex / sh.run_shell_guards.
#  Keep the menu: 1 Everything, 2 CLI tools, 3 AI tools, 4 Register, 5 Shell guards, 6 Sync.
#  CLI vs AI is just a category filter now — AI = categories {"ai","ai-cli"}.)
```

Then port the existing menu/flows from the current `setup.py` (audit table, category select, confirm, summary, AI action panel, register, shell guards) to call the engine. The AI "Actions available / ACTIONS NEEDED" panel and `ai_action_hint` move into `setup.py` (or `engine.py`) using `eng.status`. Add menu item **6) Version sync** → `eng.sync(mdl.load_tools(MANIFEST))`.

- [ ] **Step 4: Run it (green)**

Run: `python3 -m unittest tests.test_setup.PathReminderFromRegistryTests -v 2>&1 | tail -5`
Expected: PASS.

- [ ] **Step 5: Smoke-test the wizard non-interactively**

Run: `printf '6\n' | uv run tools/setup.py 2>&1 | tail -20`
Expected: the Version sync table renders (no traceback).

- [ ] **Step 6: Commit**

```bash
git add tools/setup.py tests/test_setup.py
git commit -m "feat(installer): rewrite setup.py onto engine; registry-derived PATH reminder; sync menu"
```

### Task 10: Delete the old stack; migrate remaining tests; full green

**Files:**
- Delete: `tools/_cli_tools.py`, `tools/_ai_tools.py`
- Modify: `tests/test_setup.py`

- [ ] **Step 1: Delete the superseded modules**

```bash
git rm tools/_cli_tools.py tools/_ai_tools.py
```

- [ ] **Step 2: Migrate/replace the legacy test classes** — the old `ManifestTests`, `CategoryTests`, `AuditTests`, `AIToolTests`, `AIActionHintTests`, `InstallOrderTests`, `NoBareNpmTests`, `PathReminderTests` referenced `_cli_tools`/`_ai_tools`. Re-point each to the new modules:
  - `cli.load_cli_tools` → `mdl.load_tools`; `cli.check_tool` → `eng.check`; `cli.order_for_install` → `eng.order_for_install`; `cli.categories` → `mdl.categories`.
  - `ai.ai_status` → `eng.status`; `ai.ai_action_hint` → the hint fn now in `setup`/`engine`.
  - `NoBareNpmTests.test_no_npm_or_pip_invocation_in_source` → scan `tools/installer/*.py` (skip `shell.py`); `install_npm` ban test → `strategies.install_node` raising (already covered in StrategyTests; delete the duplicate).
  - `cli._is_broken_volta_shim` → `eng._is_broken_volta_shim`.

- [ ] **Step 3: Run the FULL suite**

Run: `python3 -m unittest discover -s tests -p 'test_*.py' 2>&1 | tail -4`
Expected: `OK` (all tests, no `ModuleNotFoundError`).

- [ ] **Step 4: Verify no stale imports remain**

Run: `grep -rnE 'import _cli_tools|import _ai_tools|import _ui|import _register|import _shell|from _ui' tools tests; echo "exit=$?"`
Expected: no matches.

- [ ] **Step 5: Entropy check — confirm the net reduction**

Run: `wc -l tools/installer/*.py tools/setup.py | tail -1`
Expected: total well below the previous install-stack total of 1191 lines (target ≈ 720).

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor(installer): delete _cli_tools/_ai_tools; migrate tests to unified engine"
```

### Task 11: Update bootstrap + docs

**Files:**
- Modify: `tools/install-dev-tools.sh` (path sanity), `docs/ia-helper-tools.md`

- [ ] **Step 1: Confirm the bootstrap still targets `tools/setup.py`**

Run: `grep -n 'setup.py' tools/install-dev-tools.sh`
Expected: it execs `"$SCRIPT_DIR/setup.py"` — no change needed (setup.py stayed put). If it referenced any `tools/_*.py` or `tools/registry.toml`, update to `tools/installer/...`.

- [ ] **Step 2: Update `docs/ia-helper-tools.md`** — document the unified registry (`tools/installer/registry.toml`), the `kind` field and its strategies, how to add a tool by editing one row, the `[tool.version]` block, the `sync` menu item, and the `kind="custom"`/`fn=` escape hatch. Add a short "extending" section: which `kind` to pick, the asset-template placeholders, and how `requires` drags in dependencies.

- [ ] **Step 3: Run the full suite once more + py-compile everything**

Run: `python3 -m py_compile tools/setup.py tools/installer/*.py && python3 -m unittest discover -s tests -p 'test_*.py' 2>&1 | tail -3`
Expected: compiles clean; `OK`.

- [ ] **Step 4: Commit**

```bash
git add tools/install-dev-tools.sh docs/ia-helper-tools.md
git commit -m "docs(installer): document unified registry, kinds, version sync, extending"
```

### Task 12: Live verification + finish

- [ ] **Step 1: Audit renders for all tools**

Run: `printf '2\n\n n\n' | uv run tools/setup.py 2>&1 | tail -30`
Expected: the CLI-tools audit table lists every tool with a real status (incl. `pi`, `opencode`, `codegraph`); no traceback.

- [ ] **Step 2: AI panel + hints render**

Run: `printf '3\n\n n\n' | uv run tools/setup.py 2>&1 | tail -25`
Expected: AI toolkits table + the bright-yellow ACTIONS NEEDED panel with gentle-ai wiring showing `--agent claude-code,opencode` (no `pi`).

- [ ] **Step 3: Sync runs against the network (best-effort)**

Run: `printf '6\n' | uv run tools/setup.py 2>&1 | tail -20`
Expected: version table; github-release tools show installed/latest/date; pkg tools omitted; failures degrade to `unknown`, never crash.

- [ ] **Step 4: Finish the branch**

REQUIRED SUB-SKILL: superpowers:finishing-a-development-branch (verify tests, then merge/PR per your choice).

---

## Self-Review

**Spec coverage:**
- Unify two tables → one model → Tasks 1-2, 10. ✓
- Generic strategies + escape hatch → Tasks 4-5. ✓
- Version + **date** autodiscovery → Tasks 3, 7. ✓
- `sync` outdated check → Task 7, 9 (menu), 12. ✓
- Single PATH/bin function (`ensure_on_path`) → Task 3, used in 4/5; registry-derived reminder → Task 9. ✓
- Dependencies ordered **and dragged in** → Task 6 (`order_for_install` + `with_required`). ✓
- Everything editable from TOML (urls/commands/wiring/notes/category/priority/deps) → Task 2 schema. ✓
- gentle-ai wiring fix (no pi) → Task 2 + verified Task 12. ✓
- `tools/installer/` subfolder → Tasks 0, 3-8. ✓
- Reduce entropy → Task 10 Step 5 measures it. ✓

**Placeholder scan:** No "TBD/TODO" steps. The 3 custom installers and ui/register/shell are explicit verbatim moves with exact source line ranges, not placeholders. Task 9 Step 3 ports the existing menu flows — the engine API they call is fully defined in Tasks 5-7; the menu rendering itself already exists in the current `setup.py` and is mechanical re-wiring.

**Type consistency:** `status()`/`check()`/`install()`/`install_all()`/`order_for_install()`/`with_required()`/`sync_row()`/`sync()` signatures are used consistently across engine, setup, and tests. `STRATEGIES[kind](tool, os_name, arch)` matches every strategy and custom fn's 3-arg signature. `Tool` field names (`version_latest`, `version_cmd`, `version_re`, `bin_dir`, `wired_marker`, `member`, `raw`, `os_token`) are identical in model, loader, strategies, engine, and tests.

**Note on gentle-ai default wiring:** `--agent claude-code,opencode --scope global`. Change the `wiring=` line in Task 2 Step 3 if you want a different agent set, a preset (`--preset minimal`), or `--scope workspace`.
