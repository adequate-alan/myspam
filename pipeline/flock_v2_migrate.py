"""One-time migration (Oct 14, 2026): data/market/flock.json (one Flock list, CSV text) -> the two Flock market lists.

  data/market/flock_sf.json                         the Superflex list, version 2 (structured rows)
  data/market/flock_ppr.json                        the Regular PPR list, empty until Alan imports one
  data/market/flock_snapshots/flock-sf/2026-10.json the migrated list as the first immutable snapshot (with its CSV)

Every one of the 362 rows is kept. Flock's `player_id` is a Sleeper ID for established players but NOT for many 2025-26
rookies: some are Flock's own IDs (2025013 = Tyler Shough), some are another player's Sleeper ID (Flock's Chris Bell
13269 is Sleeper's Fernando Mendoza; Caleb Douglas 13299 is Nate Boerkircher). The matching rule, the same one the
page's import uses (flockMatch in index.html):
  1. the ID is accepted when the player our files know under it has the row's position and the same name: equal last
     name, or equal first name with a last name within two letters (Etienne / Ettienne, Bateman / Batemen);
  2. otherwise the one player in our files with the row's name and position (team breaks a tie) gets the row, and
     Flock's own ID is kept in `flock_id`;
  3. otherwise an ID none of our files knows is kept as it is (our player file lags new players), flagged `unknown`;
  4. anything else (an ID that belongs to someone else and no name match, or a second row for a player already
     listed) is left unmatched: kept in `unmatched` with the reason, never priced.
"Our files" = data/sleeper_players.json plus the AM board's own Sleeper IDs.

Run from the repo root:  python3 pipeline/flock_v2_migrate.py   (needs git history with data/market/flock.json)
"""
import csv, io, json, os, re, subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FMT = {"qb": "sf", "teams": 12, "rec": 1, "tep": 0}
COLS = ["sleeper_id", "rank", "pos", "pos_rank", "tier", "name", "team", "expert_rank", "flock_id", "match"]

def norm(s):
    s = re.sub(r"[.'’`]", "", str(s or "").lower()); s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()

def lev(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1): cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]

def same_player(n1, p1, n2, p2):
    if p1 != p2: return False
    a, b = norm(n1).split(), norm(n2).split()
    if not a or not b: return False
    return a[-1] == b[-1] or (a[0] == b[0] and lev(a[-1], b[-1]) <= 2)

def known_players():
    sp = json.load(open(os.path.join(ROOT, "data", "sleeper_players.json"), encoding="utf-8"))
    known = {k: (v[0], v[1], v[2] or "") for k, v in sp.items()}
    src = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
    for r in csv.DictReader(io.StringIO(re.search(r"RANKINGS_CSV\s*=\s*`(.*?)`", src, re.S).group(1).strip())):
        if r["sleeper_id"]: known[r["sleeper_id"]] = (r["player"], r["pos"], r["team"])
    return known

def match(rows, known):
    """rows: [{id, name, pos, team, ...}] in rank order -> each row gets sid / match, or a reason it's unmatched"""
    by = {}
    for k, (n, p, t) in known.items(): by.setdefault((norm(n), p), []).append(k)
    seen = set()
    for r in rows:
        fid, kn = r["id"], known.get(r["id"])
        if fid and kn and same_player(r["name"], r["pos"], kn[0], kn[1]): sid, how = fid, "id"
        else:
            c = by.get((norm(r["name"]), r["pos"]), [])
            if len(c) > 1: c = [k for k in c if known[k][2] and known[k][2] == r["team"]]
            if len(c) == 1: sid, how = c[0], "name"
            elif fid and not kn and re.fullmatch(r"\d+", fid): sid, how = fid, "unknown"
            else: sid, how = None, ("this ID belongs to " + kn[0] + " (" + kn[1] + ")" if kn else "no player with this name and position")
        if sid and sid in seen: sid, how = None, "a second row for a player already listed higher"
        r["sid"], r["match"] = sid, how
        if sid: seen.add(sid)
    return rows

def main():
    old = json.loads(subprocess.run(["git", "show", "b4e84d6:data/market/flock.json"], cwd=ROOT, capture_output=True, text=True, check=True).stdout)
    rd = list(csv.reader(io.StringIO(old["csv"]))); H = {h: i for i, h in enumerate(rd[0])}
    rows = [{"id": r[H["player_id"]].strip(), "rank": int(r[H["Rank"]]), "name": r[H["Name"]], "team": r[H["Team"]], "pos": r[H["Position"]],
             "tier": r[H["Tier"]], "er": float(r[H["Expert Rank"]]) if r[H["Expert Rank"]] else None} for r in rd[1:]]
    rows.sort(key=lambda r: r["rank"])
    match(rows, known_players())
    pc, out, unmatched = {}, [], []
    for r in rows:   # position ranks over the whole list, matched or not: Flock's own order
        pc[r["pos"]] = pc.get(r["pos"], 0) + 1
        if r["sid"]: out.append([r["sid"], r["rank"], r["pos"], pc[r["pos"]], r["tier"], r["name"], r["team"], r["er"], r["id"], r["match"]])
        else: unmatched.append({"rank": r["rank"], "pos": r["pos"], "pos_rank": pc[r["pos"]], "name": r["name"], "team": r["team"], "flock_id": r["id"], "reason": r["match"]})
    note = ("Flock redraft rankings, added by Alan for his own non-commercial use. Market data, never an AM board: nothing here changes AM "
            "ranks, tiers or values. `exported` = when the list was exported from Flock (Flock publishes no time for its own ranking changes); "
            "`published` = when it went live on Adequate. `flock_id` = Flock's own player_id; `match` = how the row was matched to a Sleeper ID "
            "(id / name / unknown: see pipeline/flock_v2_migrate.py). Every published version is kept in data/market/flock_snapshots/flock-sf/.")
    live = {"version": 2, "set": "flock-sf", "label": "Flock Superflex", "note": note, "fmt": FMT,
            "fmt_source": "recorded with the Oct 8 import: Superflex, Full PPR, no TE premium; 12 teams (Alan, Oct 14)",
            "exported": old["updated"], "published": old["synced"], "by": "adequate-alan", "file": old["file"], "cols": COLS, "rows": out, "unmatched": unmatched}
    snap = {"version": 1, "set": "flock-sf", "note": "Every published version of this Flock list, never rewritten (Alan, Oct 14). The first entry is the list built into the site on Oct 8 (data/market/flock.json), migrated with its original export and publish times and its original CSV.",
            "snapshots": [{"exported": old["updated"], "published": old["synced"], "by": "adequate-alan", "fmt": FMT, "file": old["file"],
                           "migrated_from": "data/market/flock.json", "cols": COLS, "rows": out, "unmatched": unmatched, "csv": old["csv"]}]}
    ppr = {"version": 2, "set": "flock-ppr", "label": "Flock Regular PPR",
           "note": "No list yet. Import Alan's Flock Regular PPR export (its format is confirmed at import). Until then 1QB leagues use FantasyCalc alone: a Superflex list is never used for a 1QB league.",
           "fmt": None, "exported": None, "published": None, "by": None, "file": "", "cols": COLS, "rows": [], "unmatched": []}
    def dump(rel, o):
        p = os.path.join(ROOT, rel); os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f: f.write(json.dumps(o, ensure_ascii=False, separators=(",", ":")).replace("],[", "],\n[") + "\n")
    dump("data/market/flock_sf.json", live); dump("data/market/flock_ppr.json", ppr); dump("data/market/flock_snapshots/flock-sf/2026-10.json", snap)
    by = {}
    for r in rows: by[r["match"] if r["sid"] else "unmatched"] = by.get(r["match"] if r["sid"] else "unmatched", 0) + 1
    print(f"{len(rows)} rows: {by}")
    for r in rows:
        if r["match"] != "id": print(f"  #{r['rank']:>3} {r['name']:<24} {r['pos']} flock {r['id']:<8} -> {r['sid'] or '-':<8} {r['match']}")

if __name__ == "__main__":
    main()
