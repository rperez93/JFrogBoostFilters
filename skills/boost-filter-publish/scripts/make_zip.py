#!/usr/bin/env python3
"""Build the archive that `boost filters import` accepts.

    make_zip.py --dir filters --out dist/boost-filters.zip

Boost accepts `filters/*.toml` or `*.toml` inside the archive and rejects any
other path — including the folder GitHub's own "Download ZIP" wraps a repository
in, so that download cannot be imported. Entries are written under `filters/` so
the archive mirrors this repository's layout.

The archive is built deterministically (sorted entries, fixed timestamps, fixed
permissions), so an unchanged filter set produces a byte-identical zip and
republishing does not churn the repository.
"""
from __future__ import annotations

import argparse, pathlib, sys, zipfile

FIXED_DATE = (1980, 1, 1, 0, 0, 0)  # the earliest zip timestamp, so it never drifts


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="directory of scrubbed *.toml filters")
    ap.add_argument("--out", required=True)
    ap.add_argument("--prefix", default="filters/", help="path inside the zip (Boost allows 'filters/' or '')")
    args = ap.parse_args()

    src = pathlib.Path(args.dir).expanduser()
    out = pathlib.Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)

    files = sorted(src.glob("*.toml"), key=lambda p: p.name)
    if not files:
        print(f"no *.toml in {src}", file=sys.stderr)
        return 1

    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            info = zipfile.ZipInfo(args.prefix + path.name, date_time=FIXED_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, path.read_bytes())

    print(f"{out}: {len(files)} filter(s), {out.stat().st_size:,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
