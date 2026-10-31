"""Federal Register of Legislation: the parts of the model this build uses.

The OData service answers entity-set queries with $filter. Keyed access
and navigation properties return 404, so everything here is a filtered
query against Versions or Documents.

Document bytes are not served through OData at all -- `bytes` is always
null in a projection. They come from the public site, under a URL whose
grammar is:

    /{titleId}/asmade/{date}/text/{rectification}/{format}            as made
    /{titleId}/{date}/{date}/text/{rectification}/{format}            compilation
    /{titleId}/{date}/{date}/text/{rectification}/{format}/{volume}   one volume

where {date} is the version's start date and {rectification} is
"original" or, for a rectified document, its rectification version
number. All
three forms were confirmed against the download links the site itself
emits, which is also how the volume segment was found: without it a
multi-volume compilation answers 404, and the Corporations Regulations
run to twelve volumes.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fetch

SITE = "https://www.legislation.gov.au"


def title(title_id):
    rows = fetch.odata("Titles", filter="id eq '%s'" % title_id,
                       label="title %s" % title_id)
    if not rows:
        raise KeyError("no such title: %s" % title_id)
    return rows[0]


def versions(title_id):
    """Every version of a title, oldest first."""
    return fetch.odata("Versions", filter="titleId eq '%s'" % title_id,
                       orderby="start asc", label="versions %s" % title_id)


def documents(title_id):
    """Every document of a title, across all versions and volumes."""
    return fetch.odata("Documents", filter="titleId eq '%s'" % title_id,
                       label="documents %s" % title_id)


#: The register calls three different things "Word". Only Office Open
#: XML is read here: the legacy binary .doc and .rtf formats would need
#: a converter, and text that has been through a converter can no longer
#: be checked word for word against the document the register publishes.
#: What that excludes is reported rather than hidden -- see
#: excluded_documents.
OOXML = {".docx"}


def is_ooxml(document):
    return (document.get("extension") or "").lower() in OOXML


def word_documents(title_id, *, ooxml_only=True):
    """Primary Word documents -- the compiled text, one row per volume.

    Where a compilation has been rectified there is more than one row for
    the same start date; the highest rectificationVersionNumber is the one
    in force, so earlier ones are dropped.
    """
    rows = [d for d in documents(title_id)
            if d.get("format") == "Word" and d.get("type") == "Primary"
            and (is_ooxml(d) or not ooxml_only)]
    best = {}
    for d in rows:
        key = (d.get("start"), d.get("volumeNumber") or 0)
        current = best.get(key)
        if current is None or (d.get("rectificationVersionNumber") or 0) > (
                current.get("rectificationVersionNumber") or 0):
            best[key] = d
    return [best[k] for k in sorted(best, key=lambda k: (k[0] or "", k[1]))]


def excluded_documents(title_id):
    """Primary Word documents this build cannot read, by format.

    These are real compilations on the register; they are simply not
    published in a format that can be read without a converter.
    """
    out = {}
    for d in documents(title_id):
        if d.get("format") != "Word" or d.get("type") != "Primary":
            continue
        if is_ooxml(d):
            continue
        out.setdefault((d.get("extension") or "?").lower(), []).append(
            (d.get("start") or "")[:10])
    return {k: sorted(set(v)) for k, v in out.items()}


def volume_coverage(title_id, version):
    """(readable, total) Word volumes for one version.

    A version where those differ cannot be built: the missing volumes
    hold real provisions, and a partial file set would read as though
    those provisions had been repealed.
    """
    start = version.get("start")
    rows = [d for d in documents(title_id)
            if d.get("format") == "Word" and d.get("type") == "Primary"
            and d.get("start") == start]
    best = {}
    for d in rows:
        key = d.get("volumeNumber") or 0
        if key not in best or (d.get("rectificationVersionNumber") or 0) > (
                best[key].get("rectificationVersionNumber") or 0):
            best[key] = d
    return sum(1 for d in best.values() if is_ooxml(d)), len(best)


def download_url(document, *, as_made):
    """The public-site URL for a document's bytes."""
    date = (document.get("start") or "")[:10]
    spec = "asmade" if as_made else date
    # Fifth segment identifies the rectification: "original" for a
    # document that has never been rectified, and otherwise the
    # rectification version number itself. "latest" is accepted by the
    # site but is not reliable -- for F2023L01310 at 2024-05-15 it
    # serves rectification 0 while the record's current document is
    # rectification 1 -- so the number is used instead. The size check
    # below is what caught that.
    version = document.get("rectificationVersionNumber") or 0
    rect = str(version) if version else "original"
    # A multi-volume compilation carries the volume as a final segment.
    # Volume 0 means the instrument is not split into volumes, and the
    # segment must then be absent.
    volume = document.get("volumeNumber") or 0
    return "%s/%s/%s/%s/text/%s/word%s" % (
        SITE, document["titleId"], spec, date, rect,
        ("/%d" % volume) if volume else "")


def document_bytes(document, *, as_made):
    """The .docx bytes, from cache when present.

    A download that returns HTML is the site's single-page shell, which
    means the URL did not resolve to a file. That is a build error rather
    than a document, so it is raised instead of being written to disk.
    """
    url = download_url(document, as_made=as_made)
    body = fetch.fetch(url, binary=True,
                       label="docx %s %s" % (document["titleId"], (document.get("start") or "")[:10]))
    if body[:4] != b"PK\x03\x04":
        # The site answers an unresolvable document URL with its
        # single-page shell, at HTTP 200. Caching that would poison the
        # cache, which is the unit of reproducibility, so drop it.
        fetch.forget(url)
        raise RuntimeError(
            "%s did not return a .docx (got %r...); the URL grammar may have "
            "changed" % (url, body[:16]))
    expected = document.get("sizeInBytes")
    if expected and len(body) != expected:
        raise RuntimeError(
            "%s returned %d bytes, register says %d" % (url, len(body), expected))
    return body


def is_repeal(version):
    """Whether this version is the instrument ceasing to exist.

    A sunsetting repeal under s 50 of the Legislation Act 2003, or a
    self-repeal, has no compiled text: the register records the version with
    no document at all. That is not a missing document, so a caller can
    commit it as the removal of the instrument rather than skip it. A future
    version whose reasons say "Amend" and which has no document is the other
    case entirely -- the amendment is made but its compilation is not
    published yet -- and must not be treated this way.
    """
    reasons = version.get("reasons") or []
    return bool(reasons) and all(
        (reason.get("affect") or "").lower() == "repeal" for reason in reasons)


def amending_instrument(version):
    """The single instrument a compilation is attributable to, or None.

    The register gives one or more `reasons` per version. Exactly one
    amending title is the attributable case; anything else is left for the
    caller to label, because guessing an author here would put a false
    name in the git history.
    """
    titles = []
    for reason in version.get("reasons") or []:
        for slot in ("affectedByTitle", "amendedByTitle"):
            t = reason.get(slot)
            if t and t.get("titleId"):
                titles.append((t["titleId"], t.get("name") or t["titleId"],
                               reason.get("affect"), t.get("provisions")))
    unique = {t[0]: t for t in titles}
    if len(unique) == 1:
        return next(iter(unique.values()))
    return None
