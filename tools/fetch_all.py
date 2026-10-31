"""Download every Primary Word document for the Tier 1 instruments.

Ordered smallest first, so a complete instrument exists early rather than
after every volume of the Corporations Regulations. Resumable: anything
already in the cache is skipped, so re-running after an interruption
costs nothing but the scan.
"""

import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import register
import fetch

TIER1 = [
    "F2015L01854",   # Foreign Acquisitions and Takeovers Regulation 2015
    "F2025L00753",   # Competition and Consumer (Notification of Acquisitions) Determination 2025
    "F2025L01604",   # ... (Notification of Acquisitions-Forms) Determination 2025
    "F2023L01310",   # ASIC Corporations (Takeover Bids) Instrument 2023/683
    "F2001B00274",   # Corporations Regulations 2001 -- 12 volumes, longest history
]


def plan(title_id):
    """(document, as_made) pairs for one title, oldest first."""
    vs = register.versions(title_id)
    first_start = vs[0].get("start") if vs else None
    out = []
    for d in register.word_documents(title_id):
        as_made = (str(d.get("compilationNumber")) == "0"
                   and d.get("start") == first_start)
        out.append((d, as_made))
    return out


def main():
    only = sys.argv[1:] or TIER1
    with fetch.sole_fetcher():
        return run(only)


def run(only):
    for title_id in only:
        pairs = plan(title_id)
        print("%s: %d documents" % (title_id, len(pairs)), flush=True)
        done = 0
        started = time.time()
        for d, as_made in pairs:
            try:
                register.document_bytes(d, as_made=as_made)
            except Exception as error:               # noqa: BLE001 - logged, not fatal
                print("  FAIL %s v%s %s: %s" % (
                    title_id, d.get("volumeNumber"), (d.get("start") or "")[:10], error),
                    flush=True)
                continue
            done += 1
            if done % 25 == 0:
                rate = (time.time() - started) / done
                print("  %s %d/%d  (%.1fs/doc, ~%.0f min left)" % (
                    title_id, done, len(pairs), rate,
                    rate * (len(pairs) - done) / 60), flush=True)
        print("%s: %d/%d downloaded" % (title_id, done, len(pairs)), flush=True)
    print("ALL DONE", flush=True)


if __name__ == "__main__":
    main()
