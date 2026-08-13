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
| `claude-keep doctor` | Audit the registry against the transcripts on disk. Flags **DRIFT** (the `<uuid>.jsonl` moved to another cwd's project dir — e.g. the session wandered into a git worktree), **DEAD-CWD** (cwd deleted), and **LOST** (no transcript anywhere). These are the entries that silently fail to resume. Read-only; suggests the fix per row. |
| `claude-keep migrate <session> <new-cwd>` | Relocate a session's transcript to `<new-cwd>` (copy its `<uuid>.jsonl` into that cwd's project dir + repoint the registry) so it resumes there. Fixes a DRIFT/DEAD-CWD, or deliberately moves a session's working dir. **Copies** (original kept as backup). |
| `claude-keep restore` | Re-launch every registered session that isn't live, then **tidy** the live ones. Idempotent. **Auto-heals a drifted transcript** (copies it into the registered cwd's project dir) and **skips a lost one** instead of launching a doomed `--resume`. |
| `claude-keep tidy` | Tidy **LIVE** sessions only (no relaunch): clear a stuck **"Resume session?"** dialog (option 2 = full) or a stuck **Remote Control** panel, **re-establish Remote Control when its bridge is genuinely absent** (read from Claude Code's per-process state file, not the flaky TUI — see below), and alert via `$KEEP_NOTIFY_CMD` if the shared login is logged out. Folded into `restore`, so the one timer keeps sessions both **alive and reachable**. |
| `claude-keep status` | Print one structured record per session as JSON — the **state engine's** merged view (registry + tmux liveness + `~/.claude/sessions/<pid>.json` + parsed pane): `live`, `status`, `rc_bridge`, `rc_footer`, `dialog`, `drift`, etc. This is the same data `tidy`/`restore` act on. Needs `python3`. |
| `claude-keep install-timer [--interval M]` | Install a systemd --user timer (default 5 min) that runs `restore` (which now includes the tidy pass). |
| `claude-keep uninstall-timer` | Remove the restore timer. |

## Restore behaviour (what the timer does)

For each registered session that isn't currently live:

- **cwd not reachable** (e.g. a network mount isn't up yet) → **skipped**, retried next tick.
  `claude-keep` knows nothing about mounts — keep mounts healthy with their own keeper.
- **cwd GONE because the folder was renamed/moved** → detected and **auto-fixed**, not silently
  skipped forever. A session records its `cwd` in every transcript entry, so a mid-session rename
  leaves the **new** path in its recent entries. When the registered cwd no longer exists but the
  transcript's dominant recent cwd is a *different, existing* folder, `restore` **auto-relocates**
  it (copies the transcript into the new cwd's project dir + repoints the registry — original kept)
  and resumes there, emitting an informational `$KEEP_NOTIFY_CMD` note; `doctor` names the path too.
  Opt out with **`KEEP_AUTO_MIGRATE_RENAMED=0`** — then it only alerts and suggests
  `claude-keep migrate '<session>' '<new>'`. A still-down mount is distinguished (its recent cwd is
  the *same* missing path, so nothing existing-and-different dominates) and just keeps waiting.
- otherwise → `tmux new-session … claude --resume <uuid> [--effort <e>]`, then it:
  - answers the **"Resume session?"** dialog with **option 2 (full)** — never a lossy summary;
  - re-issues **`/remote-control <title>`** (unless `--no-rc`) and auto-confirms the prompt.

**Memory gate.** Each `--resume` is a full process loading its whole transcript — a real memory
spike. So restore **paces** its relaunches (it drives each session's resume dialog to completion
before the next) and **stops** if free memory falls below a floor (`$KEEP_RESTORE_MEM_MIN` MiB,
default 400), leaving the rest for the next tick and alerting via `$KEEP_NOTIFY_CMD`. This is what
keeps an **OOM-driven mass restart** (the box ran out of RAM and killed a batch of sessions) from
piling N heavy resumes back onto an already-tight box — it brings them back gradually as memory
frees. A box without `free` is treated as "plenty" (the gate never blocks on a missing reading).

Then a second pass **tidies every live session** (`tidy`, below).

## Tidying live sessions (`tidy`)

`restore` relaunches **dead** sessions; `tidy` touches only **live** ones — it clears stuck
dialogs and re-establishes a genuinely-absent Remote Control channel, without relaunching. It's
folded into `restore` (and its timer), and also runnable on its own. What it does per live session:

- a stuck **"Resume session?"** dialog → answers **option 2 (full)**, never a lossy summary;
- a stuck **Remote Control management panel** (Disconnect / QR / Continue) → dismissed;
- the one-time **"Enable Remote Control"** confirm → accepted;
- **Remote Control genuinely absent → re-issues `/remote-control <title>`** to bring it back
  (see below).

### Re-establishing Remote Control (the authoritative signal)

The `/rc` footer in the TUI is a **hint, not a reliable state** — scraping it false-positives (a
bare `/rc` misread as "dropped" → a spurious re-issue → a stuck management panel). So `tidy` reads
Claude Code's per-process state file instead: **`~/.claude/sessions/<pid>.json`**, keyed by pid and
carrying the session's `sessionId`, `status` (idle/busy), and — when Remote Control is registered —
a **`bridgeSessionId`**. `tidy` acts on **one signal only: the bridge is ABSENT** (the field isn't
there) → RC never came up or was torn down → re-issue `/remote-control`. That's the sole RC signal
that **cannot** false-positive.

- **A present `bridgeSessionId` is left untouched.** It is *not* proof of a live channel — it can go
  stale on a silent bridge death (upstream `anthropics/claude-code` #78878 / #57715), and there is
  no local way to tell a stale one from a live one (no API — confirmed). But re-issuing a session
  that still holds a bridge is exactly what left panels stuck before, so presence ⇒ hands off.
  Corollary: a **silent** RC death (bridge stays stale-present) is **not** auto-recovered — only a
  genuinely-absent bridge is. Recover a silent one by re-issuing `/remote-control` yourself.
- The state file is **undocumented internal state** (explicitly, in #54981) — treated as a
  best-effort accelerator with a hard fallback: **no state file for a session ⇒ RC is left alone**
  (no scraping), so a future Claude Code that changes/drops the file degrades safely.

Guardrails, learned the hard way:

- **idle-gate** — a session mid-generation is never touched (checked twice: the state file's
  `status` must be `idle`, and the pane must not show `esc to interrupt`);
- **login-aware** — if the shared credential has no refresh token (genuinely logged out), it emits
  one deduped "run `claude auth login`" alert via `$KEEP_NOTIFY_CMD` and does **not** re-issue RC (a
  login is the real blocker). An expired *access* token is normal — it refreshes on use — so that
  alone is never treated as login-needed.

## Session migration — the transcript is portable (canonical)

A Claude Code session is just two things:

1. its **transcript** — `~/.claude/projects/<cwd-encoded>/<uuid>.jsonl`, where `<cwd-encoded>`
   is the working directory with **every `/` replaced by `-`** (`/home/me/dev` →
   `-home-me-dev`); and
2. a **cwd** it was launched from.

`claude --resume <uuid>` looks for `<uuid>.jsonl` **in the current cwd's project dir**. So a
session is *relocatable*: **copy its jsonl into another cwd's project dir, then
`claude --resume` from that cwd**, and the same conversation continues there. The registry
just needs its `cwd` column repointed. That's the whole trick behind `migrate` — and behind
recovering a session whose cwd vanished.

**Drift** is when the transcript and the registered cwd disagree — the `<uuid>.jsonl` lives in
a *different* project dir than the cwd says. It happens when a session **wanders into a git
worktree** (Claude re-homes the transcript to the worktree's project dir) and the worktree is
later auto-deleted, or when the cwd is otherwise moved/removed. A drifted session **dies
instantly on `--resume`** (the jsonl isn't where the cwd points), so it looks like it "won't
come back up". `doctor` finds it; `migrate` (or `restore`'s auto-heal) fixes it by copying the
transcript to a live cwd's project dir.

(The same idea one level up — shipping the jsonl + registry row to *another machine* — is a
separate concern handled by a dedicated cross-machine tool; this skill stays same-machine.)

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
