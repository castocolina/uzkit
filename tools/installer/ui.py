"""Shared console helpers for the uz-kit setup tool.

Uses `rich` when available (the `setup.py` uv header pins it). Falls back to a
markup-stripping plain-print shim when rich is absent, so the pure-data modules
(`_cli_tools` manifest parsing, etc.) stay importable under a bare `python3`
for unit tests — only the live wizard actually needs rich.
"""
from __future__ import annotations

import re

try:
    from rich.console import Console
    console = Console()
except ModuleNotFoundError:  # pragma: no cover - exercised only without rich
    _MARKUP = re.compile(r"\[/?[a-zA-Z0-9 #=_-]+\]")

    class _PlainConsole:
        def print(self, *args, **kwargs) -> None:
            text = " ".join(str(a) for a in args)
            print(_MARKUP.sub("", text))

        def rule(self, title: str = "") -> None:
            print(_MARKUP.sub("", title))

    console = _PlainConsole()


def info(msg: str) -> None:
    console.print(f"[cyan][info][/cyan] {msg}")


def ok(msg: str) -> None:
    console.print(f"[green][ok][/green]   {msg}")


def warn(msg: str) -> None:
    console.print(f"[yellow][warn][/yellow] {msg}")


def die(msg: str) -> None:
    console.print(f"[red][error][/red] {msg}")
    raise SystemExit(1)


def header(msg: str) -> None:
    console.rule(f"[bold cyan]{msg}[/bold cyan]")
