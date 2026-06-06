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
    # one-time post-install init/setup shell command (e.g. pnpm: "pnpm self-update && pnpm setup")
    setup: str = ""
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
            id=row["id"], name=row.get("name", row["id"]), kind=row["kind"], category=row["category"],
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
            fn=row.get("fn", ""), setup=row.get("setup", ""),
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
