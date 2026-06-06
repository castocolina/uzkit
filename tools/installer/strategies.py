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
from ui import info, warn

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
    else:
        _run(["sh", "-c", f"curl -fsSL '{url}' | tar -xz -C '{dest_dir}' '{tool.member}'"])
        target = dest_dir / tool.member
    if target.exists():                      # a failed curl/tar already raised (check=True)
        target.chmod(0o755)


# ── marketplace / launcher / custom ────────────────────────────────────────────────

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
