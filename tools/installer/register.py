"""Self-registration of uz-kit assets into Claude Code and Codex via symlinks.

Neither side uses a marketplace here — we just drop symlinks for the skills/commands/
agents that aren't already present in the user's global config:

  Claude  → native layout: ~/.claude/commands/*.md, ~/.claude/skills/<name>/ (dir),
            ~/.claude/agents/*.md
  Codex   → flat prompts:  ~/.codex/prompts/<name>.md (SKILL.md exposed as a prompt)

Both syncs are idempotent and prune only stale links that point back into uz-kit;
a real file the user placed there, or a symlink to something else, is left untouched.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from ui import warn

SETTINGS = Path.home() / ".claude" / "settings.json"


def plugin_root() -> Path:
    """The uz-kit repo root — installer/ lives under tools/, so go up three."""
    return Path(__file__).resolve().parent.parent.parent


# ── marketplace status (read from ~/.claude/settings.json enabledPlugins) ─────────

def _enabled_plugins() -> dict:
    try:
        return json.loads(SETTINGS.read_text()).get("enabledPlugins", {})
    except (OSError, ValueError):
        return {}


def marketplace_enabled(tool) -> bool:
    """True if a marketplace tool's plugins are enabled in settings.json."""
    ep = _enabled_plugins()
    if tool.plugins:
        return any(ep.get(f"{p}@{tool.marketplace}") for p in tool.plugins)
    return any(k.endswith(f"@{tool.marketplace}") and v for k, v in ep.items())


# ── generic idempotent symlink sync ──────────────────────────────────────────────

def _sync_links(wanted: dict[Path, Path], prune_dirs: list[Path], root: Path) -> dict[str, int]:
    """Create/refresh the wanted {link: target} symlinks; prune stale uz-kit links in
    prune_dirs. Never clobbers a non-symlink or a link pointing outside `root`."""
    counts = {"created": 0, "updated": 0, "kept": 0, "removed": 0, "skipped": 0}
    for link, target in wanted.items():
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.is_symlink():
            if link.resolve() == target.resolve():
                counts["kept"] += 1
            else:
                link.unlink()
                link.symlink_to(target)
                counts["updated"] += 1
        elif link.exists():
            warn(f"{link} exists and is not a symlink — leaving it alone.")
            counts["skipped"] += 1
        else:
            link.symlink_to(target)
            counts["created"] += 1

    wanted_links = set(wanted)
    root_resolved = str(root.resolve())
    for d in prune_dirs:
        if not d.is_dir():
            continue
        for link in list(d.iterdir()):
            if not link.is_symlink():
                continue
            abs_target = os.path.normpath(os.path.join(d, os.readlink(link)))
            if abs_target.startswith(root_resolved) and (link not in wanted_links or not link.exists()):
                link.unlink()
                counts["removed"] += 1
    return counts


# ── Claude (native ~/.claude layout) ─────────────────────────────────────────────

def sync_claude(root: Path, dest: Path | None = None) -> dict[str, int]:
    """Symlink uz-kit commands/skills/agents into ~/.claude using the native layout.
    Skills are linked as whole directories (Claude needs SKILL.md + its resources)."""
    base = dest or (Path.home() / ".claude")
    wanted: dict[Path, Path] = {}

    cmds = root / "commands"
    if cmds.is_dir():
        for f in sorted(cmds.glob("*.md")):
            wanted[base / "commands" / f.name] = f.resolve()

    skills = root / "skills"
    if skills.is_dir():
        for sk in sorted(p for p in skills.iterdir() if p.is_dir()):
            if (sk / "SKILL.md").is_file():
                wanted[base / "skills" / sk.name] = sk.resolve()

    agents = root / "agents"
    if agents.is_dir():
        for f in sorted(agents.glob("*.md")):
            wanted[base / "agents" / f.name] = f.resolve()

    prune = [base / "commands", base / "skills", base / "agents"]
    return _sync_links(wanted, prune, root)


# ── Codex (flat ~/.codex/prompts layout) ─────────────────────────────────────────

def _codex_assets(root: Path):
    """Yield (codex_prompt_filename, source_path) for each linkable uz-kit asset."""
    cmds = root / "commands"
    if cmds.is_dir():
        for f in sorted(cmds.glob("*.md")):
            yield f.name, f
    skills = root / "skills"
    if skills.is_dir():
        for sk in sorted(p for p in skills.iterdir() if p.is_dir()):
            if (sk / "SKILL.md").is_file():
                yield f"{sk.name}.md", sk / "SKILL.md"      # skill name as the prompt name
    agents = root / "agents"
    if agents.is_dir():
        for f in sorted(agents.glob("*.md")):
            yield f"agent-{f.name}", f


def sync_codex(root: Path, dest: Path | None = None) -> dict[str, int]:
    """Idempotently symlink uz-kit commands + skills into Codex's prompt dir."""
    dest = dest or (Path.home() / ".codex" / "prompts")
    wanted = {dest / name: src.resolve() for name, src in _codex_assets(root)}
    return _sync_links(wanted, [dest], root)
