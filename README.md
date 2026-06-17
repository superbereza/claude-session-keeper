# claude-session-keeper

Persist long-running Claude Code **Remote Control / tmux** sessions across **reboots, the
machine sleeping, and OOM kills**. A session registers itself, the list is a plain TSV, and a
systemd timer self-heals anything that died — re-launching it with the same conversation
(`claude --resume`) and re-enabling Remote Control.

Built after one too many "the box rebooted and I lost 13 sessions" mornings.

## Why

A reboot (or an OOM, or the laptop you SSHF-mount from going to sleep) kills your tmux server
and every `claude` process — but the **conversations survive on disk** as resumable JSONLs.
This tool keeps a small registry of which sessions matter and brings them back automatically.

## Install

**Claude Code** (also its own marketplace):

```
/plugin marketplace add superbereza/claude-session-keeper
/plugin install claude-session-keeper@claude-session-keeper
```

The `claude-keep` CLI is auto-added to PATH while the plugin is enabled. Other agents read their own
manifests (`.cursor-plugin/`, `.codex-plugin/`, `gemini-extension.json`, `.opencode/`).

## Use

```bash
# once: turn on the self-heal timer (survives reboot via lingering)
claude-keep install-timer --interval 5

# in each session you want to keep — the agent runs this in its own session:
claude-keep add

# manage
claude-keep ls                 # registry + who's live
claude-keep rm trendwatcher    # stop tracking one (bare title or full cc— name)
claude-keep restore            # manually bring back everything that's down
```

`claude-keep add` needs no arguments — it reads the calling session's own environment
(`$CLAUDE_CODE_SESSION_ID`, the tmux session name, `$PWD`, `$CLAUDE_EFFORT`). Model isn't
stored; `claude --resume` restores the session's own model.

## How restore works

For each registered session that isn't live:

- **cwd not reachable** (e.g. a network mount isn't up yet) → **skipped**, retried next tick.
- otherwise → `tmux new-session … claude --resume <uuid>`, then it answers the
  "Resume session?" dialog with **option 2 (full)** — never a lossy summary — and re-issues
  `/remote-control` (unless `--no-rc`).

Idempotent: a session already live is left alone, so it's safe on a timer.

## Scope

This keeps **sessions** alive. It knows nothing about mounts — if your sessions live on a
network-mounted cwd, give that mount its **own** keeper. The two reconcile independently:
`restore` simply waits (skips + retries) until the cwd is ready.

## Files

| Path | What |
|---|---|
| `bin/claude-keep` | the CLI (self-contained bash) |
| `skills/claude-session-keeper/SKILL.md` | the skill (agent instructions) |
| `~/.claude-keep/sessions.tsv` | the registry (override with `$CLAUDE_KEEP_HOME`) |

## Versioning

`scripts/bump.sh <v>` keeps `VERSION` + every manifest in sync. Tag `vX.Y.Z` + a GitHub
Release is what propagates a change to installed plugins.
