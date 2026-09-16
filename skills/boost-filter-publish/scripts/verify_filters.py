#!/usr/bin/env python3
"""Two gates for a scrubbed filter directory.

    verify_filters.py --dir <scrubbed dir> [--aliases <private aliases.toml>]
                      [--commands <commands.toml>] [--skip-engine]

1. Leak scan — the scrubbed files must not contain any alias-file term, the local
   user name, host name, home path, an e-mail address, a UUID, or anything shaped
   like a credential. Failures print the file and line number, never the match.
2. Engine tests — every `[[tests.<filter>]]` case is run through the real `boost`
   binary under a throwaway HOME with all other filters disabled, so a scrubbed
   fixture is proved to still produce its expected output. A filter needs a probe
   command that its `match_command` selects; `commands.toml` supplies one per
   filter (`[commands]` / `[nomatch]`), defaulting to the filter's own name.

Exit code is non-zero if any gate fails.
"""
from __future__ import annotations

import argparse, json, os, pathlib, re, shutil, socket, sqlite3, subprocess, sys, tempfile, tomllib

BOOST = os.environ.get("BOOST_EXE", os.path.expanduser("~/.local/bin/boost"))
SECRET = re.compile(r"(?i)(api[_-]?key|secret|passwd|password|credential|authorization|bearer"
                    r"|BEGIN [A-Z ]*PRIVATE KEY|ghp_[A-Za-z0-9]{20,}|xox[bp]-|AKIA[0-9A-Z]{10,}|sk-[A-Za-z0-9]{20,})")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
MARKER = re.compile(r"\n?\[Boost compressed .*\]$")


def boundary(term: str) -> str:
    """See scrub.py: `\b` would miss a term embedded in snake_case."""
    return r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])"


def leak_scan(dirpath: pathlib.Path, aliases: pathlib.Path | None) -> list[str]:
    needles: list[tuple[str, re.Pattern]] = []
    home, user, host = os.path.expanduser("~"), os.environ.get("USER", ""), socket.gethostname()
    for label, literal in (("home path", home), ("user name", user), ("host name", host)):
        if literal and len(literal) > 2:
            needles.append((label, re.compile(boundary(literal), re.I)))
    if aliases and aliases.exists():
        for term in tomllib.load(open(aliases, "rb")).get("terms", {}):
            needles.append((f"alias term ({len(term)} chars)", re.compile(boundary(term), re.I)))
    needles += [("e-mail address", EMAIL), ("uuid", UUID), ("credential-shaped string", SECRET)]

    problems = []
    for path in sorted(dirpath.glob("*.toml")):
        for n, line in enumerate(path.read_text().splitlines(), 1):
            for label, rx in needles:
                if rx.search(line):
                    problems.append(f"{path.name}:{n}: contains a {label}")
    return problems


def engine_tests(dirpath: pathlib.Path, commands: dict) -> list[str]:
    if not os.path.exists(BOOST):
        return [f"boost binary not found at {BOOST}; set BOOST_EXE"]
    failures = []
    for path in sorted(dirpath.glob("*.toml")):
        spec = tomllib.load(open(path, "rb"))
        name = next(iter(spec.get("filters", {})), None)
        if not name or name not in spec.get("tests", {}):
            continue
        home = pathlib.Path(tempfile.mkdtemp(prefix="bfp-verify-"))
        (home / ".boost/filters").mkdir(parents=True)
        (home / ".boost/config.toml").write_text(
            'accept_terms = "yes"\naccept_terms_at = "2026-01-01T00:00:00Z"\nterms_version = "preview-1"\n')
        shutil.copy(path, home / ".boost/filters")
        listing = subprocess.run([BOOST, "filters", "show"], capture_output=True, text=True,
                                 env=dict(os.environ, HOME=str(home))).stdout
        others = sorted({l.split()[2] for l in listing.splitlines()[1:] if len(l.split()) >= 3} - {name})
        cfg = (home / ".boost/config.toml").read_text()
        (home / ".boost/config.toml").write_text(cfg + "[filters]\ndisabled = " + json.dumps(others) + "\n")

        def run(cmd: str, text: str) -> str:
            meta = home / "meta.json"
            meta.write_text(json.dumps({"agent_type": "claude_code", "cwd": "/tmp", "hook_event_name": "PreToolUse",
                                        "session_id": "verify", "tool_name": "Bash", "tool_input": {"command": cmd}}))
            env = dict(os.environ, HOME=str(home), BOOST_DB_PATH=str(home / "t.db"),
                       BOOST_AUTO_UPDATE="0", BOOST_HOOK_META_FILE=str(meta))
            out = subprocess.run([BOOST], input=text, capture_output=True, text=True, env=env).stdout
            return MARKER.sub("", out.rstrip("\n"))

        match_cmd = commands.get("commands", {}).get(name, name)
        no_cmd = commands.get("nomatch", {}).get(name, "true")
        for case in spec["tests"][name]:
            expect_applied = case.get("expect_match_output", True)
            got = run(match_cmd if expect_applied else no_cmd, case["input"])
            want = (case["expected"] if expect_applied else case["input"]).rstrip("\n")
            if got != want:
                failures.append(f"{path.name}: test {case['name'][:70]!r} did not reproduce its expected output")
        shutil.rmtree(home, ignore_errors=True)
    return failures


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--aliases")
    ap.add_argument("--commands")
    ap.add_argument("--skip-engine", action="store_true")
    args = ap.parse_args()

    dirpath = pathlib.Path(args.dir).expanduser()
    commands = tomllib.load(open(args.commands, "rb")) if args.commands and os.path.exists(args.commands) else {}
    problems = leak_scan(dirpath, pathlib.Path(args.aliases).expanduser() if args.aliases else None)
    print(f"leak scan: {'clean' if not problems else str(len(problems)) + ' problem(s)'}")
    for p in problems:
        print("  " + p)

    failures = [] if args.skip_engine else engine_tests(dirpath, commands)
    if not args.skip_engine:
        print(f"engine tests: {'all passed' if not failures else str(len(failures)) + ' failure(s)'}")
        for f in failures:
            print("  " + f)
    return 1 if (problems or failures) else 0


if __name__ == "__main__":
    sys.exit(main())
