# CLI Tools for AI Coding Agents

> Reference guide for tools that maximize speed and minimize token consumption
> for AI coding agents (Claude Code and similar). Every tool includes a specific
> justification for why it matters to an agent, not just a human developer.

---

## Why these tools matter for agents (not just humans)

Every byte an agent reads goes into context. Every imprecise search fills that context
with noise. The right tools mean:

- Fewer calls to get the same information
- More precise results (fewer false positives polluting context)
- Surgical queries instead of "read the whole file"

---

## Search & Grep

### `ripgrep` (`rg`) — CRITICAL

Replaces `grep`/`egrep`. Written in Rust, uses SIMD and CPU parallelism.

**Why it matters for agents:** Respects `.gitignore` automatically — no flags needed.
Never returns `node_modules/`, `target/`, `.venv/`. An agent using plain `grep` wastes
tokens reading noise; `rg` filters it before the result ever reaches context.

```bash
rg "fn process_order" --type rust -l    # file names only
rg "TODO|FIXME" --stats                  # compact summary
rg -l "import React" --type ts           # which files use React
rg "class \w+Error" --type py -A 2       # error classes + 2 lines of context
```

### `ast-grep` (`sg`) — CRITICAL for structural navigation

AST-based search (tree-sitter). Understands syntax, not plain text.
Prevents false positives that pollute context (e.g., the string "function" vs an actual
function definition).

```bash
sg -p 'console.log($MSG)' -l js          # all console.log calls
sg -p 'async fn $NAME($$$)' -l rs        # async signatures in Rust
sg -p 'import { $X } from "$LIB"' -l ts  # named imports
sg -p 'try { $$$ } catch($E) { $$$ }'    # try/catch blocks across files
```

### `fd` — replaces `find`

`find . -name "*.ts" -not -path "*/node_modules/*"` becomes `fd -e ts`.
Less prompt noise, no syntax errors, respects gitignore by default.

```bash
fd -e py -t f              # .py files only
fd "config" --type f       # files with "config" in name
fd -e json -E node_modules # json files, excluding node_modules
fd --changed-within 2days  # recently modified files
```

---

## AST-based Code Navigation

### CodeGraph (MCP, already configured) — THE PRIMARY TOOL

Full AST index, sub-millisecond queries. See `CLAUDE.md` for usage rules.
Answers "what calls this function?" without reading any file.

### `ast-bro` — token-efficient symbol navigation

Built specifically for LLM coding agents. Exposes file shape (signatures + line numbers,
no bodies), package public API, dependency graphs, call graphs.

An agent asking "what methods does this file have?" pays ~40 tokens instead of reading
the whole file (1000+ tokens).

```bash
ast-bro outline src/main.rs     # signatures without bodies
ast-bro api src/lib.rs          # public API only
ast-bro calls src/handler.rs    # call graph
```

---

## Directory Exploration

### `eza` — replaces `ls`

`eza --tree --level=2 --git-ignore` gives project structure in one call,
automatically ignoring irrelevant paths. Far more useful than `ls -la`.

```bash
eza --tree --level=3 --git-ignore --icons
eza -la --git                    # git status per file
eza --tree --level=2 -I "*.pyc"  # exclude compiled files
```

### `tree` — classic recursive tree view

Still the most portable option for quick visual structure overview.

```bash
tree -L 2 -I "node_modules|.git|__pycache__"
tree -L 3 --dirsfirst -h          # show sizes, dirs first
tree -L 2 -I "*.pyc|*.egg-info"   # exclude multiple patterns
```

### `tokei` — codebase overview in one call

When landing on an unknown project, `tokei` gives in a single call: what languages
exist, how much code, code-to-comment ratio. Orientation without reading any file.

```bash
tokei .
# ───────────────────────────────────────────────────────────────────────────────
# Language                     Files        Lines         Code     Comments
# ───────────────────────────────────────────────────────────────────────────────
# Python                         143       12,430        9,810        1,200
# TypeScript                      67        5,200        4,100          400
# ───────────────────────────────────────────────────────────────────────────────
```

---

## Viewing & Inspection

### `bat` — replaces `cat`

Syntax highlighting + line numbers + inline git diff markers.
More useful when a human is watching; in headless mode `cat -n` is often enough.

```bash
bat --style=numbers,changes src/main.py
bat -l json config.json             # force language detection
bat --diff HEAD src/handler.ts      # show changes vs HEAD
```

### `jq` — CRITICAL for JSON

Surgical queries on JSON config files. Instead of reading a 200-line `package.json`
to find one dependency version, get exactly what's needed in one call.

```bash
jq '.dependencies.react' package.json       # exact version
jq '.scripts' package.json                  # only scripts
jq '.[] | select(.name == "foo")' arr.json  # filter array
jq -r '.version' package.json               # raw output (no quotes)
jq 'keys' package.json                      # top-level keys only
jq '{name,version}' package.json            # extract specific fields
```

### `yq` — CRITICAL for YAML/TOML/XML

Same as jq but for YAML, TOML, XML. Essential for Dockerfiles, CI configs,
Helm charts, any infrastructure-as-code.

```bash
yq '.services.api.image' docker-compose.yml
yq '.jobs.build.steps[0]' .github/workflows/ci.yml
yq -o=json . config.yaml                    # convert YAML → JSON
yq eval '.version = "2.0"' app.yaml         # inline edit
yq '. | keys' values.yaml                   # list all top-level keys
```

### `gron` — grepable JSON

Transforms JSON into flat assignments so `rg` can search it line by line.

```bash
gron package.json | rg "dependencies"
# json.dependencies.react = "^18.0.0";
# json.devDependencies.typescript = "^5.0.0";

gron package.json | rg "^json\." | head -20   # top-level keys only
```

---

## Git Tools

### `gh` (GitHub CLI) — CRITICAL for GitHub workflows

PRs, issues, CI checks, releases — all from the terminal. An agent can create PRs,
read reviews, check CI status, comment on issues without opening a browser.

```bash
gh pr create --title "fix: handle null case" --body "..."
gh pr checks                           # CI status summary
gh pr view --comments                  # read review comments inline
gh issue list --label bug --limit 20
gh run view                            # GitHub Actions output
gh run watch                           # stream CI in real time
gh api repos/:owner/:repo/releases     # raw API access
gh pr diff                             # diff of current PR
```

### `delta` — readable diffs

Diffs with syntax highlighting and word-level diffing. Configured in `~/.gitconfig`.

```bash
# ~/.gitconfig:
# [core]
#   pager = delta
# [delta]
#   navigate = true
#   side-by-side = true

git diff              # now uses delta automatically
git show HEAD         # same
git log -p            # log with delta-rendered patches
```

### `lazygit` — TUI for git

Primarily for humans, but useful for visually staging hunks before committing.

```bash
lazygit                    # full TUI
lazygit -p /path/to/repo   # open specific repo
```

---

## Package Managers (safe alternatives)

### The problem with `npm` and `pip`

| Tool | Main risk |
|------|-----------|
| `npm install` | No lockfile integrity guarantee by default; `-g` flag contaminates system PATH |
| `pip install` | Without venv, installs into system Python; easily breaks OS-level tooling |
| `yarn install` | Similar to npm; `yarn global add` is especially dangerous |

### Node.js — `volta` (toolchain) + `pnpm` (project packages)

**`volta`** manages Node.js versions and global CLI tools. It pins versions per-project
via `package.json` so every agent and developer gets the same Node automatically.
It is the preferred way to install Node itself and any globally-used binaries.

```bash
# Install volta
curl https://get.volta.sh | bash

# Install and pin Node globally
volta install node@20
volta install node@lts

# Install global CLI tools (safer than npm -g)
volta install typescript
volta install eslint
volta install pnpm        # install pnpm itself via volta

# Pin a specific node version per project (writes to package.json)
cd my-project && volta pin node@20
volta pin npm@10          # also pins npm version

# List installed toolchain
volta list
```

**`pnpm`** handles project-local package installs. Content-addressable store (saves
disk across projects), strict lockfile, native workspaces.

```bash
pnpm install              # install all deps from lockfile
pnpm add express          # add runtime dependency
pnpm add -D vitest        # add dev dependency
pnpm run build            # run script
pnpm dlx create-next-app  # one-off execution (replaces npx)
pnpm list --depth 1       # show installed packages
pnpm why lodash           # why is lodash installed?
```

**When to use which:**

| Task | Tool |
|------|------|
| Install Node.js itself | `volta install node` |
| Install global CLI (tsc, eslint) | `volta install <tool>` |
| Install project dependencies | `pnpm install` |
| Add a package to a project | `pnpm add <pkg>` |
| One-off script execution | `pnpm dlx <tool>` |
| Switch Node version per project | `volta pin node@X` |

### Python — `uv`

Replaces `pip`, `pip3`, `virtualenv`, `pyenv`, and partially `poetry`. Written in Rust,
10-100x faster than pip. Manages Python versions, virtual environments, and dependencies
under a single unified CLI.

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Project workflow
uv init my-project         # new project with pyproject.toml
uv add requests            # add dep (creates/updates venv automatically)
uv add --dev pytest        # add dev dependency
uv sync                    # install all deps from lockfile
uv run python script.py    # run inside venv without activating
uv run pytest              # run tool inside venv

# Python version management
uv python install 3.12
uv python pin 3.12         # pin version for current project

# Global tool installation (replaces pipx)
uv tool install ruff
uv tool install black
uv tool install httpie

# Inspect environment
uv pip show requests        # show package info
uv tree                     # dependency tree
```

### Safe Package Manager Policy

| Instead of | Use | Reason |
|------------|-----|--------|
| `pip install` | `uv add` / `uv sync` | No system contamination, lockfile, 100x faster |
| `pip install -U` | `uv add --upgrade` | Same |
| `pip install -g` | `uv tool install` | Isolated global tools |
| `npm install` | `pnpm install` | Strict lockfile, disk-efficient store |
| `npm install -g` | `volta install` | Version-pinned, clean PATH management |
| `npm i <pkg>` | `pnpm add <pkg>` | Consistent with pnpm workflow |
| `npx <tool>` | `pnpm dlx <tool>` | Same speed, consistent with pnpm |
| `yarn add` | `pnpm add` | Same ecosystem, better isolation |
| `yarn install` | `pnpm install` | Same |
| `node version switching` | `volta pin` | Per-project, automatic |
| `pyenv` | `uv python` | Same capability, one unified tool |

**Emergency override:** If a project has no `pnpm` or `uv` configured, ask the user
before using the legacy tool. Suggest migrating (`pnpm import`, `uv init`) first.

---

## System Utilities (often missing from distros)

### `sd` — replaces `sed`

Rust regex (not POSIX). Cleaner syntax, no escaping nightmares.

```bash
sd 'foo(\w+)' 'bar$1' file.txt         # no -E flag or backslash hell
sd -s 'literal.string' 'replace' file  # literal string mode (no regex)
sd 'old' 'new' **/*.ts                  # glob across files
```

### `dust` — replaces `du`

Visual disk usage tree. Useful before exploring large directories.

```bash
dust -d 2 .               # depth 2
dust -r .                 # reverse sort (smallest first)
dust -n 20 .              # show top 20 entries
```

### `ncdu` — interactive disk usage (ncurses)

Browse and delete files interactively.

```bash
ncdu /home
ncdu --exclude .git .
```

### `hyperfine` — command benchmarking

Useful when comparing performance of alternative commands or build scripts.

```bash
hyperfine 'rg pattern .' 'grep -r pattern .'
hyperfine --warmup 3 'pnpm run build'
hyperfine --runs 10 'uv sync' 'pip install -r requirements.txt'
```

### `fzf` — fuzzy finder

Most useful in interactive flows (human). For agents, its value is in pipes to filter
lists before using them as input.

```bash
rg --files | fzf             # interactive file picker
git branch | fzf             # interactive branch picker
history | fzf                # fuzzy shell history search
```

### `vim` / `nvim` — terminal editor

Essential on remote servers and containers where no GUI is available.

```bash
vim +/pattern file.txt                               # open at first match
vim -d file1 file2                                   # vimdiff
nvim --headless -c ":%s/foo/bar/g" -c "wq" file.txt  # scripted edit
```

### `htop` / `btop` — process monitoring

`btop` is the modern replacement with GPU stats, network graphs, disk I/O.

```bash
htop -u $USER     # filter by user
btop              # full system dashboard
```

### `tmux` — terminal multiplexer

Run long agent tasks in the background; split panes for parallel work.
Sessions survive disconnects.

```bash
tmux new -s work          # new named session
tmux attach -t work       # reattach after disconnect
# Ctrl+b d   →  detach (session keeps running)
# Ctrl+b %   →  split pane vertical
# Ctrl+b "   →  split pane horizontal
# Ctrl+b [   →  scroll mode
```

### `httpie` (`http`) — human-friendly HTTP client

Colored JSON output, intuitive syntax for quick API calls.

```bash
http GET api.example.com/users
http POST api.example.com/users name=Alice email=alice@example.com
http -a user:pass api.example.com/protected
http --download api.example.com/file.zip
```

### `tldr` — simplified man pages

Practical examples instead of full manuals.

```bash
tldr tar        # common tar examples
tldr docker     # common docker examples
tldr git        # common git examples
```

### `watch` — repeat a command on interval

```bash
watch -n 2 'gh run list --limit 5'    # poll CI every 2s
watch -n 1 'df -h'                    # monitor disk usage
watch -d 'cat /proc/meminfo'          # highlight changes
```

### `jless` — interactive JSON pager

Browse and explore large JSON files interactively.

```bash
cat package-lock.json | jless
curl -s api.example.com/data | jless
```

---

## Priority Ranking (agent ROI)

| Priority | Tool | Primary reason |
|----------|------|----------------|
| **P0** | `ripgrep` | Precise search, ignores noise automatically |
| **P0** | `jq` + `yq` | Surgical queries on config files |
| **P0** | `fd` | `find` without syntax friction |
| **P0** | `gh` | GitHub workflows without a browser |
| **P0** | `uv` | Safe, fast Python dependency management |
| **P0** | `volta` + `pnpm` | Safe, version-pinned Node.js management |
| **P1** | `ast-grep` | Structural search, not textual |
| **P1** | `tokei` | Instant orientation on new repos |
| **P1** | `eza` | Tree view with automatic gitignore |
| **P1** | `tmux` | Background tasks, session persistence |
| **P2** | `bat` | Useful when human is watching |
| **P2** | `delta` | More readable diffs |
| **P2** | `ast-bro` | Token savings in symbol navigation |
| **P2** | `htop` / `btop` | System health at a glance |
| **P2** | `tree` | Quick portable directory overview |
| **P3** | `fzf` | More useful in interactive flows |
| **P3** | `hyperfine` | Only needed for benchmarking |
| **P3** | `dust` / `ncdu` | Occasional disk inspection |
| **P3** | `jless` | Large JSON file exploration |

---

## Quick Install

**Interactive wizard:**

```bash
# Prerequisite: install uv once
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.local/bin/env   # or restart shell

uv run tools/setup.py
```

**Bare machine with no Python?** The bootstrap ensures uv (Linux/macOS), then launches the wizard:

```bash
bash tools/install-dev-tools.sh
```

The wizard menu:

| # | Action |
|---|--------|
| 1 | **Everything** — CLI tools + AI tools + register (default) |
| 2 | **CLI dev tools** — pick categories, pre-flight audit, install, summary |
| 3 | **AI tools** — superpowers, agent-toolkit, gsd, gentle-ai (install/wire/update) |
| 4 | **Register uz-kit** — symlink skills/commands/agents into Claude + Codex |
| 5 | **Shell guards** — ban `npm`/`pip` (point at volta/pnpm/uv) for every executor |
| 6 | **Version sync** — installed vs latest version **+ release date**; flags outdated |

Detects your OS (apt / pacman / brew) and installs only missing tools. Dependencies declared
via `requires` are installed first **and dragged in** when missing (e.g. selecting `pyright`
pulls `volta`; `pi` pulls `volta` + Node 22).

---

## The registry (`tools/installer/registry.toml`)

One declarative `[[tool]]` table is the single source of truth — **add or rewire a tool by
editing a row, no Python change** (unless it needs a bespoke `custom` installer).

Each row picks a `kind`, and a generic strategy (`tools/installer/strategies.py`) installs it:

| `kind` | Fields | What it does |
|--------|--------|--------------|
| `pkg` | `pkg.{debian,arch,brew}`, `alias_cmd` | OS package manager install |
| `cargo` | `crate`, `pkg.{arch,brew}` fallback | `cargo install` (or distro pkg) |
| `node` | `npm_pkg` | install via **volta** then pnpm — never bare npm |
| `curl` | `url`, `shell`, `brew`, `bin_dir` | run an official curl installer |
| `github-release` | `repo`, `asset` (templated), `member`, `raw` | download a release asset |
| `marketplace` | `marketplace`, `marketplace_ref`, `plugins[]` | Claude plugin marketplace |
| `launcher` | `bootstrap_*`, `wiring`, `update`, `verify`, `wired_marker`, `interactive` | obtain a CLI then wire it |
| `custom` | `fn` | escape hatch → a Python fn in `installer/custom.py` |

**Asset templates** (`github-release`) expand `{ver}` (autodiscovered), `{os}`, and
`{arch.deb|go|suffix|machine}`. `raw=true` downloads the asset directly as the binary
(no archive extract). Example:

```toml
[[tool]]
id = "lazygit"
kind = "github-release"
category = "git"
priority = "P2"
repo = "jesseduffield/lazygit"
asset = "lazygit_{ver}_Linux_{arch.suffix}.tar.gz"
member = "lazygit"
bin_dir = "~/.local/bin"
[tool.version]                         # optional — powers `sync`
latest = "github:jesseduffield/lazygit"   # or crates:<name> | json:URL#dotted.key
installed_cmd = "lazygit --version"
installed_re = "version=([0-9.]+)"
```

**Common fields:** `id` (unique), `name`, `kind`, `category`, `priority`, `cmd` (defaults to
`id`), `requires=[ids]` (ordered + dragged in), `bin_dir` (PATH is managed by the single
`ensure_on_path()` helper), `setup` (a one-time post-install shell command, e.g. pnpm's
`"pnpm self-update && pnpm setup"`), and `notes`.

**Extending — which `kind` to pick:**
- A binary from a GitHub release tarball → `github-release` (set `repo`/`asset`; add a
  `[tool.version]` block so `sync` can flag it outdated).
- An official `curl … | sh` installer → `curl`.
- In apt/pacman/brew → `pkg`; a Rust crate → `cargo`; a Node global → `node`.
- Anything irregular (gpg-keyed apt repo, dmg mount, MCP wiring) → `custom` + a
  `install_<id>(tool, os_name, arch)` function in `installer/custom.py`.
