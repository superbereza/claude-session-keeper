---
name: claude-session-keeper
description: Persist long-running Claude Code sessions (the tmux-backed Remote Control ones) across reboots and crashes. Use when the user wants a session to survive a reboot / the machine sleeping / an OOM, to "keep this session", "add this to recovery", "persist this chat", "restore my sessions after reboot", "remember this session", or to list / remove tracked sessions. Also use to add THIS session to the recovery list on request, or to set up the self-heal timer. CLI is `csk`.
---

# claude-session-keeper

Keeps long-running Claude Code **Remote Control / tmux** sessions alive across reboots,
the machine sleeping, and OOM kills. A session **registers itself**, the list is a plain
TSV, and a systemd timer **self-heals** anything that died — re-launching it with the same
conversation (`claude --resume <uuid>`) and re-enabling Remote Control.

> **CLI:** call **`csk`** (auto-added to PATH when installed as a plugin). If it's somehow
> not on PATH, fall back to `"$CLAUDE_PLUGIN_ROOT/bin/csk"`. Never hardcode a versioned cache path.

## How a session identifies itself

`csk add` takes **no arguments** — it reads the calling session's own environment:

| Field | Source |
|---|---|
| uuid | `$CLAUDE_CODE_SESSION_ID` |
| tmux name | `tmux display-message -p '#{session_name}'` |
| cwd | `$PWD` |
| effort | `$CLAUDE_EFFORT` |

So an agent can add *itself* in one call. **Run `csk add` from inside the session you want
to persist** (e.g. the agent runs it in its own Bash tool) so the env reflects that session.
Model is **not** stored — `claude --resume` restores the session's own model.

## Commands

| Command | Action |
|---|---|
| `csk add [--no-rc] [--effort <e>]` | Register THIS session. `--no-rc` = plain tmux session (don't re-enable Remote Control on restore). |
| `csk rm [name]` | Remove THIS session (no arg) or a named one. Accepts the bare title (`yango`) or full tmux name (`cc—dev-serv-in/yango`). |
| `csk ls` | List the registry + who is live right now. |
| `csk restore` | Re-launch every registered session that isn't live. Idempotent. |
| `csk install-timer [--interval M]` | Install a systemd --user timer (default 5 min) that runs `restore`. |
| `csk uninstall-timer` | Remove the timer. |

## Restore behaviour (what the timer does)

For each registered session that isn't currently live:

- **cwd not reachable** (e.g. a network mount isn't up yet) → **skipped**, retried next tick.
  `csk` knows nothing about mounts — keep mounts healthy with their own keeper.
- otherwise → `tmux new-session … claude --resume <uuid> [--effort <e>]`, then it:
  - answers the **"Resume session?"** dialog with **option 2 (full)** — never a lossy summary;
  - re-issues **`/remote-control <title>`** (unless `--no-rc`) and auto-confirms the prompt.

## Typical setup

```bash
# once: turn on the self-heal timer (survives reboot via lingering)
csk install-timer --interval 5

# in each session you want to keep (the agent runs this in its own session):
csk add

# anytime
csk ls                 # see what's tracked and what's live
csk rm trendwatcher    # stop tracking one
csk restore            # manually bring back everything that's down
```

## Notes

- The registry lives at `~/.claude-session-keeper/sessions.tsv` (override with `$CSK_HOME`).
- `restore` is **idempotent** — a session already live is left alone; safe to run on a timer.
- A reboot kills tmux + the claude processes, but the conversation JSONLs survive on disk, so
  `--resume` brings each session back where it was (with the always-**full** resume policy the
  uuid stays stable — `/compact` and full-resume keep the same JSONL).
- This skill persists **sessions**. If your sessions live on a **network-mounted cwd**, that
  mount needs its own keeper so the cwd is ready when `restore` runs.
