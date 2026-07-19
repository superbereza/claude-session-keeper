# claude-session-keeper — agent guide

Persist long-running Claude Code **Remote Control / tmux** sessions across reboots, the
machine sleeping, and OOM kills. A session **registers itself**, the list is a plain TSV,
and a systemd timer **self-heals** anything that died (`claude --resume` + re-enable
Remote Control).

The skill is wired up for several coding agents from one source:

- **Claude Code / Cursor / Codex** — load the skill at [`skills/claude-session-keeper/SKILL.md`](skills/claude-session-keeper/SKILL.md)
  (auto-discovered via `.claude-plugin/`, `.cursor-plugin/`, `.codex-plugin/`).
- **Gemini** — reads this file (`gemini-extension.json` → `contextFileName: AGENTS.md`).
- Full, authoritative usage: [`skills/claude-session-keeper/SKILL.md`](skills/claude-session-keeper/SKILL.md).

Requires `tmux`, `claude` (logged in), and `systemd --user` (for the timer).

## Invoking the CLI

`claude-keep` is on PATH when installed as a plugin (Claude Code auto-adds `bin/`). Otherwise call
`./bin/claude-keep` from this repo, or `"$CLAUDE_PLUGIN_ROOT/bin/claude-keep"`. Self-contained bash — no build.

## Cheat sheet

```bash
claude-keep add [--no-rc] [--effort <e>]   # register THIS session (reads its own env)
claude-keep rm [name]                      # remove THIS session, or a named one
claude-keep ls                             # list registry + who's live
claude-keep restore                        # re-launch everything that's down (idempotent)
claude-keep install-timer [--interval M]   # systemd --user timer → restore (default 5 min)
claude-keep uninstall-timer
```

`claude-keep add` reads the calling session's identity from its env: `$CLAUDE_CODE_SESSION_ID`
(uuid), `tmux display-message` (name), `$PWD` (cwd), `$CLAUDE_EFFORT`. Run it **inside**
the session you want to keep. Model isn't stored — `claude --resume` restores it.

## Design

Two concerns, deliberately decoupled — this repo owns only the first:

1. **session liveness** (here) — keep registered sessions running.
2. **mount health** (elsewhere) — keep a network-mounted cwd up.

`restore` **skips** a session whose cwd isn't reachable (mount not up yet) and retries next
tick; it never blocks or fails on it. If your sessions live on a network mount, give that
mount its own keeper — the two reconcile independently on their own timers.

**Notifications are a pluggable seam, not a dependency:** the keeper calls `$KEEP_NOTIFY_CMD`
"message" if set, else stays silent. Bring your own notifier (Telegram, ntfy, anything) — the
repo bundles none. See the SKILL's "Notifications (optional)" section.

## Maintainer note

Changing a skill or its payload reaches installed plugins **only after a release** —
`scripts/bump.sh <v>` → commit → tag `vX.Y.Z` → GitHub release → `/plugin update`. A commit on
`main` alone propagates nothing (plugins are cached by version string).
