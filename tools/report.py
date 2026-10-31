"""Write corpus.json and REPRODUCE.md from the build and verify reports.

Both files make factual claims -- how many compilations, how far the
record runs, whether verification passed. Generating them from the
reports rather than writing them by hand means the claims cannot drift
away from what the build and the verifier actually did.
"""

import argparse
import json
import os
import platform
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

REPO_URL = "https://github.com/drfinlaymccall/australia-instruments.git"

# One rule covers both file shapes this corpus uses. Group 1 is the
# folder to search (the instrument), group 2 the provision number, which
# is substituted into "cites" to find references to it.
# The number group takes a hyphen so the compound section numbers of the
# modern Commonwealth style resolve too ("section 1-9" of the merger
# determination, the file s-1-9.md). Schedule clauses are not citable this
# way: "clause 1 of Schedule 1" names two numbers, and one group cannot hold
# both. `cites` runs through `git grep -E`, so it stays POSIX extended --
# no \d, no lookaround.
CITATION = {
    "file": r"([a-z0-9-]+)/(?:s-0*|r-)([0-9][0-9A-Za-z.\-]*)\.md",
    "cites": r"(section|sections|s\.?|regulation|regulations|reg\.?|r\.?) ?{n}([^0-9A-Za-z.]|$)",
}


def git(*args):
    out = subprocess.run(["git", "-C", ROOT] + list(args),
                         capture_output=True, text=True)
    return out.stdout.strip()


def load(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def cache_stats():
    index = load(os.path.join(ROOT, "cache", "index.json"))
    docs = [e for u, e in index.items()
            if "/word" in u and e.get("status") == 200]
    times = sorted(e.get("fetched_at") for e in index.values()
                   if e.get("fetched_at"))
    return {"responses": len(index), "documents": len(docs),
            "bytes": sum(e.get("bytes") or 0 for e in index.values()),
            "first_fetch": times[0] if times else None,
            "last_fetch": times[-1] if times else None}


def complete_from(item):
    """The first day after which the record has no format holes.

    The compilations the register publishes only as legacy `.doc` or `.rtf`
    are not an early block that the record simply starts after: 71 of the
    Corporations Regulations' 72 fall after its first commit, so the record
    before them has gaps scattered through it. The useful date is the first
    committed day with no excluded compilation at or after it, and saying
    "coverage from <first commit>" without it would overstate the record.
    """
    days = sorted(tag.rsplit("/", 1)[1] for tag, _n, scope in item["commits"]
                  if scope == "main")
    if not days:
        return None
    excluded = [o["start"] for o in item["out_of_scope"]]
    if not excluded:
        return days[0]
    last = max(excluded)
    return next((d for d in days if d > last), None)


def build_corpus_json(build, verify, cache, complete):
    starts, ends = [], []
    has_future = False
    for item in build["instruments"]:
        days = sorted(tag.rsplit("/", 1)[1] for tag, _n, scope in item["commits"]
                      if scope == "main")
        has_future = has_future or any(scope == "future"
                                       for _tag, _n, scope in item["commits"])
        if days:
            starts.append(days[0])
            ends.append(days[-1])
    checked = verify["compilations_checked"]
    bad = verify["compilations_with_mismatches"]
    listed = complete.get("checked", 0)
    gaps = complete.get("gaps", 0)
    names = "; ".join("%s (%s)" % (i["name"], i["title_id"])
                      for i in build["instruments"])
    return {
        # `corpus` is the key global-law reads (tools/build.py from_corpus_json)
        # and the only one its preflight treats as required: <iso>/<level>/<name>.
        # The folder the submodule sits at and the manifest entry are both
        # derived from it there, so neither is written here.
        "corpus": "au/federal/instruments",
        "url": REPO_URL,
        "name": "Australian (Commonwealth) legislative instruments: "
                "foreign investment, merger notification and takeovers",
        "label": "Australia (Commonwealth): legislative instruments",
        "language": "en",
        "coverage": "from %s" % min(starts) if starts else "none",
        "history": "replayed",
        "has_future_branch": has_future,
        "history_from": min(starts) if starts else None,
        "record_to": max(ends) if ends else None,
        "checked_on": build["today"],
        "in_force_trailer": "In-force",
        "tool": "tools/build.py",
        "citation": CITATION,
        "instruments": [
            {"register_id": i["title_id"], "name": i["name"],
             "folder": i["folder"], "commits": len(i["commits"]),
             "versions": i["versions"],
             # The day this instrument's record becomes continuous. Before it
             # the register publishes some compilations only as legacy .doc or
             # .rtf, and those days are missing from the history.
             "no_gaps_from": complete_from(i),
             "excluded_compilations": sorted(o["start"] for o in i["out_of_scope"])}
            for i in build["instruments"]],
        "record_note": (
            "%s. Compiled text from the Federal Register of Legislation, "
            "one commit per compilation on the day it took effect, authored "
            "by the amending instrument the register's version record names. "
            "Documents retrieved %s to %s. Only compilation days are in the "
            "record: a change the register dates between two compilations "
            "appears on the later compilation's commit. Compilations the "
            "register publishes only as legacy .doc or .rtf are not in the "
            "record and are not an early block the record starts after; "
            "each instrument's no_gaps_from is the day its record becomes "
            "continuous, and a date before it may resolve to an earlier "
            "committed day."
            % (names, (cache["first_fetch"] or "")[:10],
               (cache["last_fetch"] or "")[:10])),
        "verification": (
            "Verified against official text: every compilation on its "
            "compilation day (%d compilations, %d with mismatches). The "
            "comparison is word for word against the register's own Word "
            "documents, using a second extractor written separately from "
            "the one the build uses. The register's endnotes, the table of "
            "contents and running headers are outside the compared text. "
            "Because both extractors drop the same apparatus, a second "
            "check reads the provision numbers out of each compilation's "
            "own table of contents -- the one part the build never reads -- "
            "and reports any whose text is nowhere in the tree (%d "
            "compilations, %d with such an entry)."
            % (checked, bad, listed, gaps)),
        "scope": {
            "trailer": None,
            "when_absent": "this corpus records no scope notes; the absence "
                           "is not a statement that a change reaches every case",
            "default_reach": {
                "rule": "a legislative instrument takes effect as its "
                        "commencement provision says, and an amendment does "
                        "not disturb what was done before it commenced",
                "meaning": "the Acts Interpretation Act 1901 and the "
                           "Legislation Act 2003 apply to Commonwealth "
                           "instruments; the repeal or amendment of an "
                           "instrument does not affect its previous "
                           "operation or any right or liability already "
                           "acquired or incurred under it, unless a contrary "
                           "intention appears",
                "authority": "Acts Interpretation Act 1901 (Cth) s 7(2); "
                             "Legislation Act 2003 (Cth) Part 2 of Chapter 3; "
                             "not checked in this corpus",
                "decided_here": False,
            },
        },
    }


def reproduce_md(build, verify, cache, corpus, complete):
    # entry["notes"] carries several kinds. Two of them account for versions
    # the register lists that this corpus has no tag for, and the version
    # count in the table below does not add up without them.
    def noted(kind):
        return sorted((i["folder"], n.get("start", ""), n.get("scope", "main"))
                      for i in build["instruments"] for n in i.get("notes", [])
                      if n.get("kind") == kind)
    notext = noted("no-document")
    nopublish = "\n".join("  - `%s` at %s (on `%s`)" % row
                          for row in notext) or "  - None."
    unchanged = noted("no-change")
    nochange = "\n".join("  - `%s` at %s (on `%s`)" % row
                         for row in unchanged) or "  - None."
    rows = []
    for item in build["instruments"]:
        days = sorted(tag.rsplit("/", 1)[1] for tag, _n, _s in item["commits"])
        result = next((r for r in verify["results"]
                       if r["title_id"] == item["title_id"]), {})
        whole = complete_from(item)
        rows.append(
            "| %s | `%s` | %d | %d | %s to %s | %s | %s |"
            % (item["name"], item["title_id"], item["versions"],
               len(item["commits"]), days[0] if days else "-",
               days[-1] if days else "-",
               (whole or "-") if whole != (days[0] if days else None) else "throughout",
               "%d checked, %d mismatches"
               % (result.get("checked", 0), len(result.get("mismatches", [])))))

    # What a rebuild reproduces is the end of the generated history, not
    # HEAD: the tooling, licence and record commits sit on top of it and the
    # build does not write them. Where two instruments have a commit on the
    # same last day, the one with more history behind it is the later.
    main_tags = [tag for i in build["instruments"]
                 for tag, _n, scope in i["commits"] if scope == "main"]
    last_day = max((tag.rsplit("/", 1)[1] for tag in main_tags), default="")
    last = [tag for tag in main_tags if tag.endswith("/" + last_day)]
    tip = (git("rev-parse", "%s^{commit}"
               % max(last, key=lambda t: int(git("rev-list", "--count", t))))
           if last else "-")
    tags = git("tag")
    return """# Reproducing this corpus

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
python3 tools/build.py  --today %(today)s --report build-report.json
python3 tools/verify.py --today %(today)s --report verify-report.json
python3 tools/completeness.py --today %(today)s --report completeness-report.json
python3 tools/report.py                        # regenerate this file
```

Run in a clone, the build finds the history already there and writes
nothing: every file already holds the text it would give it. The two
checks still do their work, against the history that is there. To build
the history again from nothing and compare it, build into an empty
repository:

```bash
git init -q -b main /tmp/rebuild
python3 tools/build.py --repo /tmp/rebuild --today 2026-10-31
git -C /tmp/rebuild rev-parse main   # the commit named below
```

The cache stays where it is: `tools/fetch.py` reads it from beside the
tools rather than from `--repo`, so nothing is downloaded twice.

`tools/build.py --fresh` does the same thing in place, which is how a
release is built. It deletes `main`, `future` and every tag in the
repository it is pointed at, so do not run it in a clone you want to
keep.

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
%(rows)s

- **Versions in the register's lists:** %(versions)d, which the corpus
  accounts for as %(oncommits)d commits (%(onmain)d on `main`,
  %(onfuture)d on `future`), %(outofscope)d out of scope by format,
  %(notext)d the register publishes no text for and %(unchanged)d with
  no textual change
- **Compilations checked:** %(checked)d
- **Compilations with mismatches:** %(bad)d
- **Compilations skipped:** %(skipped)d
- **Compilations outside the readable-format scope:** %(outside)d
- **Compilations checked against the official contents:** %(complete_checked)d
- **Compilations with a contents entry whose text is nowhere in the tree:** %(complete_gaps)d
- **Documents downloaded:** %(documents)d (%(megabytes).0f MB, %(responses)d cached responses)
- **Retrieved:** %(first)s to %(last)s (UTC; the Register's own dates, and the attribution date in LICENSE, are Canberra time)
- **Tags:** %(tagcount)d
- **The generated history ends at:**
  `%(tip)s`. The tooling, licence and record commits sit on top of that;
  the build does not write them, and a rebuild from the same cache
  reproduces that commit.

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
%(nopublish)s
- **Versions whose text is identical to the version before them.** The
  register lists the version; there is nothing to commit, so there is no
  tag of its own to check. The law on that day is the text of the tag
  before it.
%(nochange)s
- **The endnotes**, which are not in the corpus.
- **Whether a compilation is the whole law.** A compiled instrument
  does not include uncommenced amendments, and the Register marks those
  separately.

## Software

- Python %(python)s (%(implementation)s), standard library only
- git %(git)s
- %(platform)s

No third-party Python packages are used, by design: the `.docx` files
are read with `zipfile` and `xml.etree.ElementTree`, so there is no
dependency whose version could change the output.

Generated by `tools/report.py` for `--today %(today)s`, from the build
and check reports named above.
""" % {
        "today": build["today"],
        "rows": "\n".join(rows),
        "checked": verify["compilations_checked"],
        "bad": verify["compilations_with_mismatches"],
        "skipped": verify["skipped"],
        "outside": verify.get("out_of_scope", 0),
        "nopublish": nopublish,
        "notext": len(notext),
        "nochange": nochange,
        "unchanged": len(unchanged),
        "versions": sum(i["versions"] for i in build["instruments"]),
        "oncommits": sum(len(i["commits"]) for i in build["instruments"]),
        "onmain": sum(1 for i in build["instruments"]
                      for c in i["commits"] if c[2] == "main"),
        "onfuture": sum(1 for i in build["instruments"]
                        for c in i["commits"] if c[2] == "future"),
        "outofscope": sum(len(i["out_of_scope"]) for i in build["instruments"]),
        "complete_checked": complete.get("checked", 0),
        "complete_gaps": complete.get("gaps", 0),
        "documents": cache["documents"],
        "megabytes": cache["bytes"] / 1e6,
        "responses": cache["responses"],
        "first": (cache["first_fetch"] or "")[:10],
        "last": (cache["last_fetch"] or "")[:10],
        "tagcount": len(tags.split("\n")) if tags else 0,
        "tip": tip,
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "git": git("--version").replace("git version ", ""),
        "platform": platform.platform(),
    }


def pr_description(build, verify, cache, corpus, complete):
    """The upstream pull request text for lexifina/global-law.

    Generated from the same reports as REPRODUCE.md so the numbers in it
    cannot drift from the numbers that were measured. The brief says to
    draft this and not to open it; nothing here opens anything.
    """
    rows = []
    for item in build["instruments"]:
        main = [c for c in item["commits"] if c[2] == "main"]
        days = sorted(tag.rsplit("/", 1)[1] for tag, _n, scope in main)
        rows.append("| %s | `%s` | %d | %s |"
                    % (item["name"], item["title_id"], len(main),
                       ("%s to %s" % (days[0], days[-1])) if days else "none"))
    checked = verify["compilations_checked"]
    bad = verify["compilations_with_mismatches"]
    listed = complete.get("checked", 0)
    gaps = complete.get("gaps", 0)
    return """\
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
%s

The repo is at %s.
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
Legislation and labelled as such. Commits across the %d instruments interleave
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
one does not hide in the other. **%d compilations checked, %d with
mismatches.** The register's endnotes, tables of contents and running headers
are outside the compared text.

Two extractors that agree word for word still share their scope rules, so
neither can report a provision both of them skipped. A third check reads the
provision numbers out of each compilation's own table of contents -- the one
part of the document the build never reads -- and reports any whose text is
nowhere in the tree. **%d compilations checked against the official contents,
%d with such an entry.** That check is here because this build had exactly that failure:
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
""" % ("\n".join(rows), REPO_URL.removesuffix(".git"),
       len(build["instruments"]), checked, bad, listed, gaps)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", default=os.path.join(ROOT, "build-report.json"))
    parser.add_argument("--verify", default=os.path.join(ROOT, "verify-report.json"))
    parser.add_argument("--completeness",
                        default=os.path.join(ROOT, "completeness-report.json"))
    args = parser.parse_args(argv)

    build, verify = load(args.build), load(args.verify)
    complete = load(args.completeness)
    cache = cache_stats()
    corpus = build_corpus_json(build, verify, cache, complete)
    with open(os.path.join(ROOT, "corpus.json"), "w", encoding="utf-8") as handle:
        json.dump(corpus, handle, indent=2, sort_keys=False)
        handle.write("\n")
    with open(os.path.join(ROOT, "REPRODUCE.md"), "w", encoding="utf-8") as handle:
        handle.write(reproduce_md(build, verify, cache, corpus, complete))
    docs = os.path.join(ROOT, "docs")
    os.makedirs(docs, exist_ok=True)
    with open(os.path.join(docs, "global-law-pr.md"), "w", encoding="utf-8") as handle:
        handle.write(pr_description(build, verify, cache, corpus, complete))
    print("wrote corpus.json, REPRODUCE.md and docs/global-law-pr.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
