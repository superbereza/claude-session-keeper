"""Session-state engine — pure core (no I/O).

See docs/superpowers/specs/2026-08-09-session-state-engine-design.md. The parse_*/merge/
derive_health/decide functions take strings/dicts and return dicts/strings — no file, tmux, or
subprocess access. All I/O lives in gather()/main() at the bottom.
"""
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
