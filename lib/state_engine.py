"""Session-state engine — pure core (no I/O).

See docs/superpowers/specs/2026-08-09-session-state-engine-design.md. The parse_*/merge/
derive_health/decide functions take strings/dicts and return dicts/strings — no file, tmux, or
subprocess access. All I/O lives in gather()/main() at the bottom.
"""
import json
import re

_RULE = re.compile(r"^\s*─{5,}\s*$")                  # a horizontal rule line (≥5 box dashes)
_LASTGEN = re.compile(r"[✻✢✳✽✺●]\s*(.+?\bfor\b.+)$")  # a generation marker: "✻ Crunched for 6s"


def parse_pane(text):
    """Classify a captured tmux pane. Pure: text in, dict out.

    The screen is zoned by the last two rule lines: output (above) | composer (between) |
    footer (below). This resolves the two ambiguities naive greps trip on: a `❯ /remote-control`
    echo in the output zone is NOT the live composer, and the footer `/rc` (a persistent hint) is
    a different signal from an output-zone `⎿ /rc connecting…`.
    """
    lines = text.splitlines()
    rules = [i for i, ln in enumerate(lines) if _RULE.match(ln)]
    if len(rules) >= 2:
        r1, r2 = rules[-2], rules[-1]
        output = lines[:r1]
        composer_lines = lines[r1 + 1:r2]
        footer = "\n".join(lines[r2 + 1:])            # joined → tolerant of footer wrapping
    else:                                             # no rules → treat the whole thing as output
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
    last_gen = None
    for ln in output:
        m = _LASTGEN.search(ln)
        if m:
            last_gen = m.group(1).strip()

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
            "banners": banners, "last_gen": last_gen}


def parse_state(json_text):
    """Read a ~/.claude/sessions/<pid>.json body. Only bridge PRESENCE is trusted (an absent
    bridgeSessionId is authoritative; a present one can be stale). Garbage → all-unknown."""
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


_DIALOG = {"resume-dialog": "resume", "rc-panel": "rc-panel",
           "enable-rc": "enable-rc", "login-needed": "login"}


def encode_cwd(path):
    """Claude's project-dir encoding: EVERY non-alphanumeric char → '-' (lossy by design).
    /home/me/dev/ai-auth-lib → -home-me-dev-ai-auth-lib. Pure; used to locate a transcript."""
    return re.sub(r"[^A-Za-z0-9]", "-", path or "")


def merge(reg, live, state, tui):
    """Combine registry row + tmux liveness + state-file + TUI parse into one record.

    Record keys are FIXED (later tasks depend on these exact spellings). rc_health is left
    'unknown' here — derive_health fills it. `drift` is an I/O-derived signal computed by the
    caller (gather: is the transcript in the registered cwd's project dir?) — NOT the live cwd,
    which wanders normally (subdirs, worktrees) without breaking resume.
    """
    cwd_reg = reg.get("cwd_registered")
    cwd_act = state.get("cwd_actual")
    drift = bool(reg.get("drift"))
    # status is busy if EITHER signal says so (double idle-gate): the state file OR a live
    # 'esc to interrupt' pane. So an action never fires on a session either source calls busy.
    status = "busy" if tui.get("state") == "busy" else state.get("status", "unknown")
    return {
        "name": reg.get("name"), "uuid": reg.get("uuid"),
        "cwd_registered": cwd_reg, "effort": reg.get("effort", ""),
        "rc_desired": bool(reg.get("rc_desired")),
        "live": bool(live), "pane_id": reg.get("pane_id"),
        "pid": state.get("pid"), "status": status,
        "rc_bridge": state.get("rc_bridge", "absent"),
        "rc_footer": tui.get("rc_footer", "none"), "rc_health": "unknown",
        "dialog": _DIALOG.get(tui.get("state"), "none"),
        "composer": tui.get("composer", "unknown"),
        "cwd_actual": cwd_act, "drift": drift,
        "banners": tui.get("banners", []), "last_gen": tui.get("last_gen"),
    }


FOOTER_DROP_CONFIRMED = False   # flip to True only after the /rc-vs-/rc-active experiment


def derive_health(record):
    """Remote Control health from the record. Bridge ABSENCE is authoritative → down. A present
    bridge is up only if the footer confirms 'active'; a bare '/rc' silent-drop stays 'unknown'
    until the footer experiment validates it (then FOOTER_DROP_CONFIRMED gates it to 'down')."""
    if record.get("rc_bridge") == "absent":
        return "down"
    if record.get("rc_footer") == "active":
        return "up"
    if FOOTER_DROP_CONFIRMED and record.get("rc_footer") == "rc":
        return "down"
    return "unknown"


def decide(record):
    """One action per record. Order encodes the guardrails; first match wins.

    NB `drift` (transcript not in the registered cwd's project dir) is a FLAG, not an auto-action:
    migrating a LIVE session would copy a transcript it's still appending to, so a later restore
    would resume the STALE copy and lose work. Dead-session drift is healed inline by restore's
    relaunch. So decide surfaces drift in the record (for status/doctor) but never auto-migrates.
    """
    if record.get("status") == "busy":
        return "none"                              # never interrupt a working session
    if not record.get("live"):
        return "relaunch"                          # dead → relaunch (restore auto-heals any drift inline)
    if record.get("dialog") in ("resume", "rc-panel", "enable-rc"):
        return "tidy"
    if record.get("rc_desired") and record.get("logged_in", True) \
            and record.get("status") == "idle" and derive_health(record) == "down":
        return "reissue-rc"
    return "none"                                  # incl. live-drift (flag only), rc up/unknown, rc=0


# ── impure shell: gather() reads the world and feeds strings to the pure core ────────────────
import glob     # noqa: E402
import os       # noqa: E402
import subprocess  # noqa: E402


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


def _transcript_in_place(uuid, cwd_registered):
    """Real drift check (I/O): does <uuid>.jsonl live in the REGISTERED cwd's project dir? If not,
    `claude --resume` from that cwd dies instantly. Mirrors doctor's definition."""
    projdir = os.path.join(os.path.expanduser("~/.claude/projects"), encode_cwd(cwd_registered))
    return os.path.isfile(os.path.join(projdir, "%s.jsonl" % uuid))


def gather():
    """Read the registry + state files + tmux panes → one record per registered session."""
    home = os.environ.get("CLAUDE_KEEP_HOME", os.path.expanduser("~/.claude-keep"))
    states = _state_files_by_uuid()
    records = []
    for reg in _read_registry(os.path.join(home, "sessions.tsv")):
        pane = _pane_of(reg["name"])
        reg["pane_id"] = pane
        reg["drift"] = not _transcript_in_place(reg["uuid"], reg["cwd_registered"])
        if pane:
            tui = parse_pane(_run("tmux", "capture-pane", "-p", "-J", "-t", pane, "-S", "-80"))
        else:
            tui = {"state": "at-prompt", "rc_footer": "none",
                   "composer": "unknown", "banners": [], "last_gen": None}
        state = states.get(reg["uuid"], parse_state(""))
        records.append(merge(reg, pane is not None, state, tui))
    return records


def main(argv):
    if argv[:1] == ["status"]:
        print(json.dumps(gather(), indent=2, ensure_ascii=False))
        return 0
    if argv[:1] == ["decide-all"]:
        logged_in = "--logged-out" not in argv
        for r in gather():                       # one gather for the whole fleet
            r["logged_in"] = logged_in
            print("%s\t%s" % (r["uuid"], decide(r)))
        return 0
    if argv[:1] == ["decide-one"] and len(argv) >= 2:
        uuid = argv[1]
        logged_in = "--logged-out" not in argv
        for r in gather():
            if r["uuid"] == uuid:
                r["logged_in"] = logged_in
                print(decide(r))
                return 0
        print("none")
        return 0
    print("usage: state_engine.py status | decide-all [--logged-out] | decide-one <uuid> [--logged-out]")
    return 2


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
