"""Flock market lists (Alan, Oct 14): two independent lists, Flock Superflex and Flock Regular PPR, each its own dataset.

Run from the repo root:  CHROMIUM=/path/to/chromium python3 tests/flock_lists_check.py

Checks, on the real files (data/market/flock_sf.json, flock_ppr.json and the snapshot of the migrated list):
  · every row of the migrated export is accounted for: matched rows + unmatched rows = the export's rows, ranks 1..N
  · the page's import parser matches the snapshot's original CSV exactly like pipeline/flock_v2_migrate.py did
  · Flock IDs that belong to another player are never trusted (Flock's Chris Bell 13269 is Sleeper's Mendoza); a matching
    surname and position is never enough (normalized full names, or an alias verified by hand, identical in the page and
    the migration); a Flock ID no player has stays unmatched with its ID kept, and is still unmatched once that ID turns
    out to be someone else's Sleeper ID
  · a Superflex format reads Flock Superflex; a 1QB format never reads the Superflex list (FantasyCalc alone while
    there is no Regular PPR list), and the page names the missing list
  · a list saved by an older page (spm_flock) moves into the list its format belongs to, the old key kept
  · the AM board (ranks, position ranks, tiers, values) is identical with and without the Flock lists and the old key
  · no page errors
"""
import csv, functools, http.server, io, json, os, re, socketserver, sys, threading
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)

SF = json.load(open(os.path.join(ROOT, "data/market/flock_sf.json")))
PPR = json.load(open(os.path.join(ROOT, "data/market/flock_ppr.json")))
SNAP = json.load(open(os.path.join(ROOT, "data/market/flock_snapshots/flock-sf/2026-10.json")))["snapshots"][0]
C = {c: i for i, c in enumerate(SF["cols"])}
src_rows = list(csv.DictReader(io.StringIO(SNAP["csv"])))
ranks = sorted([r[C["rank"]] for r in SF["rows"]] + [u["rank"] for u in SF["unmatched"]])
ok(len(src_rows) == len(SF["rows"]) + len(SF["unmatched"]) and ranks == list(range(1, len(src_rows) + 1)),
   f"Every exported row is kept: {len(SF['rows'])} matched + {len(SF['unmatched'])} unmatched = {len(src_rows)}, ranks 1..N")
ok(SNAP["rows"] == SF["rows"] and SNAP["unmatched"] == SF["unmatched"] and SNAP["exported"] == SF["exported"],
   "The snapshot holds the same rows, unmatched rows and export time as the live list")
ok(SF["fmt"] == {"qb": "sf", "teams": 12, "rec": 1, "tep": 0} and PPR["rows"] == [] and PPR["fmt"] is None,
   "Flock Superflex is 12-team Full PPR no TEP; Flock Regular PPR has no list yet (no format assumed)")
by_flock = {r[C["flock_id"]]: r for r in SF["rows"]}
bell = by_flock.get("13269")
ok(bell and bell[C["name"]] == "Chris Bell" and bell[C["sleeper_id"]] != "13269" and bell[C["match"]] == "name",
   f"Flock's Chris Bell (13269, Sleeper's Mendoza) is matched by name, not by that ID: {bell and bell[C['sleeper_id']]}")
mendoza = next((r for r in SF["rows"] if r[C["name"]] == "Fernando Mendoza"), None)
ok(mendoza and mendoza[C["sleeper_id"]] == "13269", "Fernando Mendoza gets his own Flock rank")
ok(all(r[C["match"]] in ("id", "name") for r in SF["rows"]), "Every priced row has a verified identity (matched by ID + full name, or by full name)")
unres = {u["flock_id"]: u for u in SF["unmatched"] if u["reason"].startswith("unresolved")}
sids = {r[C["sleeper_id"]] for r in SF["rows"]}
ok(set(unres) == {"13253", "7437"} and all(u["name"] and u["rank"] for u in unres.values()) and not (set(unres) & sids),
   f"Unresolved Flock IDs stay in the list with their ID, unpriced: {[(u['name'], k) for k, u in unres.items()]}")
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
import flock_v2_migrate as MIG
page_src = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
page_alias = dict(re.findall(r'"([a-z0-9 ]+\|(?:QB|RB|WR|TE))": "(\d+)"', re.search(r"const FLOCK_ALIASES = \{(.*?)\};", page_src, re.S).group(1)))
ok(page_alias == MIG.ALIASES and len(page_alias) == 8, f"The page and the migration share the same {len(page_alias)} verified aliases")
ok(not MIG.same_player("Kyle Allen", "QB", "Josh Allen", "QB", "4984") and not MIG.same_player("Joshua Palmer", "WR", "Josh Palmer", "WR", "1")
   and MIG.same_player("Joshua Palmer", "WR", "Josh Palmer", "WR", "7670") and MIG.same_player("Marvin Harrison Jr.", "WR", "Marvin Harrison", "WR"),
   "Migration: a shared surname is not the same player; an alias counts only for its own Sleeper ID; suffixes are ignored")

def serve():
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a): pass
    h = functools.partial(Quiet, directory=ROOT)
    srv = socketserver.TCPServer(("127.0.0.1", 0), h)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv.server_address[1]
port = serve()
FLOCK_FILES = re.compile(r".*/data/market/flock_(sf|ppr)\.json(\?.*)?$")

with sync_playwright() as p:
    br = p.chromium.launch(**({"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}))
    errs = []
    def page(q="", flock=True, legacy=None):
        pg = br.new_context(viewport={"width": 1440, "height": 1000}).new_page()
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.route(re.compile(r"https://.*"), lambda r: r.abort())   # no network: Sleeper, photos, fonts
        if not flock: pg.route(FLOCK_FILES, lambda r: r.fulfill(status=404, body=""))
        pg.add_init_script("window.__SPM_TEST_HOOKS = true;" + (f"localStorage.setItem('spm_flock', {json.dumps(json.dumps(legacy))});" if legacy else ""))
        pg.goto(f"http://127.0.0.1:{port}/{q}#rankings"); pg.wait_for_selector("#rank-body tr.player")
        pg.wait_for_function("() => SPM.market && SPM.market().srcs.length > 0", timeout=20000); pg.wait_for_timeout(500)
        return pg

    pg = page()
    m = pg.evaluate("() => SPM.market()")
    fl = next((s for s in m["srcs"] if s["id"] == "fl"), None)
    lists = {x["id"]: x for x in m["lists"]}
    ok(m["set"] == "flock-sf" and fl and fl["set"] == "flock-sf" and fl["list"] == "Flock Superflex",
       f"The AM default (Superflex) reads Flock Superflex: {fl and (fl['set'], fl['w'], fl['fmt'])}")
    ok(lists["flock-sf"]["loaded"] and lists["flock-sf"]["rows"] == len(SF["rows"]) and lists["flock-sf"]["site"] and not lists["flock-ppr"]["loaded"],
       f"Both lists registered separately: {[(x['id'], x['loaded'], x['rows']) for x in m['lists']]}")
    parsed = pg.evaluate("t => SPM.flockParse(t)", SNAP["csv"])
    want = [[r[C["sleeper_id"]], r[C["rank"]]] for r in SF["rows"]]
    got = [[str(r[0]), r[1]] for r in parsed["rows"]]
    ok(got == want, f"The page's import matches the snapshot CSV exactly as the migration did ({len(got)} vs {len(want)} rows)")
    ok(parsed["total"] == len(src_rows) and len(parsed["missed"]) == len(SF["unmatched"]),
       f"The page lists the same unmatched rows: {parsed['missed']}")
    syn = pg.evaluate("""async () => {
      const csv = "player_id,Rank,Name,Team,Position,Tier\\n9001,1,Kyle Allen,BUF,QB,A\\n99999,2,Kyle Williams,,WR,B\\n5848,3,Hollywood Brown,PHI,WR,B\\n9002,4,Jaylen Wright,MIA,RB,C";
      const known = new Map([["9001", ["Josh Allen", "QB", "BUF"]], ["5848", ["Marquise Brown", "WR", "PHI"]], ["9002", ["Jaylen Wright", "RB", "MIA"]]]);
      const a = await SPM.flockParse(csv, [...known]);
      known.set("99999", ["Kyle Pitts", "WR", "ATL"]);   // the unresolved ID later turns out to be another player's Sleeper ID
      const b = await SPM.flockParse(csv, [...known]);
      return { a: a.rows.map(r => String(r[0])), am: a.missed, b: b.rows.map(r => String(r[0])), bm: b.missed, unk: a.unknownIds };
    }""")
    ok(syn["a"] == ["5848", "9002"] and syn["b"] == ["5848", "9002"],
       f"Import: Kyle Allen is never priced as Josh Allen (same surname and position), the unresolved ID stays unpriced, the verified alias and an exact name match count: {syn['a']} / {syn['b']}")
    ok(any("Kyle Allen" in x and "9001" in x for x in syn["am"]) and any("Kyle Williams" in x and "Flock ID 99999" in x and "unresolved" in x for x in syn["am"]) and syn["unk"] == 1,
       f"Import: the unmatched rows keep their Flock IDs and reasons: {syn['am']}")
    ok(any("Kyle Williams" in x and "belongs to Kyle Pitts" in x for x in syn["bm"]), f"Import: once the ID belongs to someone else it is still not his: {syn['bm']}")
    snap0 = pg.evaluate("() => SPM.rankingSnapshot()")
    pg.close()

    pg = page("?fmt=t12_qb1_rec1_tep0")
    m = pg.evaluate("() => SPM.market()")
    ok(m["set"] == "flock-ppr" and not m["sf"] and [s["id"] for s in m["srcs"]] == ["fc"],
       f"A 1QB format never reads the Superflex list: sources {[(s['id'], s.get('set')) for s in m['srcs']]}")
    pg.evaluate("() => { const s = document.getElementById('rk-sort'); s.value = 'mkbuy'; s.dispatchEvent(new Event('change')); }"); pg.wait_for_timeout(800)
    bar = pg.inner_text("#mk-bar")
    ok("Flock Regular PPR" in bar and "FantasyCalc alone" in bar, "The market bar names the missing Regular PPR list and says FantasyCalc is used alone")
    ok(pg.evaluate("() => SPM.rankingSnapshot()") == snap0, "The AM board is identical in a 1QB format view")
    pg.close()

    legacy = {"at": "2026-10-10T12:00:00Z", "sf": False, "teams": 12, "tep": 0, "rec": 1, "file": "old.csv",
              "rows": [[SF["rows"][i][C["sleeper_id"]], i + 1, i + 1, "A"] for i in range(5)], "missed": []}
    pg = page("?fmt=t12_qb1_rec1_tep0", legacy=legacy)
    st = pg.evaluate("() => ({ ppr: localStorage.getItem('spm_flock:ppr'), sf: localStorage.getItem('spm_flock:sf'), old: localStorage.getItem('spm_flock') })")
    m = pg.evaluate("() => SPM.market()")
    ok(st["ppr"] and not st["sf"] and st["old"], "A list saved by the older page (1QB) moves into Flock Regular PPR; the old key is kept, nothing goes into Superflex")
    ok(any(s["id"] == "fl" and s["set"] == "flock-ppr" for s in m["srcs"]), "That browser list is read in a 1QB format")
    pg.close()

    pg = page(flock=False)
    ok(pg.evaluate("() => SPM.rankingSnapshot()") == snap0, "The AM board is identical with the Flock lists missing (no AM value stands in)")
    ok(not any(s["id"] == "fl" for s in pg.evaluate("() => SPM.market()")["srcs"]), "No Flock source without a list")
    pg.close()
    br.close()

ok(not errs, f"No page errors: {errs[:3]}")
print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
