#!/usr/bin/env bash
# install-dev-tools.sh — thin bootstrap for the uz-kit setup wizard.
#
# Entrypoint is tools/setup.py; all data lives in tools/installer/registry.toml. This
# wrapper exists only so a bare machine with no Python can still run the wizard:
# it ensures `uv` is present (uv provides Python AND installs the script's deps),
# then launches setup.py. Linux & macOS.
#
# Usage:  bash tools/install-dev-tools.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OS="$(uname -s)"

have() { command -v "$1" >/dev/null 2>&1; }

ensure_uv() {
    if have uv; then
        return
    fi
    echo "[info] Installing uv (provides Python + script deps)..."
    case "$OS" in
        Darwin)
            if have brew; then
                brew install uv
            else
                curl -LsSf https://astral.sh/uv/install.sh | sh
            fi
            ;;
        Linux)
            curl -LsSf https://astral.sh/uv/install.sh | sh
            ;;
        *)
            echo "[error] Unsupported OS: $OS (Linux/macOS only)" >&2
            exit 1
            ;;
    esac
    # uv installs into ~/.local/bin
    export PATH="$HOME/.local/bin:$PATH"
    if ! have uv; then
        echo "[error] uv install failed; add \$HOME/.local/bin to PATH and retry" >&2
        exit 1
    fi
}

ensure_uv
exec uv run "$SCRIPT_DIR/setup.py" "$@"
