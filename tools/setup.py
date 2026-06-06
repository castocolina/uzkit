# /// script
# requires-python = ">=3.11"
# dependencies = ["rich>=13"]
# ///
#
# setup.py — uz-kit setup wizard (entrypoint). All data lives in installer/registry.toml.
#
# Usage:
#   uv run tools/setup.py
# or via the bootstrap wrapper on a machine without Python:
#   bash tools/install-dev-tools.sh
#
# Detects: Ubuntu/Debian (apt), Arch Linux (pacman), macOS (Homebrew).
# See ../docs/ia-helper-tools.md for full documentation.
from __future__ import annotations

import os
import shutil
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
AI_CATEGORIES = {"ai"}                     # the toolkits menu; everything else is "CLI"


def load() -> list[mdl.Tool]:
    return mdl.load_tools(MANIFEST)


# ── PATH reminder (derived from the registry's declared bin dirs) ────────────────

def bin_dirs(tools: list[mdl.Tool]) -> list[str]:
    dirs = {str(Path.home() / ".local" / "bin")}
    for t in tools:
        if t.bin_dir:
            dirs.add(str(Path(t.bin_dir).expanduser()))
    return sorted(dirs)


def _rc_text() -> str:
    out = ""
    for rc in (".bashrc", ".zshrc", ".profile", ".zprofile", ".bash_profile"):
        try:
            out += (Path.home() / rc).read_text()
        except OSError:
            pass
    return out


def path_reminder(tools: list[mdl.Tool]) -> None:
    cur, rc = os.environ.get("PATH", ""), _rc_text()
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


# ── shared prompts ───────────────────────────────────────────────────────────────

def confirm(n: int) -> bool:
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


def _ensure_cargo(os_name: str) -> None:
    if shutil.which("cargo"):
        return
    info("Installing Rust toolchain (needed for cargo-based tools)...")
    subprocess.run(["sh", "-c",
                    "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y"],
                   check=True)
    pth.ensure_on_path(Path.home() / ".cargo" / "bin")


# ── CLI dev-tools flow ───────────────────────────────────────────────────────────

def choose_categories(tools: list[mdl.Tool]) -> list[str]:
    cats = mdl.categories(tools)
    console.print("\n[bold]Tool categories:[/bold]")
    for i, c in enumerate(cats, 1):
        n = sum(1 for t in tools if t.category == c)
        console.print(f"  [bold]{i}[/bold]) {c} [dim]({n})[/dim]")
    raw = input("Select categories (e.g. 1,3 — or Enter for all): ").strip().lower()
    if raw in ("", "a", "all"):
        return cats
    chosen = []
    for part in raw.replace(" ", "").split(","):
        if part.isdigit() and 1 <= int(part) <= len(cats):
            cat = cats[int(part) - 1]
            if cat not in chosen:
                chosen.append(cat)
    if not chosen:
        warn("No valid selection — defaulting to all categories.")
        return cats
    return chosen


def audit_table(tools: list[mdl.Tool], os_name: str) -> list[mdl.Tool]:
    """Render a status table; return the actionable (not-installed) tools."""
    from rich.table import Table
    table = Table(show_header=True, header_style="bold cyan")
    for col in ("Tool", "Category", "Status", "Notes"):
        table.add_column(col)
    style = {"installed": "[green]✓ installed[/green]", "missing": "[red]✗ missing[/red]",
             "alias_needed": "[yellow]● alias needed[/yellow]"}
    actionable = []
    for t in tools:
        st = eng.status(t, os_name)
        if st != "installed":
            actionable.append(t)
        table.add_row(t.name, t.category, style.get(st, st), t.notes)
    console.print(table)
    return actionable


def summary(tools: list[mdl.Tool], os_name: str, failed: list[str]) -> None:
    header("Summary")
    from collections import defaultdict
    from rich.table import Table
    rows: dict[str, dict[str, int]] = defaultdict(lambda: {"installed": 0, "missing": 0})
    ok_n = miss_n = 0
    for t in tools:
        key = "installed" if eng.status(t, os_name) == "installed" else "missing"
        rows[t.category][key] += 1
        ok_n, miss_n = (ok_n + 1, miss_n) if key == "installed" else (ok_n, miss_n + 1)
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Category", style="bold")
    table.add_column("Installed", justify="right", style="green")
    table.add_column("Still missing", justify="right", style="red")
    for cat in mdl.categories(tools):
        r = rows[cat]
        table.add_row(cat, str(r["installed"]), str(r["missing"]) if r["missing"] else "")
    console.print(table)
    console.print(f"\n[bold green]{ok_n}[/bold green] installed  "
                  f"[bold red]{miss_n}[/bold red] still missing")
    if failed:
        warn(f"Failed this run: {', '.join(failed)} — re-run or install manually.")
    path_reminder(tools)


def run_cli_tools(select_categories: bool = True) -> int:
    all_tools = load()
    cli_tools = [t for t in all_tools if t.category not in AI_CATEGORIES]
    os_name, arch = pth.detect_os(), pth.detect_arch()

    cats = choose_categories(cli_tools) if select_categories else mdl.categories(cli_tools)
    chosen = [t for t in cli_tools if t.category in cats]
    info(f"Selected categories: {', '.join(cats)}  ({len(chosen)} tools)")

    header("Pre-flight audit")
    actionable = audit_table(chosen, os_name)
    if not actionable:
        ok("All selected tools already installed — nothing to do.")
        summary(chosen, os_name, [])
        return 0

    # Drag in any missing required tools (e.g. selecting pyright pulls volta).
    installed = lambda t: eng.status(t, os_name) == "installed"      # noqa: E731
    actionable = eng.with_required(actionable, all_tools, installed)

    if not confirm(len(actionable)):
        return 0
    if any(t.kind == "cargo" for t in actionable):
        _ensure_cargo(os_name)

    header("Installing")
    failed = eng.install_all(actionable, os_name, arch)
    summary(chosen, os_name, failed)
    return 1 if failed else 0


# ── AI-toolkits flow ───────────────────────────────────────────────────────────

def ai_action_hint(tool: mdl.Tool, os_name: str) -> str:
    st = eng.status(tool, os_name)
    if st == "installed":
        return ""
    if tool.kind == "marketplace":
        return f"claude plugin marketplace add {tool.marketplace_ref}"
    if tool.kind == "launcher":
        verb = "wire" if st == "unwired" else "install"
        extra = " (interactive)" if tool.interactive or tool.cmd == "npx" else ""
        return f"{verb}: {tool.wiring or tool.cmd}{extra}"
    return "select to (re)install"


def audit_ai_table(tools: list[mdl.Tool], os_name: str) -> None:
    from rich.table import Table
    table = Table(title="AI toolkits", show_header=True, header_style="bold cyan")
    for col in ("#", "Toolkit", "Kind", "Status", "Notes"):
        table.add_column(col)
    style = {"installed": "[green]✓ installed[/green]",
             "unwired": "[yellow]● installed, needs wiring[/yellow]",
             "missing": "[red]✗ missing[/red]",
             "unknown": "[yellow]? run to (re)install[/yellow]"}
    for i, t in enumerate(tools, 1):
        st = eng.status(t, os_name)
        table.add_row(str(i), t.name, t.kind, style.get(st, st), t.notes)
    console.print(table)


def run_ai_tools(select: bool = True) -> int:
    os_name, arch = pth.detect_os(), pth.detect_arch()
    tools = [t for t in load() if t.category in AI_CATEGORIES]

    header("AI toolkits")
    audit_ai_table(tools, os_name)

    pending = [(i, t, ai_action_hint(t, os_name)) for i, t in enumerate(tools, 1)
               if eng.status(t, os_name) != "installed"]
    if pending:
        from rich.panel import Panel
        lines = [f"[bold bright_white]{i}[/]) [bold cyan]{t.name}[/]\n"
                 f"     [bold black on bright_yellow] ▶ {hint} [/]" for i, t, hint in pending]
        console.print(Panel("\n".join(lines),
                            title="[bold black on bright_yellow] ACTIONS NEEDED [/]",
                            border_style="bright_yellow", expand=False, padding=(1, 2)))

    if select:
        raw = input("Select toolkits (e.g. 1,3 — Enter for all pending): ").strip().lower()
        if raw in ("", "a", "all"):
            chosen = [t for t in tools if eng.status(t, os_name) != "installed"] or list(tools)
        else:
            idx = [int(p) for p in raw.replace(" ", "").split(",") if p.isdigit()]
            chosen = [tools[i - 1] for i in idx if 1 <= i <= len(tools)]
    else:
        chosen = [t for t in tools if eng.status(t, os_name) == "missing"]
        deferred = [t for t in tools if eng.status(t, os_name) in ("unwired", "unknown")]
        if deferred:
            info("Needs interactive setup — run setup → AI tools to handle: "
                 + ", ".join(t.name for t in deferred))
    if not chosen:
        ok("Nothing to auto-install. See 'ACTIONS NEEDED' above for manual steps.")
        return 0
    if not confirm(len(chosen)):
        return 0

    failed = []
    for tool in chosen:
        try:
            st = eng.status(tool, os_name)
            if st == "installed" and tool.update:
                info(f"Updating {tool.name}...")
                (subprocess.run if tool.interactive else _checked)(["sh", "-c", tool.update])
            else:
                eng.install(tool, os_name, arch)
            ok(f"{tool.name} done")
        except (subprocess.CalledProcessError, OSError, RuntimeError) as exc:
            warn(f"{tool.name} failed: {exc}")
            failed.append(tool.name)

    header("Summary")
    audit_ai_table([t for t in load() if t.category in AI_CATEGORIES], os_name)
    if failed:
        warn(f"Failed this run: {', '.join(failed)}")
    return 1 if failed else 0


def _checked(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


# ── register / shell / sync flows ────────────────────────────────────────────────

def run_register() -> int:
    root = reg.plugin_root()

    def _show(c: dict) -> None:
        console.print(f"  created [green]{c['created']}[/green]  updated [cyan]{c['updated']}[/cyan]  "
                      f"kept [dim]{c['kept']}[/dim]  removed [yellow]{c['removed']}[/yellow]  "
                      f"skipped [red]{c['skipped']}[/red]")

    header("Register uz-kit — Claude (~/.claude)")
    _show(reg.sync_claude(root))
    ok("Claude commands/skills/agents symlinked.")
    header("Register uz-kit — Codex (~/.codex/prompts)")
    _show(reg.sync_codex(root))
    ok("Codex prompts synced (commands + skills).")
    return 0


def run_shell_guards() -> int:
    header("Shell guards — ban npm / pip")
    console.print("Intercepts [bold]npm[/bold]/[bold]pip[/bold] for every executor and points at "
                  "volta/pnpm/uv.\n  [bold]1[/bold]) Add ban [dim]— default[/dim]\n  [bold]2[/bold]) Remove ban\n")
    try:
        choice = input("Choice [1]: ").strip() or "1"
    except (KeyboardInterrupt, EOFError):
        console.print("\nAborted.")
        return 0
    return sh.run_shell_guards(remove=(choice == "2"))


def run_sync() -> int:
    header("Version sync")
    eng.sync(load())
    return 0


# ── top-level wizard ─────────────────────────────────────────────────────────────

def main() -> None:
    header("uz-kit setup")
    console.print(
        "What do you want to do?\n"
        "  [bold]1[/bold]) Everything      (CLI tools + AI tools + register) [dim]— default[/dim]\n"
        "  [bold]2[/bold]) CLI dev tools   (search, git, system, LSP, AI agents, …)\n"
        "  [bold]3[/bold]) AI tools        (superpowers, agent-toolkit, gsd, gentle-ai)\n"
        "  [bold]4[/bold]) Register uz-kit (Claude + Codex symlinks)\n"
        "  [bold]5[/bold]) Shell guards    (ban npm/pip → volta/pnpm/uv)\n"
        "  [bold]6[/bold]) Version sync    (installed vs latest + release date)\n"
    )
    try:
        choice = input("Choice [1]: ").strip() or "1"
    except (KeyboardInterrupt, EOFError):
        console.print("\nAborted.")
        sys.exit(0)

    if choice == "1":
        sys.exit(run_cli_tools(select_categories=False) or run_ai_tools(select=False) or run_register())
    elif choice == "2":
        sys.exit(run_cli_tools())
    elif choice == "3":
        sys.exit(run_ai_tools())
    elif choice == "4":
        sys.exit(run_register())
    elif choice == "5":
        sys.exit(run_shell_guards())
    elif choice == "6":
        sys.exit(run_sync())
    else:
        warn(f"Unknown choice: {choice}")
        sys.exit(1)


if __name__ == "__main__":
    main()
