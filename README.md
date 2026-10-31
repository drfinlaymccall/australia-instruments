# Australian Commonwealth legislative instruments

The regulations, determinations and ASIC instruments that sit under the
Commonwealth statute book, as a git history: **one commit per amending
instrument, on the day it took effect**.

That makes two questions cheap which are otherwise slow:

```bash
# What has ever changed this provision, and when?
git log --date=short --format='%ad  %s' \
  -- corpus/foreign-acquisitions-and-takeovers-regulation-2015/s-052.md

# What did the whole instrument say on the day a deal signed?
git checkout foreign-acquisitions-and-takeovers-regulation-2015/2023-07-01
```

The corpus is built for **M&A diligence**, where the Australian-side
instruments — foreign investment screening, merger notification, takeover
relief — are the ones most often missed, and where the question is
usually not "what does this say?" but "what did this say in March, and
who changed it since?".

It is laid out to match [`lexifina/global-law`](https://github.com/lexifina/global-law),
and is intended to sit in that tree as `australia/federal/instruments`.

## What is in it

See [`corpus.json`](corpus.json) for the machine-readable record of
coverage, and [`REPRODUCE.md`](REPRODUCE.md) for the counts and the
verification result.

## Layout

```
corpus/<instrument-slug>/
    intro.md            name, authorising provision, preamble
    s-052.md            section 52
    r-6.10.01.md        regulation 6.10.01
    sch-1/cl-01.md      Schedule 1, clause 1
    part-6/div-2.md     a Division that holds law text directly
```

Most law sits in a provision file. Some does not: a Part, Division or
Schedule can carry text with no provision heading beneath it, and the
notification forms in the merger determinations are whole Divisions
written that way. That text is filed under the containers that hold it,
so the ACCC short-form notification is
`competition-and-consumer-notification-of-acquisitions-forms-determination-2025/part-6/div-2.md`.

Inside a file: `##` lines for the Part and Division headings that open
at that provision, a `#` line with the provision number and heading,
then one line per paragraph. A table row is one line, cells separated
by ` | `.

A plain section number is zero-padded to three digits (`s-052.md`) so
sections sort in numerical order. Numbers that are already compound keep
the form the instrument writes, so that the file name is the citation:
the modern Commonwealth style `s-1-9.md` for section 1-9, and
`r-6.10.01.md` for regulation 6.10.01.

## Reading the history

Every commit is one amending instrument taking effect:

```
Foreign Acquisitions and Takeovers Amendment (UK Free Trade Agreement) Regulations 2022

In-force: 2023-05-31
Compilation: 17
Compilation-id: F2023C00520
Affecting: intro.md
Affecting: s-005.md
Affecting: s-079.md
Kind: Amend
Amending-provisions: sch 1 (items 1, 2)
```

The commit is **authored by the amending instrument**, not by a person,
so `git log --author` and `git shortlog` work on instruments. Its date
is noon in Canberra on the day the change took effect. Each compilation
is tagged `<instrument-slug>/<YYYY-MM-DD>`.

Where the Register attributes a compilation to more than one instrument,
the commit is authored `Federal Register of Legislation` and carries an
`Attribution:` trailer naming what it could not be narrowed to. Nothing
is guessed.

`main` holds only what is in force today. Compilations with a future
start date are on the `future` branch.

Every instrument here sunsets, and a sunsetting repeal has no compiled
text -- the Register records the version with no document at all -- so
the repeal is committed on `future` as the removal of the instrument,
with `Kind: Repeal`:

```bash
# Will the Forms Determination still exist at the longstop date?
git log --format='%ad %s' --date=short future \
  -- corpus/competition-and-consumer-notification-of-acquisitions-forms-determination-2025
```

## Building it

```bash
python3 tools/fetch_all.py                      # download, 10s between requests
python3 tools/build.py   --today 2026-10-31     # parse and replay into git
python3 tools/verify.py  --today 2026-10-31     # check against the official text
python3 tools/completeness.py --today 2026-10-31 # check against the official contents
```

No dependencies beyond the Python 3.11+ standard library. The fetcher
waits at least ten seconds between requests, as the Register's
robots.txt asks, and never re-fetches anything already cached. The build
and the verifier never touch the network at all.

**Do not point `fetch_all.py` at the whole Register.** It covers a named
list of instruments. The Register asks to be contacted before a full
crawl, and that request is worth honouring.

## Is it right?

Two checks, which fail in different ways.

`tools/verify.py` reads every compilation back out of git and compares
it word for word with the Register's own Word document, through a second
extractor written a different way from the one the build uses, so a bug
in the build shows up as a mismatch rather than being reproduced
identically on both sides. The release bar is zero mismatches.

That is not enough on its own. Both extractors drop the same things --
the contents, the page furniture, the endnotes -- so neither can report
a provision that both of them skipped: the comparison comes back clean
and the provision is simply absent. `tools/completeness.py` checks that
against the one part of the document the build never reads. The
compilation's own table of contents names every provision it holds, so
any number listed there whose text is nowhere in the tree is a gap. (A
prescribed Schedule written as a flat run of numbered items is filed as
one file for the whole Schedule, so the check looks for the item there
before calling it missing.) That check exists
because this build had such a gap: about five hundred paragraphs of the
ACCC's prescribed notification forms, which are whole Divisions of law
written with no section heading beneath them, and the word-for-word
comparison was clean the whole time they were missing.

[REPRODUCE.md](REPRODUCE.md) carries both results, the counts and the
software versions.

Builds are deterministic: the same cache and the same `--today` give
the same commit hashes.

## Licence

Law text under CC BY 4.0, code under Apache-2.0. The Register's
required attribution and the full list of changes made to the text are
in [LICENSE](LICENSE). This is a derived copy and not a substitute for
the Register, which is authoritative.
