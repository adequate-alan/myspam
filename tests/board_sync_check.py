"""AM PPR → AM SF PPR TE+ position order sync (Alan, Oct 19: "AM PPR decides who stands in each position spot, the SF
board decides what that spot is worth").

Part A runs the page's own syncOrder on small synthetic boards (the edge cases); parts B–D run the real editor and
publishing code against an in-memory GitHub repository (tests/gh_mock.py) holding this checkout's index.html and both
boards' history and snapshot files. Nothing touches GitHub or the files on disk.

Run from the repo root:  CHROMIUM=/path/to/chromium python3 tests/board_sync_check.py   (REPORT=file.md for a before /
after table of the published example)

Checks:
A. syncOrder ("spots stay"): a reorder moves players, never spots (overall rank, position rank, tier, tier name, value and
   source stay put); other positions untouched; Out for season on either board, a value of 0 on SF, a player missing from
   AM PPR or at another position there keeps his own row and the others are ordered around him; a player only on AM PPR
   is never added; a second run changes nothing.
B. The boards in this checkout already follow each other (the first activation was applied), Achane and Dart kept as
   Out for season on both.
C. Unpublished: an AM PPR move saved in a browser without a token changes nothing on GitHub (either block).
D. Published: an AM PPR move RB8 → RB5 publishes ONE commit with both blocks, AM PPR's history and snapshot and AM SF
   PPR TE+'s (source O, from "ppr", the same timestamp); on SF he takes RB5's rank, value and tier, RB5–RB7 shift down a
   spot, nobody else changes; the code outside the blocks is byte-identical; the commit message names the sync.
E. Atomic: a commit GitHub refuses leaves both boards and every history file as they were.
F. The SF editor: a move inside a position is refused (board unchanged, the toast says why); a move across positions,
   a same-rank tier move, a value edit and Out for season still work; an SF publish whose order doesn't follow AM PPR is
   stopped with nothing written. No page errors.
"""
import csv, functools, http.server, io, json, os, re, socketserver, sys, threading
from playwright.sync_api import sync_playwright
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gh_mock import Repo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def rd(p): return open(os.path.join(ROOT, p), "rb").read()
FILES = {"index.html": rd("index.html"), "data/rank_history.json": rd("data/rank_history.json"),
         "data/injury_overrides.json": rd("data/injury_overrides.json"), "data/boards/ppr/rank_history.json": rd("data/boards/ppr/rank_history.json")}
for d in ("data/rank_snapshots", "data/boards/ppr/rank_snapshots"):
    for f in os.listdir(os.path.join(ROOT, d)): FILES[f"{d}/{f}"] = rd(f"{d}/{f}")
HIST_FILES = [p for p in FILES if p != "index.html" and p != "data/injury_overrides.json"]

def block_re(name): return re.compile(rb"(const " + name.encode() + rb" = `\n)([\s\S]*?)(\n`;)")
SF_RE, PPR_RE = block_re("RANKINGS_CSV"), block_re("RANKINGS_CSV_PPR")
def block(html, rx): return rx.search(html)[2].decode()
def outside(html, *rxs):
    for rx in rxs: m = rx.search(html); html = html[:m.start(2)] + html[m.end(2):]
    return html
def table(text):
    rows = list(csv.reader(io.StringIO(text))); h = rows[0]
    return {r[h.index("sleeper_id")]: dict(zip(h, r)) for r in rows[1:]}

failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)

class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
srv = socketserver.TCPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=ROOT))
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"

# --- A. synthetic boards: player, pos, team, rank, pos_rank, tier, value, sleeper_id, source, tier_name
HEAD = "player,pos,team,rank,pos_rank,tier,value,sleeper_id,source,tier_name"
def mk(rows): return HEAD + "\n" + "\n".join(",".join(map(str, r)) for r in rows)
SF = [  # rank order: RB1 A, WR1 W, RB2 B, RB3 C, QB1 Q, RB4 D, RB5 E (Auto), RB6 F (Out, 0)
    ["Ann", "RB", "X", 1, 1, 1, 9000, "1", "manual", "Elite"], ["Wes", "WR", "X", 2, 1, 1, 8500, "9", "manual", "WR1s"],
    ["Bob", "RB", "X", 3, 2, 1, 8000, "2", "manual", "Elite"], ["Cal", "RB", "X", 4, 3, 2, 6000, "3", "manual", "RB1s"],
    ["Quin", "QB", "X", 5, 1, 1, 5000, "8", "manual", "QB1s"], ["Dan", "RB", "X", 6, 4, 2, 4000, "4", "manual", "RB1s"],
    ["Eli", "RB", "X", 7, 5, 3, 1000, "5", "auto", "Depth"], ["Fay", "RB", "X", 8, 6, 99, 0, "6", "manual", "Out for season"]]
def ppr(order):   # AM PPR with the given RB order (sleeper ids), WR and QB as on SF; overall ranks just follow the list
    rows, k = [], 0
    for sid in order + ["9", "8"]:
        k += 1; r = next(r for r in SF if r[7] == sid)
        rows.append([r[0], r[1], "X", k, 0, 1, 10000 - k, sid, "manual", "T"])
    pr = {}
    for r in rows: pr[r[1]] = pr.get(r[1], 0) + 1; r[4] = pr[r[1]]
    return rows

with sync_playwright() as p:
    br = p.chromium.launch(**({"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}))
    errs = []
    repo = Repo(dict(FILES))
    def page(token=True, board=None, ctx=None):
        ctx = ctx or br.new_context(viewport={"width": 1440, "height": 1000})
        pg = ctx.new_page(); pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.route("https://api.github.com/**", repo.handle)
        pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.sleeper\.(app|com)|use\.typekit\.net|fonts\.(googleapis|gstatic)\.com)/.*"), lambda r: r.abort())
        pg.route(re.compile(re.escape(BASE) + r"/(index\.html)?([?#].*)?$"), lambda r: r.fulfill(status=200, content_type="text/html; charset=utf-8", body=repo.read("index.html")))
        pg.route(re.compile(re.escape(BASE) + r"/data/(rank_history\.json|rank_snapshots/|boards/ppr/).*"), lambda r: (lambda b: r.fulfill(status=200, content_type="application/json", body=b) if b is not None else r.fulfill(status=404, body=""))(
            repo.read(r.request.url.split(BASE + "/")[1].split("?")[0])))
        init = "window.__SPM_TEST_HOOKS = true;"
        if token: init += " localStorage.setItem('spm_editor_token', 'test-token');"
        if board: init += f" localStorage.setItem('spm_edit_board', '{board}'); localStorage.setItem('spm_rk_board', '{board}');"
        pg.add_init_script("try { if (!sessionStorage.getItem('i0')) { sessionStorage.setItem('i0', '1'); " + init + " } else { window.__SPM_TEST_HOOKS = true; } } catch (e) {}")
        pg.goto(BASE + "/#rankings"); pg.wait_for_selector("#rank-body tr.player"); pg.wait_for_timeout(1800)
        return pg
    def sync(pg, src, dst): return pg.evaluate("([s, d]) => SPM.syncOrder(s, d)", [src, dst])
    def rows_of(text):
        t = list(csv.DictReader(io.StringIO(text))); return {r["sleeper_id"]: r for r in t}

    pg = page(token=False)

    # A. syncOrder edge cases
    base = rows_of(mk(SF))
    r = sync(pg, mk(ppr(["1", "3", "2", "4", "5", "6"])), mk(SF)); out = rows_of(r["csv"])
    ok([m["name"] for m in r["moved"]] == ["Cal", "Bob"], f"A reorder moves the two players: {[m['name'] for m in r['moved']]}")
    spot = lambda x: (x["rank"], x["pos_rank"], x["tier"], x["tier_name"], x["value"], x["source"])
    ok(spot(out["3"]) == spot(base["2"]) and spot(out["2"]) == spot(base["3"]), "…each takes the other's spot: overall rank, position rank, tier, tier name and value stay with the spot")
    ok(all(out[s] == base[s] for s in ("1", "4", "5", "6", "8", "9")), "Nobody else changes (other RBs, the QB, the WR)")
    r2 = sync(pg, mk(ppr(["1", "3", "2", "4", "5", "6"])), r["csv"])
    ok(not r2["moved"] and r2["csv"] == r["csv"], "A second run changes nothing")
    r = sync(pg, mk(ppr(["1", "2", "3", "5", "4", "6"])), mk(SF)); out = rows_of(r["csv"])
    ok(out["5"]["value"] == "4000" and out["5"]["source"] == "manual" and out["4"]["value"] == "1000" and out["4"]["source"] == "auto",
       "Source stays with the spot (an Auto spot under every Manual one keeps the board's Auto tail intact)")
    # Fay is Out for season on SF (tier 99, value 0): AM PPR ranks her RB1, she keeps her own row, the rest keep order
    r = sync(pg, mk(ppr(["6", "1", "2", "3", "4", "5"])), mk(SF)); out = rows_of(r["csv"])
    ok(not r["moved"] and out == base and any(k["name"] == "Fay" for k in r["kept"]), f"Out for season on SF stays with Fay (never given to a healthy player): {r['kept']}")
    # Dan is Out for season on AM PPR only: he keeps his SF spot, nobody takes it
    P = ppr(["1", "3", "2", "4", "5", "6"]); next(x for x in P if x[7] == "4")[5] = 99
    r = sync(pg, mk(P), mk(SF)); out = rows_of(r["csv"])
    ok(out["4"] == base["4"] and spot(out["3"]) == spot(base["2"]) and any(k["name"] == "Dan" and "source board" in k["why"] for k in r["kept"]),
       "Out for season on AM PPR only: his SF spot stays his (the sync never moves a status), the others still follow")
    # a value of 0 on SF outside a tag tier stays with the player
    Z = [x[:] for x in SF]; Z[5][6] = 0; Z[6][6] = 0
    r = sync(pg, mk(ppr(["1", "2", "3", "5", "4", "6"])), mk(Z))
    ok(not r["moved"] and {k["name"] for k in r["kept"]} >= {"Dan", "Eli"}, f"A value of 0 stays with its player: {[k['name'] for k in r['kept']]}")
    # a player only on SF; a player only on AM PPR; a player at another position on AM PPR
    P = [x for x in ppr(["1", "3", "2", "4", "5", "6"]) if x[7] != "4"] + [["New", "RB", "X", 99, 9, 1, 1, "77", "manual", "T"]]
    r = sync(pg, mk(P), mk(SF)); out = rows_of(r["csv"])
    ok("77" not in out and len(out) == len(base) and out["4"] == base["4"] and spot(out["3"]) == spot(base["2"]),
       "A player only on SF keeps his spot; a player only on AM PPR is never added")
    P = ppr(["1", "3", "2", "4", "5", "6"]); next(x for x in P if x[7] == "3")[1] = "WR"
    r = sync(pg, mk(P), mk(SF))
    ok(not r["moved"] and any(k["name"] == "Cal" and "listed as WR" in k["why"] for k in r["kept"]), "A player at another position on AM PPR keeps his spot")

    # B. the boards in this checkout already follow each other
    live = repo.read("index.html")
    r = sync(pg, block(live, PPR_RE), block(live, SF_RE))
    ok(not r["moved"], f"AM SF PPR TE+ follows AM PPR's published position order in this checkout ({len(r['moved'])} differences)")
    ok(sorted(k["name"] for k in r["kept"]) == ["De'Von Achane", "Jaxson Dart"], f"…with only the Out for season players kept in place: {[k['name'] + ' (' + k['why'] + ')' for k in r['kept']]}")
    pg.close()

    # C. an unpublished AM PPR move never reaches either block on GitHub
    pg = page(token=False, board="ppr")
    ok(pg.evaluate("() => SPM.boards().active") == "ppr", "AM PPR is the edited board")
    rb = pg.evaluate("() => SPM.edit.board().filter(p => p.pos === 'RB').sort((a, b) => a.posNum - b.posNum).map(p => [p.id, String(p.sid), p.name])")
    head0, n0 = repo.head, len(repo.log())
    pg.evaluate("id => SPM.edit.movePlayer(id, 5)", rb[7][0]); pg.wait_for_timeout(500)
    pg.evaluate("() => SPM.edit.save()"); pg.wait_for_timeout(1500)
    ok(repo.head == head0 and len(repo.log()) == n0, "A saved, unpublished AM PPR move (no token) commits nothing: neither block changes on GitHub")
    ok(pg.evaluate("() => (localStorage.getItem('spm_local_edits:ppr') || '{}') !== '{}'"), "…it stays a draft in this browser")
    pg.context.close()

    # E. atomic: GitHub refuses the commit → nothing changes anywhere
    pg = page(token=True, board="ppr")
    rb = pg.evaluate("() => SPM.edit.board().filter(p => p.pos === 'RB').sort((a, b) => a.posNum - b.posNum).map(p => [p.id, String(p.sid), p.name])")
    def save():
        pg.evaluate("() => { const t = document.getElementById('toast'); t.textContent = ''; t.hidden = true; }")
        pg.click("#eb-publish" if pg.is_disabled("#eb-save") else "#eb-save")
        pg.wait_for_function("() => /Publish|Already live|Nothing to publish|Saved/.test(document.getElementById('toast').textContent)", timeout=30000)
        pg.wait_for_timeout(300); return pg.inner_text("#toast")
    pg.evaluate("id => SPM.edit.movePlayer(id, 5)", rb[7][0]); pg.wait_for_timeout(500)
    snap0 = {f: repo.read(f) for f in FILES}; head0 = repo.head
    repo.faults["patch"] = 500
    msg = save(); repo.faults.clear()
    ok("Publish failed" in msg and repo.head == head0 and all(repo.read(f) == snap0[f] for f in FILES), f"A refused commit leaves both blocks and every history and snapshot file unchanged ({msg[:70]!r})")

    # D. the published move reaches SF in the same commit
    sf0, ppr0 = table(block(repo.read("index.html"), SF_RE)), table(block(repo.read("index.html"), PPR_RE))
    rbs0 = sorted((v for v in sf0.values() if v["pos"] == "RB"), key=lambda v: int(v["rank"]))
    before = repo.read("index.html"); n0 = len(repo.log()); head0 = repo.head
    msg = save()
    after = repo.read("index.html"); new = repo.log()[n0:]
    ok("Published and confirmed" in msg and len(new) == 1, f"One commit ({[m.splitlines()[0] for m in new]}; {msg[:110]!r})")
    ok("AM SF PPR TE+ follows the new position order" in msg, "The toast says the SF board followed")
    ok(new and new[0].startswith("AM PPR rankings edit by @tester") and "AM SF PPR TE+ position order follows: 4 players" in new[0], f"The commit message names the sync: {new[0][:300] if new else ''!r}")
    ok(outside(before, SF_RE, PPR_RE) == outside(after, SF_RE, PPR_RE), "index.html outside the two blocks is byte-identical")
    sf1, ppr1 = table(block(after, SF_RE)), table(block(after, PPR_RE))
    sid = rb[7][1]
    ok(ppr1[sid]["pos_rank"] == "5", f"AM PPR: {rb[7][2]} RB8 → RB{ppr1[sid]['pos_rank']}")
    spotf = lambda v: (v["rank"], v["pos_rank"], v["tier"], v.get("tier_name", ""), v["value"], v["source"])
    ok(spotf(sf1[sid]) == spotf(rbs0[4]), f"AM SF PPR TE+: {rb[7][2]} takes RB5's spot: #{sf1[sid]['rank']} · RB{sf1[sid]['pos_rank']} · T{sf1[sid]['tier']} · {sf1[sid]['value']} (was #{sf0[sid]['rank']} · RB{sf0[sid]['pos_rank']} · {sf0[sid]['value']})")
    ok(all(spotf(sf1[rbs0[k]["sleeper_id"]]) == spotf(rbs0[k + 1]) for k in (4, 5, 6)), "RB5–RB7 each move down one spot and take that spot's rank, value and tier")
    changed = sorted(s for s in sf0 if sf0[s] != sf1[s])
    ok(len(changed) == 4, f"Nobody else on SF changes ({len(changed)} rows changed)")
    ok(sorted(int(v["value"]) for v in sf0.values()) == sorted(int(v["value"]) for v in sf1.values()) and {v["rank"] for v in sf0.values()} == {v["rank"] for v in sf1.values()},
       "SF's value ladder and overall rank slots are exactly the same set")
    ok(sf1[sid]["value"] != ppr1[sid]["value"], f"RB5 on both boards, different values: AM PPR {ppr1[sid]['value']}, AM SF PPR TE+ {sf1[sid]['value']}")
    hs, hp = json.loads(repo.read("data/rank_history.json")), json.loads(repo.read("data/boards/ppr/rank_history.json"))
    hs0, hp0 = json.loads(repo.read("data/rank_history.json", head0)), json.loads(repo.read("data/boards/ppr/rank_history.json", head0))
    es, ep = hs["events"][-1], hp["events"][-1]
    ok(len(hs["events"]) == len(hs0["events"]) + 1 and len(hp["events"]) == len(hp0["events"]) + 1 and es["ts"] == ep["ts"], "Each board's history gets one event, at the same timestamp")
    ok(es["src"] == "O" and es.get("from") == "ppr" and es["by"] == "tester" and sorted(x[0] for x in es["ranking"]) == changed,
       f"The SF event says it came from the AM PPR publish (src {es['src']}, from {es.get('from')}) and lists the {len(es['ranking'])} players")
    ok(all(hs["players"][s][-1][5] == "O" and hs["players"][s][-1][0] == es["ts"] for s in changed), "Each SF player's entry is marked O (position order from AM PPR)")
    ok(all(hs["players"].get(s, [])[:len(l)] == l for s, l in hs0["players"].items()) and hs["events"][:-1] == hs0["events"], "Every earlier SF history entry and event kept")
    snap = lambda path: json.loads(repo.read(path))["snapshots"][-1]
    ss, sp = snap(f"data/rank_snapshots/{es['ts'][:7]}.json"), snap(f"data/boards/ppr/rank_snapshots/{ep['ts'][:7]}.json")
    ok(ss["ts"] == es["ts"] and all(ss["players"][s] == [int(v["rank"]), int(v["pos_rank"]), int(v["tier"]), int(v["value"])] for s, v in sf1.items() if s),
       "The SF snapshot is the synced SF board")
    ok(sp["ts"] == ep["ts"] and sp["players"][sid][1] == 5, "The AM PPR snapshot is the published AM PPR board")
    ok(not pg.evaluate("([p, s]) => SPM.syncOrder(p, s).moved.length", [block(after, PPR_RE), block(after, SF_RE)]), "After the publish SF follows AM PPR exactly")
    pg.reload(); pg.wait_for_selector("#rank-body tr.player"); pg.wait_for_timeout(1500)
    ok(pg.evaluate("() => SPM.boards().active") == "ppr" and pg.inner_text("#eb-count").strip() == "All saved", "A reload shows the published board with nothing pending")
    if os.environ.get("REPORT"):
        lines = ["| Player | SF before | SF after | AM PPR after |", "|---|---|---|---|"]
        for s in [sid] + [rbs0[k]["sleeper_id"] for k in (4, 5, 6)]:
            a, b, c = sf0[s], sf1[s], ppr1[s]
            lines.append(f"| {a['player']} | RB{a['pos_rank']} · #{a['rank']} · T{a['tier']} · {int(a['value']):,} | RB{b['pos_rank']} · #{b['rank']} · T{b['tier']} · {int(b['value']):,} | RB{c['pos_rank']} · #{c['rank']} · {int(c['value']):,} |")
        open(os.environ["REPORT"], "w").write("\n".join(lines) + "\n")
    pg.context.close()

    # F. the SF editor
    pg = page(token=True, board="sf-tep")
    ok(pg.evaluate("() => SPM.boards().active") == "sf-tep", "AM SF PPR TE+ is the edited board")
    B = lambda: pg.evaluate("() => SPM.edit.board().map(p => [String(p.sid), p.rank, p.posNum, String(p.tier), Math.round(p.value)]).sort()")
    start = B()
    wr = pg.evaluate("() => SPM.edit.board().filter(p => p.pos === 'WR').sort((a, b) => a.posNum - b.posNum).map(p => [p.id, p.name, p.rank])")
    pg.evaluate("() => { const t = document.getElementById('toast'); t.textContent = ''; }")
    pg.evaluate("id => SPM.edit.movePlayer(id, 2)", wr[5][0]); pg.wait_for_timeout(400)
    ok(B() == start and "order within each position comes from AM PPR" in pg.inner_text("#toast"), f"WR6 → WR2 on SF is refused, board unchanged ({pg.inner_text('#toast')[:80]!r})")
    pg.evaluate("([id, r]) => SPM.edit.moveOverall(id, r)", [wr[5][0], wr[4][2]]); pg.wait_for_timeout(400)
    ok(B() == start, "An overall move past a WR is refused too")
    ov = pg.evaluate("() => SPM.edit.board().sort((a, b) => a.rank - b.rank).map(p => [p.id, p.pos, p.name, p.rank])")
    k = next(i for i in range(60, 120) if ov[i][1] != ov[i - 1][1])
    pg.evaluate("([id, r]) => SPM.edit.moveOverall(id, r)", [ov[k][0], ov[k][3] - 1]); pg.wait_for_timeout(400)
    now = {r[0]: r for r in B()}
    sid_k = pg.evaluate("id => String(SPM.edit.board().find(p => p.id === id).sid)", ov[k][0])
    ok(now[sid_k][1] == ov[k][3] - 1, f"A move across positions still works ({ov[k][2]} #{ov[k][3]} → #{now[sid_k][1]})")
    pg.evaluate("() => SPM.edit.cancel()"); pg.wait_for_timeout(400)
    ok(B() == start, "Cancel restores the board")
    edge = pg.evaluate("""() => { const b = SPM.edit.board().filter(p => p.pos === 'QB').sort((a, b) => a.posNum - b.posNum);
        for (let i = 1; i < b.length; i++) if (b[i].tier !== b[i - 1].tier && Number(b[i].tier) < 90 && b.filter(p => p.tier === b[i - 1].tier).length > 1) return [b[i - 1].id, b[i].tier, b[i - 1].name, b[i - 1].rank];
        return null; }""")
    pg.evaluate("([id, t]) => SPM.edit.movePlayer(id, SPM.edit.board().find(p => p.id === id).posNum, t)", edge); pg.wait_for_timeout(400)
    now = {r[0]: r for r in B()}
    me = pg.evaluate("id => { const p = SPM.edit.board().find(p => p.id === id); return [String(p.sid), p.rank, String(p.tier)]; }", edge[0])
    ok(me[1] == edge[3] and me[2] == str(edge[1]), f"A same-rank tier move still works ({edge[2]} → Tier {me[2]} at #{me[1]})")
    pg.evaluate("() => SPM.edit.cancel()"); pg.wait_for_timeout(300)
    out_p = pg.evaluate("() => SPM.edit.board().filter(p => p.pos === 'TE' && Number(p.tier) < 90).sort((a, b) => a.posNum - b.posNum)[10]")
    pg.evaluate("id => SPM.edit.sendOut(id)", out_p["id"]); pg.wait_for_timeout(400)
    o = pg.evaluate("id => SPM.edit.board().find(p => p.id === id)", out_p["id"])
    ok(o["tier"] == "99" and o["value"] == 0, f"Out for season still works on SF ({out_p['name']}: Tier {o['tier']}, value {o['value']})")
    pg.evaluate("() => SPM.edit.cancel()"); pg.wait_for_timeout(300)
    ok(B() == start, "Cancel restores the board")
    # an SF publish whose order doesn't follow AM PPR (edits saved by another page, an old browser) is stopped
    sfb = block(repo.read("index.html"), SF_RE); T = list(csv.reader(io.StringIO(sfb))); H = T[0]
    w = sorted((r for r in T[1:] if r[H.index("pos")] == "WR"), key=lambda r: int(r[H.index("rank")]))[2:4]
    key = lambda r: (r[H.index("player")] + "|" + r[H.index("pos")]).lower()
    edits = {key(w[0]): {c: w[1][H.index(c)] for c in ("rank", "pos_rank", "tier", "value", "tier_name")},
             key(w[1]): {c: w[0][H.index(c)] for c in ("rank", "pos_rank", "tier", "value", "tier_name")}}
    pg.evaluate("e => localStorage.setItem('spm_local_edits', JSON.stringify(e))", edits)
    pg.reload(); pg.wait_for_selector("#rank-body tr.player"); pg.wait_for_timeout(1500)
    head0 = repo.head
    pg.evaluate("() => { const t = document.getElementById('toast'); t.textContent = ''; t.hidden = true; }")
    pg.click("#eb-publish" if pg.is_disabled("#eb-save") else "#eb-save")   # loaded as unsaved: Save publishes (a token is saved)
    pg.wait_for_function("() => /Publish/.test(document.getElementById('toast').textContent)", timeout=30000)
    msg = pg.inner_text("#toast")
    ok(repo.head == head0 and "position order comes from AM PPR" in msg, f"An SF publish that reorders WRs is stopped, nothing written ({msg[:110]!r})")
    ok(not errs, f"No page errors: {errs[:3]}")
    br.close()

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
