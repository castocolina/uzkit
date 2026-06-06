"""The installer engine: audit, ordering, install, and sync — model + strategies only."""
from __future__ import annotations

import re as _re
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from model import Tool
from paths import latest_version as paths_latest_version
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
        from register import marketplace_enabled
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
    if tool.setup:                                # one-time post-install init
        info(f"Setup: {tool.setup}")
        subprocess.run(["sh", "-c", tool.setup], check=True)
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


# ── sync (installed vs latest version + release date) ──────────────────────────────

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
