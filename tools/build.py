"""Build the corpus: parse every cached compilation and replay it as git.

    python3 tools/build.py --today 2026-10-31 [TITLE_ID ...]

The build never reaches the network. Everything it reads is in the
cache, placed there by tools/fetch_all.py, so a rebuild from the same
cache with the same --today produces the same commit hashes.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import fetch
import history
import register

TIER1 = ["F2015L01854", "F2025L00753", "F2025L01604", "F2023L01310",
         "F2001B00274"]


def ensure_repo(repo):
    if not os.path.isdir(os.path.join(repo, ".git")):
        raise SystemExit("%s is not a git repository" % repo)
    head = os.path.join(repo, ".git", "HEAD")
    with open(head, "r", encoding="utf-8") as handle:
        if handle.read().strip() == "ref: refs/heads/master":
            with open(head, "w", encoding="utf-8") as out:
                out.write("ref: refs/heads/main\n")


def reset_history(repo):
    """Throw away the generated history so the build starts from nothing.

    Determinism only means anything from an empty history. Replaying onto a
    history that is already built writes no commits at all: every file
    already holds the text the build would give it, so write_tree reports no
    change and every compilation is skipped.

    Everything outside corpus/ is left on disk, but this unstages it: in a
    clone, where the tools, the licence and the record are tracked, that
    means the commits carrying them are gone from the history as well. It
    is how a release is built, not something to run in a clone.
    """
    def run(*args, **kw):
        return subprocess.run(["git", "-C", repo] + list(args),
                              capture_output=True, text=True, **kw)

    tags = run("tag").stdout.split()
    if tags:
        run("tag", "-d", *tags)
    unborn = run("rev-parse", "--verify", "-q", "HEAD").returncode != 0
    if not unborn:
        run("checkout", "-q", "--orphan", "__rebuild")
        run("rm", "-rq", "--cached", ".")
        for branch in ("main", "future"):
            run("branch", "-D", branch)
        run("branch", "-m", "__rebuild", "main")
    shutil.rmtree(os.path.join(repo, "corpus"), ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("titles", nargs="*", default=None)
    parser.add_argument("--today", required=True,
                        help="YYYY-MM-DD; versions starting after it go to "
                             "the future branch")
    parser.add_argument("--repo", default=ROOT)
    parser.add_argument("--report", default=None,
                        help="write a JSON build report here")
    parser.add_argument("--fresh", action="store_true",
                        help="discard the generated history and build it "
                             "again from nothing (what a release does)")
    args = parser.parse_args(argv)

    fetch.OFFLINE = True
    ensure_repo(args.repo)
    if args.fresh:
        reset_history(args.repo)
    os.makedirs(os.path.join(args.repo, "corpus"), exist_ok=True)

    started = time.time()
    titles = args.titles or TIER1
    # One pass over all of them: the commits interleave by in-force day, so
    # the instruments cannot be replayed one after another.
    summaries = history.replay_all(args.repo, titles, today=args.today)
    for summary in summaries:
        print("  %s: %d commits over %d versions%s"
              % (summary["folder"], len(summary["commits"]),
                 summary["versions"],
                 "".join([
                     "  (%d INCOMPLETE)" % len(summary["incomplete"])
                     if summary["incomplete"] else "",
                     "  [%d out of scope: %s]" % (
                         len(summary["out_of_scope"]),
                         ", ".join("%d %s" % (n, e) for e, n
                                   in sorted(summary["excluded_formats"].items())))
                     if summary["out_of_scope"] else ""])),
              flush=True)

    report = {
        "today": args.today,
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "elapsed_seconds": round(time.time() - started, 1),
        "instruments": summaries,
    }
    if args.report:
        with open(args.report, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=1, sort_keys=True)
    holes = sum(len(s["incomplete"]) for s in summaries)
    report["incomplete_versions"] = holes
    report["complete"] = holes == 0
    if args.report:
        with open(args.report, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=1, sort_keys=True)
    print("built %d instruments in %.0fs; %s"
          % (len(summaries), time.time() - started,
             "complete" if not holes else
             "%d versions INCOMPLETE -- corpus is not releasable" % holes))
    return 0 if not holes else 1


if __name__ == "__main__":
    raise SystemExit(main())
