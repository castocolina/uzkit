# Design: install-dev-tools.py (data-driven Python rewrite)

**Date:** 2026-06-01  
**Scope:** Create `tools/install-dev-tools.py` as a cross-platform, modular Python installer with
a pre-flight audit table.

---

## Goals

- Show a pre-flight audit table (installed / missing / version) before changing anything
- Ask for confirmation before installing
- Mirror all tools and priorities defined in `docs/ia-helper-tools.md`. Where a tool is present
  in `install-dev-tools.sh` but absent from the priority table in `ia-helper-tools.md` (e.g.
  `mmdc`), the `.sh` file is the authoritative source for inclusion; priority defaults to P0 if the
  `.sh` file places it in the P0 section.
- Be well-organized: data (tool registry) separated from logic (install/audit functions)
- Run via `uv run tools/install-dev-tools.py` or remotely via `uv run <raw-URL>`

---

## Non-Goals

- No `--install` flag or dry-run flag — interactive confirmation is the UX model
- No GUI, no config file, no external state
- Does not update already-installed tools (idempotent: skips if present)
- `ast-bro` is **excluded from scope**: no stable binary release exists for automated install.
  Users install it manually per its own README. The audit table will show it as missing if absent,
  but no `install_ast_bro` function will be implemented.

---

## File

`tools/install-dev-tools.py` — single self-contained file with PEP 723 inline deps.

```python
# /// script
# requires-python = ">=3.11"
# dependencies = ["rich>=13"]
# ///
```

Only `rich` is needed. No `packaging` — version parsing is done with simple string checks.

---

## Architecture

```
main()
  └── bootstrap()        # install shellcheck + Rust before audit
  └── audit_table()      # print Rich table, return list of actionable Tool entries
  └── confirm()          # "Proceed? [y/N]" — exits on N
  └── install_all()      # iterate actionable list, call install_tool() per entry
  └── path_reminder()    # print shell config lines
```

`audit_table()` returns **both** missing (`✗`) and alias-needed (`⚠`) entries. Both are passed to
`install_all()` so alias creation is handled in the same install pass as fresh installs.

Everything flows through `main()`. No global state.

---

## Tool Registry

Each tool is a `Tool` dataclass instance. The registry is a plain list — order defines install order.

```python
@dataclass
class Tool:
    cmd: str           # binary name to check with `which`
    name: str          # display name for the audit table
    priority: str      # "P0" | "P1" | "P2" | "P3"
    method: str        # "pkg" | "cargo" | "npm" | "custom"
    pkg_debian: str    # apt package name (or "" if not available)
    pkg_arch: str      # pacman package name
    pkg_brew: str      # brew package name
    cargo_crate: str   # crate name if method=="cargo" (else "")
    npm_pkg: str       # npm package name if method=="npm" (else "")
    alias_cmd: str     # Debian-only alternate binary name that must be symlinked to `cmd`
                       # (e.g. "fdfind" for fd, "batcat" for bat); "" for all other tools
    notes: str         # shown in audit table (e.g. "Debian alias: batcat")
```

Custom installs use `method="custom"` and each has a dedicated `install_<cmd>(os, arch)` function.
The full list of custom-install `cmd` values and their functions:

| `cmd` | Function |
|-------|----------|
| `gh` | `install_gh` |
| `yq` | `install_yq` |
| `volta` | `install_volta` |
| `uv` | `install_uv` |
| `lazygit` | `install_lazygit` |
| `eza` | `install_eza` (apt if available; binary download fallback; cargo last resort) |
| `gron` | `install_gron` (requires `arch["go"]` — used in the Linux binary URL) |

The registry entry still carries display metadata for the audit table; the installer dispatches
to the named function via `globals()[f"install_{tool.cmd}"]`.

### Registry enumeration by method

All 30 tools from `install-dev-tools.sh` are represented in the registry:

**`method="pkg"`** (installed via OS package manager, same package name across distros or minor
name variants covered by `pkg_debian`/`pkg_arch`/`pkg_brew` fields):
`rg`, `jq`, `tree`, `htop`, `tmux`, `ncdu`, `fzf`, `vim`, `tldr`

**`method="pkg"` with Debian alias** (binary name differs on Debian; alias handled separately — see
Debian Aliases section):
`fd` (`pkg_debian="fd-find"`, `cmd="fd"`), `bat` (`pkg_debian="bat"`, Debian binary is `batcat`)

**`method="cargo"` with OS-specific fallback** (cargo on Debian, native pkg on Arch/macOS):
`tokei`, `sg` (ast-grep), `delta` (git-delta), `dust` (du-dust), `sd`, `hyperfine`, `jless`

**`method="pkg"` with OS-specific package names** (Debian: `httpie`, Arch/macOS: same or similar):
`http` (httpie)

**`method="custom"`**:
`yq`, `gh`, `uv`, `volta`, `pnpm`, `node`, `lazygit`, `eza`, `gron`

`pnpm` and `node` use `method="custom"` and delegate to `volta` (installed earlier in the custom
chain). `install_pnpm` calls `volta install pnpm`; `install_node` calls `volta install node`.

**`method="npm"`**:
`mmdc` (@mermaid-js/mermaid-cli) — installed via `pnpm add -g` (preferred) or `volta install`
(fallback), matching `install_npm_global` in the `.sh` file.

**`method="pkg"` OS-conditional** (Debian uses apt if available, then snap fallback):
`btop`

---

## OS + Arch Detection

```python
def detect_os() -> str:   # returns "debian" | "arch" | "macos"
def detect_arch() -> dict: # returns {"deb": "amd64", "go": "amd64", "suffix": "x86_64"}
```

Called once at startup. Results passed as arguments — no globals.

---

## Audit Table

Printed with `rich.table.Table` before any changes. Columns:

| Tool | Priority | Status | Version | Notes |
|------|----------|--------|---------|-------|

Status values:
- `[green]✓ installed[/]` — binary found on PATH
- `[red]✗ missing[/]` — binary not found
- `[yellow]⚠ alias needed[/]` — e.g. `batcat` found but `bat` not linked

Version: output of `cmd --version` first line, truncated to 40 chars. Empty if missing.

After the table, a summary line: `N tools installed, M need action (missing or alias needed).`

---

## Confirmation Flow

```
┌─ Audit complete ───────────────────────────────────────────┐
│  14 installed   7 missing                                   │
└─────────────────────────────────────────────────────────────┘
Proceed with installing/fixing 7 tools? [y/N]: 
```

- `y` / `Y` → continue
- anything else (including Enter) → print "Aborted." and exit 0

---

## Bootstrap Phase

Runs **before** the audit table, because shellcheck and Rust (cargo) affect what the audit
can report accurately.

1. **shellcheck** — install via OS package manager if missing
2. **Rust** — install via `curl … | sh -s -- -y --no-modify-path` if `cargo` not found;
   then `source ~/.cargo/env` equivalent (`os.environ` update)

Bootstrap uses `subprocess.run()` with `check=True`. Errors are fatal (print + `sys.exit(1)`).

---

## Install Dispatch

```python
def install_tool(tool: Tool, os: str, arch: dict) -> None:
    match tool.method:
        case "pkg":    install_pkg(tool, os)
        case "cargo":  install_cargo(tool)
        case "npm":    install_npm(tool)
        case "custom": globals()[f"install_{tool.cmd}"](os, arch)
    # After the package install, create the Debian alias symlink if needed.
    # audit_table() sets status="alias needed" when tool.alias_cmd is found but tool.cmd is not.
    if tool.alias_cmd and os == "debian":
        create_alias(tool.cmd, tool.alias_cmd)  # symlinks alias_cmd → ~/.local/bin/cmd
```

Each installer prints `[info] Installing <name>...` before and `[ok] <name> installed` after.
Errors are caught and printed as `[warn]` — never crash mid-install.

### Error-handling contract

**Bootstrap phase** (shellcheck, Rust): fatal — any failure calls `sys.exit(1)`. These are
prerequisites; the rest of the script cannot proceed meaningfully without them.

**Install pass** (all tools in `install_all()`): soft — each tool is wrapped in a
`try/except subprocess.CalledProcessError` (and `OSError`). On failure the tool is added to a
`failed: list[str]` accumulator; install continues for remaining tools.

**Exit code**: the script exits `0` if all installs succeeded (or nothing needed action), and `1`
if one or more install-pass tools failed. The caller can detect partial failure via exit code.

**Final summary** (printed after `path_reminder()`): if `failed` is non-empty, print:

```
[warn] The following tools failed to install: rg, delta
       Re-run or install them manually.
```

If `failed` is empty, print nothing extra (the audit table and individual `[ok]` lines are
sufficient).

---

## Debian Aliases

After installing `fd-find` and `bat`, the script creates symlinks in `~/.local/bin/` if the
canonical command name (`fd`, `bat`) is not already on PATH. Reported as `⚠ alias needed` in
the audit table and auto-fixed during install.

---

## PATH Reminder

Printed unconditionally at the end (regardless of whether anything was installed):

```
Add to ~/.bashrc or ~/.zshrc if not already present:
  export PATH="$HOME/.local/bin:$PATH"
  export PATH="$HOME/.cargo/bin:$PATH"
  export VOLTA_HOME="$HOME/.volta"
  export PATH="$VOLTA_HOME/bin:$PATH"
```

---

## Bootstrap Instructions (for new machines)

Printed at the top of the script as a comment block and in the doc:

```bash
# 1. Install uv (Python package manager):
#    curl -LsSf https://astral.sh/uv/install.sh | sh
#    source ~/.local/bin/env   # or restart shell
#
# 2. Run locally:
#    uv run tools/install-dev-tools.py
#
# 3. Run without cloning (replace URL with your raw repo URL):
#    uv run https://raw.example.com/uz-kit/main/tools/install-dev-tools.py
```

---

## Changes to install-dev-tools.sh

None. All inline comments in `install-dev-tools.sh` are already in English. No changes to this file are required.

---

## Testing

Manual test on a fresh Debian container (e.g. `docker run --rm -it debian:bookworm bash`):

1. Install `uv` per the bootstrap instructions.
2. Run `uv run tools/install-dev-tools.py` and verify the audit table renders with correct status values.
3. Confirm `y` proceeds to install and `N` (or Enter) prints "Aborted." and exits 0.
4. Re-run immediately — verify all tools now show `✓ installed` and the script exits without installing anything.
5. On macOS, repeat steps 2–4 with Homebrew available (no `apt`).

No CI automation is planned for the initial version; smoke-test passes are the acceptance criterion.

---

## Files Touched

| File | Action |
|------|--------|
| `tools/install-dev-tools.py` | Create (new) |
| `docs/ia-helper-tools.md` | Add `uv run` remote usage example under Quick Install |
