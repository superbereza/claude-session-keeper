# Session-State Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a pure-core state engine that turns Claude Code's per-session signals into one authoritative record per session, and a single `decide()` policy — then wire Remote-Control re-establishment (the driving use case) onto it.

**Architecture:** A pure Python core (`lib/state_engine.py`) with no I/O — `parse_pane`, `parse_state`, `merge`, `derive_health`, `decide` — is unit-tested against sanitized fixtures. A thin impure shell (`gather()` + a `status` CLI) captures tmux panes / reads JSON files / reads the TSV and feeds strings into the core. The bash `claude-keep` CLI calls the Python for its `status` view and for the RC-heal decision, replacing today's scattered greps.

**Tech Stack:** Python 3 (stdlib only — no third-party deps), `python3 -m unittest`, bash (existing `bin/claude-keep`), tmux.

## Global Constraints

- **Zero third-party deps.** Core + tests use only the Python 3 standard library (`json`, `re`, `unittest`). The public skill must stay dependency-free.
- **Pure core, I/O at the edges.** Functions in `lib/state_engine.py` named `parse_*`, `merge`, `derive_health`, `decide` take strings/dicts and return dicts/strings. No file/tmux/subprocess access inside them. All I/O lives in `gather()` / `main()`.
- **Fixtures are sanitized** (this is a PUBLIC repo): pane fixtures contain only TUI chrome — no conversation text, real paths, PRs; session names → `MACHINE/SESSION`. State-file fixtures use fake `sessionId`/`bridgeSessionId`/`cwd`.
- **Undocumented signals degrade safely.** `~/.claude/sessions/<pid>.json` is undocumented internal state; a missing/unreadable file yields `unknown`, never an action.
- **`rc_desired` comes ONLY from the registry `rc` column** (set at `claude-keep add`); the engine never re-derives or flips it.
- **Record key names are fixed** (Task 4 defines them); every later task uses those exact spellings.
- Commit messages end with the repo's two trailer lines (Co-Authored-By + Claude-Session), per `~/dev/CLAUDE.md`.

---

## File Structure

- `lib/state_engine.py` — the pure core (`parse_pane`, `parse_state`, `merge`, `derive_health`, `decide`) + the impure `gather()` and a `main()` CLI (`status`). One file: these functions are the engine and change together.
- `tests/test_parse_pane.py` — parse_pane cases.
- `tests/test_parse_state.py` — parse_state cases.
- `tests/test_derive_and_decide.py` — derive_health + decide truth tables.
- `tests/fixtures/panes/*.txt` — sanitized pane captures.
- `tests/fixtures/state/*.json` — sanitized state files.
- `tests/run.py` — zero-arg test entry (`python3 tests/run.py` → discovers `tests/`).
- `bin/claude-keep` — MODIFY: `status` subcommand delegates to the engine; the RC-heal step in `_do_tidy_sweep` delegates to `decide`.

---

## Task 1: `parse_pane` — the zoned TUI parser

**Files:**
- Create: `lib/state_engine.py`
- Create: `tests/fixtures/panes/at-prompt-rc.txt`, `busy.txt`, `rc-connecting.txt`, `at-prompt-nonempty.txt`, `resume-dialog.txt`
- Create: `tests/test_parse_pane.py`, `tests/run.py`

**Interfaces:**
- Produces: `parse_pane(text: str) -> dict` with keys `state` (`"busy"|"resume-dialog"|"rc-panel"|"enable-rc"|"login-needed"|"at-prompt"`), `rc_footer` (`"active"|"rc"|"connecting"|"none"`), `composer` (`"empty"|"nonempty"`), `banners` (`list[str]`), `last_gen` (`str|None`).

- [ ] **Step 1: Create the sanitized fixtures**

`tests/fixtures/panes/at-prompt-rc.txt` (idle, empty composer, bare `/rc`):
```
✻ Crunched for 6s
  ✘ Auto-update failed · Try claude doctor or npm i -g @anthropic-ai/claude-co…
────────────────────────────────────────────────────────────────────────────────
❯ 
────────────────────────────────────────────────────────────────────────────────
  ⏵⏵ bypass permissions on (shift+tab to cycle) · ← for agents              /rc
```

`tests/fixtures/panes/at-prompt-nonempty.txt` (idle, composer has unsent text):
```
✻ Crunched for 1m 6s
────────────────────────────────────────────────────────────────────────────────
❯ how do I refresh the token when it expires?
────────────────────────────────────────────────────────────────────────────────
  ⏵⏵ bypass permissions on (shift+tab to cycle) · ← for agents              /rc
```

`tests/fixtures/panes/busy.txt` (mid-generation; footer wraps, `/rc` on its own line):
```
✢ Working… (43s · ↓ 2.1k tokens)
  ✘ Auto-update failed · Try claude doctor or npm i -g @anthropic-ai/claude-co…
────────────────────────────────────────────────────────────────────────────────
❯ 
────────────────────────────────────────────────────────────────────────────────
  ⏵⏵ bypass permissions on (shift+tab to cycle) · esc to interrupt · ctrl+t to…
                                                                            /rc
```

`tests/fixtures/panes/rc-connecting.txt` (a `/remote-control` command echo in the OUTPUT zone + handshake):
```
✻ Crunched for 6s

❯ /remote-control MACHINE/SESSION
  ⎿  /rc connecting…
  ✘ Auto-update failed · Try claude doctor or npm i -g @anthropic-ai/claude-co…
────────────────────────────────────────────────────────────────────────────────
❯ 
────────────────────────────────────────────────────────────────────────────────
  ⏵⏵ bypass permissions on (shift+tab to cycle) · ← for agents              /rc
```

`tests/fixtures/panes/resume-dialog.txt` (synthetic — the stuck "Resume session?" dialog):
```
 Resume session?

   1. Resume with a summary of the conversation so far
 ❯ 2. Resume full session as-is

   Enter to select · Esc to cancel
────────────────────────────────────────────────────────────────────────────────
❯ 
────────────────────────────────────────────────────────────────────────────────
  ⏵⏵ bypass permissions on (shift+tab to cycle) · ← for agents              /rc
```

`tests/run.py`:
```python
import sys, unittest
if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = loader.discover("tests")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
```

- [ ] **Step 2: Write the failing tests**

`tests/test_parse_pane.py`:
```python
import os, unittest
from lib.state_engine import parse_pane

FX = os.path.join(os.path.dirname(__file__), "fixtures", "panes")
def load(name): return open(os.path.join(FX, name), encoding="utf-8").read()

class TestParsePane(unittest.TestCase):
    def test_at_prompt_bare_rc(self):
        r = parse_pane(load("at-prompt-rc.txt"))
        self.assertEqual(r["state"], "at-prompt")
        self.assertEqual(r["rc_footer"], "rc")
        self.assertEqual(r["composer"], "empty")
        self.assertIn("auto-update-failed", r["banners"])
        self.assertEqual(r["last_gen"], "Crunched for 6s")

    def test_nonempty_composer(self):
        r = parse_pane(load("at-prompt-nonempty.txt"))
        self.assertEqual(r["composer"], "nonempty")   # live composer between the rules has text
        self.assertEqual(r["state"], "at-prompt")

    def test_busy_wins_and_footer_wraps(self):
        r = parse_pane(load("busy.txt"))
        self.assertEqual(r["state"], "busy")          # 'esc to interrupt' in the (wrapped) footer
        self.assertEqual(r["rc_footer"], "rc")        # /rc found despite wrapping to its own line

    def test_rc_connecting_from_output_zone_and_echo_is_not_composer(self):
        r = parse_pane(load("rc-connecting.txt"))
        self.assertEqual(r["rc_footer"], "connecting") # '⎿ /rc connecting…' in the output zone
        self.assertEqual(r["composer"], "empty")       # the ❯ /remote-control echo is NOT the composer

    def test_resume_dialog_detected(self):
        r = parse_pane(load("resume-dialog.txt"))
        self.assertEqual(r["state"], "resume-dialog")

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run tests, verify they fail**

Run: `cd ~/dev/claude-session-keeper && python3 tests/run.py`
Expected: FAIL — `ModuleNotFoundError: lib.state_engine` / `parse_pane` undefined.

- [ ] **Step 4: Implement `parse_pane`**

Create `lib/state_engine.py`:
```python
"""Session-state engine — pure core (no I/O). See docs/superpowers/specs/2026-08-09-*."""
import re

_RULE = re.compile(r"^\s*─{5,}\s*$")          # a horizontal rule line (≥5 box-drawing dashes)
_LASTGEN = re.compile(r"[✻✢✳✽✺●]\s*(.+?\bfor\b.+)$")   # a generation marker: "✻ Crunched for 6s"

def parse_pane(text):
    """Classify a captured tmux pane. Pure: text in, dict out.

    Screen is zoned by the last two rule lines: output(above) | composer(between) | footer(below).
    """
    lines = text.splitlines()
    rules = [i for i, ln in enumerate(lines) if _RULE.match(ln)]
    if len(rules) >= 2:
        r1, r2 = rules[-2], rules[-1]
        output = lines[:r1]
        composer_lines = lines[r1 + 1:r2]
        footer = "\n".join(lines[r2 + 1:])       # joined → tolerant of footer wrapping
    else:                                        # no rules → treat whole thing as output
        output, composer_lines, footer = lines, [], ""
    out = "\n".join(output)

    busy = "esc to interrupt" in footer
    # rc_footer: /rc active (footer) > connecting (output handshake) > bare /rc (footer) > none
    if "/rc active" in footer:
        rc_footer = "active"
    elif "/rc connecting" in out:
        rc_footer = "connecting"
    elif re.search(r"(^|\s)/rc(\s|$)", footer):
        rc_footer = "rc"
    else:
        rc_footer = "none"

    composer = "empty"
    for ln in composer_lines:
        m = re.match(r"\s*❯\s?(.*)$", ln)
        if m and m.group(1).strip():
            composer = "nonempty"
            break

    banners = []
    if "Auto-update failed" in out:
        banners.append("auto-update-failed")
    lg = None
    for ln in output:
        m = _LASTGEN.search(ln)
        if m:
            lg = m.group(1).strip()

    # state precedence (first match wins) — the hard-won ordering
    if busy:
        state = "busy"
    elif "Resume full session as-is" in out:
        state = "resume-dialog"
    elif "Disconnect this session" in out or "Enter to select · Esc to continue" in out:
        state = "rc-panel"
    elif "Enable Remote Control" in out:
        state = "enable-rc"
    elif "Select login method" in out or "Press Enter to login" in out:
        state = "login-needed"
    else:
        state = "at-prompt"

    return {"state": state, "rc_footer": rc_footer, "composer": composer,
            "banners": banners, "last_gen": lg}
```

Note: the `resume-dialog` fixture's `Enter to select · Esc to cancel` must NOT trip the `rc-panel` branch — `rc-panel` keys on `Esc to continue`, and `resume-dialog` is matched first anyway.

- [ ] **Step 5: Run tests, verify they pass**

Run: `python3 tests/run.py`
Expected: PASS (5 tests). Also `python3 -c "import ast; ast.parse(open('lib/state_engine.py').read())"` → no error.

- [ ] **Step 6: Commit**

```bash
git add lib/state_engine.py tests/
git commit -m "feat(engine): zoned parse_pane + sanitized pane fixtures"
```

---

## Task 2: `parse_state` — read the per-process state file

**Files:**
- Modify: `lib/state_engine.py` (add `parse_state`)
- Create: `tests/fixtures/state/bridge-present.json`, `bridge-absent.json`, `busy.json`
- Create: `tests/test_parse_state.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `parse_state(json_text: str) -> dict` with keys `status` (`"idle"|"busy"|"unknown"`), `rc_bridge` (`"present"|"absent"`), `pid` (`int|None`), `cwd_actual` (`str|None`), `session_id` (`str|None`). Invalid/empty input → all-unknown dict (`status="unknown"`, `rc_bridge="absent"`, others `None`).

- [ ] **Step 1: Create the sanitized state fixtures**

`tests/fixtures/state/bridge-present.json`:
```json
{"pid": 1111, "sessionId": "00000000-aaaa-bbbb-cccc-000000000001", "cwd": "/home/me/dev/proj", "status": "idle", "bridgeSessionId": "session_01FAKEfakefake"}
```
`tests/fixtures/state/bridge-absent.json`:
```json
{"pid": 2222, "sessionId": "00000000-aaaa-bbbb-cccc-000000000002", "cwd": "/home/me/dev/proj", "status": "idle"}
```
`tests/fixtures/state/busy.json`:
```json
{"pid": 3333, "sessionId": "00000000-aaaa-bbbb-cccc-000000000003", "cwd": "/home/me/dev/proj", "status": "busy", "bridgeSessionId": "session_01FAKEbusy"}
```

- [ ] **Step 2: Write the failing tests**

`tests/test_parse_state.py`:
```python
import os, unittest
from lib.state_engine import parse_state

FX = os.path.join(os.path.dirname(__file__), "fixtures", "state")
def load(name): return open(os.path.join(FX, name), encoding="utf-8").read()

class TestParseState(unittest.TestCase):
    def test_bridge_present_idle(self):
        r = parse_state(load("bridge-present.json"))
        self.assertEqual(r["rc_bridge"], "present")
        self.assertEqual(r["status"], "idle")
        self.assertEqual(r["pid"], 1111)
        self.assertEqual(r["session_id"], "00000000-aaaa-bbbb-cccc-000000000001")

    def test_bridge_absent(self):
        r = parse_state(load("bridge-absent.json"))
        self.assertEqual(r["rc_bridge"], "absent")

    def test_busy(self):
        self.assertEqual(parse_state(load("busy.json"))["status"], "busy")

    def test_garbage_is_unknown(self):
        r = parse_state("not json")
        self.assertEqual(r["status"], "unknown")
        self.assertEqual(r["rc_bridge"], "absent")
        self.assertIsNone(r["pid"])

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run tests, verify they fail**

Run: `python3 tests/run.py`
Expected: FAIL — `parse_state` undefined.

- [ ] **Step 4: Implement `parse_state`**

Add to `lib/state_engine.py`:
```python
import json

def parse_state(json_text):
    """Read a ~/.claude/sessions/<pid>.json body. Bridge PRESENCE only is trusted."""
    try:
        d = json.loads(json_text)
        if not isinstance(d, dict):
            raise ValueError
    except Exception:
        return {"status": "unknown", "rc_bridge": "absent", "pid": None,
                "cwd_actual": None, "session_id": None}
    status = d.get("status")
    status = status if status in ("idle", "busy") else "unknown"
    return {
        "status": status,
        "rc_bridge": "present" if d.get("bridgeSessionId") else "absent",
        "pid": d.get("pid") if isinstance(d.get("pid"), int) else None,
        "cwd_actual": d.get("cwd") or None,
        "session_id": d.get("sessionId") or None,
    }
```

- [ ] **Step 5: Run tests, verify they pass**

Run: `python3 tests/run.py`
Expected: PASS (9 tests total).

- [ ] **Step 6: Commit**

```bash
git add lib/state_engine.py tests/
git commit -m "feat(engine): parse_state — state-file reader (bridge presence, status)"
```

---

## Task 3: `merge` — build one record from all sources

**Files:**
- Modify: `lib/state_engine.py` (add `merge` + `_EMPTY_RECORD` docs)
- Create: `tests/test_merge.py`

**Interfaces:**
- Consumes: `parse_pane` output, `parse_state` output.
- Produces: `merge(reg: dict, live: bool, state: dict, tui: dict) -> dict` — the **record**. `reg` keys: `name, uuid, cwd_registered, effort, rc_desired(bool)`. Record keys (fixed spelling for all later tasks):
  `name, uuid, cwd_registered, effort, rc_desired, live, pane_id, pid, status, rc_bridge, rc_footer, rc_health, dialog, composer, cwd_actual, drift, banners, last_gen`.
  `pane_id` is passed in `reg["pane_id"]` (from gather). `dialog` is derived from `tui["state"]`. `drift` = `cwd_actual` set and its non-worktree value differs from `cwd_registered`. `rc_health` is left `"unknown"` here (Task 4 fills it).

- [ ] **Step 1: Write the failing tests**

`tests/test_merge.py`:
```python
import unittest
from lib.state_engine import merge

REG = {"name": "cc—x/proj", "uuid": "u1", "cwd_registered": "/home/me/dev/proj",
       "effort": "", "rc_desired": True, "pane_id": "%3"}
TUI = {"state": "at-prompt", "rc_footer": "rc", "composer": "empty", "banners": [], "last_gen": None}
STATE = {"status": "idle", "rc_bridge": "present", "pid": 1111,
         "cwd_actual": "/home/me/dev/proj", "session_id": "u1"}

class TestMerge(unittest.TestCase):
    def test_basic_record_shape(self):
        r = merge(REG, True, STATE, TUI)
        self.assertEqual(r["rc_desired"], True)
        self.assertEqual(r["live"], True)
        self.assertEqual(r["status"], "idle")
        self.assertEqual(r["rc_bridge"], "present")
        self.assertEqual(r["dialog"], "none")            # at-prompt → no dialog
        self.assertEqual(r["drift"], False)
        self.assertEqual(r["rc_health"], "unknown")      # filled by derive_health later

    def test_dialog_mapped_from_state(self):
        tui = dict(TUI, state="resume-dialog")
        self.assertEqual(merge(REG, True, STATE, tui)["dialog"], "resume")

    def test_drift_when_cwd_differs(self):
        st = dict(STATE, cwd_actual="/home/me/dev/other")
        self.assertTrue(merge(REG, True, st, TUI)["drift"])

    def test_worktree_cwd_is_not_drift(self):
        st = dict(STATE, cwd_actual="/home/me/dev/proj/.claude/worktrees/x")
        self.assertFalse(merge(REG, True, st, TUI)["drift"])   # worktree cwd is expected, not drift
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `python3 tests/run.py` → FAIL (`merge` undefined).

- [ ] **Step 3: Implement `merge`**

Add to `lib/state_engine.py`:
```python
_DIALOG = {"resume-dialog": "resume", "rc-panel": "rc-panel",
           "enable-rc": "enable-rc", "login-needed": "login"}

def merge(reg, live, state, tui):
    cwd_reg = reg.get("cwd_registered")
    cwd_act = state.get("cwd_actual")
    drift = bool(cwd_act and "/.claude/worktrees/" not in cwd_act and cwd_act != cwd_reg)
    return {
        "name": reg.get("name"), "uuid": reg.get("uuid"),
        "cwd_registered": cwd_reg, "effort": reg.get("effort", ""),
        "rc_desired": bool(reg.get("rc_desired")),
        "live": bool(live), "pane_id": reg.get("pane_id"),
        "pid": state.get("pid"), "status": state.get("status", "unknown"),
        "rc_bridge": state.get("rc_bridge", "absent"),
        "rc_footer": tui.get("rc_footer", "none"), "rc_health": "unknown",
        "dialog": _DIALOG.get(tui.get("state"), "none"),
        "composer": tui.get("composer", "unknown"),
        "cwd_actual": cwd_act, "drift": drift,
        "banners": tui.get("banners", []), "last_gen": tui.get("last_gen"),
    }
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `python3 tests/run.py` → PASS (13 tests).

- [ ] **Step 5: Commit**

```bash
git add lib/state_engine.py tests/
git commit -m "feat(engine): merge — one record per session from all sources"
```

---

## Task 4: `derive_health` + `decide` — the truth tables (tests first)

**Files:**
- Modify: `lib/state_engine.py` (add `derive_health`, `decide`)
- Create: `tests/test_derive_and_decide.py`

**Interfaces:**
- Consumes: a record from `merge`.
- Produces:
  - `derive_health(record: dict) -> str` → `"up"|"down"|"unknown"`. Truth table: `rc_bridge=="absent"` → `down`; `present`+`rc_footer=="active"` → `up`; `present`+`connecting`|`rc`|`none` → `unknown`. (The `present`+`rc`→`down` silent-drop rule is GATED behind `FOOTER_DROP_CONFIRMED` = `False` until the footer experiment; when False it stays `unknown`.)
  - `decide(record: dict) -> str` → one of `"none"|"relaunch"|"tidy"|"migrate"|"reissue-rc"`. `decide` calls `derive_health` internally (reads `record["rc_bridge"]`/`["rc_footer"]`) so callers needn't pre-fill `rc_health`.

- [ ] **Step 1: Write the failing tests (the guardrails)**

`tests/test_derive_and_decide.py`:
```python
import unittest
from lib.state_engine import derive_health, decide

def rec(**kw):
    base = {"live": True, "rc_desired": True, "status": "idle",
            "rc_bridge": "present", "rc_footer": "active", "dialog": "none",
            "drift": False, "logged_in": True}
    base.update(kw); return base

class TestDeriveHealth(unittest.TestCase):
    def test_absent_is_down(self):
        self.assertEqual(derive_health(rec(rc_bridge="absent")), "down")
    def test_present_active_is_up(self):
        self.assertEqual(derive_health(rec(rc_bridge="present", rc_footer="active")), "up")
    def test_present_bare_rc_is_unknown_until_experiment(self):
        self.assertEqual(derive_health(rec(rc_bridge="present", rc_footer="rc")), "unknown")
    def test_present_connecting_is_unknown(self):
        self.assertEqual(derive_health(rec(rc_bridge="present", rc_footer="connecting")), "unknown")

class TestDecide(unittest.TestCase):
    def test_busy_never_touched(self):
        self.assertEqual(decide(rec(status="busy", rc_bridge="absent")), "none")
    def test_not_subscribed_never_healed(self):
        self.assertEqual(decide(rec(rc_desired=False, rc_bridge="absent")), "none")
    def test_live_channel_never_reissued(self):
        self.assertEqual(decide(rec(rc_bridge="present", rc_footer="active")), "none")
    def test_dead_session_relaunched(self):
        self.assertEqual(decide(rec(live=False)), "relaunch")
    def test_drift_migrates(self):
        self.assertEqual(decide(rec(drift=True)), "migrate")
    def test_stuck_dialog_tidied(self):
        self.assertEqual(decide(rec(dialog="resume")), "tidy")
    def test_absent_bridge_idle_reissues(self):
        self.assertEqual(decide(rec(rc_bridge="absent", status="idle")), "reissue-rc")
    def test_absent_bridge_but_logged_out_no_reissue(self):
        self.assertEqual(decide(rec(rc_bridge="absent", logged_in=False)), "none")
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `python3 tests/run.py` → FAIL (`derive_health`/`decide` undefined).

- [ ] **Step 3: Implement `derive_health` and `decide`**

Add to `lib/state_engine.py`:
```python
FOOTER_DROP_CONFIRMED = False   # flip to True only after the /rc-vs-/rc-active experiment

def derive_health(record):
    if record.get("rc_bridge") == "absent":
        return "down"
    if record.get("rc_footer") == "active":
        return "up"
    if FOOTER_DROP_CONFIRMED and record.get("rc_footer") == "rc":
        return "down"          # silent drop — bridge stale-present, footer says not-connected
    return "unknown"

def decide(record):
    """One action per record. Order encodes the guardrails; first match wins."""
    if record.get("status") == "busy":
        return "none"                              # never interrupt a working session
    if not record.get("live"):
        return "relaunch"
    if record.get("drift"):
        return "migrate"
    if record.get("dialog") in ("resume", "rc-panel", "enable-rc"):
        return "tidy"
    if record.get("rc_desired") and record.get("logged_in", True) \
            and record.get("status") == "idle" and derive_health(record) == "down":
        return "reissue-rc"
    return "none"                                  # incl. rc_health up/unknown, rc_desired False
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `python3 tests/run.py` → PASS (21 tests).

- [ ] **Step 5: Commit**

```bash
git add lib/state_engine.py tests/
git commit -m "feat(engine): derive_health + decide truth tables (guardrails as tests)"
```

---

## Task 5: `gather()` + `claude-keep status --json` (the impure shell)

**Files:**
- Modify: `lib/state_engine.py` (add `gather`, `main`)
- Modify: `bin/claude-keep` (add `status` subcommand + usage line)

**Interfaces:**
- Consumes: `parse_pane`, `parse_state`, `merge` (pure core).
- Produces: `gather() -> list[dict]` (records for every registry row); `main(argv)` printing JSON for `status`. `bin/claude-keep status [--json]` delegates to `python3 <root>/lib/state_engine.py status`.

- [ ] **Step 1: Implement `gather` + `main` (I/O shell)**

Add to `lib/state_engine.py`:
```python
import os, glob, subprocess

def _run(*args):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return ""

def _state_files_by_uuid():
    out = {}
    for f in glob.glob(os.path.expanduser("~/.claude/sessions/*.json")):
        try:
            txt = open(f, encoding="utf-8").read()
        except Exception:
            continue
        st = parse_state(txt)
        if st["session_id"]:
            out[st["session_id"]] = st
    return out

def _read_registry(tsv):
    rows = []
    try:
        lines = open(tsv, encoding="utf-8").read().splitlines()
    except Exception:
        return rows
    for ln in lines:
        if not ln or ln.startswith("#"):
            continue
        parts = ln.split("\t")
        if len(parts) < 2:
            continue
        parts += [""] * (5 - len(parts))
        rows.append({"name": parts[0], "uuid": parts[1], "cwd_registered": parts[2],
                     "effort": parts[3], "rc_desired": (parts[4] or "1") == "1"})
    return rows

def _pane_of(name):
    for ln in _run("tmux", "list-panes", "-a", "-F", "#{session_name}\t#{pane_id}").splitlines():
        if "\t" in ln:
            s, pid = ln.split("\t", 1)
            if s == name:
                return pid
    return None

def gather():
    home = os.environ.get("CLAUDE_KEEP_HOME", os.path.expanduser("~/.claude-keep"))
    states = _state_files_by_uuid()
    records = []
    for reg in _read_registry(os.path.join(home, "sessions.tsv")):
        pane = _pane_of(reg["name"])
        live = pane is not None
        reg["pane_id"] = pane
        tui = parse_pane(_run("tmux", "capture-pane", "-p", "-J", "-t", pane, "-S", "-80")) \
            if pane else {"state": "at-prompt", "rc_footer": "none",
                          "composer": "unknown", "banners": [], "last_gen": None}
        state = states.get(reg["uuid"], parse_state(""))
        records.append(merge(reg, live, state, tui))
    return records

def main(argv):
    import json as _json
    if argv[:1] == ["status"]:
        print(_json.dumps(gather(), indent=2, ensure_ascii=False))
        return 0
    print("usage: state_engine.py status [--json]"); return 2

if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 2: Manual smoke test (real sessions)**

Run: `python3 lib/state_engine.py status | head -40`
Expected: a JSON array; each element has the record keys; live sessions show `"live": true` and a `rc_bridge`. (No unit test — this is the I/O boundary; the pure core is already covered.)

- [ ] **Step 3: Wire the `status` subcommand into `bin/claude-keep`**

In `bin/claude-keep`, add a resolver + command. Near the top helpers add:
```bash
_engine() { python3 "$(dirname "$(dirname "$(readlink -f "$0")")")/lib/state_engine.py" "$@"; }
cmd_status() { command -v python3 >/dev/null || die "python3 not installed"; _engine status "$@"; }
```
In `main()`'s `case`, add:
```bash
    status|state)     cmd_status "$@" ;;
```
Add to the header-comment usage block (the lines `usage()` prints):
```
#   claude-keep status                         Print the state engine's per-session records (JSON).
```
Update the `usage()` line-range if the header grew (verify: the last `sed -n '2,NNp'` range still ends on the last comment line).

- [ ] **Step 4: Verify**

Run: `bash -n bin/claude-keep && ./bin/claude-keep status | python3 -m json.tool >/dev/null && echo OK`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add lib/state_engine.py bin/claude-keep
git commit -m "feat(engine): gather() + claude-keep status (impure shell over the pure core)"
```

---

## Task 6: Wire RC-heal onto `decide` (the driving goal)

**Files:**
- Modify: `bin/claude-keep` — replace the bespoke bridge-absence check inside `_do_tidy_sweep` with a `decide`-driven reissue.

**Interfaces:**
- Consumes: `decide` via a small engine call that, given a uuid + logged-in flag, returns the action string.
- Produces: unchanged external behavior for the common case; the decision now comes from the tested `decide`.

- [ ] **Step 1: Add a per-session decision entry point to the engine**

Add to `lib/state_engine.py` `main()` (before the `status` branch return):
```python
    if argv[:1] == ["decide-one"] and len(argv) >= 2:
        uuid = argv[1]
        logged_in = "--logged-out" not in argv
        for r in gather():
            if r["uuid"] == uuid:
                r["logged_in"] = logged_in
                print(decide(r)); return 0
        print("none"); return 0
```

- [ ] **Step 2: Manual check against a real session**

Run: `python3 lib/state_engine.py decide-one <a-live-uuid>`
Expected: prints one of `none|relaunch|tidy|migrate|reissue-rc` (a healthy bridged idle session → `none`).

- [ ] **Step 3: Replace the bridge check in `_do_tidy_sweep`**

In `bin/claude-keep`, the current RC block reads `_state_for` and re-issues on `bridge==0 && status==idle`. Replace that inner `if` with a `decide` call:
```bash
    # RC re-establishment decision comes from the tested engine (decide): it returns
    # reissue-rc only for an rc_desired, logged-in, idle session whose RC is down.
    if command -v python3 >/dev/null; then
      local _lo=""; [[ "$login" == login-needed ]] && _lo="--logged-out"
      if [[ "$(_engine decide-one "$uuid" $_lo)" == "reissue-rc" ]]; then
        tmux send-keys -t "$pid" "/remote-control ${title}"; sleep 0.4; tmux send-keys -t "$pid" Enter
        notify "ℹ claude-keep: re-issued /remote-control for '$name' (RC bridge was absent)"
        sleep 1; _tidy_pane "$pid"
      fi
    fi
```
(Leave the surrounding `_tidy_pane "$pid"` sweep and the `_state_for` helper in place — `_state_for` may still be referenced elsewhere; if `grep -n _state_for bin/claude-keep` shows only the removed block, delete the helper too.)

- [ ] **Step 4: Verify no behavior regression on the live fleet**

Run: `bash -n bin/claude-keep && ./bin/claude-keep tidy`
Expected: `✓ tidied…`, and on an all-bridged idle fleet NO session is re-issued (same as before the change). Confirm with `python3 lib/state_engine.py status | grep -c '"rc_bridge": "present"'`.

- [ ] **Step 5: Commit + release**

```bash
git add bin/claude-keep lib/state_engine.py
git commit -m "feat(keeper): RC-heal decision now comes from the tested engine (decide)"
bash scripts/bump.sh 0.8.0
git add -A && git commit -m "chore: release v0.8.0 — session-state engine"
git tag -a v0.8.0 -m "v0.8.0 — session-state engine + engine-driven RC-heal"
git push origin HEAD --tags
gh release create v0.8.0 --title "v0.8.0 — session-state engine" --latest --notes "Pure-core state engine (parse_pane/parse_state/merge/derive_health/decide) with unittest coverage over sanitized fixtures; claude-keep status --json; RC-heal now driven by the tested decide()."
```

---

## Future (out of scope for this plan)

- The footer-semantics experiment → flip `FOOTER_DROP_CONFIRMED = True` and add the `rc-active` fixture, closing silent-drop detection.
- Migrate `restore`'s relaunch and `tidy`'s dialog handling to consume `decide`/records directly (currently only RC-heal does).

## Self-Review

- **Spec coverage:** pure core (Tasks 1-4) ✓; reliability tiering — soft TUI fields only via parser, authoritative via state-file (Tasks 1-3) ✓; zoned parser + `❯` ambiguity + footer wrap (Task 1 tests) ✓; derive_health table incl. experiment gate (Task 4) ✓; decide guardrails as tests (Task 4) ✓; `rc_desired` from registry only (Task 5 `_read_registry`, Task 4 guard) ✓; one heal loop / status view (Tasks 5-6) ✓; graceful degradation — no state file → unknown (Task 2 test), no python → keeper still runs (Task 6 `command -v python3`) ✓; sanitized fixtures (Tasks 1-2) ✓. Deferred by design: silent-drop action (gated), full restore/tidy migration (Future).
- **Placeholder scan:** every code/test step carries real content; no TBD/TODO in steps.
- **Type consistency:** record keys defined in Task 3 `merge` and reused verbatim in Tasks 4-6 (`rc_bridge`, `rc_footer`, `rc_desired`, `dialog`, `drift`, `status`, `live`, `pid`, `pane_id`). `decide` reads `logged_in` (injected in Task 6 `decide-one`; defaulted `True` in Task 4 so pure tests pass). `parse_pane` keys (`state/rc_footer/composer/banners/last_gen`) consumed by `merge` verbatim.
