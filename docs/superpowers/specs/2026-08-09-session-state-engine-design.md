# Session-state engine + zoned TUI parser — design

**Date:** 2026-08-09
**Repo:** claude-session-keeper
**Status:** design, pending implementation

## Goal

Reliably **restore Remote Control (RC)** on every tracked session — including the case we
currently can't: a **silent bridge drop** (the RC channel dies while the process keeps running,
leaving `bridgeSessionId` stale-present in the state file). Today `tidy` re-establishes RC only
when the bridge is *absent* (v0.7.0). The silent drop is the remaining gap.

Getting there cleanly means one structural change: stop scattering ad-hoc `grep`s of the TUI
across `_drive_restore` / `_tidy_pane` / `_state_for`, and instead build **one engine that
produces a single authoritative state record per session**, which the self-heal actions
(`restore`, `tidy`, RC re-establish) read as thin policies.

RC restoration is the driving use case; the engine is the substrate that makes it — and the
existing actions — testable and correct.

## Non-goals (YAGNI)

- No rewrite of `restore`/`tidy` in one shot. Build the engine + fixtures + a `status` view
  first, then migrate policies onto it **one at a time**, starting with RC re-establish.
- No general "dashboard". A `status --json` falls out of the engine for free; anything richer
  is out of scope.
- No attempt to detect a silent RC drop until the footer-semantics experiment (below) confirms
  the signal. Until then the relevant field stays `unknown` and no action is taken on it.

## Architecture: pure core, I/O at the edges

The engine is soaked in external state (tmux, JSON files, a TSV). To make it testable we keep
the **core pure** — functions from strings/dicts to records — and confine all I/O to a thin
shell.

```
PURE CORE (unit-tested)                     IMPURE SHELL (thin, not unit-tested)
  parse_pane(text)        -> tui_fields      gather():
  parse_state(json_text)  -> state_fields      - tmux capture-pane / has-session / list-panes
  merge(reg,live,state,tui) -> record          - read ~/.claude/sessions/*.json
  derive_health(record)   -> up|down|unknown   - read ~/.claude-keep/sessions.tsv
  decide(record)          -> action|none        └─ passes raw STRINGS into the core
```

Sources feed the engine; the engine emits one record per session; policies act on records.

```
  registry (tsv) ─┐
  tmux liveness  ─┤      session_state()          restore  → dead        → relaunch
  state-file json ┼──►  [ per-session record ] ─► tidy     → stuck dialog → clear
  TUI pane parse ─┘                               rc-heal  → RC down      → /remote-control
```

## The per-session record

```
{
  # identity — from registry ONLY (set at `claude-keep add`, never re-derived)
  name, uuid, cwd_registered, effort,
  rc_desired: bool,           # registry `rc` column: 1 default, 0 with --no-rc

  # liveness — tmux + state-file
  live: bool, pane_id, pid, status: idle|busy|unknown,

  # RC
  rc_bridge: present|absent,  # ~/.claude/sessions/<pid>.json — AUTHORITATIVE on ABSENCE only
  rc_footer: active|rc|connecting|none,   # TUI footer — SOFT (see experiment)
  rc_health: up|down|unknown, # derived (truth table below)

  # hygiene
  dialog: none|resume|rc-panel|enable-rc|login,   # blocking dialog tidy must clear
  composer: empty|nonempty|unknown,               # live input box (between the rules)
  cwd_actual, drift: bool,    # state-file cwd / transcript location vs cwd_registered
  banners: [ "auto-update-failed", ... ],         # non-blocking notices
  last_gen: "Crunched for 6s" | null,
}
```

### Reliability tiering (load-bearing)

Every field carries an implicit trust level and policies respect it:

- **authoritative** — registry, tmux liveness, state-file `status`, and the **absence** of
  `bridgeSessionId`. Policies act on these directly.
- **soft** — everything parsed from the TUI (`rc_footer`, `dialog`, `composer`, `banners`).
  Produced only through the zoned parser (below), and a policy may act on a soft signal **only
  when it is corroborated** — e.g. RC is treated as a silent-drop `down` on
  `rc_bridge=present && rc_footer≠active` *only after* the experiment validates that reading.

## The zoned TUI parser

The screen is **zoned by two horizontal rule lines** (`──────`). Naive line greps conflate the
zones — the bug that made a command *echo* look like stuck input. The parser splits first, then
reads each zone:

```
  <output/scroll zone>            → dialogs, banners, "Crunched for Ns",
                                     command echoes ("❯ /remote-control …"), "⎿ /rc connecting…"
  ────────────────────────────    ← RULE
  ❯ <text | empty>                → the LIVE composer (this zone only)
  ────────────────────────────    ← RULE
  ⏵⏵ bypass permissions … /rc     ← FOOTER (may wrap across lines; /rc vs /rc active live here)
```

Consequences, each a parser rule + a test:

1. **`❯` is ambiguous.** A `❯ /remote-control …` echo lives in the output zone; the live
   composer is the `❯` line **between the rules**. `composer` is read from the between-rules
   zone only — never from an output-zone `❯`.
2. **`/rc` is zoned.** Footer `/rc` / `/rc active` (the persistent RC health hint) is a
   different signal from an output-zone `⎿ /rc connecting…` (the result of issuing the command).
   `rc_footer` reads the footer zone; `connecting` is recognized from the output zone.
3. **The footer wraps.** `/rc` can land on its own continuation line. The parser joins the
   footer zone before matching.

### State precedence (first match wins)

`state` is a single classification, evaluated top-down so the most-constraining wins — the
exact ordering our incidents taught us:

```
1. busy           footer contains "esc to interrupt"      → never touch
2. resume-dialog  output has "Resume full session as-is"
3. rc-panel       output has "Disconnect this session" / "Enter to select · Esc to continue"
4. enable-rc      output has "Enable Remote Control"
5. login-needed   "Select login method" / "Press Enter to login"
6. error          a visual failure distinct from a non-blocking banner
7. at-prompt      otherwise
```

`rc_footer`, `banners`, `last_gen`, `composer` are extracted **independently** of `state`.

## derive_health — truth table

```
rc_bridge   rc_footer     → rc_health   note
absent      *             → down        authoritative; re-establish (v0.7.0 already)
present     active        → up
present     rc            → down        ⚠ ONLY after the experiment; until then → unknown
present     connecting    → unknown     handshake in progress; wait
present     none          → unknown     footer not readable
```

## decide — policy truth table (write these tests FIRST)

These encode the hard-won guardrails as regression tests. `decide(record)` is implemented to
satisfy them (red → green).

```
busy                                                   → none    # never interrupt a working session
rc_desired == false                                    → none    # not subscribed to RC — never heal it
rc_health == up                                        → none    # never re-issue a LIVE channel (the stuck-panel incident)
not live                                               → relaunch
drift == true                                          → migrate
dialog in {resume, rc-panel, enable-rc}                → tidy
rc_desired && rc_health==down && status==idle && logged-in → reissue-rc
otherwise                                              → none
```

`reissue-rc` also requires the pane not show `esc to interrupt` (a second idle-gate beyond
state-file `status`), matching current behavior.

## The footer-semantics experiment (blocks the `present+rc → down` rule)

We must confirm what the footer means before acting on it. Controlled test on ONE idle session
showing bare `/rc`:

1. Issue `/remote-control <title>` into the pane; watch the footer transition.
   - `/rc` → `/rc connecting…` → **`/rc active`** ⇒ bare `/rc` was *not connected*; re-issuing
     reconnects. Hypothesis confirmed → wire `present+rc → down`.
   - a management panel opens immediately ⇒ the channel was live; bare `/rc` ≠ drop. Hypothesis
     rejected → keep `present+rc → unknown`, find another signal.
2. Ground truth (optional): the operator checks from the mobile app whether that session was
   reachable **before** the test.

The confirmed `/rc active` screen is then captured as the `rc-active` fixture, locking the rule.

## TDD approach

**Fixtures** — real captures, sanitized (this is a PUBLIC repo): keep only the TUI chrome the
parser keys on; strip conversation text, real paths/PRs, `sessionId`, and `bridgeSessionId`
(session name → `MACHINE/SESSION`). Live-captured now: `busy`, `rc-connecting`
(+`/remote-control` echo), `at-prompt` (bare `/rc`, empty and nonempty composer). Synthesized
from known chrome until seen live: `resume-dialog`, `rc-panel`, `enable-rc`, `login-needed`,
`rc-active` (post-experiment). Layout:

```
tests/fixtures/panes/*.txt          # sanitized pane captures
tests/fixtures/state/*.json         # sanitized state files (bridge-present / bridge-absent / busy)
tests/fixtures/registry.tsv         # a small synthetic registry
```

**Three test layers, bottom-up:**

1. `parse_pane(fixture)` == expected `tui_fields` — one case per pane fixture, incl. the
   composer-between-rules and footer-wrap edge cases.
2. `derive_health` — the truth table above as parametrized cases.
3. `decide` — the policy truth table above; **written first**, red, then implement `decide`.

**Runner:** stdlib `python3 -m unittest` (zero third-party deps, so the public skill stays
dependency-free). Runs fully offline — no tmux, no server.

## Language & integration

- **Core in Python** (`bin/claude-pane-parse` + an importable module): zoned string parsing,
  merging, and JSON output are painful in bash. `python3` is present on the server.
- **The keeper stays bash** and calls the Python core: either `bin/claude-pane-parse` emitting
  JSON, or a `state=` line for cheap bash consumption. No rewrite of the keeper's CLI surface.
- **Rollout order:** (a) pure core + fixtures + tests; (b) `gather()` shell + `claude-keep
  status --json`; (c) migrate `rc-heal` onto `decide` (the goal); (d) later, migrate the
  resume-dialog / drift handling in `tidy`/`restore` onto the same records.

## Error handling / graceful degradation

- **No state file** for a session (older Claude Code, changed layout) ⇒ `rc_bridge=unknown`,
  and RC is left alone (never scraped-and-acted). The state file is undocumented internal state
  — treated as a best-effort accelerator with a hard fallback, never a contract.
- **Parser can't classify** ⇒ `state=at-prompt`/`unknown` with soft fields `none`; `decide`
  yields `none`. Unknown never triggers an action.
- **logged-out** (no refresh token) ⇒ one deduped `/login` alert; `rc-heal` suppressed (login
  is the real blocker), matching current behavior.

## Testing summary

Everything the parser and policies do is a pure function under `python3 -m unittest`, driven by
sanitized fixtures captured from real sessions. The incident guardrails (never touch busy, never
re-issue a live channel, never heal an `rc_desired=0` session) are locked as decision-table
tests, so the stuck-panel class of bug cannot regress silently.
