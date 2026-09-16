#!/usr/bin/env python3
"""Refresh the metrics block in the repository README from the local Boost report.

    metrics.py --repo <repo root> [--days 30] [--screenshot docs/report-ui.png]

`boost report -f json` also carries every recorded command, its stdout, and the
working directory it ran in. This reads a fixed whitelist of aggregate fields and
the per-filter rows for the filters this repository publishes — the event stream
is never opened, so nothing about what was run can reach the README.
"""
from __future__ import annotations

import argparse, datetime, json, os, pathlib, subprocess, sys, tempfile, tomllib

BOOST = os.environ.get("BOOST_EXE", os.path.expanduser("~/.local/bin/boost"))
START, END = "<!-- metrics:start -->", "<!-- metrics:end -->"
# Aggregate savings only. Account spend and token-usage totals are deliberately excluded.
TOTALS = ["days", "total_commands", "total_saved", "total_context_saved", "total_saved_usd",
          "total_context_saved_usd", "total_saved_co2e_kg", "total_context_saved_co2e_kg"]
FILTER_FIELDS = ["name", "enabled", "event_count", "tokens_before", "tokens_after", "saved_tokens", "retrieve_count"]


def human(n: float) -> str:
    for unit, size in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(n) >= size:
            return f"{n / size:.1f}{unit}"
    return f"{n:.0f}"


def collect(days: int, repo: pathlib.Path) -> tuple[dict, list]:
    with tempfile.TemporaryDirectory() as tmp:
        out = pathlib.Path(tmp) / "report.json"
        with open(out, "w") as fh:
            subprocess.run([BOOST, "report", "-f", "json", "-d", str(days)], stdout=fh, check=True)
        doc = json.load(open(out))
    totals = {k: doc.get(k) for k in TOTALS}
    published = {p.stem for p in (repo / "filters").glob("*.toml")}
    rows = []
    for entry in doc.get("filters", {}).get("custom", []):
        if entry.get("name") in published:
            rows.append({k: entry.get(k) for k in FILTER_FIELDS})
    rows.sort(key=lambda r: -(r.get("saved_tokens") or 0))
    return totals, rows


def render(totals: dict, rows: list, screenshot: str | None) -> str:
    days = totals.get("days") or 30
    saved_usd = (totals.get("total_saved_usd") or 0) + (totals.get("total_context_saved_usd") or 0)
    co2 = (totals.get("total_saved_co2e_kg") or 0) + (totals.get("total_context_saved_co2e_kg") or 0)
    lines = [START, "",
             f"*Measured on the install these filters come from, over the last {days} days; "
             f"refreshed automatically, last on {datetime.date.today().isoformat()}.*", "",
             "| | |", "|---|---|",
             f"| Commands recorded | {totals.get('total_commands', 0):,} |",
             f"| Tokens removed from tool output | {human(totals.get('total_saved') or 0)} |",
             f"| Tokens never re-sent in later turns | {human(totals.get('total_context_saved') or 0)} |",
             f"| Estimated cost avoided | ${saved_usd:,.0f} |",
             f"| Estimated CO₂e avoided | {co2:,.1f} kg |", ""]
    if rows:
        lines += ["These filters' own share of that, by filter:", "",
                  "| Filter | Enabled | Events | Tokens before | Tokens after | Saved | Retrieves |",
                  "|---|---|---:|---:|---:|---:|---:|"]
        for r in rows:
            before, after = r.get("tokens_before") or 0, r.get("tokens_after") or 0
            pct = f"{100 * (1 - after / before):.0f}%" if before else "—"
            lines.append(f"| `{r['name']}` | {'yes' if r.get('enabled') else 'no'} | {r.get('event_count', 0):,} "
                         f"| {human(before)} | {human(after)} | {pct} | {r.get('retrieve_count', 0)} |")
        lines.append("")
        notes = ["A retrieve count above zero means an agent had to recover output that a filter chain removed — "
                 "the number these filters are tuned to keep at zero. Before Boost v0.13.20 a retrieve was attributed "
                 "to every filter in the chain that handled the command, including filters that changed nothing "
                 "([jfrog/boost#85](https://github.com/jfrog/boost/issues/85), fixed 2026-09-16), so counts "
                 "recorded before that release are not proof that this filter was the one responsible."]
        if any(not r.get("event_count") for r in rows):
            notes.append("Rows with no events have not yet matched a command inside the window — a filter added "
                         "recently starts at zero and fills in as work runs.")
        for note in notes:
            lines.append(note)
            lines.append("")
    if screenshot:
        lines += [f"![Boost report]({screenshot})", "",
                  "*The report UI on the same install.*", ""]
    lines.append(END)
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--screenshot")
    args = ap.parse_args()

    repo = pathlib.Path(args.repo).expanduser()
    readme = repo / "README.md"
    totals, rows = collect(args.days, repo)
    block = render(totals, rows, args.screenshot)

    text = readme.read_text()
    if START not in text or END not in text:
        print(f"README has no metrics markers ({START} … {END})", file=sys.stderr)
        return 1
    head, rest = text.split(START, 1)
    _, tail = rest.split(END, 1)
    readme.write_text(head + block + tail)
    print(f"metrics block refreshed: {len(rows)} filter row(s), {args.days}-day window")
    return 0


if __name__ == "__main__":
    sys.exit(main())
