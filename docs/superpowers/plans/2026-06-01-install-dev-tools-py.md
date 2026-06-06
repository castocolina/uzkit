# install-dev-tools.py Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create `tools/install-dev-tools.py` — a data-driven, cross-platform Python installer that shows a Rich pre-flight audit table, asks for confirmation, then installs only missing/alias-broken tools.

**Architecture:** Single self-contained PEP 723 script. `TOOLS` is a list of `Tool` dataclasses (data). All logic is in functions with no global state. `main()` orchestrates: `bootstrap → audit_table → confirm → install_all → path_reminder`. Bootstrap (shellcheck, Rust) runs before the audit so those tools report correctly.

**Tech Stack:** Python ≥3.11, `rich>=13` (inline PEP 723 dep), `subprocess`, `shutil`, `urllib.request` (stdlib). Run via `uv run tools/install-dev-tools.py`.

---

## File Structure

| File | Action |
|------|--------|
| `tools/install-dev-tools.py` | Create (new, ~450 lines) |
| `docs/ia-helper-tools.md` | Append `uv run` remote example under Quick Install |

---

### Task 1: Scaffold — PEP 723 header, imports, Tool dataclass, console helpers

**Files:**
- Create: `tools/install-dev-tools.py`

- [ ] **Step 1: Create `tools/install-dev-tools.py` with this exact content**

```python
# /// script
# requires-python = ">=3.11"
# dependencies = ["rich>=13"]
# ///
#
# install-dev-tools.py — AI agent & developer CLI tool installer
#
# Usage:
#   1. Install uv (Python package manager):
#      curl -LsSf https://astral.sh/uv/install.sh | sh
#      source ~/.local/bin/env   # or restart shell
#
#   2. Run locally:
#      uv run tools/install-dev-tools.py
#
#   3. Run without cloning (replace URL with your raw repo URL):
#      uv run https://raw.example.com/uz-kit/main/tools/install-dev-tools.py
#
# Detects: Ubuntu/Debian (apt), Arch Linux (pacman), macOS (Homebrew)
# See: ../docs/ia-helper-tools.md for full documentation

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import urllib.request
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from rich.console import Console
from rich.table import Table
from rich import print as rprint

console = Console()


def info(msg: str) -> None:
    console.print(f"[cyan][info][/cyan] {msg}")


def ok(msg: str) -> None:
    console.print(f"[green][ok][/green]   {msg}")


def warn(msg: str) -> None:
    console.print(f"[yellow][warn][/yellow] {msg}")


def die(msg: str) -> None:
    console.print(f"[red][error][/red] {msg}")
    sys.exit(1)


def header(msg: str) -> None:
    console.rule(f"[bold cyan]{msg}[/bold cyan]")


@dataclass
class Tool:
    cmd: str           # binary name checked via shutil.which()
    name: str          # display name in the audit table
    priority: str      # "P0" | "P1" | "P2" | "P3"
    method: str        # "pkg" | "cargo" | "npm" | "custom" | "manual"
    pkg_debian: str    # apt package name ("" if not in apt)
    pkg_arch: str      # pacman package name
    pkg_brew: str      # brew package name
    cargo_crate: str   # crate name for method=="cargo" (else "")
    npm_pkg: str       # npm package name for method=="npm" (else "")
    alias_cmd: str     # Debian-only alternate binary symlinked to cmd
                       # (e.g. "fdfind" for fd, "batcat" for bat); "" otherwise
    notes: str         # shown in audit table Notes column
```

- [ ] **Step 2: Verify syntax**

```bash
python3 -c "import ast; ast.parse(open('tools/install-dev-tools.py').read()); print('syntax ok')"
```

Expected: `syntax ok`

- [ ] **Step 3: Commit**

```bash
git add tools/install-dev-tools.py
git commit -m "feat: scaffold install-dev-tools.py — PEP 723 header, Tool dataclass"
```

---

### Task 2: TOOLS registry — full list of 31 entries

**Files:**
- Modify: `tools/install-dev-tools.py` (append after the dataclass)

- [ ] **Step 1: Append the TOOLS registry after the `Tool` dataclass**

```python

# ── Tool registry ─────────────────────────────────────────────────────────────
# Order defines install order. Data only — no logic here.

TOOLS: list[Tool] = [
    # ── P0: Critical search & navigation ─────────────────────────────────────
    Tool("rg",      "ripgrep",        "P0", "pkg",    "ripgrep",  "ripgrep",    "ripgrep",    "",           "",                          "", ""),
    Tool("fd",      "fd",             "P0", "pkg",    "fd-find",  "fd",         "fd",         "",           "",                          "fdfind", "Debian binary: fdfind"),
    Tool("jq",      "jq",             "P0", "pkg",    "jq",       "jq",         "jq",         "",           "",                          "", ""),
    Tool("yq",      "yq",             "P0", "custom", "",         "",           "",           "",           "",                          "", "Binary from GitHub"),
    Tool("gh",      "GitHub CLI",     "P0", "custom", "",         "",           "",           "",           "",                          "", "GitHub CLI"),
    # ── P0: Safe package managers ─────────────────────────────────────────────
    Tool("uv",      "uv",             "P0", "custom", "",         "",           "",           "",           "",                          "", "Python package manager"),
    Tool("volta",   "volta",          "P0", "custom", "",         "",           "",           "",           "",                          "", "Node.js toolchain"),
    Tool("pnpm",    "pnpm",           "P0", "custom", "",         "",           "",           "",           "",                          "", "Via volta"),
    Tool("node",    "Node.js LTS",    "P0", "custom", "",         "",           "",           "",           "",                          "", "Via volta"),
    # ── P0: Workflow tools ────────────────────────────────────────────────────
    Tool("mmdc",    "mermaid CLI",    "P0", "npm",    "",         "",           "",           "",           "@mermaid-js/mermaid-cli",   "", "Diagram generation"),
    # ── P1: Navigation & exploration ──────────────────────────────────────────
    Tool("eza",     "eza",            "P1", "custom", "",         "",           "",           "",           "",                          "", "apt / binary / cargo fallback"),
    Tool("tmux",    "tmux",           "P1", "pkg",    "tmux",     "tmux",       "tmux",       "",           "",                          "", ""),
    Tool("tokei",   "tokei",          "P1", "cargo",  "",         "tokei",      "tokei",      "tokei",      "",                          "", ""),
    Tool("sg",      "ast-grep",       "P1", "cargo",  "",         "ast-grep",   "ast-grep",   "ast-grep",   "",                          "", ""),
    # ── P2: Git & viewing ─────────────────────────────────────────────────────
    Tool("bat",     "bat",            "P2", "pkg",    "bat",      "bat",        "bat",        "",           "",                          "batcat", "Debian binary: batcat"),
    Tool("delta",   "delta",          "P2", "cargo",  "",         "git-delta",  "git-delta",  "git-delta",  "",                          "", ""),
    Tool("lazygit", "lazygit",        "P2", "custom", "",         "",           "",           "",           "",                          "", "Binary from GitHub"),
    # ── P2: System utilities ──────────────────────────────────────────────────
    Tool("htop",    "htop",           "P2", "pkg",    "htop",     "htop",       "htop",       "",           "",                          "", ""),
    Tool("btop",    "btop",           "P2", "custom", "",         "",           "",           "",           "",                          "", "apt / snap fallback on Debian"),
    Tool("ncdu",    "ncdu",           "P2", "pkg",    "ncdu",     "ncdu",       "ncdu",       "",           "",                          "", ""),
    Tool("http",    "httpie",         "P2", "pkg",    "httpie",   "httpie",     "httpie",     "",           "",                          "", ""),
    Tool("fzf",     "fzf",            "P2", "pkg",    "fzf",      "fzf",        "fzf",        "",           "",                          "", ""),
    Tool("vim",     "vim",            "P2", "pkg",    "vim",      "vim",        "vim",        "",           "",                          "", ""),
    Tool("tree",    "tree",           "P2", "pkg",    "tree",     "tree",       "tree",       "",           "",                          "", ""),
    # ── P2: Code navigation (manual install) ──────────────────────────────────
    Tool("ast-bro", "ast-bro",        "P2", "manual", "",         "",           "",           "",           "",                          "", "Install manually per README"),
    # ── P3: Extra utilities ───────────────────────────────────────────────────
    Tool("dust",    "dust",           "P3", "cargo",  "",         "dust",       "dust",       "du-dust",    "",                          "", ""),
    Tool("sd",      "sd",             "P3", "cargo",  "",         "sd",         "sd",         "sd",         "",                          "", ""),
    Tool("hyperfine","hyperfine",     "P3", "cargo",  "",         "hyperfine",  "hyperfine",  "hyperfine",  "",                          "", ""),
    Tool("tldr",    "tldr",           "P3", "pkg",    "tldr",     "tldr",       "tldr",       "",           "",                          "", ""),
    Tool("gron",    "gron",           "P3", "custom", "",         "",           "",           "",           "",                          "", "Binary from GitHub (uses arch[\"go\"])"),
    Tool("jless",   "jless",          "P3", "cargo",  "",         "jless",      "jless",      "jless",      "",                          "", ""),
]
```

- [ ] **Step 2: Verify syntax**

```bash
python3 -c "import ast; ast.parse(open('tools/install-dev-tools.py').read()); print('syntax ok')"
```

Expected: `syntax ok`

- [ ] **Step 3: Commit**

```bash
git add tools/install-dev-tools.py
git commit -m "feat: add TOOLS registry — 31 entries with method/priority/alias metadata"
```

---

### Task 3: detect_os(), detect_arch(), github_latest_version()

**Files:**
- Modify: `tools/install-dev-tools.py` (append after TOOLS)

- [ ] **Step 1: Append these three functions**

```python

# ── Detection helpers ──────────────────────────────────────────────────────────

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
    return ""  # unreachable; die() calls sys.exit


def detect_arch() -> dict[str, str]:
    """Returns arch strings for deb packages, Go binaries, and release suffixes."""
    import platform
    machine = platform.machine()
    mapping = {
        "x86_64":  {"deb": "amd64", "go": "amd64", "suffix": "x86_64"},
        "aarch64": {"deb": "arm64", "go": "arm64", "suffix": "arm64"},
        "armv7l":  {"deb": "armhf", "go": "arm",   "suffix": "armv6"},
    }
    if machine not in mapping:
        warn(f"Unknown architecture {machine} — binary downloads may fail")
        return {"deb": machine, "go": machine, "suffix": machine}
    return mapping[machine]


def github_latest_version(repo: str) -> str:
    """Returns version string without leading 'v'. Empty string on failure."""
    try:
        url = f"https://api.github.com/repos/{repo}/releases/latest"
        req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            tag = json.loads(resp.read()).get("tag_name", "")
            return tag.lstrip("v")
    except Exception:
        warn(f"Could not fetch latest version for {repo} (rate-limited or network error)")
        return ""
```

- [ ] **Step 2: Verify syntax**

```bash
python3 -c "import ast; ast.parse(open('tools/install-dev-tools.py').read()); print('syntax ok')"
```

- [ ] **Step 3: Commit**

```bash
git add tools/install-dev-tools.py
git commit -m "feat: add detect_os, detect_arch, github_latest_version helpers"
```

---

### Task 4: check_tool() and audit_table()

**Files:**
- Modify: `tools/install-dev-tools.py` (append)

- [ ] **Step 1: Append check_tool() and audit_table()**

```python

# ── Audit ──────────────────────────────────────────────────────────────────────

StatusT = Literal["installed", "missing", "alias_needed", "manual"]


def check_tool(tool: Tool, os_name: str) -> tuple[StatusT, str]:
    """
    Returns (status, version_string).
    - 'installed'    → cmd found on PATH
    - 'alias_needed' → alias_cmd found but cmd not linked (Debian only)
    - 'missing'      → neither found
    - 'manual'       → method=="manual"; always show as missing, never install
    """
    if tool.method == "manual":
        return "manual", ""

    if shutil.which(tool.cmd):
        try:
            result = subprocess.run(
                [tool.cmd, "--version"],
                capture_output=True, text=True, timeout=5
            )
            version = (result.stdout or result.stderr).splitlines()[0][:40]
        except Exception:
            version = ""
        return "installed", version

    if tool.alias_cmd and os_name == "debian" and shutil.which(tool.alias_cmd):
        return "alias_needed", ""

    return "missing", ""


def audit_table(tools: list[Tool], os_name: str) -> list[Tool]:
    """
    Prints a Rich audit table. Returns actionable tools (missing + alias_needed).
    'manual' tools appear in the table but are never returned as actionable.
    """
    table = Table(title="Pre-flight audit", show_header=True, header_style="bold cyan")
    table.add_column("Tool",     style="bold",   no_wrap=True)
    table.add_column("Priority", justify="center")
    table.add_column("Status",   no_wrap=True)
    table.add_column("Version",  style="dim",    no_wrap=True)
    table.add_column("Notes",    style="dim")

    actionable: list[Tool] = []
    installed_count = 0

    for tool in tools:
        status, version = check_tool(tool, os_name)

        if status == "installed":
            status_cell = "[green]✓ installed[/green]"
            installed_count += 1
        elif status == "alias_needed":
            status_cell = "[yellow]⚠ alias needed[/yellow]"
            actionable.append(tool)
        elif status == "manual":
            status_cell = "[dim]○ manual install[/dim]"
        else:
            status_cell = "[red]✗ missing[/red]"
            actionable.append(tool)

        table.add_row(tool.name, tool.priority, status_cell, version, tool.notes)

    console.print(table)
    need = len(actionable)
    console.print(
        f"[bold]{installed_count}[/bold] installed  "
        f"[bold]{need}[/bold] need action (missing or alias needed)\n"
    )
    return actionable
```

- [ ] **Step 2: Verify syntax**

```bash
python3 -c "import ast; ast.parse(open('tools/install-dev-tools.py').read()); print('syntax ok')"
```

- [ ] **Step 3: Commit**

```bash
git add tools/install-dev-tools.py
git commit -m "feat: add check_tool and audit_table with Rich output"
```

---

### Task 5: confirm() and bootstrap()

**Files:**
- Modify: `tools/install-dev-tools.py` (append)

- [ ] **Step 1: Append confirm() and bootstrap()**

```python

# ── Confirmation ───────────────────────────────────────────────────────────────

def confirm(n: int) -> bool:
    """Prints a confirmation prompt. Returns True on 'y'/'Y', False otherwise."""
    console.rule()
    try:
        answer = input(f"Proceed with installing/fixing {n} tools? [y/N]: ").strip()
    except (KeyboardInterrupt, EOFError):
        console.print("\nAborted.")
        return False
    if answer.lower() == "y":
        return True
    console.print("Aborted.")
    return False


# ── Bootstrap ──────────────────────────────────────────────────────────────────

def _run(cmd: list[str], **kwargs) -> None:
    """Runs a command with check=True. Raises subprocess.CalledProcessError on failure."""
    subprocess.run(cmd, check=True, **kwargs)


def bootstrap(os_name: str) -> None:
    """
    Installs shellcheck and Rust before the audit.
    Errors are fatal — prerequisites must succeed for the rest to work.
    """
    header("Bootstrap — shellcheck")
    if shutil.which("shellcheck"):
        ok("shellcheck already installed")
    else:
        info("Installing shellcheck...")
        try:
            if os_name == "debian":
                _run(["sudo", "apt-get", "install", "-y", "shellcheck"])
            elif os_name == "arch":
                _run(["sudo", "pacman", "-S", "--noconfirm", "--needed", "shellcheck"])
            elif os_name == "macos":
                _run(["brew", "install", "shellcheck"])
            ok("shellcheck installed")
        except subprocess.CalledProcessError as exc:
            die(f"Failed to install shellcheck: {exc}")

    header("Bootstrap — Rust")
    if shutil.which("cargo"):
        ok(f"cargo already installed")
        # Ensure cargo bin is on PATH even if not in caller's environment
        cargo_bin = Path.home() / ".cargo" / "bin"
        if str(cargo_bin) not in os.environ.get("PATH", ""):
            os.environ["PATH"] = str(cargo_bin) + ":" + os.environ.get("PATH", "")
    else:
        info("Installing Rust via rustup...")
        try:
            _run([
                "sh", "-c",
                "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs"
                " | sh -s -- -y --no-modify-path"
            ])
            # Update PATH so cargo is available for the rest of this process
            cargo_bin = Path.home() / ".cargo" / "bin"
            os.environ["PATH"] = str(cargo_bin) + ":" + os.environ.get("PATH", "")
            ok(f"Rust installed")
        except subprocess.CalledProcessError as exc:
            die(f"Failed to install Rust: {exc}")
```

- [ ] **Step 2: Verify syntax**

```bash
python3 -c "import ast; ast.parse(open('tools/install-dev-tools.py').read()); print('syntax ok')"
```

- [ ] **Step 3: Commit**

```bash
git add tools/install-dev-tools.py
git commit -m "feat: add confirm prompt, bootstrap (shellcheck + Rust)"
```

---

### Task 6: Base install helpers — install_pkg, install_cargo, install_npm, create_alias

**Files:**
- Modify: `tools/install-dev-tools.py` (append)

- [ ] **Step 1: Append the four base install helpers**

```python

# ── Base install helpers ───────────────────────────────────────────────────────

def install_pkg(tool: Tool, os_name: str) -> None:
    """Installs a tool via the OS package manager."""
    if os_name == "debian":
        _run(["sudo", "apt-get", "install", "-y", tool.pkg_debian])
    elif os_name == "arch":
        _run(["sudo", "pacman", "-S", "--noconfirm", "--needed", tool.pkg_arch])
    elif os_name == "macos":
        _run(["brew", "install", tool.pkg_brew])


def install_cargo(tool: Tool, os_name: str) -> None:
    """
    On Debian: installs via cargo (cargo must be on PATH after bootstrap).
    On Arch/macOS: installs via native package manager using pkg_arch / pkg_brew.
    """
    if os_name == "debian":
        _run(["cargo", "install", tool.cargo_crate, "--quiet"])
    elif os_name == "arch":
        _run(["sudo", "pacman", "-S", "--noconfirm", "--needed", tool.pkg_arch])
    elif os_name == "macos":
        _run(["brew", "install", tool.pkg_brew])


def install_npm(tool: Tool) -> None:
    """
    Installs a global npm package via pnpm (preferred) or volta (fallback).
    pnpm and volta must already be installed (they appear earlier in TOOLS).
    """
    if shutil.which("pnpm"):
        _run(["pnpm", "add", "-g", tool.npm_pkg])
    elif shutil.which("volta"):
        _run(["volta", "install", tool.npm_pkg])
    else:
        raise RuntimeError("Neither pnpm nor volta found — cannot install npm package")


def create_alias(cmd: str, alias_cmd: str) -> None:
    """
    Creates ~/.local/bin/<cmd> → <alias_cmd_path> symlink.
    Called after installing a tool with a Debian-specific binary name.
    """
    local_bin = Path.home() / ".local" / "bin"
    local_bin.mkdir(parents=True, exist_ok=True)
    alias_path = shutil.which(alias_cmd)
    if not alias_path:
        warn(f"{alias_cmd} not found on PATH — cannot create {cmd} alias")
        return
    link = local_bin / cmd
    if link.exists() or link.is_symlink():
        link.unlink()
    link.symlink_to(alias_path)
    ok(f"{cmd} alias created at {link}")
```

- [ ] **Step 2: Verify syntax**

```bash
python3 -c "import ast; ast.parse(open('tools/install-dev-tools.py').read()); print('syntax ok')"
```

- [ ] **Step 3: Commit**

```bash
git add tools/install-dev-tools.py
git commit -m "feat: add install_pkg, install_cargo, install_npm, create_alias helpers"
```

---

### Task 7: Custom install functions — package managers (uv, volta, pnpm, node)

**Files:**
- Modify: `tools/install-dev-tools.py` (append)

- [ ] **Step 1: Append the four package-manager custom installers**

```python

# ── Custom install functions ───────────────────────────────────────────────────
# Each function is named install_<cmd> and matches a Tool entry with method="custom".
# Signature: (os_name: str, arch: dict[str, str]) -> None
# Raise on failure; install_tool() catches and records to failed[].

def install_uv(os_name: str, arch: dict[str, str]) -> None:
    _run(["sh", "-c", "curl -LsSf https://astral.sh/uv/install.sh | sh"])
    uv_bin = Path.home() / ".local" / "bin"
    if str(uv_bin) not in os.environ.get("PATH", ""):
        os.environ["PATH"] = str(uv_bin) + ":" + os.environ.get("PATH", "")


def install_volta(os_name: str, arch: dict[str, str]) -> None:
    _run(["sh", "-c", "curl -fsSL https://get.volta.sh | bash"])
    volta_bin = Path.home() / ".volta" / "bin"
    os.environ["VOLTA_HOME"] = str(Path.home() / ".volta")
    os.environ["PATH"] = str(volta_bin) + ":" + os.environ.get("PATH", "")


def install_pnpm(os_name: str, arch: dict[str, str]) -> None:
    if not shutil.which("volta"):
        raise RuntimeError("volta not found — install volta first")
    _run(["volta", "install", "pnpm"])


def install_node(os_name: str, arch: dict[str, str]) -> None:
    if not shutil.which("volta"):
        raise RuntimeError("volta not found — install volta first")
    # 'volta install node' defaults to LTS
    _run(["volta", "install", "node"])
```

- [ ] **Step 2: Verify syntax**

```bash
python3 -c "import ast; ast.parse(open('tools/install-dev-tools.py').read()); print('syntax ok')"
```

- [ ] **Step 3: Commit**

```bash
git add tools/install-dev-tools.py
git commit -m "feat: add custom install functions for uv, volta, pnpm, node"
```

---

### Task 8: Custom install functions — CLI tools (gh, yq, lazygit, eza, gron, btop)

**Files:**
- Modify: `tools/install-dev-tools.py` (append)

- [ ] **Step 1: Append the six CLI custom installers**

```python

def install_gh(os_name: str, arch: dict[str, str]) -> None:
    if os_name == "debian":
        _run(["sudo", "mkdir", "-p", "-m", "755", "/etc/apt/keyrings"])
        _run([
            "sh", "-c",
            "wget -qO- https://cli.github.com/packages/githubcli-archive-keyring.gpg"
            " | sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg > /dev/null"
        ])
        dpkg_arch = subprocess.check_output(["dpkg", "--print-architecture"], text=True).strip()
        sources_line = (
            f"deb [arch={dpkg_arch} signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg]"
            " https://cli.github.com/packages stable main"
        )
        _run(["sh", "-c", f"echo '{sources_line}'"
              " | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null"])
        _run(["sudo", "apt-get", "update", "-qq"])
        _run(["sudo", "apt-get", "install", "-y", "gh"])
    elif os_name == "arch":
        _run(["sudo", "pacman", "-S", "--noconfirm", "--needed", "github-cli"])
    elif os_name == "macos":
        _run(["brew", "install", "gh"])


def install_yq(os_name: str, arch: dict[str, str]) -> None:
    if os_name in ("debian", "arch"):
        _run([
            "sudo", "wget", "-qO", "/usr/local/bin/yq",
            f"https://github.com/mikefarah/yq/releases/latest/download/yq_linux_{arch['deb']}"
        ])
        _run(["sudo", "chmod", "+x", "/usr/local/bin/yq"])
    elif os_name == "macos":
        _run(["brew", "install", "yq"])


def install_lazygit(os_name: str, arch: dict[str, str]) -> None:
    if os_name in ("debian", "arch"):
        ver = github_latest_version("jesseduffield/lazygit")
        if not ver:
            raise RuntimeError("Could not determine lazygit version")
        url = (
            f"https://github.com/jesseduffield/lazygit/releases/download"
            f"/v{ver}/lazygit_{ver}_Linux_{arch['suffix']}.tar.gz"
        )
        _run(["sh", "-c", f"curl -fsSLo /tmp/lazygit.tar.gz '{url}'"])
        _run(["tar", "-xf", "/tmp/lazygit.tar.gz", "-C", "/tmp", "lazygit"])
        _run(["sudo", "install", "/tmp/lazygit", "/usr/local/bin/lazygit"])
        Path("/tmp/lazygit.tar.gz").unlink(missing_ok=True)
        Path("/tmp/lazygit").unlink(missing_ok=True)
    elif os_name == "macos":
        _run(["brew", "install", "lazygit"])


def install_eza(os_name: str, arch: dict[str, str]) -> None:
    if os_name == "debian":
        # Try apt first (Ubuntu 24.04+), then binary download, then cargo
        result = subprocess.run(
            ["apt-cache", "show", "eza"], capture_output=True
        )
        if result.returncode == 0:
            _run(["sudo", "apt-get", "install", "-y", "eza"])
            return
        # Binary download fallback
        ver = github_latest_version("eza-community/eza")
        if ver:
            import platform
            machine = platform.machine()
            url = (
                f"https://github.com/eza-community/eza/releases/download"
                f"/v{ver}/eza_{machine}-unknown-linux-musl.tar.gz"
            )
            _run(["sh", "-c",
                  f"curl -fsSL '{url}' | sudo tar -xz -C /usr/local/bin eza"])
            return
        # Cargo last resort
        _run(["cargo", "install", "eza", "--quiet"])
    elif os_name == "arch":
        _run(["sudo", "pacman", "-S", "--noconfirm", "--needed", "eza"])
    elif os_name == "macos":
        _run(["brew", "install", "eza"])


def install_gron(os_name: str, arch: dict[str, str]) -> None:
    # arch["go"] is required for the Linux binary URL (e.g. "amd64", "arm64")
    if os_name in ("debian", "arch"):
        ver = github_latest_version("tomnomnom/gron")
        if not ver:
            raise RuntimeError("Could not determine gron version")
        url = (
            f"https://github.com/tomnomnom/gron/releases/download"
            f"/v{ver}/gron-linux-{arch['go']}-{ver}.tgz"
        )
        _run(["sh", "-c", f"curl -fsSLo /tmp/gron.tgz '{url}'"])
        _run(["tar", "-xf", "/tmp/gron.tgz", "-C", "/tmp", "gron"])
        _run(["sudo", "install", "/tmp/gron", "/usr/local/bin/gron"])
        Path("/tmp/gron.tgz").unlink(missing_ok=True)
        Path("/tmp/gron").unlink(missing_ok=True)
    elif os_name == "macos":
        _run(["brew", "install", "gron"])


def install_btop(os_name: str, arch: dict[str, str]) -> None:
    if os_name == "debian":
        result = subprocess.run(["apt-cache", "show", "btop"], capture_output=True)
        if result.returncode == 0:
            _run(["sudo", "apt-get", "install", "-y", "btop"])
        elif shutil.which("snap"):
            _run(["sudo", "snap", "install", "btop"])
        else:
            raise RuntimeError("btop not available via apt or snap on this system")
    elif os_name == "arch":
        _run(["sudo", "pacman", "-S", "--noconfirm", "--needed", "btop"])
    elif os_name == "macos":
        _run(["brew", "install", "btop"])
```

- [ ] **Step 2: Verify syntax**

```bash
python3 -c "import ast; ast.parse(open('tools/install-dev-tools.py').read()); print('syntax ok')"
```

- [ ] **Step 3: Commit**

```bash
git add tools/install-dev-tools.py
git commit -m "feat: add custom install functions for gh, yq, lazygit, eza, gron, btop"
```

---

### Task 9: install_tool(), install_all(), path_reminder(), main()

**Files:**
- Modify: `tools/install-dev-tools.py` (append)

- [ ] **Step 1: Append install_tool(), install_all(), path_reminder(), and main()**

```python

# ── Install dispatch ───────────────────────────────────────────────────────────

def install_tool(tool: Tool, os_name: str, arch: dict[str, str]) -> None:
    """
    Dispatches to the correct install function. After install, creates Debian
    alias symlink if tool.alias_cmd is set.
    method=="manual" is silently skipped (shown in table but never installed).
    """
    if tool.method == "manual":
        return

    info(f"Installing {tool.name}...")

    match tool.method:
        case "pkg":
            install_pkg(tool, os_name)
        case "cargo":
            install_cargo(tool, os_name)
        case "npm":
            install_npm(tool)
        case "custom":
            # Dispatch to install_<cmd>(os_name, arch)
            fn_name = f"install_{tool.cmd.replace('-', '_')}"
            fn = globals().get(fn_name)
            if fn is None:
                raise RuntimeError(f"No installer function found: {fn_name}")
            fn(os_name, arch)

    # Create Debian alias symlink after pkg install if needed
    if tool.alias_cmd and os_name == "debian":
        create_alias(tool.cmd, tool.alias_cmd)

    ok(f"{tool.name} installed")


def install_all(
    actionable: list[Tool], os_name: str, arch: dict[str, str]
) -> list[str]:
    """
    Installs all actionable tools. Returns list of names that failed.
    Never crashes mid-install — failures are soft-warned and accumulated.
    Exit code 1 if any tool failed (handled in main).
    """
    failed: list[str] = []
    for tool in actionable:
        try:
            install_tool(tool, os_name, arch)
        except (subprocess.CalledProcessError, OSError, RuntimeError) as exc:
            warn(f"Failed to install {tool.name}: {exc}")
            failed.append(tool.name)
    return failed


# ── PATH reminder ──────────────────────────────────────────────────────────────

def path_reminder() -> None:
    console.rule("[bold cyan]Done[/bold cyan]")
    console.print("\n[bold]Add to ~/.bashrc or ~/.zshrc if not already present:[/bold]")
    console.print('  export PATH="$HOME/.local/bin:$PATH"          # fd, bat aliases (Debian)')
    console.print('  export PATH="$HOME/.cargo/bin:$PATH"          # cargo-installed tools')
    console.print('  export VOLTA_HOME="$HOME/.volta"')
    console.print('  export PATH="$VOLTA_HOME/bin:$PATH"           # volta, node, pnpm, mmdc')
    console.print()
    console.print(
        "[green]See ~/.claude/plugins/uz-kit/docs/ia-helper-tools.md for usage examples.[/green]"
    )


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    os_name = detect_os()
    arch = detect_arch()

    # Bootstrap runs before the audit so shellcheck and cargo report correctly
    bootstrap(os_name)

    header("Pre-flight audit")
    actionable = audit_table(TOOLS, os_name)

    if not actionable:
        ok("All tools already installed — nothing to do.")
        path_reminder()
        sys.exit(0)

    if not confirm(len(actionable)):
        sys.exit(0)

    header("Installing")
    failed = install_all(actionable, os_name, arch)

    path_reminder()

    if failed:
        warn(f"The following tools failed to install: {', '.join(failed)}")
        warn("Re-run or install them manually.")
        sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify syntax**

```bash
python3 -c "import ast; ast.parse(open('tools/install-dev-tools.py').read()); print('syntax ok')"
```

Expected: `syntax ok`

- [ ] **Step 3: Smoke-test the audit table (answer N to skip installs)**

```bash
uv run tools/install-dev-tools.py
```

Expected:
- Rich table renders with Tool / Priority / Status / Version / Notes columns
- Each tool shows ✓ installed, ✗ missing, or ⚠ alias needed
- Summary line: `N installed  M need action`
- Confirmation prompt appears
- Pressing Enter (or N) prints "Aborted." and exits 0

- [ ] **Step 4: Verify exit code on abort**

```bash
uv run tools/install-dev-tools.py; echo "exit: $?"
```

Expected: `exit: 0` after pressing Enter at the prompt.

- [ ] **Step 5: Commit**

```bash
git add tools/install-dev-tools.py
git commit -m "feat: add install_tool, install_all, path_reminder, main — script complete"
```

---

### Task 10: Update docs/ia-helper-tools.md — add remote uv run example

**Files:**
- Modify: `docs/ia-helper-tools.md`

- [ ] **Step 1: Read the current Quick Install section**

Open `docs/ia-helper-tools.md` and locate the `## Quick Install` section at the bottom (currently ends at line ~496).

- [ ] **Step 2: Replace the Quick Install section**

Find this text:
```markdown
## Quick Install

See `../tools/install-dev-tools.sh` for the automated installer that detects
your OS (Ubuntu/Debian via apt, Arch via pacman, macOS via Homebrew) and installs
everything in this document.
```

Replace with:
```markdown
## Quick Install

Two installers are provided, both do the same work:

**Python (recommended) — shows a pre-flight audit table, asks for confirmation:**

```bash
# Prerequisite: install uv once
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.local/bin/env   # or restart shell

# Run locally (after cloning the repo)
uv run tools/install-dev-tools.py

# Run without cloning (replace with your actual raw URL)
uv run https://raw.example.com/uz-kit/main/tools/install-dev-tools.py
```

**Bash (no prerequisites beyond curl):**

```bash
bash tools/install-dev-tools.sh
```

Both detect your OS (Ubuntu/Debian via apt, Arch via pacman, macOS via Homebrew) and
install only missing tools — already-installed tools are skipped.
```

- [ ] **Step 3: Verify the file renders correctly**

```bash
python3 -c "
with open('docs/ia-helper-tools.md') as f:
    content = f.read()
assert 'uv run tools/install-dev-tools.py' in content
assert 'uv run https://' in content
print('doc updated ok')
"
```

Expected: `doc updated ok`

- [ ] **Step 4: Commit**

```bash
git add docs/ia-helper-tools.md
git commit -m "docs: add uv run usage examples to Quick Install section"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Covered by |
|---|---|
| PEP 723 inline deps (`rich>=13`) | Task 1 |
| `Tool` dataclass with `alias_cmd` field | Task 1 |
| Full registry (31 entries incl. ast-bro manual) | Task 2 |
| `detect_os()` / `detect_arch()` return types match spec | Task 3 |
| `github_latest_version()` using urllib (no extra deps) | Task 3 |
| `check_tool()` returns (status, version) | Task 4 |
| `audit_table()` returns actionable (missing + alias_needed) | Task 4 |
| `confirm()` exits 0 on N or Enter | Task 5 |
| `bootstrap()` fatal on failure, shellcheck + Rust | Task 5 |
| `install_pkg()` / `install_cargo(os)` / `install_npm()` | Task 6 |
| `create_alias()` for fd/bat Debian symlinks | Task 6 |
| `install_uv/volta/pnpm/node` custom functions | Task 7 |
| `install_gh/yq/lazygit/eza/gron/btop` custom functions | Task 8 |
| `install_gron` uses `arch["go"]` key | Task 8 |
| `eza` three-stage fallback (apt → binary → cargo) | Task 8 |
| `btop` apt-cache check + snap fallback | Task 8 |
| `install_tool()` dispatch via `globals()["install_<cmd>"]` | Task 9 |
| `install_all()` soft errors, `failed[]` accumulator | Task 9 |
| Exit code 1 on partial failure | Task 9 |
| Final summary for failed tools | Task 9 |
| `path_reminder()` printed unconditionally | Task 9 |
| `main()` orchestration order (bootstrap→audit→confirm→install→reminder) | Task 9 |
| `docs/ia-helper-tools.md` Quick Install updated with `uv run` | Task 10 |
| `ast-bro` shown in table but never installed (`method="manual"`) | Task 2 + 4 + 9 |

**Placeholder scan:** None found — all steps have complete code.

**Type consistency check:**
- `check_tool()` returns `tuple[StatusT, str]` — used consistently in `audit_table()`
- `audit_table()` returns `list[Tool]` — consumed by `confirm(len(...))` and `install_all(...)`
- `install_all()` returns `list[str]` — checked with `if failed:` in `main()`
- `install_cargo(tool, os_name)` — `os_name` passed in Task 6 definition and Task 9 dispatch ✓
- `install_tool(tool, os_name, arch)` — called from `install_all(tool, os_name, arch)` ✓
- `globals().get(f"install_{tool.cmd.replace('-', '_')}")` — handles `ast-bro` edge case (replaced to `ast_bro`, but method="manual" so never dispatched) ✓

---

**Plan complete and saved to `docs/superpowers/plans/2026-06-01-install-dev-tools-py.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks

**2. Inline Execution** — execute tasks in this session using executing-plans

**Which approach?**
