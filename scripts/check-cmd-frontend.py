#!/usr/bin/env python3
"""
Grep-based checker for the cmd/ Windows frontend
(fll.bat / fll.cmd / fulilian.bat / fulilian.cmd / fll.ps1 /
fll.completion.ps1 / install.cmd).

Two layers:

  static  — always runs. Checks the *specific* mistakes that are silent on the
            author's machine and only bite on a real Windows host: batch
            footguns, PowerShell quoting, line endings, the .gitattributes
            policy that decides what a clone actually contains. Not general
            batch style — every rule is annotated with the failure it causes.
  runtime — runs only when a Windows cmd.exe is reachable from a POSIX host
            (WSL interop). Copies cmd/ into a scratch directory and executes
            the launcher end to end, asserting argument fidelity, path
            translation, exit-code and stdin passthrough.

Usage:
    python scripts/check-cmd-frontend.py             # static + runtime
    python scripts/check-cmd-frontend.py --static    # static only (what CI runs)
    python scripts/check-cmd-frontend.py -v          # show every check

Exit status:
    0 — clean (runtime layer may have been skipped)
    1 — at least one failure

The runtime layer needs WSL and cmd.exe interop, which a hosted CI runner does
not guarantee, so it self-skips there; CI runs `--static`. Run the full thing
locally on a Windows+WSL box before touching anything in cmd/.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CMD_DIR = REPO_ROOT / "cmd"
GITATTRIBUTES = REPO_ROOT / ".gitattributes"

# The six launcher files install.cmd promises to ship, side by side. The
# `fulilian` pair are aliases of `fll.bat`, so the long name resolves the same
# way the short one does; `fll` stays the canonical name.
EXPECTED_FILES = (
    "fll.bat", "fll.cmd", "fulilian.bat", "fulilian.cmd",
    "fll.ps1", "fll.completion.ps1",
)
# Plus the installer itself, which the runtime layer exercises but does not ship.
ALL_CMD_FILES = EXPECTED_FILES + ("install.cmd",)

# Batch launchers and PowerShell files are CRLF by repo policy (see
# .gitattributes); the markdown docs are LF like every other *.md here.
CRLF_FILES = ALL_CMD_FILES
LF_FILES = ("README.md", "README.en.md")

# install.cmd and fll.completion.ps1 must agree on this string; it is how the
# installer's self-check decides whether $PROFILE is wired.
PROFILE_MARKER = "# fulilian-cmd completion"

failures: list[str] = []
passes = 0
verbose = False


def ok(msg: str) -> None:
    global passes
    passes += 1
    if verbose:
        print(f"  ok   {msg}")


def bad(msg: str, detail: str = "") -> None:
    failures.append(msg)
    print(f"  FAIL {msg}")
    for line in detail.splitlines():
        print(f"       {line}")


def strip_comments(text: str, style: str) -> list[tuple[int, str]]:
    """Return (lineno, line) for code lines, comments dropped.

    `style` is 'bat' (rem ... / ::) or 'ps' (# ...).
    """
    out = []
    for i, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if style == "bat":
            if line.lower().startswith(("rem ", "rem\t", "rem")) or line.startswith("::"):
                continue
        else:
            if line.startswith("#"):
                continue
        out.append((i, raw))
    return out


def has_crlf(path: Path) -> bool:
    return b"\r\n" in path.read_bytes()


# --------------------------------------------------------------------------
# static checks
# --------------------------------------------------------------------------

def check_files_present() -> None:
    missing = [f for f in EXPECTED_FILES if not (CMD_DIR / f).exists()]
    if missing:
        bad("cmd/ is missing launcher files", f"missing: {', '.join(missing)}")
    else:
        ok(f"all {len(EXPECTED_FILES)} launchers present")


def check_no_backup_residue() -> None:
    """A `.bak` left next to a launcher is invisible until someone edits the
    wrong one. The `.bak` files in cmd/ are reverse-engineering residue and
    must not ship.
    """
    residue = sorted(p.name for p in CMD_DIR.glob("*.bak"))
    if residue:
        bad("cmd/ contains backup files", ", ".join(residue) + " — delete them; they are never shipped.")
    else:
        ok("no .bak residue in cmd/")


def check_line_endings() -> None:
    """`.gitattributes` promises CRLF for the launchers on every platform. If
    the working tree disagrees, the thing being tested here is not the thing a
    cloner gets — and a batch file that was only ever tested with LF has an
    untested CRLF path (and vice versa).
    """
    wrong = [f for f in CRLF_FILES if (CMD_DIR / f).exists() and not has_crlf(CMD_DIR / f)]
    if wrong:
        bad(
            "cmd/ launchers are not CRLF",
            ", ".join(wrong) + " — .gitattributes declares eol=crlf for these; "
            "a worktree that disagrees means the tested file is not the shipped file.",
        )
    else:
        ok(f"all {len(CRLF_FILES)} launchers are CRLF")

    wrong_lf = [f for f in LF_FILES if (CMD_DIR / f).exists() and has_crlf(CMD_DIR / f)]
    if wrong_lf:
        bad("cmd/ docs are CRLF", ", ".join(wrong_lf) + " — *.md is text eol=lf.")
    else:
        ok("cmd/ docs are LF")


def check_gitattributes_policy() -> None:
    """The launchers only stay CRLF for everyone if .gitattributes says so.
    Without these rules the line endings a clone gets depend on the cloning
    host's core.autocrlf — which is exactly the class of bug that shows up as
    a whole-file phantom diff, or as a batch file that works for the author and
    not for the next person.
    """
    if not GITATTRIBUTES.exists():
        bad(".gitattributes missing", f"expected at repo root: {GITATTRIBUTES}")
        return
    text = GITATTRIBUTES.read_text(encoding="utf-8", errors="replace")

    # pattern -> whether it must carry eol=crlf
    required = {
        "*.ps1": "crlf",
        "cmd/*.bat": "crlf",
        "cmd/*.cmd": "crlf",
    }
    missing = []
    for pattern, want in required.items():
        found = None
        for line in text.splitlines():
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            parts = line.split()
            if parts and parts[0] == pattern:
                attrs = " ".join(parts[1:])
                found = attrs
                break
        if found is None or f"eol={want}" not in found:
            missing.append(pattern)

    if missing:
        bad(
            ".gitattributes does not pin cmd/ line endings",
            "missing eol=crlf for: " + ", ".join(missing)
            + " — without these, a Windows clone gets whatever core.autocrlf says.",
        )
    else:
        ok(".gitattributes pins *.ps1 and cmd/*.bat|cmd to eol=crlf")


def check_dp0_after_shift() -> None:
    """`shift` also shifts %0, so any %~dp0 evaluated after the argument loop
    resolves to the wrong directory. This shipped once: install.cmd printed
    `source : C:\\fll.bat` because %~dp0 had become the last argument's drive.
    """
    for name in ALL_CMD_FILES:
        path = CMD_DIR / name
        if not path.exists() or path.suffix not in (".bat", ".cmd"):
            continue
        saw_shift = False
        offenders = []
        for lineno, line in strip_comments(path.read_text(encoding="utf-8", errors="replace"), "bat"):
            if re.search(r"(?<!\w)shift(?!\w)", line, re.IGNORECASE):
                saw_shift = True
            elif saw_shift and "%~dp0" in line and "SRC_DIR" not in line:
                offenders.append(lineno)
        if offenders:
            bad(
                f"{name}: %~dp0 used after shift",
                "lines " + ", ".join(map(str, offenders))
                + " — %0 has moved, so this resolves to the wrong directory."
                + " Capture it once, before the parse loop.",
            )
        else:
            ok(f"{name}: no %~dp0 after shift")


def check_no_escaped_quotes_to_powershell() -> None:
    """cmd.exe does not honour \\" as an escape; it reaches PowerShell as a
    literal backslash-quote and the command fails to parse.

    The `powershell.exe ... -Command ^` idiom puts the payload on the NEXT
    line, so checking each line in isolation misses every real instance —
    install.cmd's self-check is written exactly that way. A `^` at end of line
    continues the command, so the logical line has to be reassembled first.
    """
    for name in ALL_CMD_FILES:
        path = CMD_DIR / name
        if not path.exists() or path.suffix not in (".bat", ".cmd"):
            continue
        bad_lines = []
        pending: list[tuple[int, str]] = []   # (first lineno, accumulated text)
        for lineno, line in strip_comments(path.read_text(encoding="utf-8", errors="replace"), "bat"):
            stripped = line.rstrip()
            if pending:
                pending.append((pending[0][0], line))
            elif "powershell" in line.lower():
                pending = [(lineno, line)]
            if not pending:
                continue
            if stripped.endswith("^"):
                continue            # command continues on the next line
            first, joined = pending[0][0], " ".join(t for _, t in pending)
            pending = []
            if '\\"' in joined:
                bad_lines.append(first)
        if bad_lines:
            bad(
                f"{name}: \\\" escape in a powershell command line",
                "lines " + ", ".join(map(str, bad_lines))
                + " — cmd passes the backslash through; use single-quoted PS strings.",
            )
        else:
            ok(f"{name}: no escaped quotes to PowerShell")


def check_completion_is_dot_sourceable() -> None:
    """fll.completion.ps1 is documented to be dot-sourced. A top-level `exit`
    in a dot-sourced script tears down the caller's whole session.
    """
    path = CMD_DIR / "fll.completion.ps1"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8", errors="replace")
    code = strip_comments(text, "ps")

    # The only place `exit` is harmless is inside the completion scriptblock:
    # there it runs as a child scriptblock and cannot end the caller's session.
    # Everywhere else — including inside the `if ($Install) { ... }` branch —
    # a dot-sourced invocation would tear the session down. Indentation is not
    # a usable proxy (that branch is indented too), so bound the scriptblock
    # literal by brace depth and allow `exit` only within it.
    start = end = None
    depth = 0
    for lineno, line in code:
        if start is None:
            if re.search(r"\$script:FllCompletionBlock\s*=\s*\{", line):
                start = lineno
                depth = line.count("{") - line.count("}")
                continue
        else:
            depth += line.count("{") - line.count("}")
            if depth <= 0:
                end = lineno
                break
    if start is None or end is None:
        bad(
            "fll.completion.ps1: could not locate the completion scriptblock",
            "the top-level-exit check needs $script:FllCompletionBlock = { ... } to bound it.",
        )
    else:
        offenders = [
            lineno for lineno, line in code
            if re.match(r"\s*exit\b", line) and not (start < lineno < end)
        ]
        if offenders:
            bad(
                "fll.completion.ps1: exit outside the completion scriptblock breaks dot-sourcing",
                "lines " + ", ".join(map(str, offenders))
                + " — a dot-sourced script's `exit` ends the caller's session; use `return`.",
            )
        else:
            ok(f"fll.completion.ps1: no exit outside the completion scriptblock (L{start}-L{end})")

    if re.search(r"Register-ArgumentCompleter\s+-Native", text):
        ok("fll.completion.ps1: registers a native argument completer")
    else:
        bad("fll.completion.ps1: no Register-ArgumentCompleter -Native call")


def check_installer_marker_consistency() -> None:
    """install.cmd's self-check greps $PROFILE for the marker that
    fll.completion.ps1 writes, and -Uninstall removes it by exact equality.

    Substring containment is NOT good enough here, and testing it that way is
    how this check was vacuous: "M" is a substring of "M-v2", so a drifted
    marker sailed through — while `Where-Object { $_ -ne $marker }` in
    -Uninstall is exact equality, so the ORIGINAL line would be left behind in
    the user's $PROFILE forever. Compare the two literals exactly.
    """
    install = (CMD_DIR / "install.cmd")
    completion = (CMD_DIR / "fll.completion.ps1")
    if not install.exists() or not completion.exists():
        return
    install_text = install.read_text(encoding="utf-8", errors="replace")
    completion_text = completion.read_text(encoding="utf-8", errors="replace")

    written = re.search(r"\$script:FllProfileMarker\s*=\s*'([^']*)'", completion_text)
    grepped = re.search(r"\[regex\]::Escape\(\s*'([^']*)'\s*\)", install_text)

    if not written:
        bad(
            "fll.completion.ps1: could not find the profile marker literal",
            "expected `$script:FllProfileMarker = '<marker>'` so the check has something to compare.",
        )
        return
    if not grepped:
        bad(
            "install.cmd: self-check no longer greps a [regex]::Escape('...') marker",
            "the consistency check needs the literal the installer greps for.",
        )
        return

    wrote, greps = written.group(1), grepped.group(1)
    if wrote != PROFILE_MARKER or greps != PROFILE_MARKER:
        bad(
            "profile marker drifted",
            f"fll.completion.ps1 writes   {wrote!r}\n"
            f"install.cmd greps for       {greps!r}\n"
            f"expected both to be         {PROFILE_MARKER!r} — "
            "-Uninstall removes by exact equality, so a mismatch leaves the old line in $PROFILE.",
        )
    else:
        ok(f"install.cmd and fll.completion.ps1 agree on the profile marker ({wrote!r})")


def check_installer_uninstall_removes_marker() -> None:
    """-Install and -Uninstall must agree on the exact block added.

    -Uninstall dropping only the marker line leaves the separator -Install added
    behind, so the pair does not round-trip; and a half-removed wiring resurrects
    a completer pointing at a file that is gone. Both sides therefore go through
    $script:FllProfileChunk, and the invariant checked here is that the chunk
    interpolates the marker and the dot-source line, -Install appends exactly
    those two, and -Uninstall removes the chunk.
    """
    path = CMD_DIR / "fll.completion.ps1"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8", errors="replace")

    chunk = re.search(r"\$script:FllProfileChunk\s*=\s*\"([^\"]*)\"", text)
    composed = (
        chunk is not None
        and "FllProfileMarker" in chunk.group(1)
        and "FllProfileLine" in chunk.group(1)
    )
    install = re.search(
        r"Add-Content -LiteralPath \$ProfilePath -Value \$script:FllProfileMarker"
        r"[\s\S]{0,200}?Add-Content -LiteralPath \$ProfilePath -Value \$script:FllProfileLine",
        text,
    )
    uninstall = re.search(
        r"\$raw\.Remove\(\s*\$idx\s*,\s*\$script:FllProfileChunk\.Length\s*\)", text
    )

    if composed and install and uninstall:
        ok("fll.completion.ps1: -Install/-Uninstall share one removable chunk")
    else:
        missing = [
            name
            for name, got in (
                ("chunk definition", composed),
                ("install append", install is not None),
                ("uninstall removal", uninstall is not None),
            )
            if not got
        ]
        bad(
            "fll.completion.ps1: the installed block is not removed as a whole",
            "missing/mismatched: " + ", ".join(missing)
            + " — install and uninstall must agree on the exact bytes, "
            "or residue is left in $PROFILE.",
        )


def check_installer_enumerates_every_launcher() -> None:
    """install.cmd enumerates the launchers by hand in three places — the copy
    lines, the `del` lines and the MISSING accumulator — plus a fourth as a
    literal count in the self-check's "all N files" message.

    Adding a launcher means editing all four, and every omission is silent in
    the worst direction: a file that installs but never uninstalls leaves
    residue in the user's bin, one the self-check does not know about reports
    OK while `fll` quietly fails to resolve, and a stale count reads as
    authoritative. Nothing else in this file can catch that, so tie all four
    back to EXPECTED_FILES.
    """
    path = CMD_DIR / "install.cmd"
    if not path.exists():
        return
    code = [
        line
        for _, line in strip_comments(path.read_text(encoding="utf-8", errors="replace"), "bat")
    ]

    buckets = {
        "install": [ln for ln in code if "copied " in ln],
        "uninstall": [ln for ln in code if "removed " in ln],
        "self-check": [ln for ln in code if "MISSING=%MISSING%" in ln],
    }
    gaps = []
    for name in EXPECTED_FILES:
        absent = [
            label
            for label, lines in buckets.items()
            if not any(re.search(re.escape(name), ln) for ln in lines)
        ]
        if absent:
            gaps.append(f"{name}: missing from {', '.join(absent)}")
    if gaps:
        bad(
            "install.cmd does not enumerate every launcher",
            "\n".join(gaps)
            + "\n→ install, uninstall and the self-check each list the launchers; "
            "an omission ships silently.",
        )
    else:
        ok(f"install.cmd copies, deletes and self-checks all {len(EXPECTED_FILES)} launchers")

    m = re.search(
        r"OK - all (\d+) files in %DEST_DIR%",
        path.read_text(encoding="utf-8", errors="replace"),
    )
    if m is None:
        bad(
            "install.cmd: self-check no longer reports an 'all N files' count",
            "the count is checked against EXPECTED_FILES; keep the message greppable.",
        )
    elif int(m.group(1)) != len(EXPECTED_FILES):
        bad(
            "install.cmd: self-check file count is stale",
            f"says 'all {m.group(1)} files' but EXPECTED_FILES has {len(EXPECTED_FILES)} — "
            "the message is the only thing a user reads, so a wrong count reads as a wrong install.",
        )
    else:
        ok(f"install.cmd: self-check reports 'all {m.group(1)} files' (matches EXPECTED_FILES)")


def check_launcher_is_a_bat() -> None:
    """install.cmd and the launcher entry points are batch; fll.ps1 is not. A
    launcher saved under the wrong extension fails at the shell level, not at
    review. Every .bat/.cmd ships a twin because hosts differ in which
    extension their PATHEXT resolves, so both halves of each pair must be batch.
    """
    known = {
        "fll.bat": "bat", "fll.cmd": "bat",
        "fulilian.bat": "bat", "fulilian.cmd": "bat",
        "install.cmd": "bat",
        "fll.ps1": "ps1", "fll.completion.ps1": "ps1",
    }
    wrong = []
    for name, kind in known.items():
        path = CMD_DIR / name
        if not path.exists():
            continue
        head = path.read_text(encoding="utf-8", errors="replace").lstrip()
        if kind == "bat":
            if not head.lower().startswith("@echo off"):
                wrong.append(f"{name} (expected to start with @echo off)")
        else:
            if head.lower().startswith("@echo off"):
                wrong.append(f"{name} (batch content in a .ps1)")
    if wrong:
        bad("cmd/ launcher/extension mismatch", "; ".join(wrong))
    else:
        ok("launcher contents match their extensions")


def run_static() -> None:
    print("[static]")
    check_files_present()
    check_no_backup_residue()
    check_line_endings()
    check_gitattributes_policy()
    check_launcher_is_a_bat()
    check_installer_enumerates_every_launcher()
    check_dp0_after_shift()
    check_no_escaped_quotes_to_powershell()
    check_completion_is_dot_sourceable()
    check_installer_marker_consistency()
    check_installer_uninstall_removes_marker()


# --------------------------------------------------------------------------
# runtime checks
# --------------------------------------------------------------------------

PROBE = """#!/bin/sh
# argv / stdin / exit-code probe for check-cmd-frontend.py
echo "PROBE_ARGC=$#"
i=0
for a in "$@"; do
  i=$((i+1))
  printf 'PROBE_ARG%d=[%s]\\n' "$i" "$a"
done
case "$1" in
  --stdin) n=$(cat | wc -l); echo "PROBE_STDIN_LINES=$n" ;;
  --exit)  exit "${2:-0}" ;;
esac
"""


# Exercises -Install/-Uninstall through -ProfilePath against throwaway files and
# asserts a byte-exact round trip. Deliberately ASCII-only (CJK fixture bytes are
# spelled as hex) because PowerShell 5.1 reads a BOM-less .ps1 as ANSI, which
# would mangle any literal non-ASCII in this script itself.
#
# Never pass a real profile path to this: -ProfilePath defaults to $PROFILE, and
# the default is the one thing that must not be touched here.
ROUNDTRIP_PS1 = r"""
$ErrorActionPreference = 'Stop'
$comp = Join-Path $PSScriptRoot 'fll.completion.ps1'
$u8 = New-Object System.Text.UTF8Encoding($false)
$cases = @(
    @{ n = 'empty'; b = [byte[]]@() },
    @{ n = 'blank'; b = [byte[]](0x0D, 0x0A) },
    @{ n = 'nonl';  b = [byte[]](0x57, 0x72, 0x69, 0x74, 0x65) },
    @{ n = 'cjk';   b = [byte[]](0x23, 0x20, 0xE4, 0xB8, 0xAD, 0xE6, 0x96, 0x87, 0x0D, 0x0A) }
)
$fail = 0
foreach ($c in $cases) {
    $p = Join-Path $PSScriptRoot ('rt_' + $c.n + '.ps1')
    [System.IO.File]::WriteAllBytes($p, $c.b)
    $before = (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash
    & $comp -Install -ProfilePath $p | Out-Null
    $wired = ([System.IO.File]::ReadAllText($p)).Contains('# fulilian-cmd completion')
    & $comp -Uninstall -ProfilePath $p | Out-Null
    $after = (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash
    if (-not ($before -eq $after -and $wired)) {
        $fail++
        Write-Host ("RT_FAIL " + $c.n)
    }
    Remove-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue
}
if ($fail -eq 0) { Write-Host 'RT_PROFILE_ROUNDTRIP_OK' } else { Write-Host ('RT_PROFILE_FAILURES=' + $fail) }
"""


def cmd_exe() -> str | None:
    for candidate in ("cmd.exe", "/mnt/c/Windows/System32/cmd.exe"):
        found = shutil.which(candidate) or (candidate if os.path.exists(candidate) else None)
        if found:
            return found
    return None


def run_cmd(command_line: str, workdir: Path, extra_env: dict[str, str] | None = None,
            stdin: bytes | None = None) -> tuple[int, str]:
    exe = cmd_exe()
    assert exe, "cmd_exe() returned None"
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(
        [exe, "/c", command_line],
        cwd=str(workdir),
        env=env,
        input=stdin,
        capture_output=True,
    )
    out = proc.stdout.decode("utf-8", errors="replace") + proc.stderr.decode("utf-8", errors="replace")
    # cmd.exe warns about the UNC working directory it inherits from WSL; noise.
    out = "\n".join(
        ln for ln in out.splitlines()
        if "UNC" not in ln and "wsl.localhost" not in ln and "CMD.EXE" not in ln
    )
    return proc.returncode, out


def parse_probe(out: str) -> tuple[int | None, list[str]]:
    argc = None
    args: list[str] = []
    for line in out.splitlines():
        m = re.match(r"PROBE_ARGC=(\d+)", line.strip())
        if m:
            argc = int(m.group(1))
            continue
        m = re.match(r"PROBE_ARG\d+=\[(.*)\]$", line.strip())
        if m:
            args.append(m.group(1))
    return argc, args


def run_runtime() -> bool:
    """Returns False when the runtime layer cannot run here (skipped, not failed)."""
    cmd = cmd_exe()
    if not cmd or os.name == "nt":
        print("[runtime] skipped — needs a POSIX host with Windows cmd.exe interop")
        return False
    if not shutil.which("wsl.exe") and not os.path.exists("/mnt/c/Windows/System32/cmd.exe"):
        print("[runtime] skipped — wsl.exe not reachable")
        return False

    print("[runtime]")
    tmp = Path(tempfile.mkdtemp(prefix="fll-cmd-check-"))
    try:
        probe = tmp / "probe"
        probe.write_text(PROBE)
        probe.chmod(0o755)
        probe_wsl = str(probe)

        # Stage the launchers on the Windows side: cmd.exe cannot use a UNC
        # path as its working directory.
        win_tmp = subprocess.run(
            [cmd, "/c", "echo %TEMP%"], capture_output=True, cwd="/mnt/c"
        ).stdout.decode("utf-8", errors="replace").strip()
        staged = Path(win_tmp.replace("\\", "/").replace("C:", "/mnt/c", 1)) / "fll-cmd-check"
        if staged.exists():
            shutil.rmtree(staged)
        staged.mkdir(parents=True)
        for f in ALL_CMD_FILES:
            shutil.copy2(CMD_DIR / f, staged / f)
        win_dir = str(staged).replace("/mnt/c", "C:").replace("/", "\\")

        base = f"cd /d {win_dir} && set FLL_BIN={probe_wsl}&& set FLL_QUIET=1&& "

        cases: list[tuple[str, str, callable]] = [
            ("spaces+quotes survive",
             'fll.bat a "b c" --version',
             lambda rc, o: parse_probe(o) == (3, ["a", "b c", "--version"])),
            ("quoted Windows path stays one arg",
             'fll.bat "C:\\Program Files\\my app\\a.txt"',
             lambda rc, o: parse_probe(o) == (1, ["C:\\Program Files\\my app\\a.txt"])),
            ("CJK argument survives",
             'fll.bat "中文 参数"',
             lambda rc, o: parse_probe(o) == (1, ["中文 参数"])),
            ("Windows path translated to /mnt",
             "fll.bat C:\\Users\\me\\ctf\\chall.bin",
             lambda rc, o: parse_probe(o) == (1, ["/mnt/c/Users/me/ctf/chall.bin"])),
            ("fll.cmd alias forwards the same way",
             'fll.cmd a "b c"',
             lambda rc, o: parse_probe(o) == (2, ["a", "b c"])),
            # The `fulilian` pair must forward identically - they are thin
            # delegators to fll.bat, and a delegator that re-quotes or
            # re-tokenises the argument text would show up right here.
            ("fulilian.bat alias forwards the same way",
             'fulilian.bat a "b c"',
             lambda rc, o: parse_probe(o) == (2, ["a", "b c"])),
            ("fulilian.cmd alias forwards the same way",
             'fulilian.cmd C:\\Users\\me\\ctf\\chall.bin',
             lambda rc, o: parse_probe(o) == (1, ["/mnt/c/Users/me/ctf/chall.bin"])),
        ]

        for label, invocation, assertion in cases:
            rc, out = run_cmd(base + invocation, staged)
            argc, args = parse_probe(out)
            try:
                good = assertion(rc, out)
            except Exception:  # noqa: BLE001 - assertion helper, any shape
                good = False
            if good:
                ok(f"runtime: {label}")
            else:
                bad(f"runtime: {label}", f"got argc={argc} args={args}\n{out.strip()}")

        # exit code
        rc, _ = run_cmd(base + "fll.bat --exit 7", staged)
        if rc == 7:
            ok("runtime: exit code 7 forwarded")
        else:
            bad("runtime: exit code not forwarded", f"expected 7, got {rc}")

        # stdin
        rc, out = run_cmd(base + "fll.bat --stdin", staged, stdin=b"l1\nl2\nl3\n")
        if "PROBE_STDIN_LINES=3" in out:
            ok("runtime: stdin reaches WSL intact")
        else:
            bad("runtime: stdin drained or lost", out.strip())

        # The batch launcher must reach fll.ps1 at all — if it silently took the
        # :no_powershell fallback, every case above passes for the wrong reason.
        rc, out = run_cmd(base + "fll.bat --version", staged)
        if "[fll] WARNING: PowerShell not found" in out:
            bad(
                "runtime: fll.bat fell back to the no-PowerShell branch",
                "the argv cases above then prove nothing about fll.ps1.",
            )
        else:
            ok("runtime: fll.bat delegated to fll.ps1 (no degraded fallback)")

        # install.cmd /check must resolve its own directory even after the
        # argument parse loop (the shift bug).
        rc, out = run_cmd(f"cd /d C:\\ && {win_dir}\\install.cmd /check", staged)
        if win_dir.lower() + "\\fll.bat" in out.lower():
            ok("runtime: install.cmd /check resolves its own directory")
        else:
            bad("runtime: install.cmd /check resolved the wrong source path", out.strip())

        # -Install/-Uninstall must round-trip the profile byte-for-byte. A
        # separator the installer adds but the uninstaller forgets is exactly the
        # kind of residue nobody notices until it is in a thousand profiles.
        rt = staged / "roundtrip.ps1"
        rt.write_text(ROUNDTRIP_PS1, encoding="ascii")
        rc, out = run_cmd(
            f"cd /d {win_dir} && powershell.exe -NoProfile -ExecutionPolicy Bypass "
            f"-File {win_dir}\\roundtrip.ps1",
            staged,
        )
        if "RT_PROFILE_ROUNDTRIP_OK" in out:
            ok("runtime: profile -Install/-Uninstall round-trips exactly")
        else:
            bad("runtime: profile wiring does not round-trip", out.strip())

        return True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    global verbose
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--static", action="store_true", help="skip the runtime layer")
    ap.add_argument("-v", "--verbose", action="store_true", help="show passing checks")
    args = ap.parse_args()
    verbose = args.verbose

    if not CMD_DIR.is_dir():
        print(f"error: {CMD_DIR} not found", file=sys.stderr)
        return 1

    run_static()
    ran_runtime = False
    if not args.static:
        ran_runtime = run_runtime()

    print()
    if failures:
        print(f"{len(failures)} failure(s):")
        for f in failures:
            print(f"  - {f}")
        return 1
    suffix = "" if ran_runtime else " (runtime skipped)"
    print(f"all {passes} checks passed{suffix}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
