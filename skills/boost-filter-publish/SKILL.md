---
name: boost-filter-publish
description: Publish the local JFrog Boost filters to a shareable repository — copy them to a throwaway directory, replace local names and identifying details with neutral ones without changing filter behaviour, verify, refresh the README metrics from `boost report`, and commit. Use when the user asks to publish, update, share or sync their Boost filters, to scrub filters before sharing, to refresh the filter repository's metrics or screenshot, to choose a filter's `match_mode` after a Boost engine change, or to install the published copies back into `~/.boost/filters`.
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
their expected output. It also runs `boost filters validate` on each file, whose
checks tighten between Boost releases — a filter set that passed last week can
fail today. If either gate fails, fix it in the source and re-run. Do not publish.

The two runners disagree in one known way. `boost filters validate` applies the
filter as written, while a real run skips a filter whose saving is below Boost's
minimum (roughly under 5 % and under 16 tokens) and returns the input unchanged.
A small fixture can therefore pass one gate and fail the other. Write fixtures
whose expected output holds under both, rather than editing `expected` until one
passes.

Before this step, also read the whole scrubbed output once — every fixture,
not only the lines the scrub touched. The scans catch paths, e-mails, UUIDs and
credential shapes; they cannot catch a product name, a business domain, a route
name or a sentence copied from a private README. When you find one, fix it in
the source (an alias, or invented text in a new fixture) and scrub again. The
repository is public and its history keeps whatever was pushed.

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
# start the server as a background task (not `&` + `sleep` in the foreground);
# it prints e.g. "Boost report web UI: http://127.0.0.1:PORT"
boost ui -d 30 > "$WORK/boost-ui.log" 2>&1
grep -oE 'http://[0-9.]+:[0-9]+' "$WORK/boost-ui.log"
agent-browser open "<that url>"
agent-browser set viewport 1600 1000 2
agent-browser wait --text "TOKENS SAVED"    # the page shows "Loading…" first; a large history takes a while
agent-browser wait 3000
agent-browser screenshot "$WORK/report-ui.png"   # view it, then copy to $REPO/docs/report-ui.png
agent-browser close
kill "$(pgrep -f '^boost ui -d 30')"
```

Do not stop the server with `pkill -f "boost ui"`. That pattern also matches the
shell whose command line contains it, and kills that shell too.

**Look at the image before it is committed.** The dashboard mixes aggregate
panels with lists that name real files, and other views show commands and
conversation titles. Only the aggregate panels may be published: totals, the
savings chart, the filter activity grid. If anything identifying is in frame,
reframe or scroll and shoot again — do not commit a screenshot you have not
viewed. If the page renders blank, the server has stopped; restart it. If it still says
"Loading…", it was captured too early: wait for the text again.

**6. Commit and push.** Describe what changed — filters updated, metrics
refreshed — without naming anything the scrub removed. The README may say that
identifiers were replaced; it must never say what they were, and a diff of
`filters/` must never be explained in terms of the originals.

Stage the generated paths by name (`README.md dist docs filters skills`), not
with `git add -A`. Other tools leave local state in the working tree (for
example `.collab/`) that must not be pushed.

**7. Installing the published copies locally (only when asked).** Filter
behaviour in `filters/` is identical to `~/.boost/filters`; only comments,
descriptions and fixtures differ. To make the install match the repository, back
up first, then copy and validate:

```bash
cp -a ~/.boost/filters ~/.boost/backup-$(date +%Y%m%d)-pre-sync
cp $REPO/filters/*.toml ~/.boost/filters/
boost filters validate && boost filters show
```

After that the local fixtures carry the neutral names, so later scrubs of those
lines are no-ops. That is expected.

## Choosing how a filter is selected

A filter is selected by `match_command`, by `match_output_select`, or by both.
`match_mode` (Boost v0.13.20 and later) decides how the two combine:

- `"any"`, the default: either one selects. An output fingerprint therefore
  *widens* selection to every command whose output looks like the tool's.
- `"all"`: both must match. The fingerprint *gates* the command.
- no `match_output_select`: command-only.

Decide from measurement, not from taste. The history database
(`~/.local/share/boost/history.db`, table `commands`: `cmd`, `original_output`,
`capability_id` naming the filters that ran) is enough. Open it read-only
(`?mode=ro`). Replay each candidate mode's regexes over it in Python, and count
the events and removable bytes each mode keeps or loses. Also look at a few
events a stricter mode would block. For the six filters here, the answer
differed per filter, and each file's header comment records the numbers.

Tests follow from the mode. `boost filters validate` checks
`expect_match_output` against `match_output_select` only; the test has no
command. So a command-only filter must omit `expect_match_output = true`, and
use `expect_match_output = false` only for input that must pass through
unchanged. Record the minimum Boost version in the README when a filter uses a
key that older releases lack.

Write new fixtures from invented text in the shape of the real output. Do not
paste private output into them.

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
