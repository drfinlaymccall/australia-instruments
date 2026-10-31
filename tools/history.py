"""Replay an instrument's compilations as a git history.

One commit per compilation, dated noon Canberra time on the day it took
effect and authored by the instrument that amended it. The result is a
repository where `git log` on a provision file is that provision's
amendment history, and checking out a tag gives the law as it stood.

The instruments share one history and their commits interleave by the day
each change took force, so `main` reads as one timeline and a commit is the
state of the whole corpus at one moment.

Determinism is a requirement, not a nicety: the same cache and the same
--today must produce the same commit hashes. That holds because every
input to a commit is fixed -- tree, parent, message, and both the author
and committer identity and date.
"""

import os
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import docx_text
import fetch
import parse
import register

CANBERRA = ZoneInfo("Australia/Sydney")


class OutOfScope(Exception):
    """A compilation the register publishes in a format this build does
    not read. A documented boundary of the corpus, not a defect."""

UNATTRIBUTED = ("Federal Register of Legislation",
                "register@legislation.invalid")


def git(repo, *args, **kwargs):
    env = dict(os.environ)
    env.update(kwargs.pop("env", {}))
    result = subprocess.run(["git", "-C", repo] + list(args),
                            capture_output=True, text=True, env=env, **kwargs)
    if result.returncode != 0:
        raise RuntimeError("git %s failed: %s%s"
                           % (" ".join(args), result.stdout, result.stderr))
    return result.stdout.strip()


def noon(date_text):
    """Noon Canberra on a YYYY-MM-DD, as a git date string."""
    year, month, day = (int(p) for p in date_text[:10].split("-"))
    stamp = datetime(year, month, day, 12, 0, 0, tzinfo=CANBERRA)
    return stamp.strftime("%Y-%m-%d %H:%M:%S %z")


def files_for_version(title_id, version, documents, instrument_name,
                      notes=None):
    """The whole file set for one compilation, across all its volumes."""
    start = version.get("start")
    volumes = sorted((d for d in documents if d.get("start") == start),
                     key=lambda d: d.get("volumeNumber") or 0)
    readable, total = register.volume_coverage(title_id, version)
    if total and readable < total:
        # Some volumes of this compilation are legacy .doc or .rtf. Half
        # a compilation is worse than none: the provisions in the
        # missing volumes would read as repealed.
        raise OutOfScope(
            "%d of %d volumes are not Office Open XML" % (total - readable, total))
    if not volumes:
        return None
    as_made = str(version.get("compilationNumber")) == "0"
    merged = {}
    for document in volumes:
        body = register.document_bytes(document, as_made=as_made)
        produced = parse.parse(docx_text.blocks(body),
                               instrument_name=instrument_name, notes=notes)
        for path, text in produced.items():
            if path == "intro.md":
                merged.setdefault(path, text)      # volume 1 carries it
            elif path in merged:
                # A Schedule that runs past the end of a volume continues in
                # the next one. The volumes are read in order, so joining
                # them keeps the compilation's own order.
                merged[path] = merged[path].rstrip() + "\n\n" + text
                if notes is not None:
                    notes.append({"kind": "spans-volumes", "path": path,
                                  "volume": document.get("volumeNumber")})
            else:
                merged[path] = text
    return merged


def commit_message(version, amender, changed, folder):
    """Subject and trailers for one compilation's commit."""
    compilation = version.get("compilationNumber")
    if amender is not None:
        title_id, name, affect, provisions = amender
        subject = name
        kind = affect or "Amend"
    elif str(compilation) == "0":
        subject = "%s as made" % version.get("name")
        kind = "AsMade"
    elif register.is_repeal(version):
        # A self-repeal: the instrument says it repeals itself on a date, so
        # there is no amending instrument to name and the version is not a
        # compilation either.
        subject = "%s repealed" % (version.get("name") or "Instrument")
        kind = "Repeal"
    elif compilation is None:
        # The register records a version with no compilation number of its
        # own. Dating it is the only honest way to name it.
        subject = "Compilation in force %s" % (version.get("start") or "")[:10]
        kind = "Unattributed"
    else:
        subject = "Compilation %s" % compilation
        kind = "Unattributed"

    lines = [subject, ""]
    lines.append("In-force: %s" % (version.get("start") or "")[:10])
    if compilation is not None:
        lines.append("Compilation: %s" % compilation)
    if version.get("registerId"):
        # A repeal has no compilation of its own, so it has no identifier;
        # the trailer is omitted rather than written as "None".
        lines.append("Compilation-id: %s" % version["registerId"])
    for path in sorted(changed):
        lines.append("Affecting: %s" % path)
    lines.append("Kind: %s" % kind)
    if amender is not None and amender[3]:
        lines.append("Amending-provisions: %s" % amender[3])
    if amender is None and str(compilation) != "0" and kind != "Repeal":
        reasons = version.get("reasons") or []
        names = sorted({(r.get("affectedByTitle") or r.get("amendedByTitle") or {})
                        .get("titleId") for r in reasons})
        lines.append("Attribution: not attributable to one instrument (%s)"
                     % (", ".join(n for n in names if n) or "no reason recorded"))
    return "\n".join(lines) + "\n"


def author_for(amender):
    if amender is None:
        return UNATTRIBUTED
    title_id, name, _affect, _provisions = amender
    return ("%s (%s)" % (name, title_id), "%s@legislation.invalid" % title_id)


def write_tree(repo, folder, files):
    """Make corpus/<folder> exactly match `files`. Returns changed paths."""
    base = os.path.join(repo, "corpus", folder)
    existing = set()
    for root, _dirs, names in os.walk(base):
        for name in names:
            existing.add(os.path.relpath(os.path.join(root, name), base))
    changed = set()
    for path, text in files.items():
        target = os.path.join(base, path)
        if path in existing:
            with open(target, "r", encoding="utf-8") as handle:
                if handle.read() == text:
                    continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as handle:
            handle.write(text)
        changed.add(path)
    for path in existing - set(files):
        os.remove(os.path.join(base, path))
        changed.add(path)
    for root, dirs, names in os.walk(base, topdown=False):
        if not names and not os.listdir(root) and root != base:
            os.rmdir(root)
    return changed


def plan(title_id, *, today):
    """What one instrument contributes to the history: its versions split
    into the ones in force by `today` and the ones still to come.

    No git and no parsing happen here, so every instrument can be planned
    before any commit is made and the commits can then be put in the order
    the changes took force."""
    title = register.title(title_id)
    name = title["name"]
    versions = register.versions(title_id)
    current, future = [], []
    for version in versions:
        start = (version.get("start") or "")[:10]
        (future if start > today else current).append(version)
    return {"title_id": title_id, "name": name,
            "folder": parse.folder_for(name),
            "documents": register.word_documents(title_id),
            "versions": versions, "main": current, "future": future,
            "commits": [], "incomplete": [], "out_of_scope": [], "notes": []}


def apply_version(repo, entry, version, scope, log=print):
    """Commit one compilation of one instrument, recording the result on
    `entry`. Stages only that instrument's folder, so the commit says nothing
    about the instruments beside it in the tree."""
    title_id, name, folder = entry["title_id"], entry["name"], entry["folder"]
    start = (version.get("start") or "")[:10]
    version_notes = []
    try:
        files = files_for_version(title_id, version, entry["documents"], name,
                                  notes=version_notes)
    except OutOfScope as reason:
        entry["out_of_scope"].append({"start": start,
                                      "compilation": version.get("compilationNumber"),
                                      "reason": str(reason)})
        return
    except Exception as error:            # noqa: BLE001
        # A compilation that cannot be read is a hole in the history. Record
        # it and carry on, so one bad document does not hide the state of the
        # rest; build.py refuses to call the corpus complete while any hole
        # remains.
        entry["incomplete"].append({"start": start,
                                    "compilation": version.get("compilationNumber"),
                                    "error": str(error)})
        log("    %s %s: INCOMPLETE -- %s" % (title_id, start, error))
        return
    if files is None:
        if register.is_repeal(version):
            # The instrument ceases to exist. There is no compiled text to
            # commit, and the removal of its files is what the law did.
            files = {}
        else:
            # A version the register has not published text for -- a future
            # amendment whose compilation is not out yet. Recorded rather
            # than silently passed over.
            entry["notes"].append({"kind": "no-document", "start": start,
                                   "scope": scope})
            log("    %s %s: no Word document, skipped" % (title_id, start))
            return
    changed = write_tree(repo, folder, files)
    if not changed:
        # The register lists a version whose text is identical to the one
        # before it. There is nothing to commit, so there is no tag either,
        # and the law on that day is the text of the tag before it. Recorded
        # so that the version count in REPRODUCE.md adds up.
        entry["notes"].append({"kind": "no-change", "start": start,
                               "scope": scope})
        log("    %s %s: no textual change, no commit" % (title_id, start))
        return
    amender = register.amending_instrument(version)
    author_name, author_email = author_for(amender)
    message = commit_message(version, amender, changed, folder)
    when = noon(version.get("start"))
    git(repo, "add", "-A", os.path.join("corpus", folder))
    git(repo, "commit", "-q", "--no-verify", "-m", message,
        env={"GIT_AUTHOR_NAME": author_name,
             "GIT_AUTHOR_EMAIL": author_email,
             "GIT_AUTHOR_DATE": when,
             "GIT_COMMITTER_NAME": author_name,
             "GIT_COMMITTER_EMAIL": author_email,
             "GIT_COMMITTER_DATE": when})
    tag = "%s/%s" % (folder, start)
    git(repo, "tag", "-f", tag)
    entry["commits"].append((tag, len(changed), scope))
    for note in version_notes:
        entry["notes"].append(dict(note, start=start))
    log("    %s  %-4s %3d files  %s  %s"
        % (start, version.get("compilationNumber"), len(changed), scope, folder))


def summarise(entry):
    """The per-instrument record build.py and report.py read."""
    excluded = {}
    if entry.get("planned", True):
        excluded = {k: len(v) for k, v in
                    register.excluded_documents(entry["title_id"]).items()}
    return {"title_id": entry["title_id"], "name": entry["name"],
            "folder": entry["folder"], "commits": entry["commits"],
            "versions": len(entry["versions"]),
            "incomplete": entry["incomplete"],
            "out_of_scope": entry["out_of_scope"],
            "notes": entry.get("notes", []),
            "excluded_formats": excluded}


def replay_all(repo, title_ids, *, today, log=print):
    """Commit every compilation of every instrument, in the order the changes
    took force. Returns one summary per instrument.

    The instruments share one history, so their commits interleave. Replaying
    each instrument to its end before starting the next would put 2023 after
    2026: the history would no longer read as a timeline, and global-law's
    preflight rejects a corpus whose main is out of in-force order. Ordering
    is by in-force day, then by the order the instruments were asked for, so
    the same cache and the same --today give the same commits every time.
    """
    plans = []
    for title_id in title_ids:
        try:
            plans.append(plan(title_id, today=today))
        except fetch.CacheMiss as miss:
            # Nothing of this instrument is cached, so it has no versions to
            # order against the others. A hole, not a skip: the completeness
            # gate has to see it.
            log("  %s: INCOMPLETE -- %s" % (title_id, miss))
            plans.append({"title_id": title_id, "name": title_id, "folder": "",
                          "documents": [], "versions": [], "main": [], "future": [],
                          "commits": [], "out_of_scope": [], "notes": [],
                          "planned": False,
                          "incomplete": [{"start": None, "compilation": None,
                                          "error": str(miss)}]})
    for scope in ("main", "future"):
        steps = sorted((((version.get("start") or "")[:10], rank, order), entry, version)
                       for rank, entry in enumerate(plans)
                       for order, version in enumerate(entry[scope]))
        if not steps:
            continue
        if scope == "future":
            git(repo, "checkout", "-q", "-B", "future")
        for _key, entry, version in steps:
            apply_version(repo, entry, version, scope, log=log)
        if scope == "future":
            git(repo, "checkout", "-q", "main")
    return [summarise(entry) for entry in plans]


def replay(repo, title_id, *, today, log=print):
    """One instrument on its own. Kept for building or checking a single
    instrument; a release goes through replay_all, which orders the whole
    corpus by in-force day."""
    return replay_all(repo, [title_id], today=today, log=log)[0]
