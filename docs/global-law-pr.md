# Add Australia's Commonwealth legislative instruments (au/federal/instruments)

## What this adds

A new corpus of Commonwealth legislative instruments -- the regulations,
determinations and ASIC instruments made under the Acts -- sitting beside the
statute book already pinned at `australia/federal/acts`. The instruments carry
the thresholds and the exemptions that the Acts leave to be prescribed, so the
two are read together: the Act says a threshold applies, the instrument says
what it is.

| Instrument | Register ID | Commits | Compilations |
| --- | --- | --- | --- |
| Foreign Acquisitions and Takeovers Regulation 2015 | `F2015L01854` | 21 | 2015-11-27 to 2025-11-01 |
| Competition and Consumer (Notification of Acquisitions) Determination 2025 | `F2025L00753` | 2 | 2025-06-30 to 2026-01-01 |
| Competition and Consumer (Notification of Acquisitions—Forms) Determination 2025 | `F2025L01604` | 1 | 2025-12-18 to 2025-12-18 |
| ASIC Corporations (Takeover Bids) Instrument 2023/683 | `F2023L01310` | 4 | 2023-09-27 to 2024-05-15 |
| Corporations Regulations 2001 | `F2001B00274` | 138 | 2001-07-15 to 2026-09-01 |

The repo is at https://github.com/drfinlaymccall/australia-instruments.
It ships a `corpus.json` declaring `corpus: "au/federal/instruments"`, so
`tools/build.py` places it without a fallback entry. It is not in the `lexifina` organisation, so `discover()` will
not find it from `gh repo list` alone. It needs to be listed under Australia as
a `more_repos` entry in the `countries.json` that `tools/build.py` reads from
`world-law/`, which is not part of the repository, or the repo moved into the
organisation. That is the only change needed outside this diff, and it is one
only a maintainer can make.

## The code change in this PR

`tools/mcp_server.py` learns the dotted regulation citation. The Corporations
Regulations 2001 number their regulations chapter.part.number -- `reg 6.10.01`,
`r 7.1.04`, `regulation 1.0.02` -- and nothing in the existing citation forms
resolves that shape. A plain `reg 15` is deliberately left alone: every other
instrument numbers that way too, so resolving it would need the instrument
named, and guessing would point at the wrong law.

The corpus is located by country code and its own folder name rather than by a
hard-coded path, so it keeps working if the corpus moves.

`tests/test_mcp.py` gains `test_australian_instrument_citation_forms`,
following the shape of `test_malta_citation_forms`. It asserts on the tail of
the resolved path, so it survives the corpus being placed elsewhere.

## History and verification

One commit per compilation, on the day it took effect, authored by the
amending instrument the register's own version record names
(`<Name> (<register ID>)` at `<id>@legislation.invalid`); where the register
names no single amender the commit is authored by the Federal Register of
Legislation and labelled as such. Commits across the 5 instruments interleave
by in-force day, so `main` reads as one timeline and a commit is the state of
the whole corpus at one moment. Each compilation is tagged
`<folder>/<YYYY-MM-DD>`. Versions in force after the build date are on a
`future` branch; `main` holds only what is in force. A sunsetting repeal
carries no compiled text -- the register records the version with no
document at all -- so it is committed as the removal of the instrument,
with `Kind: Repeal`, rather than skipped.

Verification reads every compilation back out of git at its tag and compares
it word for word with text extracted from the register's own `.docx` by a
second extractor written independently of the one the build uses -- the build
walks the XML tree, the checker runs regexes over the raw XML, so a mistake in
one does not hide in the other. **166 compilations checked, 0 with
mismatches.** The register's endnotes, tables of contents and running headers
are outside the compared text.

Two extractors that agree word for word still share their scope rules, so
neither can report a provision both of them skipped. A third check reads the
provision numbers out of each compilation's own table of contents -- the one
part of the document the build never reads -- and reports any whose text is
nowhere in the tree. **166 compilations checked against the official contents,
0 with such an entry.** That check is here because this build had exactly that failure:
about five hundred paragraphs of the ACCC's prescribed notification forms are
whole Divisions written with no section heading beneath them, and the
word-for-word comparison was clean on both sides while they were missing.

Builds are deterministic: the same cache and the same `--today` give the same
commit hashes, verified by building into two separate repositories and
comparing.

## Licensing

The legislative text is CC BY 4.0 from the Federal Register of Legislation,
with the Register's required attribution and a list of the changes made (format
and whitespace only -- no word of the legislative text is added, removed or
altered) in LICENSE. The build tooling is Apache-2.0.

## What is not in it

Only the instruments. The Acts they are made under -- the Foreign Acquisitions
and Takeovers Act 1975, the Competition and Consumer Act 2010, the Corporations
Act 2001 -- are not here, and neither is any tax law. Compilations the register
publishes only as legacy `.doc` or `.rtf` are outside the corpus and are listed
in REPRODUCE.md rather than converted, because converted text cannot be
compared word for word with the published document.
