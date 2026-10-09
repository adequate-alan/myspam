"""Prints a fingerprint of the site's code (Phase 1 reliability): every tracked file, except exactly two kinds of data:
  - the RANKINGS_CSV block inside index.html (blanked; everything else in index.html counts), and
  - JSON files under data/ (rankings history, snapshots, stats, market, ids).
Everything else is in it: the page's HTML/CSS/JS, tests and their pinned requirements (tests/requirements-ci.txt),
tests/ci_policy.json, the workflow, pipeline scripts, the manifest, favicon, .gitignore, and any non-JSON file under
data/. Rankings publishes and the scheduled data jobs don't change it; any code, dependency, configuration or test
change does. The RANKINGS_CSV block can't carry code: the editor and tests/static_check.py reject a backtick, a
backslash or ${ in it, so it can't end the template literal it sits in.

CI uses it to keep rankings-only publishes quick without letting untested code through: after the full suite passes,
the workflow records this fingerprint (an Actions cache entry "verified-<fingerprint>"); a later push whose fingerprint
was already verified runs only the fast checks (static + smoke), anything else runs the full suite before deploying.
So a rankings publish made on top of code that failed its checks still runs the full suite and stays blocked.

Run from the repo root:  python3 tests/release_fingerprint.py [--rev COMMIT]   (the working tree, or a commit's tree)
"""
import hashlib, os, re, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_RE = re.compile(rb"(const RANKINGS_CSV = `\n)([\s\S]*?)(\n`;)")

def _files(rev):
    """(path, bytes) for every tracked file: the working tree, or the tree of commit `rev`."""
    if rev is None:
        names = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout.split(b"\0")
        for f in sorted(x.decode() for x in names if x):
            yield f, (lambda f=f: open(os.path.join(ROOT, f), "rb").read())
        return
    tree = subprocess.run(["git", "ls-tree", "-r", "-z", rev], cwd=ROOT, capture_output=True, check=True).stdout.split(b"\0")
    for ent in sorted((e for e in tree if e), key=lambda e: e.split(b"\t", 1)[1]):
        meta, path = ent.split(b"\t", 1); sha = meta.split()[2].decode()
        yield path.decode(), (lambda sha=sha: subprocess.run(["git", "cat-file", "blob", sha], cwd=ROOT, capture_output=True, check=True).stdout)

def fingerprint(rev=None):
    h = hashlib.sha256()
    for f, read in _files(rev):
        if f.startswith("data/") and f.endswith(".json"): continue
        b = read()
        if f == "index.html":
            if len(CSV_RE.findall(b)) != 1: b += b"\0unparsable rankings block"   # never matches a verified fingerprint
            else: b = CSV_RE.sub(lambda m: m[1] + b"<rankings>" + m[3], b)
        h.update(f.encode() + b"\0" + hashlib.sha256(b).digest())
    return h.hexdigest()[:32]

if __name__ == "__main__":
    print(fingerprint(sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--rev" else None))
    sys.exit(0)
