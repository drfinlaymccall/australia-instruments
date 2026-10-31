"""Cache-first fetcher for the Federal Register of Legislation API.

Every network request goes through here so that two rules hold by
construction rather than by discipline:

  * at least CRAWL_DELAY seconds pass between requests (robots.txt), and
  * nothing already in the cache is fetched twice.

The cache is the unit of reproducibility. A build run against the same
cache produces the same corpus, so the cache index records the URL, the
sha256 of the body and the time of retrieval for every object.
"""

import contextlib
import fcntl
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.prod.legislation.gov.au/v1"
CRAWL_DELAY = 10.0
USER_AGENT = (
    "australia-instruments/0.1 (legislative corpus builder; "
    "+https://github.com/drfinlaymccall/australia-instruments)"
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "cache")
BLOBS = os.path.join(CACHE, "blobs")
INDEX = os.path.join(CACHE, "index.json")
CLOCK = os.path.join(CACHE, ".last-request")
LOCK = os.path.join(CACHE, ".fetch-lock")


@contextlib.contextmanager
def sole_fetcher():
    """Hold the cache against a second fetcher.

    The index is a whole file, rewritten after every download. Two fetchers
    read it, each adds its own entry and each writes the whole thing back, so
    one silently erases the other's record and leaves a blob on disk that no
    URL points at. That happened on 31 October 2026 and cost nine downloads
    their provenance. It also doubles the request rate against a crawl delay
    the Register asks for in robots.txt, which is the worse half.
    """
    os.makedirs(CACHE, exist_ok=True)
    handle = open(LOCK, "w")
    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise SystemExit(
                "another fetcher holds %s; wait for it rather than running two "
                "(they race on the index and halve the crawl delay)" % LOCK)
        yield
    finally:
        handle.close()


def _load_index():
    if os.path.exists(INDEX):
        with open(INDEX, "r", encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def _save_index(index):
    os.makedirs(CACHE, exist_ok=True)
    tmp = INDEX + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(index, fh, indent=1, sort_keys=True)
    os.replace(tmp, INDEX)


def _wait_turn():
    """Block until CRAWL_DELAY has elapsed since the last request.

    The timestamp lives on disk so the delay survives across separate
    invocations of the build, not just within one process.
    """
    try:
        with open(CLOCK, "r", encoding="utf-8") as fh:
            last = float(fh.read().strip())
    except (OSError, ValueError):
        last = 0.0
    remaining = CRAWL_DELAY - (time.time() - last)
    if remaining > 0:
        time.sleep(remaining)
    os.makedirs(CACHE, exist_ok=True)
    with open(CLOCK, "w", encoding="utf-8") as fh:
        fh.write(str(time.time()))


def fetch(url, *, binary=False, label=None, retries=3):
    """Return the bytes at url, from cache when present.

    Raises on any status other than 200 after exhausting retries, except
    that a 403 or 404 is cached as a negative result and re-raised, so a
    known-bad URL is not retried on the next run.
    """
    index = _load_index()
    entry = index.get(url)
    if entry is not None:
        if entry.get("status") != 200:
            raise urllib.error.HTTPError(
                url, entry["status"], entry.get("reason", "cached failure"), None, None
            )
        path = os.path.join(BLOBS, entry["sha256"])
        if os.path.exists(path):
            with open(path, "rb") as fh:
                return fh.read()

    if OFFLINE:
        raise CacheMiss("not in cache and OFFLINE is set: %s" % url)

    last_error = None
    for attempt in range(retries):
        _wait_turn()
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                body = response.read()
                content_type = response.headers.get("Content-Type", "")
                status = response.status
            break
        except urllib.error.HTTPError as error:
            last_error = error
            if error.code in (403, 404):
                index[url] = {
                    "status": error.code,
                    "reason": error.reason,
                    "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "label": label,
                }
                _save_index(index)
                raise
            sys.stderr.write(
                "  retry %d/%d after HTTP %d on %s\n"
                % (attempt + 1, retries, error.code, url)
            )
        except (urllib.error.URLError, TimeoutError) as error:
            last_error = error
            sys.stderr.write(
                "  retry %d/%d after %s on %s\n" % (attempt + 1, retries, error, url)
            )
    else:
        raise RuntimeError("giving up on %s: %s" % (url, last_error))

    digest = hashlib.sha256(body).hexdigest()
    os.makedirs(BLOBS, exist_ok=True)
    blob = os.path.join(BLOBS, digest)
    if not os.path.exists(blob):
        with open(blob, "wb") as fh:
            fh.write(body)
    index[url] = {
        "status": status,
        "sha256": digest,
        "bytes": len(body),
        "content_type": content_type,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "label": label,
    }
    _save_index(index)
    return body


def fetch_json(url, *, label=None):
    return json.loads(fetch(url, label=label).decode("utf-8"))


def odata(path, *, label=None, **params):
    """Fetch an OData path, following @odata.nextLink to the end."""
    query = "&".join(
        "%s=%s" % (k if k.startswith("$") else "$" + k, urllib.parse.quote(str(v), safe="(),'/=*"))
        for k, v in params.items()
    )
    url = "%s/%s%s" % (API, path, ("?" + query) if query else "")
    collected = []
    while url:
        page = fetch_json(url, label=label)
        collected.extend(page.get("value", []))
        url = page.get("@odata.nextLink")
    return collected


def cached_urls():
    return _load_index()


#: When true, a cache miss raises instead of reaching the network. The
#: build runs this way so that "same cache, same output" is enforced
#: rather than hoped for.
OFFLINE = False


class CacheMiss(RuntimeError):
    pass


def forget(url):
    """Drop a cached response. Used when a 200 turns out not to be the
    object that was asked for, so the cache never holds a wrong answer."""
    index = _load_index()
    entry = index.pop(url, None)
    if entry is None:
        return False
    _save_index(index)
    digest = entry.get("sha256")
    if digest and not any(e.get("sha256") == digest for e in index.values()):
        blob = os.path.join(BLOBS, digest)
        if os.path.exists(blob):
            os.remove(blob)
    return True
