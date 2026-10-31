"""Check every provision the official contents list against the corpus.

verify.py compares the corpus with the text of the same `.docx`, word for
word, through a second extractor written separately from the first. That
catches a provision one of them reads differently. It cannot catch a
provision both of them skip, because they share their scope rules: both
drop the table of contents, the page furniture and the register's
endnotes, and two extractors that agree about what to ignore will agree
about a hole in it.

The compilation's own table of contents is the independent opinion. It is
the one part of the document the build never reads, and it names every
provision the compilation holds. So the check is: for each compilation,
take the provision numbers out of the contents, take the provision files
out of git, and report any number the contents list that has no file.

Character handling is deliberately shared with the build (docx_text):
hyphenation and whitespace are already covered by verify.py's second
extractor, and reimplementing them here would only find the same bugs
twice. What is independent is which paragraphs count as provisions --
contents entries here, drafting styles there.

    python3 -I tools/completeness.py --today 2026-10-31
"""

import io
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import docx_text                                        # noqa: E402
import fetch                                            # noqa: E402
import build as build_mod                               # noqa: E402
import parse as parse_mod                               # noqa: E402
import register                                         # noqa: E402
import verify                                           # noqa: E402

W = docx_text.W
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TOC_STYLE = re.compile(r"^TOC\d*$")
# A contents entry reads "<number> <heading> <page>": the number, then the
# tab that Word renders as a leader. Non-greedy so "6-3 Heading" gives
# "6-3" and not the page number with it.
NUMBER = re.compile(r"^([0-9][0-9A-Za-z.\-]*?)\.?\s")
# Containers are headings, not provisions, and have a file only when they
# hold text directly; completeness of those is verify.py's business.
CONTAINER = re.compile(r"^(Chapter|Part|Division|Subdivision|Schedule)\b", re.I)
PROVISION_FILE = re.compile(r"^(?:s-0*|r-|cl-0*)([0-9][0-9A-Za-z.\-]*)\.md$")


def toc_numbers(docx_bytes):
    """{(schedule, number)} for every provision the contents name.

    Schedules are tracked because clause 1 of Schedule 1 and clause 1 of
    Schedule 2 are different law and have different files.
    """
    with zipfile.ZipFile(io.BytesIO(docx_bytes)) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    found, schedule = set(), None
    for paragraph in root.iter(W + "p"):
        style = docx_text.paragraph_style(paragraph) or ""
        text = docx_text.paragraph_text(paragraph)
        if not text:
            continue
        heading = re.match(r"^Schedule\s+([0-9A-Za-z.]+)", text, re.I)
        if heading:
            # Both the contents entry and the schedule itself say this, and
            # either one is enough to put the clauses that follow in scope.
            schedule = heading.group(1).lower().rstrip(".")
            continue
        if CONTAINER.match(text) or not TOC_STYLE.match(style):
            continue
        number = NUMBER.match(text)
        if number:
            found.add((schedule, number.group(1)))
    return found


def corpus_numbers(repo, tag, folder):
    """({(schedule, number)} with a file, {schedule: [container texts]}).

    The second half is what a prescribed schedule or form is filed as. A
    Schedule written as a flat run of numbered items -- Schedule 10B of the
    Corporations Regulations prescribes the contents of a Product Disclosure
    Statement that way -- puts no heading style on its item numbers, so it has
    no per-item file and its text sits in a container file. The contents still
    list every item, so without this the check reports the whole Schedule
    missing when every word of it is there.

    A Schedule can have Parts of its own: Schedule 10A modifies Part 7.9 of
    the Act in seventeen Parts, and item 17.1 is in `sch-10a/part-17.md`, not
    in `sch-10a.md`. So every container file under a Schedule is collected
    against that Schedule, not only the Schedule's own heading file.
    """
    prefix = "corpus/%s/" % folder
    numbers, containers = set(), {}
    for path, text in verify.read_tree(repo, tag, prefix).items():
        inner = path.split(prefix, 1)[-1].split("/")
        schedule = next((s[4:] for s in inner[:-1] if s.startswith("sch-")), None)
        if schedule is None and inner[-1].startswith("sch-"):
            schedule = inner[-1][4:-3]
        number = PROVISION_FILE.match(inner[-1])
        if number:
            numbers.add((schedule, number.group(1)))
        else:
            containers.setdefault(schedule, []).append(text)
    return numbers, containers


def held_in_container(entry, containers):
    """Whether a contents entry with no file of its own is accounted for in a
    container file, by appearing there as a numbered item at a line start."""
    schedule, number = entry
    at_line_start = re.compile(r"^%s[ \t]" % re.escape(number), re.M)
    return any(at_line_start.search(text)
               for text in containers.get(schedule, ()))


def check(title_id, repo, *, today, log=print):
    title = register.title(title_id)
    folder = parse_mod.folder_for(title["name"])
    documents = register.word_documents(title_id)
    checked, gaps, skipped, held = 0, [], [], 0

    for version in register.versions(title_id):
        start = (version.get("start") or "")[:10]
        if start > today:
            continue
        tag = "%s/%s" % (folder, start)
        try:
            verify.git(repo, "rev-parse", "--verify", "-q", tag)
        except RuntimeError:
            skipped.append((start, "no tag"))
            continue
        volumes = sorted((d for d in documents if d.get("start") == version.get("start")),
                         key=lambda d: d.get("volumeNumber") or 0)
        if not volumes:
            skipped.append((start, "no Office Open XML document"))
            continue
        as_made = str(version.get("compilationNumber")) == "0"
        listed = set()
        try:
            for document in volumes:
                listed |= toc_numbers(register.document_bytes(document, as_made=as_made))
        except Exception as error:                               # noqa: BLE001
            skipped.append((start, str(error)))
            continue
        present, containers = corpus_numbers(repo, tag, folder)
        absent = sorted(listed - present)
        in_container = [e for e in absent if held_in_container(e, containers)]
        missing = [e for e in absent if e not in in_container]
        checked += 1
        note = ("" if not in_container else
                "  (%d in a schedule's own file)" % len(in_container))
        if missing:
            gaps.append({"tag": tag, "start": start, "listed": len(listed),
                         "present": len(present),
                         "in_container": len(in_container),
                         "missing": ["/".join(filter(None, m)) for m in missing[:20]],
                         "count": len(missing)})
            log("  GAP %s: %d of %d contents entries have no text anywhere%s"
                % (tag, len(missing), len(listed), note))
        else:
            held += len(in_container)
            log("  ok %s  (%d in the contents, %d provision files)%s"
                % (tag, len(listed), len(present), note))
    return {"title_id": title_id, "folder": folder, "checked": checked,
            "gaps": gaps, "skipped": skipped, "held_in_containers": held}


def main(argv=None):
    import argparse
    import json
    parser = argparse.ArgumentParser()
    parser.add_argument("titles", nargs="*")
    parser.add_argument("--today", required=True)
    parser.add_argument("--repo", default=ROOT)
    parser.add_argument("--report")
    args = parser.parse_args(argv)

    fetch.OFFLINE = True          # a check never reaches the register
    titles = args.titles or build_mod.TIER1
    results = []
    for title_id in titles:
        print(title_id)
        results.append(check(title_id, args.repo, today=args.today))

    checked = sum(r["checked"] for r in results)
    gaps = sum(len(r["gaps"]) for r in results)
    skipped = sum(len(r["skipped"]) for r in results)
    held = sum(r.get("held_in_containers", 0) for r in results)
    print("\n%d compilations checked, %d with contents entries that have no text "
          "anywhere, %d skipped" % (checked, gaps, skipped))
    if held:
        print("%d contents entries are prescribed schedule items, held in the "
              "schedule's own file rather than one file each" % held)
    if args.report:
        with io.open(args.report, "w", encoding="utf-8") as fh:
            json.dump({"today": args.today, "checked": checked, "gaps": gaps,
                       "skipped": skipped, "held_in_containers": held,
                       "instruments": results},
                      fh, indent=1, sort_keys=True)
    return 1 if gaps else 0


if __name__ == "__main__":
    raise SystemExit(main())
