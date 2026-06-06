"""Shell guards: make npm/pip fail for ANY executor on this machine.

Aliases only fire in interactive shells, so they can't stop an agent, a script, or
an installer that calls `npm`/`pip` through PATH. The real guard is therefore a set
of **PATH shims**: tiny executables named npm/pip/pip3 dropped early on PATH
(~/.local/bin) that print the sanctioned tool and `exit` non-zero — so whoever
invoked them (you, an agent, an installer, a non-interactive shell) gets an error.

Aliases are kept as a belt-and-suspenders layer for interactive shells (a faster,
clearer message even if PATH ordering is off).

Both layers are idempotent and removable. Shims carry a sentinel so we only ever
touch our own — never a real binary the user placed there.

Sanctioned replacements: Node → volta (`volta install <pkg>`) / pnpm; Python → uv.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from ui import console, info, ok, warn

# ── what we ban, and what to use instead ────────────────────────────────────────
BANNED = {
    "npm": "volta (volta install <pkg>) or pnpm",
    "pip": "uv (uv pip install / uv add)",
    "pip3": "uv (uv pip install / uv add)",
}
EXIT_CODE = 127        # non-zero so the caller sees a hard failure

# ── PATH shims (universal: every executor that resolves via PATH) ───────────────
SHIM_DIR = ".local/bin"
SHIM_SENTINEL = "# uz-kit-ban-shim"


def shim_script(name: str) -> str:
    hint = BANNED[name]
    return (
        "#!/bin/sh\n"
        f"{SHIM_SENTINEL}\n"
        f'echo "uz-kit: \'{name}\' is banned on this machine — use {hint}." >&2\n'
        f"exit {EXIT_CODE}\n"
    )


def _is_our_shim(path: Path) -> bool:
    try:
        return SHIM_SENTINEL in path.read_text()
    except (OSError, UnicodeDecodeError):
        return False


def _shim_dir(home: Path) -> Path:
    return home / SHIM_DIR


def install_shims(home: Path | None = None) -> dict[str, str]:
    """Write npm/pip/pip3 shims into ~/.local/bin. Returns {name: action}.

    Never overwrites a real binary that lives in the shim dir but isn't ours.
    """
    home = home or Path.home()
    d = _shim_dir(home)
    d.mkdir(parents=True, exist_ok=True)
    results: dict[str, str] = {}
    for name in BANNED:
        target = d / name
        if target.exists() and not _is_our_shim(target):
            results[name] = "skipped (real binary here)"
            continue
        had = target.exists()
        target.write_text(shim_script(name))
        target.chmod(0o755)
        results[name] = "refreshed" if had else "created"
    return results


def remove_shims(home: Path | None = None) -> dict[str, str]:
    """Remove only the shims we created. Returns {name: action}."""
    home = home or Path.home()
    d = _shim_dir(home)
    results: dict[str, str] = {}
    for name in BANNED:
        target = d / name
        if target.exists() and _is_our_shim(target):
            target.unlink()
            results[name] = "removed"
        else:
            results[name] = "absent"
    return results


def shim_path_warning(home: Path | None = None) -> str | None:
    """If a real npm/pip resolves BEFORE our shim dir, the shim won't catch it.
    Returns a warning string in that case, else None."""
    home = home or Path.home()
    shim_dir = str(_shim_dir(home))
    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
    try:
        shim_idx = path_dirs.index(shim_dir)
    except ValueError:
        return (f"{shim_dir} is not on PATH — add it (early) so the shims take effect "
                f"for non-interactive callers.")
    for name in BANNED:
        real = shutil.which(name)
        if real and not _is_our_shim(Path(real)):
            real_dir = str(Path(real).parent)
            if real_dir in path_dirs and path_dirs.index(real_dir) < shim_idx:
                return (f"A real '{name}' at {real} resolves before {shim_dir}. "
                        f"Put {shim_dir} earlier on PATH so the ban applies everywhere.")
    return None


# ── interactive-shell aliases (secondary layer) ─────────────────────────────────
BEGIN = "# >>> uz-kit ban-aliases >>>"
END = "# <<< uz-kit ban-aliases <<<"


def ban_block() -> str:
    """The managed alias block, marker-delimited, ending with a trailing newline."""
    lines = [BEGIN]
    for name, hint in BANNED.items():
        lines.append(
            f"""alias {name}='echo "uz-kit: {name} is banned — use {hint}." >&2; false'""")
    lines.append(END)
    return "\n".join(lines) + "\n"


def target_rc_files(home: Path) -> list[Path]:
    """Where to write the aliases: a unified custom rc if you keep one
    (~/.myshellrc or ~/.shellrc), else the per-shell rc files (~/.zshrc, ~/.bashrc)."""
    for unified in (".myshellrc", ".shellrc"):
        p = home / unified
        if p.exists():
            return [p]
    return [home / ".zshrc", home / ".bashrc"]


def _strip_block(text: str) -> str:
    """Remove an existing managed block (and the blank line before it) if present."""
    if BEGIN not in text:
        return text
    pre, _, rest = text.partition(BEGIN)
    _, _, post = rest.partition(END)
    return pre.rstrip("\n") + ("\n" + post.lstrip("\n") if post.strip() else "\n")


def install_ban_aliases(home: Path | None = None) -> dict[str, str]:
    """Write/refresh the ban-alias block into each target rc. Returns {path: action}."""
    home = home or Path.home()
    block = ban_block()
    results: dict[str, str] = {}
    for rc in target_rc_files(home):
        existing = rc.read_text() if rc.exists() else ""
        had = BEGIN in existing
        cleaned = _strip_block(existing)
        sep = "" if cleaned == "" or cleaned.endswith("\n\n") else ("\n" if cleaned.endswith("\n") else "\n\n")
        rc.write_text(cleaned + sep + block)
        results[str(rc)] = "updated" if had else "added"
    return results


def remove_ban_aliases(home: Path | None = None) -> dict[str, str]:
    """Excise the managed alias block from each target rc. Returns {path: action}."""
    home = home or Path.home()
    results: dict[str, str] = {}
    for rc in target_rc_files(home):
        if not rc.exists():
            continue
        text = rc.read_text()
        if BEGIN not in text:
            results[str(rc)] = "absent"
            continue
        rc.write_text(_strip_block(text))
        results[str(rc)] = "removed"
    return results


# ── wizard entry ────────────────────────────────────────────────────────────────

def run_shell_guards(remove: bool = False) -> int:
    """Add or remove the npm/pip ban — PATH shims (universal) + interactive aliases."""
    if remove:
        info("Removing npm/pip ban (shims + aliases)...")
        for name, what in remove_shims().items():
            console.print(f"  [yellow]{what}[/yellow]  ~/{SHIM_DIR}/{name}")
        for path, what in remove_ban_aliases().items():
            console.print(f"  [yellow]{what}[/yellow]  {path}")
        ok("Ban removed.")
        return 0

    info("Installing npm/pip ban — PATH shims (apply to every executor)...")
    for name, what in install_shims().items():
        color = "red" if what.startswith("skipped") else "green"
        console.print(f"  [{color}]{what}[/{color}]  ~/{SHIM_DIR}/{name}")
    info("Adding interactive-shell aliases (secondary layer)...")
    for path, what in install_ban_aliases().items():
        console.print(f"  [green]{what}[/green]  {path}")

    warning = shim_path_warning()
    if warning:
        warn(warning)
    ok("npm/pip are now banned for any caller resolving them via PATH.")
    info("Open a new shell (or `hash -r`) so cached command paths refresh.")
    info("To undo later: re-run setup → Shell guards → remove.")
    return 0
