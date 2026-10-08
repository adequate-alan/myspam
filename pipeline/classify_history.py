"""Tag existing ranking-history entries by kind, only where the git history makes it certain (Alan, Oct 11).

Kinds (see index.html, "Ranking history"): R ranking change (overall rank, position rank or tier), V manual value
change (a typed value added, changed or cleared), RV both, A automatic repricing. Entries this script can't classify
with certainty keep no kind (legacy) and show as before. Nothing is deleted, reordered or rewritten except adding
that one tag; running it again changes nothing.

How it decides, entry by entry (each entry is matched to the history commit that first added it):
  - his first entry: no kind (legacy; there is nothing to compare with)
  - rank, position rank or tier differ from his previous entry: R (+V when the publish also changed his typed value)
  - otherwise (value only), source S (the scheduled job never edits typed values): A
  - otherwise, source M: the publish is the "Rankings edit" commit to index.html at most 15 minutes before that history
    commit; his typed value (the value column) changed in it → V, didn't change → A. No such commit → no kind.
  - source P (older code): no kind

Run from the repo root:  python3 pipeline/classify_history.py  [--dry-run]
"""
import argparse, csv, io, json, os, re, subprocess
from datetime import datetime, timedelta

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
HIST = "data/rank_history.json"
NOTE = ("AM ranking history: visible changes per player {sleeper_id: [[timestamp, overall rank, position rank, tier, base AM value, "
        "source M=publish S=scheduled update P=older published update, kind R=ranking change V=manual value change "
        "A=automatic repricing (none = legacy, unclassified)], ...]} and one event per publish. The exact board at every "
        "publish is in data/rank_snapshots/.")


def git(*a):
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def show(rev, path):
    try: return git("show", f"{rev}:{path}")
    except subprocess.CalledProcessError: return None


def typed_values(html):
    m = re.search(r"const RANKINGS_CSV = `\n(.*?)\n`;", html or "", re.S)
    if not m: return None
    return {r.get("sleeper_id", ""): (r.get("value") or "").strip() for r in csv.DictReader(io.StringIO(m.group(1))) if r.get("sleeper_id")}


def moved(a, b):   # entries [ts, rank, posRank, tier, value, src, kind?]
    return a[1] != b[1] or a[2] != b[2] or (a[3] != "" and b[3] != "" and str(a[3]) != str(b[3]))


def history_text(h):
    d = lambda x: json.dumps(x, separators=(",", ":"), ensure_ascii=False)
    players = ",\n".join(f"{d(sid)}:{d([e[:7] for e in h['players'][sid]])}" for sid in sorted(h["players"], key=lambda s: int(s)))
    events = ",\n".join(d(e) for e in h.get("events") or [])
    return f'{{"note":{d(NOTE)},"version":2,"events":[\n{events}\n],"players":{{\n{players}\n}}}}\n'


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--dry-run", action="store_true"); args = ap.parse_args()
    # which history commit first added each entry (keyed by sid + its first six fields)
    added = {}
    prev = {}
    for line in git("log", "--reverse", "--format=%H %cI", "--", HIST).splitlines():
        sha, when = line.split(" ", 1)
        try: h = json.loads(show(sha, HIST) or "{}")
        except json.JSONDecodeError: continue
        if h.get("version") != 2: continue
        for sid, lst in h.get("players", {}).items():
            for e in lst:
                k = (sid, json.dumps(e[:6]))
                if k not in added: added[k] = (sha, datetime.fromisoformat(when))
        prev = h
    # the "Rankings edit" publishes to index.html, with their times
    edits = []
    for line in git("log", "--format=%H %cI %s", "--", "index.html").splitlines():
        sha, when, msg = line.split(" ", 2)
        if msg.startswith("Rankings edit"): edits.append((datetime.fromisoformat(when), sha))
    edits.sort()
    typed_cache = {}
    def typed_change(publish_sha, sid):
        if publish_sha not in typed_cache:
            typed_cache[publish_sha] = (typed_values(show(publish_sha, "index.html")), typed_values(show(publish_sha + "^", "index.html")))
        after, before = typed_cache[publish_sha]
        if after is None or before is None or sid not in after or sid not in before: return None
        return after[sid] != before[sid]
    def publish_before(t):
        best = None
        for when, sha in edits:
            if t - timedelta(minutes=15) <= when <= t: best = sha
        return best

    path = os.path.join(ROOT, HIST)
    h = json.load(open(path))
    h.setdefault("events", [])
    counts = {"R": 0, "RV": 0, "V": 0, "A": 0, "legacy": 0, "kept": 0}
    for sid, lst in h["players"].items():
        for i, e in enumerate(lst):
            if len(e) > 6 and e[6]: counts["kept"] += 1; continue
            kind = None
            if i > 0:
                src, rk = e[5], moved(lst[i - 1], e)
                commit = added.get((sid, json.dumps(e[:6])))
                pub = publish_before(commit[1]) if commit and src == "M" else None
                tc = typed_change(pub, sid) if pub else None
                if rk: kind = "RV" if tc else "R"
                elif src == "S": kind = "A"
                elif src == "M" and tc is not None: kind = "V" if tc else "A"
            if kind:
                while len(e) < 6: e.append("")
                e[6:] = [kind]; counts[kind] += 1
            else: counts["legacy"] += 1
    print("entries:", counts)
    if not args.dry_run: open(path, "w").write(history_text(h)); print("wrote", HIST)


if __name__ == "__main__":
    main()
