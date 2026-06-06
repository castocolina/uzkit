"""Escape hatch: the irregular installers that don't fit a generic strategy.

Each is `install_<name>(tool, os_name, arch) -> None`, dispatched by name from
strategies.install_custom via the row's `fn` field. Kept deliberately small —
generic kinds cover everything else.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from paths import ensure_on_path
from ui import info, ok, warn


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def _local_bin() -> Path:
    d = Path.home() / ".local" / "bin"
    ensure_on_path(d)
    return d


# ── Node toolchain (volta subcommands) ──────────────────────────────────────────

def install_pnpm(tool, os_name: str, arch: dict) -> None:
    if not shutil.which("volta"):
        raise RuntimeError("volta not found — install volta first")
    _run(["volta", "install", "pnpm"])


def install_node(tool, os_name: str, arch: dict) -> None:
    if not shutil.which("volta"):
        raise RuntimeError("volta not found — install volta first")
    _run(["volta", "install", "node@22"])      # Node 22 LTS (pi requires Node 22+)


# ── GitHub CLI (apt repo / pacman / brew) ───────────────────────────────────────

def install_gh(tool, os_name: str, arch: dict) -> None:
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


# ── ast-bro (cargo / brew tap) + MCP wiring ─────────────────────────────────────

def install_ast_bro(tool, os_name: str, arch: dict) -> None:
    if os_name == "macos":
        _run(["brew", "install", "aeroxy/tap/ast-bro"])
    else:
        _run(["cargo", "install", "ast-bro", "--quiet"])
    if shutil.which("claude"):
        try:
            _run(["ast-bro", "install", "--mcp", "claude"])
            ok("ast-bro wired into Claude Code (MCP)")
        except subprocess.CalledProcessError:
            warn("ast-bro installed but MCP wiring failed — run 'ast-bro install --mcp claude' manually")


# ── jless (xcb deps on Debian / pacman / brew) ──────────────────────────────────

def install_jless(tool, os_name: str, arch: dict) -> None:
    if os_name == "debian":
        _run(["sudo", "apt-get", "install", "-y",
              "libxcb1-dev", "libxcb-render0-dev",
              "libxcb-shape0-dev", "libxcb-xfixes0-dev"])
        _run(["cargo", "install", "jless", "--quiet"])
    elif os_name == "arch":
        _run(["sudo", "pacman", "-S", "--noconfirm", "--needed", "jless"])
    elif os_name == "macos":
        _run(["brew", "install", "jless"])


# ── btop (apt / snap fallback) ──────────────────────────────────────────────────

def install_btop(tool, os_name: str, arch: dict) -> None:
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


# ── Sublime Text (apt repo / AUR-or-tarball / dmg) ──────────────────────────────

def install_subl(tool, os_name: str, arch: dict) -> None:
    local_bin = _local_bin()
    link = local_bin / "subl"

    if os_name == "debian":
        _run([
            "sh", "-c",
            "curl -fsSL https://download.sublimetext.com/sublimehq-pub.gpg"
            " | sudo gpg --dearmor -o /etc/apt/trusted.gpg.d/sublimehq-archive.gpg"
            " && echo 'deb https://download.sublimetext.com/ apt/stable/' "
            " | sudo tee /etc/apt/sources.list.d/sublime-text.list > /dev/null"
        ])
        _run(["sudo", "apt-get", "update", "-qq"])
        _run(["sudo", "apt-get", "install", "-y", "sublime-text"])
        subl_bin = Path("/opt/sublime_text/sublime_text")
        if subl_bin.exists():
            if link.exists() or link.is_symlink():
                link.unlink()
            link.symlink_to(subl_bin)
            ok(f"subl alias created at {link}")

    elif os_name == "arch":
        if shutil.which("yay"):
            _run(["yay", "-S", "--noconfirm", "sublime-text-4"])
        elif shutil.which("paru"):
            _run(["paru", "-S", "--noconfirm", "sublime-text-4"])
        else:
            url = "https://download.sublimetext.com/sublime_text_build_4180_x64.tar.xz"
            _run(["sh", "-c", f"curl -fsSLo /tmp/sublime.tar.xz '{url}'"
                  " && sudo tar -xf /tmp/sublime.tar.xz -C /opt"
                  " && rm /tmp/sublime.tar.xz"])
        subl_bin = Path("/opt/sublime_text/sublime_text")
        if subl_bin.exists():
            if link.exists() or link.is_symlink():
                link.unlink()
            link.symlink_to(subl_bin)

    elif os_name == "macos":
        apps_dir = Path.home() / "Applications"
        apps_dir.mkdir(parents=True, exist_ok=True)
        dmg_url = "https://download.sublimetext.com/sublime_text_build_4180_mac.dmg"
        dmg_path = Path("/tmp/sublime_text.dmg")
        info("Downloading Sublime Text .dmg (this may take a moment)...")
        _run(["curl", "-fsSLo", str(dmg_path), dmg_url])
        _run(["hdiutil", "attach", str(dmg_path), "-nobrowse", "-quiet"])
        src = Path("/Volumes/Sublime Text/Sublime Text.app")
        dst = apps_dir / "Sublime Text.app"
        if dst.exists():
            _run(["rm", "-rf", str(dst)])
        _run(["cp", "-r", str(src), str(dst)])
        _run(["hdiutil", "detach", "/Volumes/Sublime Text", "-quiet"])
        dmg_path.unlink(missing_ok=True)
        subl_cli = dst / "Contents" / "SharedSupport" / "bin" / "subl"
        if subl_cli.exists():
            if link.exists() or link.is_symlink():
                link.unlink()
            link.symlink_to(subl_cli)
            ok(f"subl alias created at {link}")
        else:
            warn("Sublime Text installed but subl binary not found inside .app bundle")
