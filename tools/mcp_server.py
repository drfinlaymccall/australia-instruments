"""Point-in-time lookup over the Australian legislative instruments corpus.

A deal asks a question ordinary legal search answers badly: not "what
does this say?" but "what did this say on the day we signed, and who
has changed it since?". The corpus is a git history in which every
commit is one amending instrument taking effect, so both questions are
a git command. This server makes them tools.

Nothing here reaches the network. It reads this repository, or whatever
clone or build of it AU_INSTRUMENTS_CORPUS names.

Speaks newline-delimited JSON-RPC over stdio.
"""

import datetime
import json
import os
import re
import subprocess
import sys

# Shipped inside the corpus it reads, so the repository above this file is
# the default. A plugin that wires the server into someone's working folder
# points AU_INSTRUMENTS_CORPUS at their clone instead.
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORPUS = os.environ.get("AU_INSTRUMENTS_CORPUS") or HERE
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER = {"name": "au-instruments", "version": "0.1.0"}
INSTRUCTIONS = (
    "Australian Commonwealth legislative instruments as a point-in-time "
    "record: foreign investment screening, merger notification and "
    "takeovers. Every answer is the text in force on the date asked for, "
    "with the instrument that last changed it. This is source material "
    "for advice, not advice."
)
MAX_CHARS = 40_000


class Problem(Exception):
    pass


def git(*args, check=True):
    if not CORPUS or not os.path.isdir(os.path.join(CORPUS, ".git")):
        raise Problem(
            "No corpus. Set AU_INSTRUMENTS_CORPUS to a clone of "
            "australia-instruments; it is currently %r."
            % (CORPUS or "unset"))
    done = subprocess.run(["git", "-C", CORPUS] + list(args),
                          capture_output=True, text=True, timeout=60)
    if check and done.returncode != 0:
        raise Problem("git %s failed: %s" % (" ".join(args), done.stderr.strip()))
    return done.stdout


def instruments():
    """Folder name -> instrument title, from the corpus itself."""
    out = {}
    for line in git("ls-tree", "--name-only", "HEAD", "corpus/").splitlines():
        folder = line.rstrip("/").split("/")[-1]
        if not folder:
            continue
        intro = git("show", "HEAD:corpus/%s/intro.md" % folder, check=False)
        title = intro.splitlines()[0].lstrip("# ").strip() if intro else folder
        out[folder] = title
    return out


def resolve_instrument(name):
    """Match a folder, a register id or part of a title to one instrument."""
    known = instruments()
    if name in known:
        return name
    wanted = re.sub(r"[^a-z0-9]+", "", (name or "").lower())
    if not wanted:
        raise Problem("Name an instrument. Known: %s" % ", ".join(sorted(known)))
    hits = [f for f, title in known.items()
            if wanted in re.sub(r"[^a-z0-9]+", "", f + title.lower())]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise Problem("No instrument matches %r. Known: %s"
                      % (name, ", ".join(sorted(known))))
    raise Problem("%r matches more than one: %s" % (name, ", ".join(sorted(hits))))


def tag_on(folder, date):
    """The compilation in force on a date: the latest tag at or before it."""
    tags = sorted(t for t in git("tag", "-l", "%s/*" % folder).split()
                  if t.rsplit("/", 1)[1] <= date)
    if not tags:
        first = sorted(git("tag", "-l", "%s/*" % folder).split())
        raise Problem(
            "The record for %s starts %s; nothing was recorded on %s."
            % (folder, first[0].rsplit("/", 1)[1] if first else "(never)", date))
    return tags[-1]


def provision_path(folder, provision):
    """Accept '52', 's 52', 'section 52', '6.10.01', 'reg 6.10.01', '1-9',
    and a container unit as the corpus names it ('part-6/div-2', or the
    file name itself). A container unit is law text that sits under a Part
    or Division with no section heading of its own -- the reproduced ACCC
    forms are whole Divisions written that way."""
    raw = (provision or "").strip()
    if raw.endswith(".md"):
        return raw
    if "/" in raw:
        return raw + ".md"
    number = re.sub(r"^(?:sections?|ss?\.?|regulations?|regs?\.?|r\.?|clause|cl\.?)\s*",
                    "", raw, flags=re.I).strip()
    if not number:
        raise Problem("Name a provision, such as '52' or '6.10.01'.")
    if "." in number:
        return "r-%s.md" % number
    if "-" in number:
        return "s-%s.md" % number
    match = re.match(r"^(\d+)(.*)$", number)
    return "s-%s.md" % (match.group(1).zfill(3) + match.group(2) if match else number)


def by_heading(folder, tag, phrase):
    """The provision whose heading contains this phrase, at this compilation.

    A provision is often known by its heading rather than its number -- the
    definition that decides whether a fund is a foreign government investor
    is section 17, which nobody remembers -- so a phrase is a reasonable
    thing to ask for. One match is the answer; several is a question back,
    because guessing between them would quote the wrong provision.
    """
    hits = []
    for line in git("ls-tree", "-r", "--name-only", tag,
                    "corpus/%s/" % folder).splitlines():
        if not line.endswith(".md"):
            continue
        name = line.split("corpus/%s/" % folder, 1)[-1]
        head = next((l for l in git("show", "%s:%s" % (tag, line),
                                    check=False).splitlines()
                     if l.startswith("# ")), "")
        if phrase.lower() in head[2:].lower():
            hits.append((name, head[2:].strip()))
    if len(hits) == 1:
        return hits[0][0]
    if not hits:
        return None
    raise Problem(
        "%r matches %d provisions in the compilation in force then: %s. "
        "Ask for one by number." % (phrase, len(hits),
                                    "; ".join("%s (%s)" % (n, h) for n, h in hits)))


def record_caveat(folder, date, compiled_from):
    """What to say about how well the record covers this date.

    Two different things can make an answer weaker than it looks. The
    compilations the register publishes only as legacy .doc or .rtf are not
    in the corpus, and for the Corporations Regulations they are scattered
    through the first eleven years rather than sitting in a block at the
    start -- so a date in that range resolves to the last committed day
    before it and can miss an amendment entirely. Separately, even where the
    record is continuous, a date between two compilations resolves to the
    earlier one, which is correct but worth stating when the gap is wide.
    """
    notes = []
    try:
        record = json.loads(git("show", "HEAD:corpus.json"))
    except Exception:                                        # noqa: BLE001
        notes.append("The corpus clone has no corpus.json at HEAD, so how "
                     "completely it covers this date could not be checked.")
        record = None
    if record:
        entry = next((i for i in record.get("instruments", [])
                      if i.get("folder") == folder), None)
        whole = (entry or {}).get("no_gaps_from")
        if whole and date < whole:
            notes.append(
                "The record of this instrument is not continuous before %s: "
                "the register publishes some compilations only as legacy .doc "
                "or .rtf and those are not in the corpus. An amendment in "
                "force on %s may be missing entirely. Check the register "
                "before relying on this." % (whole, date))
    try:
        gap = (datetime.date.fromisoformat(date)
               - datetime.date.fromisoformat(compiled_from)).days
    except ValueError:
        gap = None
    if gap is not None and gap > 90:
        notes.append(
            "The compilation used took effect %s, %d days before the date "
            "asked about. That is the text in force unless an amendment "
            "between the two is not yet compiled." % (compiled_from, gap))
    return notes


def last_change(folder, path, tag):
    """The commit that last touched a provision at or before a tag."""
    out = git("log", "-1", "--format=%H%n%an%n%ad%n%B", "--date=short",
              tag, "--", "corpus/%s/%s" % (folder, path), check=False)
    if not out.strip():
        return None
    sha, author, date, body = (out.split("\n", 3) + ["", "", "", ""])[:4]
    trailers = dict(re.findall(r"^([A-Za-z-]+): (.*)$", body, re.M))
    return {"commit": sha[:12], "amending_instrument": author, "in_force": date,
            "compilation": trailers.get("Compilation"),
            "compilation_id": trailers.get("Compilation-id"),
            "kind": trailers.get("Kind")}


# --- tools ---------------------------------------------------------------

def t_provision_on_date(args):
    folder = resolve_instrument(args.get("instrument", ""))
    date = date_arg(args.get("date"))
    asked = (args.get("provision") or "").strip()
    path = provision_path(folder, asked)
    tag = tag_on(folder, date)
    text = git("show", "%s:corpus/%s/%s" % (tag, folder, path), check=False)
    if not text.strip() and " " in asked:
        found = by_heading(folder, tag, asked)
        if found:
            path = found
            text = git("show", "%s:corpus/%s/%s" % (tag, folder, path),
                       check=False)
    if not text.strip():
        raise Problem(
            "%s has no %s in the compilation in force on %s (%s). Use "
            "instrument_on_date to list what it did have, or find_in_law "
            "to search the words."
            % (folder, "%r in any heading" % asked if " " in asked else path,
               date, tag.rsplit("/", 1)[1]))
    compiled_from = tag.rsplit("/", 1)[1]
    out = {"instrument": folder, "provision": path, "date": date,
           "compilation_in_force_from": compiled_from,
           "last_changed_by": last_change(folder, path, tag),
           "text": text[:MAX_CHARS]}
    caveats = record_caveat(folder, date, compiled_from)
    if caveats:
        out["caveats"] = caveats
    return out


def t_instrument_on_date(args):
    folder = resolve_instrument(args.get("instrument", ""))
    date = date_arg(args.get("date"))
    tag = tag_on(folder, date)
    names = [n.split("/", 2)[2] for n in
             git("ls-tree", "-r", "--name-only", tag, "corpus/%s/" % folder).splitlines()
             if n.endswith(".md")]
    headings = {}
    for name in names:
        if name == "intro.md":
            continue
        blob = git("show", "%s:corpus/%s/%s" % (tag, folder, name), check=False)
        line = next((l for l in blob.splitlines() if l.startswith("# ")), "")
        headings[name] = line[2:].strip()
    compiled_from = tag.rsplit("/", 1)[1]
    out = {"instrument": folder, "date": date,
           "compilation_in_force_from": compiled_from,
           "provisions": headings, "count": len(headings)}
    caveats = record_caveat(folder, date, compiled_from)
    if caveats:
        out["caveats"] = caveats
    return out


def t_what_changed(args):
    folder = resolve_instrument(args.get("instrument", ""))
    since, until = date_arg(args.get("since")), date_arg(args.get("until"))
    if since > until:
        raise Problem("'since' is after 'until'.")
    scope = ["--", "corpus/%s/" % folder]
    if args.get("provision"):
        scope = ["--", "corpus/%s/%s" % (folder, provision_path(folder, args["provision"]))]
    out = git("log", "--reverse", "--format=%x00%H%n%an%n%ad%n%B", "--date=short",
              "--since=%s" % since, "--until=%s 23:59" % until, *scope)
    changes = []
    for block in out.split("\x00"):
        if not block.strip():
            continue
        sha, author, date, body = (block.split("\n", 3) + ["", "", "", ""])[:4]
        trailers = re.findall(r"^Affecting: (.*)$", body, re.M)
        kind = re.search(r"^Kind: (.*)$", body, re.M)
        changes.append({"commit": sha[:12], "amending_instrument": author.strip(),
                        "in_force": date.strip(),
                        "kind": kind.group(1) if kind else None,
                        "provisions_affected": trailers})
    return {"instrument": folder, "since": since, "until": until,
            "changes": changes, "count": len(changes)}


def t_find_in_law(args):
    query = (args.get("query") or "").strip()
    if len(query) < 3:
        raise Problem("Give at least three characters to search for.")
    date = date_arg(args.get("date"))
    folders = ([resolve_instrument(args["instrument"])] if args.get("instrument")
               else sorted(instruments()))
    hits = []
    for folder in folders:
        try:
            tag = tag_on(folder, date)
        except Problem:
            continue
        out = git("grep", "-n", "-i", "-F", "-e", query, tag,
                  "--", "corpus/%s/" % folder, check=False)
        for line in out.splitlines()[:40]:
            _ref, _, rest = line.partition(":corpus/%s/" % folder)
            name, _, body = rest.partition(":")
            hits.append({"instrument": folder, "provision": name,
                         "line": body.partition(":")[2].strip()[:300]})
    return {"query": query, "date": date, "hits": hits[:60], "count": len(hits)}


def date_arg(value):
    text = (value or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        raise Problem("Give a date as YYYY-MM-DD (the day the question is "
                      "about, such as the day a deal signed).")
    return text


TOOLS = [
    ("provision_on_date", t_provision_on_date,
     "The text of one provision as it stood on a date, with the instrument "
     "that last changed it. Use this instead of quoting a provision from "
     "memory: the wording of a threshold or an exemption is often what the "
     "question turns on, and it changes.",
     {"instrument": "Instrument: a folder name, a register id, or part of "
                    "the title (e.g. 'foreign acquisitions').",
      "provision": "Provision number: '52', 'section 52', '6.10.01', "
                   "'reg 6.10.01', '1-9'. A container unit as the corpus "
                   "names it ('part-6/div-2') also works, as does a phrase "
                   "from the provision's heading when it matches only one.",
      "date": "YYYY-MM-DD. The day the question is about."},
     ["instrument", "provision", "date"], "Read a provision on a date"),
    ("instrument_on_date", t_instrument_on_date,
     "Every provision an instrument had on a date, with its heading. Use it "
     "to see what existed then, before asking for any one provision. An "
     "instrument as large as the Corporations Regulations lists more than "
     "the reply holds, and comes back trimmed with a count of what was "
     "left out; reach those provisions with find_in_law instead.",
     {"instrument": "Instrument name, register id, or part of the title.",
      "date": "YYYY-MM-DD."},
     ["instrument", "date"], "List an instrument's provisions on a date"),
    ("what_changed", t_what_changed,
     "Every amendment to an instrument between two dates, each with the "
     "amending instrument that made it and the provisions it touched. Use "
     "it to answer 'what has moved since we signed?'.",
     {"instrument": "Instrument name, register id, or part of the title.",
      "since": "YYYY-MM-DD, inclusive.",
      "until": "YYYY-MM-DD, inclusive.",
      "provision": "Optional: narrow to one provision."},
     ["instrument", "since", "until"], "What changed between two dates"),
    ("find_in_law", t_find_in_law,
     "Find a phrase in the instruments as they stood on a date. Returns the "
     "provisions it appears in, so they can then be read in full.",
     {"query": "A literal phrase, such as 'foreign government investor'.",
      "date": "YYYY-MM-DD.",
      "instrument": "Optional: one instrument instead of all."},
     ["query", "date"], "Find a phrase in the law"),
]


def tool_list():
    out = []
    for name, _fn, description, properties, required, title in TOOLS:
        out.append({
            "name": name, "title": title, "description": description,
            "inputSchema": {
                "type": "object", "additionalProperties": False,
                "properties": {k: {"type": "string", "description": v}
                               for k, v in properties.items()},
                "required": required},
            # Every tool reads git and nothing else: it writes nothing, and
            # reaches no network. Clients and Anthropic's connector directory
            # both read these to decide what may run without asking.
            "annotations": {"title": title, "readOnlyHint": True,
                            "idempotentHint": True, "openWorldHint": False}})
    return out


def fit(result):
    """Serialise a result for the text channel, still valid JSON.

    Cutting the serialised text at a character count leaves a string
    unterminated, so a client reading it gets a parse error instead of a
    long answer. Listing every provision of the Corporations Regulations
    overran every time. The trimming therefore happens to the data, which
    can say what it dropped; structuredContent still carries the whole
    result for a client that reads that instead.
    """
    text = json.dumps(result, indent=1, ensure_ascii=False)
    if len(text) <= MAX_CHARS:
        return text
    shown, omitted = dict(result), {}
    while len(text) > MAX_CHARS:
        sizes = {k: len(json.dumps(v, ensure_ascii=False))
                 for k, v in shown.items()
                 if k not in ("omitted", "omitted_note")
                 and isinstance(v, (dict, list, str)) and len(v) > 1}
        if not sizes:
            break                     # only short scalars left: send it long
        key = max(sizes, key=sizes.get)
        value = shown[key]
        over = len(text) - MAX_CHARS + 64
        if isinstance(value, str):
            keep = max(1, len(value) - over)
        else:
            keep = max(1, int(len(value) * (1 - min(0.9, over / sizes[key]))))
        shown[key] = (dict(list(value.items())[:keep]) if isinstance(value, dict)
                      else value[:keep])
        omitted[key] = omitted.get(key, 0) + len(value) - keep
        shown["omitted"] = omitted
        shown["omitted_note"] = (
            "Trimmed to fit one reply. Ask for a provision by name, or use "
            "find_in_law, rather than reading the whole instrument.")
        text = json.dumps(shown, indent=1, ensure_ascii=False)
    return text


def handle(message):
    mid = message.get("id")
    method = message.get("method")
    params = message.get("params") or {}
    if method == "initialize":
        asked = params.get("protocolVersion")
        return ok(mid, {
            "protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
            "capabilities": {"tools": {}}, "serverInfo": SERVER,
            "instructions": INSTRUCTIONS})
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None
    if method == "tools/list":
        return ok(mid, {"tools": tool_list()})
    if method == "tools/call":
        name = params.get("name")
        entry = next((t for t in TOOLS if t[0] == name), None)
        if entry is None:
            return ok(mid, {"content": [{"type": "text",
                                         "text": "No tool named %r." % name}],
                            "isError": True})
        try:
            result = entry[1](params.get("arguments") or {})
        except Problem as problem:
            return ok(mid, {"content": [{"type": "text", "text": str(problem)}],
                            "isError": True})
        except Exception as error:                       # noqa: BLE001
            return ok(mid, {"content": [{"type": "text",
                                         "text": "%s: %s" % (type(error).__name__, error)}],
                            "isError": True})
        return ok(mid, {"content": [{"type": "text", "text": fit(result)}],
                        "structuredContent": result})
    if mid is None:
        return None
    return {"jsonrpc": "2.0", "id": mid,
            "error": {"code": -32601, "message": "Method not found: %s" % method}}


def ok(mid, result):
    return None if mid is None else {"jsonrpc": "2.0", "id": mid, "result": result}


def main():
    for raw in sys.stdin:
        if not raw.strip():
            continue
        try:
            message = json.loads(raw)
        except ValueError:
            reply = {"jsonrpc": "2.0", "id": None,
                     "error": {"code": -32700, "message": "Parse error"}}
        else:
            reply = handle(message)
        if reply is not None:
            sys.stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
