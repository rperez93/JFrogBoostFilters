---
name: boost-filter-publish
description: Publish the local JFrog Boost filters to a shareable repository — copy them to a throwaway directory, replace local names and identifying details with neutral ones without changing filter behaviour, verify, refresh the README metrics from `boost report`, and commit. Use when the user asks to publish, update, share or sync their Boost filters, to scrub filters before sharing, or to refresh the filter repository's metrics or screenshot.
---

# Publishing Boost filters without publishing yourself

A Boost filter is only trustworthy if its tests are made of real output — which
is exactly what makes it awkward to share. The fixtures carry the names of
whatever the tests were run against. This skill separates the two: the rules go
out verbatim, the names do not.

Everything is generated. Never hand-edit a file under `filters/` in the
repository: the next run overwrites it, and a hand-edit is the one path that can
put a real name back.

## Layout

| Path | What it is |
|---|---|
| `filters/` | The published copies. Generated. |
| `skills/boost-filter-publish/` | This skill. The repository is the only copy; `~/.claude/skills/boost-filter-publish` is a symlink to it. |
| `skills/boost-filter-publish/scripts/` | `scrub.py`, `verify_filters.py`, `make_zip.py`, `metrics.py` |
| `dist/boost-filters.zip` | The archive `boost filters import` accepts. Generated. |
| `skills/boost-filter-publish/reference/commands.toml` | A probe command per filter, so the verifier can select each one |
| `docs/report-ui.png` | Optional screenshot of the report UI |
| `~/.config/boost-filter-publish/aliases.toml` | **Private.** The name mapping. Outside the repository on purpose — never commit it, never quote its contents in the README, a commit message, or a reply. |

## The run

Work in this order and stop at the first failure — a half-published filter set is
worse than a stale one.

**1. Scrub into a throwaway directory.**

```bash
REPO=~/projects/JFrogBoostFilters
WORK="${TMPDIR:-/tmp}/boost-filter-publish/$(python3 -c 'import uuid;print(uuid.uuid4())')"
python3 $REPO/skills/boost-filter-publish/scripts/scrub.py \
    --src ~/.boost/filters --out "$WORK" \
    --aliases ~/.config/boost-filter-publish/aliases.toml --report "$WORK/scrub-report.json"
```

It rewrites only comments, `description` values and `[[tests]]` fixtures, and
refuses to write anything whose behaviour fields differ from the source.

**2. Read the scrub report before trusting it.** The count that matters is
`in_prose`: replacements inside comments and descriptions. A fixture replacement
is routine; a prose replacement usually means an alias term is also an ordinary
English word, and it will have quietly mangled the documentation — a component
named after a common noun rewrites that noun everywhere it appears. When that
happens, narrow the alias — move it from `[terms]` to a `[[regex]]` rule that
targets the real identifier — and scrub again.

Check the opposite failure too: a term that should have been replaced and was
not. Names hide inside identifiers (`test_<name>`, `<name>.module`, a dotted
class path), which is why matching bounds on alphanumerics rather than `\b` —
`\b` treats `_` as a word character and walks straight past `test_<name>`. After
a scrub, grep the output for each term as a plain substring, with no boundaries
at all, and read the hits. Then diff a file or two against the source and
read the result: it should read like someone else's filter, not like a redaction.

**3. Verify. Both gates, every time.**

```bash
python3 $REPO/skills/boost-filter-publish/scripts/verify_filters.py \
    --dir "$WORK" --aliases ~/.config/boost-filter-publish/aliases.toml \
    --commands $REPO/skills/boost-filter-publish/reference/commands.toml
```

The leak scan looks for alias terms, the local user and host names, home paths,
e-mail addresses, UUIDs and credential-shaped strings. The engine gate runs every
filter's own test cases through the real `boost` binary under a throwaway `HOME`
with all other filters disabled, which proves the scrubbed fixtures still produce
their expected output. It also runs `boost filters validate` on each file, whose checks tighten
between Boost releases — a filter set that passed last week can fail today. If either fails, fix and re-run — do not publish.

**4. Copy in and refresh the metrics.**

```bash
cp "$WORK"/*.toml $REPO/filters/
python3 $REPO/skills/boost-filter-publish/scripts/make_zip.py \
    --dir $REPO/filters --out $REPO/dist/boost-filters.zip
python3 $REPO/skills/boost-filter-publish/scripts/metrics.py \
    --repo $REPO --days 30 --screenshot docs/report-ui.png   # drop --screenshot if there is none
```

The archive carries `filters/*.toml` — Boost accepts that or a flat `*.toml`
archive and rejects any other path, so GitHub's "Download ZIP" of the repository
cannot be imported. It is built deterministically, so an unchanged filter set
produces the same bytes and the repository does not churn.

`metrics.py` reads a whitelist of aggregate fields plus the per-filter rows for
the published filters. It never opens the report's event stream, which holds
every recorded command, its output and its working directory. Keep it that way:
if you want a new number in the README, add its field to the whitelist rather
than reaching into the raw JSON.

**5. Screenshot, only if `agent-browser` is installed.** The report UI is a local
web app, so it needs a URL:

```bash
boost ui -d 30 > /tmp/boost-ui.log 2>&1 &   # prints e.g. "Boost report web UI: http://127.0.0.1:PORT"
sleep 5; grep -oE 'http://[0-9.]+:[0-9]+' /tmp/boost-ui.log
agent-browser open "<that url>"
agent-browser set viewport 1600 1000 2
agent-browser screenshot $REPO/docs/report-ui.png
agent-browser close; pkill -f "boost ui"
```

**Look at the image before it is committed.** The dashboard mixes aggregate
panels with lists that name real files, and other views show commands and
conversation titles. Only the aggregate panels may be published: totals, the
savings chart, the filter activity grid. If anything identifying is in frame,
reframe or scroll and shoot again — do not commit a screenshot you have not
viewed. If the page renders blank, the server has stopped; restart it.

**6. Commit and push.** Describe what changed — filters updated, metrics
refreshed — without naming anything the scrub removed. The README may say that
identifiers were replaced; it must never say what they were, and a diff of
`filters/` must never be explained in terms of the originals.

## When a filter is added or changed locally

Add a probe command for it in `reference/commands.toml` (one command its
`match_command` selects, one it must not), so the engine gate covers it instead
of silently skipping it. If the filter's tests carry a new internal name, add
that name to the private alias file first, then run.

## Setting this up elsewhere

1. Clone the repository and link the skill:
   `ln -s "$PWD/skills/boost-filter-publish" ~/.claude/skills/boost-filter-publish`
2. Create `~/.config/boost-filter-publish/aliases.toml` with a `[terms]` table
   mapping local names to neutral ones, `chmod 600`. The scrubber already handles
   the machine's user name, host name, home paths, e-mail addresses and UUIDs
   without being told; the alias file is for project, product and component names
   that only you can recognise.
3. Run the steps above. Nothing else is machine-specific.
