"""Fast release checks, no browser (Phase 1 reliability). Runs in a few seconds; CI runs it on every push and the scheduled
data jobs run it before they commit.

Run from the repo root:  python3 tests/static_check.py [--base REF] [--frozen-rankings]
  --base REF           also compare with that commit: earlier ranking-history entries must be unchanged (history only
                       grows), and the same players must be on the board
  --frozen-rankings    with --base: no ranking field (rank, position rank, tier, value, source, tier name) may change;
                       other boards' blocks (AM PPR) keep the same players and every column but the team (sync_teams.py).
                       For automated jobs: nothing scheduled ever changes rankings (CLAUDE.md §2, §8).

Checks:
 1. Every inline <script> parses (node --check) and BUILD_ID is the "dev" placeholder the deploy stamps.
 2. Exactly one RANKINGS_CSV block, and the rankings pass the same rules the editor checks before publishing: all
    columns, every row the header's width, names and positions, ranks 1..N with no gaps or duplicates, whole-number tiers,
    numeric or blank values, manual/auto source, a Sleeper ID for every player and none repeated, no player twice,
    position ranks following the overall order, and no character that would break index.html.
 3. data/rank_history.json (and each other board's, data/boards/<id>/): version 2, every entry [timestamp, rank, position rank, tier, value, source, kind?] and the
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
# other ranking sets (BOARDS in index.html, Alan, Oct 14): each block passes the same rules, values strictly down the
# board (only 0s tie), and the same players as the original board (matched by Sleeper ID)
BOARD_RES = {"RANKINGS_CSV_PPR": re.compile(r"const RANKINGS_CSV_PPR = `\n([\s\S]*?)\n`;")}
OVERALL_TIERS = {"RANKINGS_CSV_PPR"}   # boards whose tiers are one scale down the overall order (tierScope "overall")
# each board's ranking history and snapshot folder (Oct 14: AM PPR has its own, from its baseline)
HIST_SETS = [("data/rank_history.json", "data/rank_snapshots"), ("data/boards/ppr/rank_history.json", "data/boards/ppr/rank_snapshots")]

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

FLOCK_SETS = {"flock-sf": "sf", "flock-ppr": "1"}
def flock_errors(label, d):   # data/market/flock_<sf|ppr>.json and each snapshot entry (Oct 14)
    errs = []
    if d.get("version") != 2 or d.get("set") not in FLOCK_SETS: return [f"{label}: not a version 2 Flock list of a known set"]
    cols, rows = d.get("cols") or [], d.get("rows")
    need = ["sleeper_id", "rank", "pos", "pos_rank"]
    if not isinstance(rows, list) or any(c not in cols for c in need): return [f"{label}: rows or columns {need} missing"]
    if rows and not (isinstance(d.get("fmt"), dict) and d["fmt"].get("qb") == FLOCK_SETS[d["set"]] and all(k in d["fmt"] for k in ("teams", "rec", "tep"))):
        errs.append(f"{label}: a list needs its format (qb {FLOCK_SETS[d['set']]}, teams, rec, tep)")
    if rows and not d.get("exported"): errs.append(f"{label}: a list needs its export time")
    I = {c: cols.index(c) for c in need}
    sids = [str(r[I["sleeper_id"]]) for r in rows]; ranks = [r[I["rank"]] for r in rows]
    if any(not re.fullmatch(r"\d+", x) for x in sids): errs.append(f"{label}: a row without a numeric Sleeper ID")
    if len(set(sids)) != len(sids): errs.append(f"{label}: a Sleeper ID listed twice")
    if len(set(ranks)) != len(ranks) or any(not isinstance(x, int) or x < 1 for x in ranks): errs.append(f"{label}: ranks must be unique whole numbers")
    if any(r[I["pos"]] not in ("QB", "RB", "WR", "TE") for r in rows): errs.append(f"{label}: a position other than QB/RB/WR/TE")
    # only verified players are priced (Alan, Oct 14): id / name (flockMatch) or manual (picked by hand in the list manager)
    if "match" not in cols or any(r[cols.index("match")] not in ("id", "name", "manual") for r in rows):
        errs.append(f"{label}: a priced row whose player identity isn't verified (match must be id, name or manual; unresolved rows go in unmatched)")
    if any(not isinstance(u, dict) or not u.get("reason") for u in d.get("unmatched") or []): errs.append(f"{label}: an unmatched row without its reason")
    last = {}
    for r in sorted(rows, key=lambda r: r[I["rank"]]):   # position ranks follow the list's order (unmatched rows may leave gaps)
        if r[I["pos_rank"]] <= last.get(r[I["pos"]], 0): errs.append(f"{label}: position ranks out of order at {r[I['pos']]}{r[I['pos_rank']]}"); break
        last[r[I["pos"]]] = r[I["pos_rank"]]
    return errs

def snapshot_errors(path, f):   # data/rank_snapshots/<YYYY-MM>.json: {version: 1, snapshots: [{ts, src, by, valueModelVersion?, players}]}
    """Two snapshot formats, each checked against its own schema (Oct 13): a snapshot that names its value model
    (`valueModelVersion`, values as state since Oct 12) holds [rank, posRank, tier, value] per player; an older one
    holds [rank, posRank, tier, value, typed 0/1]. Ranks are whole numbers from 1 and unique within a snapshot, values
    whole numbers from 0, tiers numbers or strings; snapshots carry a timestamp in the file's month, unique within the
    file, and at least one player."""
    if not isinstance(f, dict) or f.get("version") != 1 or not isinstance(f.get("snapshots"), list): return [f"{path} isn't a version-1 snapshot file"]
    month = os.path.basename(path)[:7]
    whole = lambda x, lo: isinstance(x, int) and not isinstance(x, bool) and x >= lo
    seen = set()
    for s in f["snapshots"]:
        label = f"{path} has a malformed snapshot ({str(s.get('ts') if isinstance(s, dict) else s)[:24]})"
        if not (isinstance(s, dict) and isinstance(s.get("ts"), str) and s["ts"].startswith(month) and isinstance(s.get("players"), dict) and s["players"]): return [label]
        if s["ts"] in seen: return [f"{path} has two snapshots at {s['ts'][:24]}"]
        seen.add(s["ts"])
        stored = "valueModelVersion" in s
        if stored and not (isinstance(s["valueModelVersion"], str) and s["valueModelVersion"]): return [label + ": valueModelVersion isn't a name"]
        n = 4 if stored else 5
        ranks = set()
        for sid, a in s["players"].items():
            if not (isinstance(a, list) and len(a) == n and whole(a[0], 1) and whole(a[1], 1) and isinstance(a[2], (int, str)) and whole(a[3], 0) and (n == 4 or a[4] in (0, 1))):
                return [label + f": player {sid} {json.dumps(a)[:60]} isn't a {n}-field entry"]
            if a[0] in ranks: return [label + f": rank {a[0]} appears twice"]
            ranks.add(a[0])
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
    ok(len(re.findall(r'const BUILD_ID = "dev";', html)) == 1 and len(re.findall(r'^\s*const BUILD_ID = ', html, re.M)) == 1,
       'BUILD_ID is the "dev" placeholder (the deploy stamps the real one; never bump it by hand)')

    # 2. rankings
    text, n = rankings(html)
    ok(n == 1, f"Exactly one RANKINGS_CSV block ({n})")
    if text is not None:
        errs = validate(text)
        ok(not errs, f"Rankings pass the publish rules ({len(table(text)[1])} players) {errs[:5]}")

    for name, rx in BOARD_RES.items():
        found = rx.findall(html)
        ok(len(found) == 1, f"Exactly one {name} block ({len(found)})")
        if len(found) != 1 or text is None: continue
        btext = found[0]; errs = validate(btext)
        bh, brows = table(btext); mh, mrows = table(text)
        bid = lambda h, r: r[h.index("sleeper_id")]
        vals = sorted(((int(r[bh.index("rank")]), int(r[bh.index("value")] or -1)) for r in brows if len(r) == len(bh)), key=lambda x: x[0])
        down = [f"#{a[0]} {a[1]} → #{b[0]} {b[1]}" for a, b in zip(vals, vals[1:]) if not (b[1] < a[1] or b[1] == a[1] == 0)]
        if down: errs.append(f"values not strictly down the board {down[:3]}")
        if any(v < 0 for _, v in vals): errs.append("a missing value")
        ids, mids = {bid(bh, r) for r in brows if len(r) == len(bh)}, {bid(mh, r) for r in mrows if len(r) == len(mh)}
        if ids != mids: errs.append(f"players differ from RANKINGS_CSV (only here {sorted(ids - mids)[:3]}, missing {sorted(mids - ids)[:3]})")
        if name in OVERALL_TIERS:   # overall tiers stay in one piece down the board (tag tiers 90+ aside)
            tiers = [int(t) for _, t in sorted((int(r[bh.index("rank")]), r[bh.index("tier")]) for r in brows if len(r) == len(bh)) if t.isdigit() and int(t) < 90]
            split = [f"Tier {a} → {b}" for a, b in zip(tiers, tiers[1:]) if b < a]
            if split: errs.append(f"overall tiers split {split[:3]}")
        ok(not errs, f"{name} passes the publish rules ({len(brows)} players) {errs[:5]}")

    # 3. ranking history: every board's history file and snapshot folder
    hists = {}
    for hpath, sdir in HIST_SETS:
        if not os.path.exists(os.path.join(ROOT, hpath)) and hpath != HIST_SETS[0][0]: ok(False, f"{hpath} exists"); continue
        try: hist = json.load(open(os.path.join(ROOT, hpath), encoding="utf-8"))
        except Exception as e: hist = None; ok(False, f"{hpath} parses ({e})")
        hists[hpath] = hist
        tag = "" if hpath == HIST_SETS[0][0] else f" ({hpath})"
        if hist is not None:
            errs = history_errors(hist)
            ok(not errs, f"Ranking history is well formed{tag} ({sum(len(v) for v in hist['players'].values())} entries) {errs[:3]}")
        snaps = sorted(glob.glob(os.path.join(ROOT, sdir, "*.json")))
        errs = []
        for f in snaps:
            try: errs += snapshot_errors(os.path.relpath(f, ROOT), json.load(open(f, encoding="utf-8")))
            except Exception as e: errs.append(f"{os.path.relpath(f, ROOT)}: {e}")
        ok(not errs, f"Board snapshots are well formed{tag} ({len(snaps)} month file(s)) {errs[:3]}")
        if hist is not None and isinstance(hist.get("events"), list):
            months = {e["snap"] for e in hist["events"] if e.get("snap")}
            missing = sorted(m for m in months if not os.path.exists(os.path.join(ROOT, sdir, m + ".json")))
            ok(not missing, f"Every publish event's snapshot month file exists{tag} {missing}")

    # 3b. Flock market lists (Oct 14): market data, kept apart from the AM boards; snapshots only ever grow (below)
    errs = []
    for f in sorted(glob.glob(os.path.join(ROOT, "data", "market", "flock_*.json"))):
        rel = os.path.relpath(f, ROOT)
        try: errs += flock_errors(rel, json.load(open(f, encoding="utf-8")))
        except Exception as e: errs.append(f"{rel}: {e}")
    for f in sorted(glob.glob(os.path.join(ROOT, "data", "market", "flock_snapshots", "*", "*.json"))):
        rel = os.path.relpath(f, ROOT)
        try:
            d = json.load(open(f, encoding="utf-8"))
            if d.get("version") != 1 or not isinstance(d.get("snapshots"), list) or not d["snapshots"]: errs.append(f"{rel}: not {{version: 1, snapshots: [...]}}")
            for k, sn in enumerate(d.get("snapshots") or []):
                errs += flock_errors(f"{rel} #{k + 1}", {"version": 2, "set": d.get("set"), **sn})
        except Exception as e: errs.append(f"{rel}: {e}")
    ok(not errs, f"Flock market lists and their snapshots are well formed {errs[:3]}")

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
                added, lost = sorted(set(ok_new) - set(ok_old)), sorted(set(ok_old) - set(ok_new))
                if a.frozen_rankings:   # a scheduled refresh never adds or drops a player
                    ok(not added and not lost, f"Same players as {a.base[:10]} (added {added[:3]}, lost {lost[:3]})")
                else:
                    # a pushed rankings change may add a player (Oct 14: Josh Cameron from Alan's WR list), never lose one;
                    # each added player needs a Sleeper ID the player file knows, at his position
                    ok(not lost, f"No player lost since {a.base[:10]} (lost {lost[:3]})")
                    try: sp = json.load(open(os.path.join(ROOT, "data", "sleeper_players.json")))
                    except Exception: sp = {}
                    bad = [k for k in added if (lambda r: (sp.get(r[nh.index("sleeper_id")]) or [None, None])[1] != r[nh.index("pos")])(ok_new[k])]
                    ok(not bad, f"Every player added since {a.base[:10]} has a known Sleeper ID at his position (added {added[:5]}, unknown {bad[:3]})")
                if a.frozen_rankings:
                    changed = []
                    for k, r in ok_new.items():
                        o = ok_old.get(k)
                        if not o: continue
                        for col in EDIT_COLS:
                            ov = o[oh.index(col)] if col in oh else ""; nv = r[nh.index(col)] if col in nh else ""
                            if ov != nv: changed.append(f"{r[nh.index('player')]} {col} {ov!r} → {nv!r}")
                    ok(not changed, f"No ranking field changed since {a.base[:10]} (automated job) {changed[:5]}")
                    for name, rx in BOARD_RES.items():   # every other board: same players, no ranking field changed
                        ob, nb = rx.findall(old_html), rx.findall(html)   # (team may follow Sleeper, sync_teams.py)
                        if not ob: continue
                        if not nb: ok(False, f"{name} still present since {a.base[:10]} (automated job)"); continue
                        (bh, brs), (ch, crs) = table(ob[0]), table(nb[0])
                        key = lambda h, rs: {r[h.index("sleeper_id")]: r for r in rs if len(r) == len(h)}
                        bo, bn = key(bh, brs), key(ch, crs)
                        ok(bh == ch and set(bo) == set(bn) and len(brs) == len(crs),
                           f"{name}: same columns and players as {a.base[:10]} (automated job)")
                        cols = [c for c in bh if c not in ("team",)]
                        diff = [f"{bn[k][ch.index('player')]} {c} {bo[k][bh.index(c)]!r} → {bn[k][ch.index(c)]!r}"
                                for k in bo if k in bn for c in cols if c in ch and bo[k][bh.index(c)] != bn[k][ch.index(c)]]
                        ok(not diff, f"{name}: nothing but the team column changed since {a.base[:10]} (automated job) {diff[:5]}")
        for hpath, sdir in HIST_SETS:
          hist = hists.get(hpath)
          old_hist = git_show(a.base, hpath)
          if old_hist and hist is not None:
            try: oh = json.loads(old_hist)
            except Exception: oh = None
            if oh and oh.get("version") == 2:
                changed = [sid for sid, lst in oh["players"].items() if hist["players"].get(sid, [])[:len(lst)] != lst]
                ok(not changed, f"Every ranking-history entry in {hpath} from {a.base[:10]} is unchanged (history only grows) {changed[:5]}")
                oe, ne = oh.get("events", []), hist.get("events", [])
                ok(ne[:len(oe)] == oe, f"Every publish event in {hpath} from {a.base[:10]} is unchanged ({len(oe)} → {len(ne)})")
          old_snaps = subprocess.run(["git", "ls-tree", "--name-only", a.base, sdir + "/"], cwd=ROOT, capture_output=True, text=True).stdout.split()
          if sdir == "data/rank_snapshots":
              old_snaps += subprocess.run(["git", "ls-tree", "-r", "--name-only", a.base, "data/market/flock_snapshots/"], cwd=ROOT, capture_output=True, text=True).stdout.split()
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
