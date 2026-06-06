# uz-kit

Personal Agent Skills and slash commands by uz. Portable across any tool that follows the [Agent Skills](https://agentskills.io) open standard — Claude Code, OpenCode, Codex CLI, Gemini CLI, Cursor, Copilot CLI, Kiro, and others.

GitLab: `git@gitlab.com:cco-open-src/uzkit.git`

## Contents

| Name | Type | Use case |
|---|---|---|
| [`reviewing-specs`](skills/reviewing-specs/SKILL.md) | skill | Audit-only reviewer for design/plan documents. Framework-agnostic. Accepts a pre-classified `DOC_TYPE` from the orchestrator; falls back to its own path heuristics + content-shape classification. |
| [`applying-review-feedback`](skills/applying-review-feedback/SKILL.md) | skill | Fixer that addresses each finding from a `reviewing-specs` report. All-or-nothing per finding (escalates if any sub-trigger requires a strategy decision). |
| [`cst-refactor`](skills/cst-refactor/SKILL.md) | skill | LibCST-based Python codemod helper. Multi-file renames and signature changes that survive comments and formatting. Bundled `codemod_template.py` with `rename-symbol`, `rename-parameter`, `add-parameter`, `remove-parameter`, `rewrite-docstring` subcommands. |
| [`/review-spec`](commands/review-spec.md) | slash command | Orchestrator for `reviewing-specs` + `applying-review-feedback`. Persists in-memory documents, classifies the document type, dispatches a fresh reviewer subagent, then a fresh fixer subagent, looping until Approved or iteration cap. |

## Install

The repo is itself the plugin. Clone it into the skills directory of whatever tool you're using.

### Claude Code

```bash
git clone git@gitlab.com:cco-open-src/uzkit.git ~/.claude/plugins/uz-kit
```

The `.claude-plugin/plugin.json` manifest is auto-detected.

### OpenCode

```bash
git clone git@gitlab.com:cco-open-src/uzkit.git ~/.opencode/skills/uz-kit
```

### Gemini CLI

```bash
git clone git@gitlab.com:cco-open-src/uzkit.git ~/.gemini/skills/uz-kit
```

### Codex CLI / Cursor / Kiro / others

Clone into the tool's standard skills directory. Skill discovery follows the [Agent Skills](https://agentskills.io) spec — every tool that supports it reads the `name` and `description` frontmatter from each `SKILL.md` and exposes the skill automatically.

Slash commands are Claude Code-specific today. On other tools, the orchestrator logic in `commands/review-spec.md` can still be invoked manually by reading and following its instructions.

## Updating across machines

```bash
cd ~/.claude/plugins/uz-kit  # or wherever cloned
git pull
```

The repo is the source of truth. Skills update on next `git pull`; tools re-read the `SKILL.md` files on next invocation.

## Layout

```
uz-kit/
├── .claude-plugin/plugin.json   # Claude Code manifest (other tools ignore)
├── README.md
├── skills/
│   ├── reviewing-specs/
│   ├── applying-review-feedback/
│   └── cst-refactor/
└── commands/
    └── review-spec.md
```

## Compatibility notes

- All `SKILL.md` files use the base [Agent Skills](https://agentskills.io/specification) frontmatter (`name`, `description`). No tool-specific extensions used. Claude-only fields (e.g. `allowed-tools`, `context: fork`) are not present, so the skills run unmodified on every conformant tool.
- The `cst-refactor` skill resolves its bundled `codemod_template.py` via `${CLAUDE_PLUGIN_ROOT}`. On non-Claude tools, substitute the path to wherever this repo is cloned.

## License

MIT.
