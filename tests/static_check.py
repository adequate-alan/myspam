"""Fast release checks, no browser (Phase 1 reliability). Runs in a few seconds; CI runs it on every push and the scheduled
data jobs run it before they commit.

Run from the repo root:  python3 tests/static_check.py [--base REF] [--frozen-rankings]
  --base REF           also compare with that commit: earlier ranking-history entries must be unchanged (history only
                       grows), and the same players must be on the board
  --frozen-rankings    with --base: no ranking field (rank, position rank, tier, value, source, tier name) may change.
                       For automated jobs: nothing scheduled ever changes rankings (CLAUDE.md §2, §8).

Checks:
 1. Every inline <script> parses (node --check) and BUILD_ID is set.
 2. Exactly one RANKINGS_CSV block, and the rankings pass the same rules the editor checks before publishing: all
    columns, every row the header's width, names and positions, ranks 1..N with no gaps or duplicates, whole-number tiers,
    numeric or blank values, manual/auto source, a Sleeper ID for every player and none repeated, no player twice,
    position ranks following the overall order, and no character that would break index.html.
 3. data/rank_history.json: version 2, every entry [timestamp, rank, position rank, tier, value, source, kind?] and the
    publish events; data/rank_snapshots/*.json well formed, and every event's snapshot month file exists. With --base,
    entries, events and snapshots from that commit are unchanged (they only grow).
 4. Every data/*.json file parses; files the page loads by a fixed path exist (data/projections.json is optional:
    the weekly job writes it and the page works without it).
 5. Assets the page references (favicon, manifest) exist, and every element looked up by a fixed id ($("…")) is
    defined somewhere in the page.
"""
import argparse, csv, glob, io, json, os, re, shutil, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_RE = re.compile(r"(const RANKINGS_CSV = `\n)([\s\S]*?)(\n`;)")
COLS = ["player", "pos", "team", "rank", "pos_rank", "tier", "value", "sleeper_id", "source"]
EDIT_COLS = ["rank", "pos_rank", "tier", "value", "source", "tier_name"]
OPTIONAL = {"data/projections.json"}

failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)

def git_show(ref, path):
    r = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=ROOT, capture_output=True)
    return r.stdout.decode("utf-8") if r.returncode == 0 else None

def rankings(html):
    blocks = CSV_RE.findall(html)
    return blocks[0][1] if len(blocks) == 1 else None, len(blocks)

def table(text):
    rows = list(csv.reader(io.StringIO(text)))
    return rows[0], rows[1:]

def validate(text):
    errs = []
    if re.search(r"[`\\]|\$\{", text): errs.append("a field contains a backtick, a backslash or ${")
    head, rows = table(text)
    missing = [c for c in COLS if c not in head]
    if missing: return errs + [f"missing columns {missing}"]
    c = head.index
    ranks, ids, keys, by_pos = [], {}, set(), {}
    for i, r in enumerate(rows):
        who = (r[c("player")] if len(r) > c("player") else "") or f"row {i + 2}"
        if len(r) != len(head): errs.append(f"{who} has {len(r)} fields instead of {len(head)}"); continue
        if not r[c("player")].strip(): errs.append(f"row {i + 2} has no player name")
        if not r[c("pos")]: errs.append(f"{who} has no position")
        if not re.fullmatch(r"[1-9]\d*", r[c("rank")]): errs.append(f"{who} has an invalid rank {r[c('rank')]!r}")
        else: ranks.append(int(r[c("rank")]))
        if not re.fullmatch(r"\d+", r[c("tier")]): errs.append(f"{who} has an invalid tier {r[c('tier')]!r}")
        v = r[c("value")]
        if v != "":
            try: float(v)
            except ValueError: errs.append(f"{who} has an invalid value {v!r}")
        if r[c("source")] not in ("manual", "auto"): errs.append(f"{who} has an invalid source {r[c('source')]!r}")
        sid = r[c("sleeper_id")]
        if not sid: errs.append(f"{who} has no Sleeper ID")
        elif sid in ids: errs.append(f"Sleeper ID {sid} appears twice ({ids[sid]} and {who})")
        else: ids[sid] = who
        k = (r[c("player")] + "|" + r[c("pos")]).lower()
        if k in keys: errs.append(f"{who} ({r[c('pos')]}) appears twice")
        keys.add(k)
        by_pos.setdefault(r[c("pos")], []).append(r)
    if sorted(ranks) != list(range(1, len(rows) + 1)): errs.append(f"overall ranks don't run 1..{len(rows)} without gaps or duplicates")
    for pos, lst in by_pos.items():
        try: lst.sort(key=lambda r: int(r[c("rank")]))
        except ValueError: continue
        bad = next((i for i, r in enumerate(lst) if r[c("pos_rank")] != str(i + 1)), None)
        if bad is not None: errs.append(f"{pos} position ranks don't follow the overall order ({lst[bad][c('player')]} is {pos}{lst[bad][c('pos_rank')]}, expected {pos}{bad + 1})")
    return errs

def history_errors(h):   # the Oct 11 model: entries [ts, rank, posRank, tier, value, source, kind?] + publish events
    if not isinstance(h, dict) or h.get("version") != 2 or not isinstance(h.get("players"), dict): return ["not a version-2 history file"]
    errs = []
    for sid, lst in h["players"].items():
        for e in lst:
            if not (isinstance(e, list) and len(e) in (6, 7) and isinstance(e[0], str) and re.match(r"\d{4}-\d\d-\d\d", e[0])
                    and isinstance(e[1], int) and e[1] >= 1 and e[5] in ("M", "S", "P", "B") and (len(e) == 6 or e[6] in ("R", "V", "RV", "A"))):
                errs.append(f"player {sid} has a malformed entry {json.dumps(e)[:80]}"); break
        if len(errs) > 5: break
    ev = h.get("events", [])
    if not isinstance(ev, list) or any(not isinstance(e, dict) or not isinstance(e.get("ts"), str) for e in ev): errs.append("publish events are malformed")
    return errs

def snapshot_errors(path, f):   # data/rank_snapshots/<YYYY-MM>.json: {version: 1, snapshots: [{ts, src, by, players: {sid: [rank, posRank, tier, value, typed]}}]}
    if not isinstance(f, dict) or f.get("version") != 1 or not isinstance(f.get("snapshots"), list): return [f"{path} isn't a version-1 snapshot file"]
    month = os.path.basename(path)[:7]
    for s in f["snapshots"]:
        if not (isinstance(s, dict) and isinstance(s.get("ts"), str) and s["ts"].startswith(month) and isinstance(s.get("players"), dict)
                and all(isinstance(a, list) and len(a) == 5 and isinstance(a[0], int) for a in s["players"].values())):
            return [f"{path} has a malformed snapshot ({str(s.get('ts'))[:24]})"]
    return []

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base"); ap.add_argument("--frozen-rankings", action="store_true")
    a = ap.parse_args()
    html = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()

    # 1. scripts parse
    node = shutil.which("node")
    scripts = re.findall(r"<script>([\s\S]*?)</script>", html)
    if node:
        bad = []
        with tempfile.TemporaryDirectory() as d:
            for i, js in enumerate(scripts):
                f = os.path.join(d, f"s{i}.js"); open(f, "w", encoding="utf-8").write(js)
                r = subprocess.run([node, "--check", f], capture_output=True, text=True)
                if r.returncode: bad.append(f"script {i + 1}: " + (r.stderr.strip().splitlines() or ["?"])[-1])
        ok(scripts and not bad, f"All {len(scripts)} inline scripts parse {bad}")
    else:
        ok(False, "node is needed to check the scripts' syntax (install Node.js)")
    ok(re.search(r'const BUILD_ID = "[^"]+";', html) is not None, "BUILD_ID is set")

    # 2. rankings
    text, n = rankings(html)
    ok(n == 1, f"Exactly one RANKINGS_CSV block ({n})")
    if text is not None:
        errs = validate(text)
        ok(not errs, f"Rankings pass the publish rules ({len(table(text)[1])} players) {errs[:5]}")

    # 3. ranking history
    try: hist = json.load(open(os.path.join(ROOT, "data/rank_history.json"), encoding="utf-8"))
    except Exception as e: hist = None; ok(False, f"data/rank_history.json parses ({e})")
    if hist is not None:
        errs = history_errors(hist)
        ok(not errs, f"Ranking history is well formed ({sum(len(v) for v in hist['players'].values())} entries) {errs[:3]}")

    snaps = sorted(glob.glob(os.path.join(ROOT, "data", "rank_snapshots", "*.json")))
    errs = []
    for f in snaps:
        try: errs += snapshot_errors(os.path.relpath(f, ROOT), json.load(open(f, encoding="utf-8")))
        except Exception as e: errs.append(f"{os.path.relpath(f, ROOT)}: {e}")
    ok(not errs, f"Board snapshots are well formed ({len(snaps)} month file(s)) {errs[:3]}")
    if hist is not None and isinstance(hist.get("events"), list):
        months = {e["snap"] for e in hist["events"] if e.get("snap")}
        missing = sorted(m for m in months if not os.path.exists(os.path.join(ROOT, "data", "rank_snapshots", m + ".json")))
        ok(not missing, f"Every publish event's snapshot month file exists {missing}")

    # 4. data files
    bad = []
    for f in glob.glob(os.path.join(ROOT, "data", "**", "*.json"), recursive=True):
        try: json.load(open(f, encoding="utf-8"))
        except Exception as e: bad.append(f"{os.path.relpath(f, ROOT)}: {e}")
    ok(not bad, f"Every data/*.json file parses {bad[:3]}")
    paths = set(re.findall(r'"(data/[A-Za-z0-9_/.-]+\.json)"', html))
    missing = sorted(p for p in paths if p not in OPTIONAL and not os.path.exists(os.path.join(ROOT, p)))
    ok(not missing, f"Data files the page loads exist ({len(paths)} paths) {missing}")

    # 5. assets and element ids
    assets = set(re.findall(r'(?:href|src)="((?!https?:|data:|#|mailto:)[^"${}]+\.(?:svg|webmanifest|png|ico))', html))
    missing = sorted(x for x in assets if not os.path.exists(os.path.join(ROOT, x.split("?")[0])))
    ok(assets and not missing, f"Referenced assets exist {sorted(assets)} {missing}")
    ids = set(re.findall(r'\$\("([A-Za-z0-9_-]+)"\)', html)) | set(re.findall(r'getElementById\(["\']([A-Za-z0-9_-]+)["\']\)', html))
    defined = set(re.findall(r'\bid=\\?["\']([A-Za-z0-9_-]+)', html)) | set(re.findall(r'\.id = ["\']([A-Za-z0-9_-]+)', html))
    undef = sorted(i for i in ids if i not in defined)
    ok(not undef, f"Every element looked up by id is defined ({len(ids)} ids) {undef[:8]}")

    # against a base commit
    if a.base:
        old_html = git_show(a.base, "index.html")
        if old_html:
            old, _ = rankings(old_html)
            if old and text:
                oh, orows = table(old); nh, nrows = table(text)
                ok_keys = lambda h, rs: {(r[h.index("player")] + "|" + r[h.index("pos")]).lower(): r for r in rs if len(r) == len(h)}
                ok_old, ok_new = ok_keys(oh, orows), ok_keys(nh, nrows)
                ok(set(ok_old) == set(ok_new), f"Same players as {a.base[:10]} (added {sorted(set(ok_new) - set(ok_old))[:3]}, lost {sorted(set(ok_old) - set(ok_new))[:3]})")
                if a.frozen_rankings:
                    changed = []
                    for k, r in ok_new.items():
                        o = ok_old.get(k)
                        if not o: continue
                        for col in EDIT_COLS:
                            ov = o[oh.index(col)] if col in oh else ""; nv = r[nh.index(col)] if col in nh else ""
                            if ov != nv: changed.append(f"{r[nh.index('player')]} {col} {ov!r} → {nv!r}")
                    ok(not changed, f"No ranking field changed since {a.base[:10]} (automated job) {changed[:5]}")
        old_hist = git_show(a.base, "data/rank_history.json")
        if old_hist and hist is not None:
            try: oh = json.loads(old_hist)
            except Exception: oh = None
            if oh and oh.get("version") == 2:
                changed = [sid for sid, lst in oh["players"].items() if hist["players"].get(sid, [])[:len(lst)] != lst]
                ok(not changed, f"Every ranking-history entry from {a.base[:10]} is unchanged (history only grows) {changed[:5]}")
                oe, ne = oh.get("events", []), hist.get("events", [])
                ok(ne[:len(oe)] == oe, f"Every publish event from {a.base[:10]} is unchanged ({len(oe)} → {len(ne)})")
        old_snaps = subprocess.run(["git", "ls-tree", "--name-only", a.base, "data/rank_snapshots/"], cwd=ROOT, capture_output=True, text=True).stdout.split()
        for path in old_snaps:
            o = git_show(a.base, path)
            try: o = json.loads(o) if o else None; n = json.load(open(os.path.join(ROOT, path), encoding="utf-8"))
            except Exception: o, n = None, None
            if o is not None:
                os_, ns_ = o.get("snapshots", []), (n or {}).get("snapshots", [])
                ok(ns_[:len(os_)] == os_, f"Every snapshot in {path} from {a.base[:10]} is unchanged ({len(os_)} → {len(ns_)})")

    print(f"\n{len(failures)} check(s) failed." if failures else "\nAll static checks passed.")
    return 1 if failures else 0

if __name__ == "__main__":
    sys.exit(main())
