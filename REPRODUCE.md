# Reproducing this corpus

Everything below was produced by the commands in this file, on the
machine and software named at the end. The numbers are generated from
the build and verification reports rather than typed, so they cannot
drift from what actually ran.

## Sources

All text comes from the Federal Register of Legislation.

- **Metadata** (which compilations exist, when each took effect, and
  which instrument amended it): the Register's OData API at
  `https://api.prod.legislation.gov.au/v1`, entity sets `Titles`,
  `Versions` and `Documents`.
- **Text**: the Word (`.docx`) file the Register publishes for each
  compilation, from `https://www.legislation.gov.au`, under
  `/{id}/{date}/{date}/text/{original|latest}/word[/{volume}]`.

The Register's `robots.txt` asks for ten seconds between requests, and
`tools/fetch.py` enforces that with a timestamp on disk, so the delay
holds across separate runs as well as within one. Every response is
cached with its URL, its sha256 and the time it was retrieved, in
`cache/index.json`, and nothing already cached is fetched again.

The clock is stamped immediately before a request is sent, so request
*starts* are at least ten seconds apart. The `fetched_at` time in the
index is written when the body has arrived, so differencing consecutive
`fetched_at` values measures ten seconds plus the difference between
two download times, and a small fast document after a large slow one
shows a gap under ten seconds. Those gaps are an artefact of the
timestamp, not a breach of the delay; the documents here run from about
80 KB to 280 KB.

Only the instruments named below were fetched. The Register asks to be
contacted before a full crawl, and no crawl beyond this list was made.

## Commands

```bash
python3 tools/fetch_all.py                     # download
python3 tools/build.py  --today 2026-10-31 --report build-report.json
python3 tools/verify.py --today 2026-10-31 --report verify-report.json
python3 tools/completeness.py --today 2026-10-31 --report completeness-report.json
python3 tools/report.py                        # regenerate this file
```

`--today` is what divides the record: compilations starting after it go
to the `future` branch, and `main` holds only what is in force. Passing
the same `--today` against the same cache gives the same commit hashes.

Every instrument here sunsets. A sunsetting repeal under s 50 of the
Legislation Act 2003, and a self-repeal, carry no compiled text at all --
the register records the version with no document -- so the repeal is
committed on `future` as the removal of the instrument's files, with
`Kind: Repeal`. Checking out `future` therefore answers what will still
exist on a date, which is the question a longstop clause turns on.

## What was built

| Instrument | Register ID | Versions | Commits | Span | No gaps from | Verification |
| --- | --- | --- | --- | --- | --- | --- |
| Foreign Acquisitions and Takeovers Regulation 2015 | `F2015L01854` | 21 | 21 | 2015-11-27 to 2025-11-01 | throughout | 21 checked, 0 mismatches |
| Competition and Consumer (Notification of Acquisitions) Determination 2025 | `F2025L00753` | 3 | 3 | 2025-06-30 to 2035-10-01 | throughout | 2 checked, 0 mismatches |
| Competition and Consumer (Notification of Acquisitions—Forms) Determination 2025 | `F2025L01604` | 2 | 2 | 2025-12-18 to 2036-04-01 | throughout | 1 checked, 0 mismatches |
| ASIC Corporations (Takeover Bids) Instrument 2023/683 | `F2023L01310` | 6 | 5 | 2023-09-27 to 2028-10-01 | throughout | 4 checked, 0 mismatches |
| Corporations Regulations 2001 | `F2001B00274` | 216 | 138 | 2001-07-15 to 2026-09-01 | 2013-03-01 | 138 checked, 0 mismatches |

- **Versions in the register's lists:** 248, which the corpus
  accounts for as 169 commits (166 on `main`,
  3 on `future`), 72 out of scope by format,
  6 the register publishes no text for and 1 with
  no textual change
- **Compilations checked:** 166
- **Compilations with mismatches:** 0
- **Compilations skipped:** 77
- **Compilations outside the readable-format scope:** 0
- **Compilations checked against the official contents:** 166
- **Compilations with a contents entry whose text is nowhere in the tree:** 0
- **Documents downloaded:** 1028 (1309 MB, 1061 cached responses)
- **Retrieved:** 2026-10-30 to 2026-10-30 (UTC; the Register's own dates, and the attribution date in LICENSE, are Canberra time)
- **Tags:** 169
- **HEAD at generation:** `835366ebce43967e5006a5bb7df11849506d64a2`

## How verification works

For every compilation, `tools/verify.py` reads the corpus back **out of
git** at that compilation's tag, and compares it word for word with the
text of the Register's own `.docx`.

The comparison does not reuse the build's parser. `tools/verify.py`
re-reads the Word document with a second extractor written a different
way -- regular expressions over the raw document XML, rather than the
element tree the build walks -- so a bug in the build's extractor
produces a mismatch instead of being reproduced identically on both
sides. That has already earned its keep: it caught the build dropping
`<w:noBreakHyphen/>`, which turns *Governor-General* into
*GovernorGeneral*, and then caught the same omission in itself.

Comparison is by provision number rather than by file, so a renumbered,
missing or duplicated provision is a mismatch and not a silent pass.

**Outside the compared text**, on both sides: the table of contents,
running page headers and footers, and the Register's endnotes (about
the endnotes, abbreviation key, legislation history, amendment
history). Those are the Register's editorial apparatus rather than the
law. The commit history carries the same information.

### The third check: the official contents

Two extractors that agree word for word still share their scope rules.
Both drop the table of contents, the page furniture and the endnotes,
so neither can report a provision that both of them skipped -- the
comparison would be clean and the provision would simply not be there.
That is not hypothetical: an early build of the merger determinations
dropped about five hundred paragraphs of the prescribed notification
forms, because they are whole Divisions of law written with no section
heading beneath them, and the word-for-word comparison was clean on
both sides while they were missing.

`tools/completeness.py` closes that gap with the one part of the
document the build never reads. The compilation's own table of contents
names every provision it holds, so the check is to take the provision
numbers out of the contents, take the provision files out of git, and
report any number the contents list whose text is nowhere in the tree.
A prescribed Schedule written as a flat run of numbered items carries no
heading on its item numbers, so it is one file for the whole Schedule and
the check looks for the item inside that file before calling it missing.
Schedule 10B of the Corporations Regulations set out the contents of a
Product Disclosure Statement that way, from 2002 until its repeal on
2015-07-01. The check shares the build's character handling on purpose --
hyphenation and whitespace are already covered twice over -- and what is
independent is which paragraphs count as provisions: contents entries
here, drafting styles there.

## What is not verified

- **Days between compilations.** Where the Register dates a change
  between two compilations, its text is carried on the later
  compilation's commit. Only compilation days are checked against
  official text.
- **Attribution.** A commit's author comes from the Register's own
  `reasons` record for that version. Where that names more than one
  instrument, the commit is authored `Federal Register of Legislation`
  and says so in an `Attribution:` trailer. No attribution is inferred.
- **Compilations the register publishes only as legacy `.doc` or
  `.rtf`.** Those formats need a converter, and text that has been
  through a converter can no longer be compared word for word with the
  document the register publishes, so they are out of scope rather than
  silently converted. Which compilations this affects is listed per
  instrument in `corpus.json`, and the span each instrument's history
  actually covers is in the table above.
- **Versions the register publishes no text for.** A future amendment
  is recorded in the version list before its compilation is published,
  so there is nothing to commit and nothing to check. Those versions
  are listed below rather than passed over.
  - `corporations-regulations-2001` at 2002-02-21 (on `main`)
  - `corporations-regulations-2001` at 2002-06-27 (on `main`)
  - `corporations-regulations-2001` at 2004-03-11 (on `main`)
  - `corporations-regulations-2001` at 2004-12-23 (on `main`)
  - `corporations-regulations-2001` at 2011-04-13 (on `main`)
  - `corporations-regulations-2001` at 2027-01-01 (on `future`)
- **Versions whose text is identical to the version before them.** The
  register lists the version; there is nothing to commit, so there is no
  tag of its own to check. The law on that day is the text of the tag
  before it.
  - `asic-corporations-takeover-bids-instrument-2023-683` at 2033-10-01 (on `future`)
- **The endnotes**, which are not in the corpus.
- **Whether a compilation is the whole law.** A compiled instrument
  does not include uncommenced amendments, and the Register marks those
  separately.

## Software

- Python 3.12.3 (CPython), standard library only
- git 2.43.0
- Linux-6.8.0-147-generic-x86_64-with-glibc2.39

No third-party Python packages are used, by design: the `.docx` files
are read with `zipfile` and `xml.etree.ElementTree`, so there is no
dependency whose version could change the output.

Generated by `tools/report.py` for `--today 2026-10-31`, from the build
and check reports named above.
