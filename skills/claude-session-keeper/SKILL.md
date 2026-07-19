---
name: claude-session-keeper
description: Persist long-running Claude Code sessions (the tmux-backed Remote Control ones) across reboots and crashes. Use when the user wants a session to survive a reboot / the machine sleeping / an OOM, to "keep this session", "add this to recovery", "persist this chat", "restore my sessions after reboot", "remember this session", or to list / remove tracked sessions. Also use to add THIS session to the recovery list on request, or to set up the self-heal timer. CLI is `claude-keep`.
---

# claude-session-keeper

Keeps long-running Claude Code **Remote Control / tmux** sessions alive across reboots,
the machine sleeping, and OOM kills. A session **registers itself**, the list is a plain
TSV, and a systemd timer **self-heals** anything that died — re-launching it with the same
conversation (`claude --resume <uuid>`) and re-enabling Remote Control.

> **CLI:** call **`claude-keep`** (auto-added to PATH when installed as a plugin). If it's somehow
> not on PATH, fall back to `"$CLAUDE_PLUGIN_ROOT/bin/claude-keep"`. Never hardcode a versioned cache path.

## How a session identifies itself

`claude-keep add` takes **no arguments** — it reads the calling session's own environment:

| Field | Source |
|---|---|
| uuid | `$CLAUDE_CODE_SESSION_ID` |
| tmux name | `tmux display-message -p '#{session_name}'` |
| cwd | `$PWD` |
| effort | `$CLAUDE_EFFORT` |

So an agent can add *itself* in one call. **Run `claude-keep add` from inside the session you want
to persist** (e.g. the agent runs it in its own Bash tool) so the env reflects that session.
Model is **not** stored — `claude --resume` restores the session's own model.

## Commands

| Command | Action |
|---|---|
| `claude-keep add [--no-rc] [--effort <e>]` | Register THIS session. `--no-rc` = plain tmux session (don't re-enable Remote Control on restore). |
| `claude-keep rm [name]` | Remove THIS session (no arg) or a named one. Accepts the bare title (`yango`) or full tmux name (`cc—dev-serv-in/yango`). |
| `claude-keep ls` | List the registry + who is live right now. |
| `claude-keep restore` | Re-launch every registered session that isn't live. Idempotent. |
| `claude-keep install-timer [--interval M]` | Install a systemd --user timer (default 5 min) that runs `restore`. |
| `claude-keep uninstall-timer` | Remove the timer. |

## Restore behaviour (what the timer does)

For each registered session that isn't currently live:

- **cwd not reachable** (e.g. a network mount isn't up yet) → **skipped**, retried next tick.
  `claude-keep` knows nothing about mounts — keep mounts healthy with their own keeper.
- otherwise → `tmux new-session … claude --resume <uuid> [--effort <e>]`, then it:
  - answers the **"Resume session?"** dialog with **option 2 (full)** — never a lossy summary;
  - re-issues **`/remote-control <title>`** (unless `--no-rc`) and auto-confirms the prompt.

## Notifications (optional)

The keeper never sends over the network itself and **bundles no notifier**. To get alerts
(e.g. a session that stays down and can't be relaunched), point **`$KEEP_NOTIFY_CMD`** at a
**single command** that takes the message as its **first argument** — the keeper runs exactly
`"$KEEP_NOTIFY_CMD" "the message"` (the value is one command, not a shell line):

```bash
export KEEP_NOTIFY_CMD='my-notify'          # your own wrapper: `my-notify "text"` → sends it
```

Need a pipeline or curl? Put it in a tiny wrapper script and point at that:

```bash
cat > ~/bin/keep-notify <<'EOF'
#!/usr/bin/env bash
curl -s -d "$1" ntfy.sh/my-topic >/dev/null    # $1 is the message
EOF
chmod +x ~/bin/keep-notify
export KEEP_NOTIFY_CMD=keep-notify
```

Unset → the keeper runs silently (logs to stderr). Set it in the environment the timer runs
under — e.g. a systemd drop-in `~/.config/systemd/user/claude-keep-restore.service.d/notify.conf`
with `[Service]\nEnvironment=KEEP_NOTIFY_CMD=…` — so alerts fire unattended. This keeps the repo
notifier-agnostic: wire your own channel in without patching the code.

## Typical setup

```bash
# once: turn on the self-heal timer (survives reboot via lingering)
claude-keep install-timer --interval 5

# in each session you want to keep (the agent runs this in its own session):
claude-keep add

# anytime
claude-keep ls                 # see what's tracked and what's live
claude-keep rm trendwatcher    # stop tracking one
claude-keep restore            # manually bring back everything that's down
```

## Notes

- The registry lives at `~/.claude-keep/sessions.tsv` (override with `$CLAUDE_KEEP_HOME`).
- `restore` is **idempotent** — a session already live is left alone; safe to run on a timer.
- A reboot kills tmux + the claude processes, but the conversation JSONLs survive on disk, so
  `--resume` brings each session back where it was (with the always-**full** resume policy the
  uuid stays stable — `/compact` and full-resume keep the same JSONL).
- This skill persists **sessions**. If your sessions live on a **network-mounted cwd**, that
  mount needs its own keeper so the cwd is ready when `restore` runs.
