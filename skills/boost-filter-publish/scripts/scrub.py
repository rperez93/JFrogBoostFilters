#!/usr/bin/env python3
"""Copy Boost filter files to a throwaway directory and replace local identifiers
with neutral ones, without touching a single byte of filter behaviour.

    scrub.py --src ~/.boost/filters --out /tmp/boost-filter-publish/<uuid> \
             [--aliases ~/.config/boost-filter-publish/aliases.toml] [--report report.json]

Only comments, `description` values and `[[tests.*]]` fixtures are rewritten.
Every field the engine acts on (match_command, strip/keep/dedupe/collapse rules,
replace patterns and replacements, on_empty, versions, …) is copied verbatim, and
the result is checked against the source with a structural diff before it is
written: if any behaviour field differs, nothing is written and the run fails.

The alias file is private. It maps real local names to the published ones and
must never be committed; `--report` deliberately carries counts, not values.
"""
from __future__ import annotations

import argparse, json, os, pathlib, re, socket, sys, tomllib

# Keys whose values the engine acts on. Anything not explicitly editable is treated
# as protected, so a key added by a future Boost version is protected by default.
EDITABLE_KEYS = {"description", "name", "input", "expected"}
TESTS_TABLE = re.compile(r"^\s*\[\[tests\.")
TABLE_HEADER = re.compile(r"^\s*\[\[?([A-Za-z0-9_.-]+)\]\]?\s*$")
KEY_LINE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")


def boundary(term: str) -> str:
    """`\b` treats `_` as a word character, so it misses a name embedded in a
    snake_case or dotted identifier: `\bwidget\b` never matches `test_widget`.
    Bound on alphanumerics instead, so `_`, `-` and `.` count as separators while
    an ordinary English word containing the term still does not match."""
    return r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])"


def case_like(model: str, repl: str) -> str:
    if model.isupper() and len(model) > 1:
        return repl.upper()
    if model[:1].isupper():
        return repl[:1].upper() + repl[1:]
    return repl


def build_rules(aliases_path: pathlib.Path | None) -> tuple[list, list]:
    """Returns (regex_rules, term_rules). Identity facts are derived from the
    environment so the scrubber is useful before anyone writes an alias file."""
    regex_rules: list[tuple[re.Pattern, str]] = []
    term_rules: list[tuple[re.Pattern, str]] = []

    home = os.path.expanduser("~")
    user = os.environ.get("USER") or pathlib.Path(home).name
    host = socket.gethostname()
    # Longest-first so /home/<user>/x is rewritten before <user> alone.
    regex_rules += [
        (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "user@example.com"),
        (re.compile(re.escape(home) + r"(?=/|\b)"), "$HOME"),
        (re.compile(r"/(?:home|Users)/[A-Za-z0-9._-]+"), "$HOME"),
        (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"), "00000000-0000-0000-0000-000000000000"),
        (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "127.0.0.1"),
    ]
    for literal, repl in ((user, "user"), (host, "host")):
        if literal and len(literal) > 2:
            regex_rules.append((re.compile(boundary(literal), re.I), repl))

    if aliases_path and aliases_path.exists():
        conf = tomllib.load(open(aliases_path, "rb"))
        for term, repl in sorted(conf.get("terms", {}).items(), key=lambda kv: -len(kv[0])):
            term_rules.append((re.compile(boundary(term), re.I), repl))
        for rule in conf.get("regex", []):
            regex_rules.append((re.compile(rule["pattern"]), rule["replacement"]))
    return regex_rules, term_rules


def scrub_text(text: str, regex_rules, term_rules, counter: dict, region: str = "fixture") -> str:
    for rx, repl in regex_rules:
        text, n = rx.subn(repl, text)
        counter["replacements"] += n
        counter[region] = counter.get(region, 0) + n
    for rx, repl in term_rules:
        def sub(m):
            counter["replacements"] += 1
            counter[region] = counter.get(region, 0) + 1
            return case_like(m.group(0), repl)
        text = rx.sub(sub, text)
    return text


def scrub_file(src: pathlib.Path, regex_rules, term_rules, counter: dict) -> str:
    """Rewrite only comments, descriptions and test fixtures; copy every other line."""
    out: list[str] = []
    in_tests = False        # inside a [[tests.*]] table
    ml_delim = None         # open multi-line string delimiter, if any
    ml_editable = False
    array_key = None        # key of an array still waiting for its closing ]

    for line in src.read_text().splitlines(keepends=True):
        body = line.rstrip("\n")

        if ml_delim is not None:                      # inside a multi-line string
            out.append(scrub_text(line, regex_rules, term_rules, counter) if ml_editable else line)
            if ml_delim in body:
                ml_delim = None
            continue

        if array_key is not None:                     # inside a multi-line array
            out.append(line)                          # arrays only ever hold rules
            if "]" in body:
                array_key = None
            continue

        header = TABLE_HEADER.match(body)
        if header:
            in_tests = bool(TESTS_TABLE.match(body))
            out.append(line)
            continue

        if body.lstrip().startswith("#") or not body.strip():
            out.append(scrub_text(line, regex_rules, term_rules, counter, "prose"))
            continue

        kv = KEY_LINE.match(body)
        if not kv:
            out.append(line)
            continue

        key, value = kv.group(1), kv.group(2)
        editable = key in EDITABLE_KEYS and (in_tests or key == "description")
        if value.startswith("[") and "]" not in value:
            array_key = key                            # rules array, always protected
            out.append(line)
            continue
        for delim in ('"""', "'''"):
            if value.startswith(delim) and not value[len(delim):].endswith(delim):
                ml_delim, ml_editable = delim, editable
                break
        out.append(scrub_text(line, regex_rules, term_rules, counter,
                              "prose" if key == "description" else "fixture") if editable else line)
    return "".join(out)


def behaviour_of(doc: dict) -> dict:
    """Everything the engine acts on: the whole document minus the fields we allow
    ourselves to rewrite."""
    filters = {}
    for name, spec in doc.get("filters", {}).items():
        filters[name] = {k: v for k, v in spec.items() if k != "description"}
    tests = {}
    for name, cases in doc.get("tests", {}).items():
        tests[name] = [{k: v for k, v in c.items() if k not in ("name", "input", "expected")} for c in cases]
    rest = {k: v for k, v in doc.items() if k not in ("filters", "tests")}
    return {"filters": filters, "tests": tests, "rest": rest}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--aliases")
    ap.add_argument("--report")
    args = ap.parse_args()

    src_dir, out_dir = pathlib.Path(args.src).expanduser(), pathlib.Path(args.out).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    regex_rules, term_rules = build_rules(pathlib.Path(args.aliases).expanduser() if args.aliases else None)

    report, failed = [], False
    for src in sorted(src_dir.glob("*.toml")):
        counter = {"replacements": 0}
        text = scrub_file(src, regex_rules, term_rules, counter)
        try:
            before, after = tomllib.loads(src.read_text()), tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            print(f"FAIL {src.name}: scrubbed file is not valid TOML: {exc}", file=sys.stderr)
            failed = True
            continue
        same_behaviour = behaviour_of(before) == behaviour_of(after)
        if not same_behaviour:
            print(f"FAIL {src.name}: a behaviour field changed — not written", file=sys.stderr)
            failed = True
            continue
        (out_dir / src.name).write_text(text)
        report.append({"file": src.name, "replacements": counter["replacements"],
                       "in_prose": counter.get("prose", 0), "in_fixtures": counter.get("fixture", 0),
                       "behaviour_identical": True})
        print(f"ok   {src.name}: {counter['replacements']} replacement(s) "
              f"({counter.get('prose', 0)} in comments/descriptions — review those), behaviour fields identical")

    if args.report:
        pathlib.Path(args.report).write_text(json.dumps(report, indent=1))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
