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
