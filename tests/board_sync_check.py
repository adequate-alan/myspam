"""Free editing on every board, with the AM PPR → AM SF PPR TE+ position order sync as an optional, previewed action
(Alan, Nov 14: "complete manual editing freedom on both AM Boards"; the sync was automatic from Oct 19 to Nov 14).

Part A runs the page's own syncOrder on small synthetic boards (the edge cases); parts B–G run the real editor and
publishing code against an in-memory GitHub repository (tests/gh_mock.py) holding this checkout's index.html and both
boards' history and snapshot files. Nothing touches GitHub or the files on disk.

Run from the repo root:  CHROMIUM=/path/to/chromium python3 tests/board_sync_check.py

Checks:
A. syncOrder ("spots stay"): a reorder moves players, never spots (overall rank, position rank, tier, tier name, value and
   source stay put); other positions untouched; Out for season on either board, a value of 0 on SF, a player missing from
   AM PPR or at another position there keeps his own row and the others are ordered around him; a player only on AM PPR
   is never added; a second run changes nothing; `only` leaves every other position exactly as it is.
B. Unpublished: an AM PPR move saved in a browser without a token changes nothing on GitHub (either block).
C. An AM PPR publish (RB8 → RB5) is ONE commit with AM PPR's block, history and snapshot only: the SF block, its history
   and its snapshots are byte-identical. A commit GitHub refuses leaves everything as it was.
D. The SF editor is free: a move inside a position (Move to rank through the popover, the last QB to QB25), an arrow, an
   overall move past players of his own position, a same-rank tier move, a value edit and Out for season all work and
   change AM PPR nowhere; only the mover's value changes on a move; Save keeps them across a reload; the publish is one
   commit with the SF block, history and snapshot only.
E. A later AM PPR publish leaves SF's own order exactly as published.
F. The optional sync: the editor bar offers it on SF only; the preview lists every player who would change spot, before
   and after, for the ticked positions (RB and WR by default); Cancel changes nothing; unsaved changes block it; without
   a token it asks to sign in; a preview that no longer matches what is live is stopped with nothing written; "Publish
   sync" is ONE commit with the SF block, history (source O, from "ppr") and snapshot, AM PPR untouched; a position left
   unticked keeps SF's own order.
G. Phone and dark theme: the preview fits the screen. No page errors.
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

    r = sync(pg, mk(ppr(["3", "2", "1", "4", "5", "6"])), mk(SF)); r1 = pg.evaluate("([s, d]) => SPM.syncOrder(s, d, ['WR', 'QB'])", [mk(ppr(["3", "2", "1", "4", "5", "6"])), mk(SF)])
    ok(len(r["moved"]) == 2 and not r1["moved"] and r1["csv"] == mk(SF), "`only`: a position that isn't asked for is left exactly as it is")
    live = repo.read("index.html")
    r = sync(pg, block(live, PPR_RE), block(live, SF_RE))
    print(f"INFO this checkout: AM SF PPR TE+ differs from AM PPR's position order at {len(r['moved'])} players (information only: the boards are edited independently)")
    pg.close()

    def save(pg):
        pg.evaluate("() => { const t = document.getElementById('toast'); t.textContent = ''; t.hidden = true; }")
        pg.click("#eb-publish" if pg.is_disabled("#eb-save") else "#eb-save")
        pg.wait_for_function("() => /Publish|Already live|Nothing to publish|Saved/.test(document.getElementById('toast').textContent)", timeout=30000)
        pg.wait_for_timeout(300); return pg.inner_text("#toast")
    SF_FILES = [f for f in FILES if f.startswith("data/rank_")]
    PPR_FILES = [f for f in FILES if f.startswith("data/boards/ppr/")]
    def ppr_files(): return {f: repo.read(f) for f in PPR_FILES}
    POS = lambda pg, pos: pg.evaluate("pos => SPM.edit.board().filter(p => p.pos === pos).sort((a, b) => a.posNum - b.posNum).map(p => [p.id, String(p.sid), p.name, p.rank, Math.round(p.value), String(p.tier)])", pos)

    # B. an unpublished AM PPR move never reaches either block on GitHub
    pg = page(token=False, board="ppr")
    ok(pg.evaluate("() => SPM.boards().active") == "ppr", "AM PPR is the edited board")
    ok(pg.locator("#eb-sync").is_hidden(), "AM PPR's editor bar offers no sync (it is nobody's follower)")
    rb = POS(pg, "RB")
    head0, n0 = repo.head, len(repo.log())
    pg.evaluate("id => SPM.edit.movePlayer(id, 5)", rb[7][0]); pg.wait_for_timeout(500)
    pg.evaluate("() => SPM.edit.save()"); pg.wait_for_timeout(1500)
    ok(repo.head == head0 and len(repo.log()) == n0, "A saved, unpublished AM PPR move (no token) commits nothing: neither block changes on GitHub")
    pg.context.close()

    # C. an AM PPR publish is AM PPR's alone
    pg = page(token=True, board="ppr")
    rb = POS(pg, "RB")
    pg.evaluate("id => SPM.edit.movePlayer(id, 5)", rb[7][0]); pg.wait_for_timeout(500)
    snap0 = {f: repo.read(f) for f in FILES}; head0 = repo.head
    repo.faults["patch"] = 500
    msg = save(pg); repo.faults.clear()
    ok("Publish failed" in msg and repo.head == head0 and all(repo.read(f) == snap0[f] for f in FILES), f"A refused commit leaves both blocks and every history and snapshot file unchanged ({msg[:70]!r})")
    before = repo.read("index.html"); n0 = len(repo.log()); sfh0 = {f: repo.read(f) for f in SF_FILES}
    msg = save(pg)
    after = repo.read("index.html"); new = repo.log()[n0:]
    ok("Published and confirmed" in msg and len(new) == 1 and new[0].startswith("AM PPR rankings edit by @tester"), f"The AM PPR publish is one commit ({[m.splitlines()[0] for m in new]})")
    ok("AM SF PPR TE+" not in msg and "AM SF PPR TE+" not in new[0], "Neither the toast nor the commit message mentions AM SF PPR TE+")
    ok(block(after, SF_RE) == block(before, SF_RE) and outside(before, PPR_RE) == outside(after, PPR_RE), "The SF block and everything outside the AM PPR block are byte-identical")
    ok(all(repo.read(f) == sfh0[f] for f in SF_FILES), "SF's history and snapshots are byte-identical")
    ok(table(block(after, PPR_RE))[rb[7][1]]["pos_rank"] == "5", f"AM PPR: {rb[7][2]} RB8 → RB5 is live")
    ppr_moved = rb[7]
    pg.context.close()

    # D. the SF editor is free
    pg = page(token=True, board="sf-tep")
    ok(pg.evaluate("() => SPM.boards().active") == "sf-tep", "AM SF PPR TE+ is the edited board")
    B = lambda: pg.evaluate("() => SPM.edit.board().map(p => [String(p.sid), p.rank, p.posNum, String(p.tier), Math.round(p.value), p.source]).sort()")
    start = B(); ppr_block0 = block(repo.read("index.html"), PPR_RE)
    def diff(a, b): return [x[0] for x, y in zip(a, b) if x != y]
    wr = POS(pg, "WR")
    pg.evaluate("id => SPM.edit.movePlayer(id, 2)", wr[5][0]); pg.wait_for_timeout(400)
    now = POS(pg, "WR")
    ok(now[1][0] == wr[5][0] and "AM PPR" not in pg.inner_text("#toast"), f"WR6 → WR2 on SF works ({wr[5][2]} is now WR2)")
    vals0 = {r[0]: r[4] for r in start}; vals1 = {r[0]: r[4] for r in B()}
    chg = [s_ for s_ in vals0 if vals0[s_] != vals1[s_]]
    ok(set(chg) <= {wr[5][1]} or all(abs(vals0[s_] - vals1[s_]) <= 1 for s_ in chg if s_ != wr[5][1]), f"Only the mover's value changes; nobody takes another player's value ({len(chg)} values changed)")
    src0 = {r[0]: r[5] for r in start}; src1 = {r[0]: r[5] for r in B()}
    ok(all(src0[s_] == src1[s_] for s_ in src0 if s_ != wr[5][1]), "Everyone else keeps his Manual / Auto status")
    pg.evaluate("() => SPM.edit.cancel()"); pg.wait_for_timeout(400)
    ok(B() == start, "Cancel restores the board exactly")
    pg.evaluate("([id, r]) => SPM.edit.moveOverall(id, r)", [wr[5][0], wr[3][3]]); pg.wait_for_timeout(400)
    ok(POS(pg, "WR")[3][0] == wr[5][0], f"An overall move past two WRs works too ({wr[5][2]} → #{wr[3][3]}, WR4)")
    pg.evaluate("() => SPM.edit.cancel()"); pg.wait_for_timeout(400)
    # an arrow on the RB tab
    pg.click('.chip-btn[data-pos="RB"]') if pg.locator('.chip-btn[data-pos="RB"]').count() else pg.evaluate("() => [...document.querySelectorAll('button')].find(b => b.textContent.trim() === 'RB').click()")
    pg.wait_for_timeout(400)
    rbs = POS(pg, "RB"); row = pg.locator(f'#rank-body tr.player[data-id="{rbs[9][0]}"]'); row.hover(); row.locator(".arrow[data-dir='-1']").click(); pg.wait_for_timeout(500)
    ok(POS(pg, "RB")[8][0] == rbs[9][0], f"The ▲ arrow moves {rbs[9][2]} RB10 → RB9 on SF")
    pg.evaluate("() => SPM.edit.cancel()"); pg.wait_for_timeout(400)
    # Move to rank through the popover: the last ranked QB to QB25 (Alan's Carson Beck example)
    pg.evaluate("() => [...document.querySelectorAll('button')].find(b => b.textContent.trim() === 'QB').click()"); pg.wait_for_timeout(400)
    qbs = [q for q in POS(pg, "QB") if int(q[5]) < 90 and q[4] > 0]; last = qbs[-1]
    row = pg.locator(f'#rank-body tr.player[data-id="{last[0]}"]'); row.scroll_into_view_if_needed(); row.hover(); row.locator(".rk-btn").click(); pg.wait_for_timeout(250)
    pg.fill("#mv-input", "25"); pg.wait_for_timeout(150); pg.keyboard.press("Enter"); pg.wait_for_timeout(600)
    qb1 = POS(pg, "QB")
    ok(qb1[24][0] == last[0] and qb1[23][4] > qb1[24][4] > qb1[25][4], f"Move to rank: {last[2]} QB{len(qbs)} → QB25 on SF, valued between his new neighbours ({qb1[23][4]:,} > {qb1[24][4]:,} > {qb1[25][4]:,})")
    ok([q[0] for q in qb1 if q[0] != last[0]] == [q[0] for q in POS(pg, "QB") if q[0] != last[0]] and [q[0] for q in qb1 if q[0] != last[0]][:len(qbs) - 1] == [q[0] for q in qbs[:-1]], "The other QBs keep their order")
    # a same-rank tier move and a value edit on top
    edge = pg.evaluate("""() => { const b = SPM.edit.board().filter(p => p.pos === 'TE').sort((a, b) => a.posNum - b.posNum);
        for (let i = 1; i < b.length; i++) if (b[i].tier !== b[i - 1].tier && Number(b[i].tier) < 90 && b.filter(p => p.tier === b[i - 1].tier).length > 1) return [b[i - 1].id, b[i].tier, b[i - 1].name, b[i - 1].rank];
        return null; }""")
    pg.evaluate("([id, t]) => SPM.edit.movePlayer(id, SPM.edit.board().find(p => p.id === id).posNum, t)", edge); pg.wait_for_timeout(400)
    me = pg.evaluate("id => { const p = SPM.edit.board().find(p => p.id === id); return [String(p.sid), p.rank, String(p.tier)]; }", edge[0])
    ok(me[1] == edge[3] and me[2] == str(edge[1]), f"A same-rank tier move works ({edge[2]} → Tier {me[2]} at #{me[1]})")
    ov = pg.evaluate("() => SPM.edit.board().sort((a, b) => a.rank - b.rank).map(p => [p.id, Math.round(p.value), p.name, String(p.sid)])")
    v_new = ov[40][1] - 1 if ov[40][1] - 1 > ov[41][1] else None
    if v_new: pg.evaluate("([id, v]) => SPM.edit.setValue(id, v)", [ov[40][0], v_new]); pg.wait_for_timeout(400)
    ok(v_new is None or pg.evaluate("id => Math.round(SPM.edit.board().find(p => p.id === id).value)", ov[40][0]) == v_new, f"A value edit works ({ov[40][2]} {ov[40][1]:,} → {v_new})")
    pg.evaluate("() => SPM.edit.cancel()"); pg.wait_for_timeout(400)
    ok(B() == start, "Cancel restores the published board exactly")
    pg.context.close()

    pg = page(token=False, board="sf-tep")
    qbs = [q for q in POS(pg, "QB") if int(q[5]) < 90 and q[4] > 0]; last = qbs[-1]
    pg.evaluate("id => SPM.edit.movePlayer(id, 25)", last[0]); pg.wait_for_timeout(400)
    pg.evaluate("id => SPM.edit.movePlayer(id, 2)", wr[5][0]); pg.wait_for_timeout(400)
    want = B(); head0 = repo.head
    pg.evaluate("() => SPM.edit.save()"); pg.wait_for_timeout(1500)
    pg.reload(); pg.wait_for_selector("#rank-body tr.player"); pg.wait_for_timeout(1500)
    ok(B() == want and repo.head == head0, "Saved without a token: the SF order is kept across a reload, nothing on GitHub")
    ok(POS(pg, "QB")[24][0] == last[0] and POS(pg, "WR")[1][0] == wr[5][0], f"…{last[2]} is QB25 and {wr[5][2]} WR2 after the reload")
    # sign in and publish: SF only
    pg.evaluate("() => { sessionStorage.setItem('spm_editor_token', 'test-token'); }")
    pg.reload(); pg.wait_for_selector("#rank-body tr.player"); pg.wait_for_timeout(1800)
    before = repo.read("index.html"); n0 = len(repo.log()); pf0 = ppr_files(); hs0 = json.loads(repo.read("data/rank_history.json"))
    msg = save(pg)
    after = repo.read("index.html"); new = repo.log()[n0:]
    ok("Published and confirmed" in msg and len(new) == 1 and new[0].startswith("Rankings edit by @tester"), f"The SF publish is one commit ({[m.splitlines()[0] for m in new]}; {msg[:90]!r})")
    ok(block(after, PPR_RE) == ppr_block0 and outside(before, SF_RE) == outside(after, SF_RE) and ppr_files() == pf0, "AM PPR's block, history and snapshots are byte-identical; nothing outside the SF block changed")
    sf1 = table(block(after, SF_RE))
    ok(sf1[last[1]]["pos_rank"] == "25" and sf1[wr[5][1]]["pos_rank"] == "2", f"Live on SF: {last[2]} QB25, {wr[5][2]} WR2")
    hs = json.loads(repo.read("data/rank_history.json")); es = hs["events"][-1]
    ok(len(hs["events"]) == len(hs0["events"]) + 1 and es["src"] == "M" and hs["events"][:-1] == hs0["events"] and all(hs["players"].get(s_, [])[:len(l)] == l for s_, l in hs0["players"].items()),
       "SF's history gets one Manual event; every earlier entry and event is kept")
    snap = lambda path: json.loads(repo.read(path))["snapshots"][-1]
    ss = snap(f"data/rank_snapshots/{es['ts'][:7]}.json")
    ok(ss["ts"] == es["ts"] and all(ss["players"][s_] == [int(v["rank"]), int(v["pos_rank"]), int(v["tier"]), int(v["value"])] for s_, v in sf1.items() if s_), "The SF snapshot is the published SF board")
    ok({s_ for s_ in sf1} == {r[0] for r in start}, "Same players as before (identity kept)")
    pg.reload(); pg.wait_for_selector("#rank-body tr.player"); pg.wait_for_timeout(1500)
    ok(pg.inner_text("#eb-count").strip() == "All saved" and POS(pg, "QB")[24][0] == last[0], "A reload shows the published SF board with nothing pending")
    sf_own = block(repo.read("index.html"), SF_RE)
    pg.context.close()

    # E. a later AM PPR publish never touches SF's own order
    pg = page(token=True, board="ppr")
    wrp = POS(pg, "WR")
    pg.evaluate("id => SPM.edit.movePlayer(id, 3)", wrp[8][0]); pg.wait_for_timeout(500)
    sfh0 = {f: repo.read(f) for f in SF_FILES}; n0 = len(repo.log())
    msg = save(pg)
    ok("Published and confirmed" in msg and len(repo.log()) == n0 + 1 and block(repo.read("index.html"), SF_RE) == sf_own and all(repo.read(f) == sfh0[f] for f in SF_FILES),
       "After another AM PPR publish (WR9 → WR3) the SF block, history and snapshots are byte-identical: SF's manual order stands")
    pg.context.close()

    # F. the optional sync
    def open_sync(pg):
        pg.click("#eb-sync"); pg.wait_for_selector("#sync-dialog[open]"); pg.wait_for_timeout(200)
    def ticked(pg): return pg.evaluate("() => [...document.querySelectorAll('#sync-pos input')].filter(i => i.checked).map(i => i.dataset.syncPos)")
    def rows(pg): return pg.evaluate("() => [...document.querySelectorAll('#sync-box tbody tr')].map(tr => [...tr.cells].map(c => c.innerText.replace(/\\s+/g, ' ').trim()))")
    pg = page(token=True, board="sf-tep")
    ok(pg.locator("#eb-sync").is_visible() and "AM PPR" in pg.inner_text("#eb-sync"), f"The SF editor bar offers the sync ({pg.inner_text('#eb-sync')!r})")
    live = repo.read("index.html"); sf0 = table(block(live, SF_RE)); ppr_now = block(live, PPR_RE)
    plan = pg.evaluate("([s, d]) => SPM.syncOrder(s, d, ['RB', 'WR'])", [ppr_now, block(live, SF_RE)])
    plan_all = pg.evaluate("([s, d]) => SPM.syncOrder(s, d)", [ppr_now, block(live, SF_RE)])
    ok(any(m["pos"] == "QB" for m in plan_all["moved"]) and any(m["pos"] == "RB" for m in plan["moved"]) and any(m["pos"] == "WR" for m in plan["moved"]),
       f"The boards now differ at QB, RB and WR ({len(plan_all['moved'])} players)")
    head0 = repo.head
    open_sync(pg)
    ok(ticked(pg) == ["RB", "WR"], f"RB and WR are ticked by default, QB and TE are not ({ticked(pg)})")
    rws = rows(pg)
    ok(len(rws) == len(plan["moved"]) and [r_[0].split(" RB")[0].split(" WR")[0] for r_ in rws] == [m["name"] for m in plan["moved"]], f"The preview lists exactly the {len(plan['moved'])} RBs and WRs who would change spot")
    m0 = plan["moved"][0]
    ok(f"#{m0['from']['rank']} " in rws[0][1] and f"{m0['from']['value']:,}" in rws[0][1] and f"#{m0['to']['rank']} " in rws[0][2] and f"{m0['to']['value']:,}" in rws[0][2],
       f"…each with his rank, position rank, tier and value before and after ({rws[0]})")
    ok(f"({len(plan['moved'])} players)" in pg.inner_text("#sync-apply") and pg.is_enabled("#sync-apply"), f"The button says what it publishes ({pg.inner_text('#sync-apply')!r})")
    pg.check('#sync-pos input[data-sync-pos="QB"]'); pg.wait_for_timeout(200)
    ok(len(rows(pg)) == len(plan_all["moved"]) - sum(m["pos"] == "TE" for m in plan_all["moved"]), "Ticking QB adds the QBs to the preview")
    pg.uncheck('#sync-pos input[data-sync-pos="QB"]'); pg.wait_for_timeout(200)
    pg.click("#sync-cancel"); pg.wait_for_timeout(300)
    ok(not pg.evaluate("() => document.getElementById('sync-dialog').open") and repo.head == head0 and pg.inner_text("#eb-count").strip() == "All saved",
       "Cancel closes the preview: nothing committed, nothing unsaved")
    # unsaved changes block it
    te = POS(pg, "TE"); pg.evaluate("id => SPM.edit.movePlayer(id, 3)", te[4][0]); pg.wait_for_timeout(400)
    open_sync(pg)
    ok(pg.is_disabled("#sync-apply") and "unsaved" in pg.inner_text("#sync-error"), f"With unsaved SF changes the sync can't be published ({pg.inner_text('#sync-error')[:70]!r})")
    pg.click("#sync-cancel"); pg.evaluate("() => SPM.edit.cancel()"); pg.wait_for_timeout(400)
    # a preview that no longer matches what is live is stopped
    open_sync(pg)
    T = list(csv.reader(io.StringIO(ppr_now))); H = T[0]
    rbl = sorted((r_ for r_ in T[1:] if r_[H.index("pos")] == "RB"), key=lambda r_: int(r_[H.index("rank")]))
    a_, b_ = rbl[1], rbl[2]
    for c in ("rank", "pos_rank", "tier", "value", "tier_name", "source"):
        if c in H: a_[H.index(c)], b_[H.index(c)] = b_[H.index(c)], a_[H.index(c)]
    out_io = io.StringIO(); csv.writer(out_io, lineterminator="\n").writerows(T)
    stale = PPR_RE.sub(lambda m: m[1] + out_io.getvalue().rstrip("\n").encode() + m[3], live, count=1)
    repo.commit_file("index.html", stale, "AM PPR changed elsewhere")
    changed_elsewhere = repo.read("index.html") == stale
    if changed_elsewhere:
        head1 = repo.head
        pg.click("#sync-apply"); pg.wait_for_function("() => /changed since/.test(document.getElementById('sync-error').textContent)", timeout=30000)
        ok(repo.head == head1 and block(repo.read("index.html"), SF_RE) == block(live, SF_RE), f"AM PPR changed since the preview: the sync is stopped, nothing written ({pg.inner_text('#sync-error')[:80]!r})")
        pg.click("#sync-cancel")
        pg.reload(); pg.wait_for_selector("#rank-body tr.player"); pg.wait_for_timeout(1800)
    else:
        ok(False, "The mock repository can take a commit from outside (needed for the stale-preview check)")
    # no token: it asks to sign in, and nothing is written
    pg.evaluate("() => { localStorage.removeItem('spm_editor_token'); sessionStorage.removeItem('spm_editor_token'); }")
    pg.reload(); pg.wait_for_selector("#rank-body tr.player"); pg.wait_for_timeout(1500)
    ok(pg.locator("#eb-sync").is_hidden(), "Signed out, the editor bar doesn't offer the sync (a tool for signed-in editors, like the warnings)")
    pg.route(re.compile(re.escape(BASE) + r"/\?debug$"), lambda r: r.fulfill(status=200, content_type="text/html; charset=utf-8", body=repo.read("index.html")))
    pg.goto(BASE + "/?debug#rankings"); pg.wait_for_selector("#rank-body tr.player"); pg.wait_for_timeout(1500)
    head1 = repo.head
    open_sync(pg); pg.click("#sync-apply"); pg.wait_for_timeout(400)
    ok(pg.evaluate("() => document.getElementById('signin-dialog').open && !document.getElementById('sync-dialog').open") and repo.head == head1, "Without a token, Publish sync asks to sign in first; nothing is written")
    pg.fill("#signin-token", "test-token"); pg.click("#signin-submit"); pg.wait_for_selector("#sync-dialog[open]", timeout=15000); pg.wait_for_timeout(300)
    ok(repo.head == head1 and pg.is_enabled("#sync-apply"), "After signing in the preview is shown again (signing in is not the approval)")
    # publish the sync
    live = repo.read("index.html"); sf0 = table(block(live, SF_RE)); ppr_now = block(live, PPR_RE)
    plan = pg.evaluate("([s, d]) => SPM.syncOrder(s, d, ['RB', 'WR'])", [ppr_now, block(live, SF_RE)])
    n0 = len(repo.log()); pf0 = ppr_files(); hs0 = json.loads(repo.read("data/rank_history.json"))
    pg.evaluate("() => { const t = document.getElementById('toast'); t.textContent = ''; }")
    pg.click("#sync-apply"); pg.wait_for_function("() => /Published and confirmed/.test(document.getElementById('toast').textContent)", timeout=30000); pg.wait_for_timeout(400)
    after = repo.read("index.html"); new = repo.log()[n0:]; sf1 = table(block(after, SF_RE))
    ok(len(new) == 1 and new[0].startswith("AM SF PPR TE+ position order synced from AM PPR by @tester") and f"{len(plan['moved'])} players" in new[0], f"One commit, named for what it is ({new[0].splitlines()[0][:150] if new else ''!r})")
    ok(block(after, PPR_RE) == ppr_now and outside(live, SF_RE) == outside(after, SF_RE) and ppr_files() == pf0, "AM PPR's block, history and snapshots are byte-identical; nothing outside the SF block changed")
    spotf = lambda v: (v["rank"], v["pos_rank"], v["tier"], v.get("tier_name", ""), v["value"], v["source"])
    by_rank = {v["rank"]: v for v in sf0.values()}
    ok(all(spotf(sf1[m["sid"]]) == spotf(by_rank[str(m["to"]["rank"])]) for m in plan["moved"]), "Every moved player holds exactly the spot the preview showed (rank, position rank, tier, tier name, value)")
    changed = sorted(s_ for s_ in sf0 if sf0[s_] != sf1[s_])
    ok(changed == sorted(m["sid"] for m in plan["moved"]), f"Nobody outside the preview changed ({len(changed)} rows)")
    ok(sorted(int(v["value"]) for v in sf0.values()) == sorted(int(v["value"]) for v in sf1.values()), "SF's value ladder is exactly the same set")
    ok(not pg.evaluate("([s, d]) => SPM.syncOrder(s, d, ['RB', 'WR']).moved.length", [ppr_now, block(after, SF_RE)]), "SF's RBs and WRs now stand in AM PPR's order")
    ok(sf1[last[1]]["pos_rank"] == "25" and [v["sleeper_id"] for v in sorted(sf1.values(), key=lambda v: int(v["rank"])) if v["pos"] == "QB"] == [v["sleeper_id"] for v in sorted(sf0.values(), key=lambda v: int(v["rank"])) if v["pos"] == "QB"],
       f"QB wasn't ticked: SF's own QB order stands ({last[2]} still QB25)")
    hs = json.loads(repo.read("data/rank_history.json")); es = hs["events"][-1]
    ok(len(hs["events"]) == len(hs0["events"]) + 1 and es["src"] == "O" and es.get("from") == "ppr" and es["by"] == "tester" and sorted(x[0] for x in es["ranking"]) == changed,
       f"The SF event says it is a sync from AM PPR (src {es['src']}, from {es.get('from')}) and lists the {len(es['ranking'])} players")
    ok(all(hs["players"].get(s_, [])[:len(l)] == l for s_, l in hs0["players"].items()) and hs["events"][:-1] == hs0["events"], "Every earlier SF history entry and event kept")
    ss = snap(f"data/rank_snapshots/{es['ts'][:7]}.json")
    ok(ss["ts"] == es["ts"] and all(ss["players"][s_] == [int(v["rank"]), int(v["pos_rank"]), int(v["tier"]), int(v["value"])] for s_, v in sf1.items() if s_), "The SF snapshot is the synced SF board")
    ok(not pg.evaluate("() => document.getElementById('sync-dialog').open") and pg.inner_text("#eb-count").strip() == "All saved", "The preview closes and the editor shows the synced board with nothing pending")
    shown = {r_[0]: r_ for r_ in B()}
    ok(all(shown[s_][1] == int(v["rank"]) and shown[s_][4] == int(v["value"]) for s_, v in sf1.items() if s_), "The page shows the synced board")
    pg.reload(); pg.wait_for_selector("#rank-body tr.player"); pg.wait_for_timeout(1500)
    shown = {r_[0]: r_ for r_ in B()}
    ok(all(shown[s_][1] == int(v["rank"]) for s_, v in sf1.items() if s_) and pg.inner_text("#eb-count").strip() == "All saved", "…and still does after a reload")
    open_sync(pg)
    ok(pg.is_disabled("#sync-apply") and "Nothing to sync" in pg.inner_text("#sync-box"), "Opened again, there is nothing left to sync at RB and WR")
    pg.click("#sync-cancel")
    pg.context.close()

    # G. phone, dark theme: the preview fits
    ctx = br.new_context(viewport={"width": 390, "height": 844})
    pg = page(token=True, board="sf-tep", ctx=ctx)
    pg.evaluate("() => document.documentElement.setAttribute('data-theme', 'dark')")
    if pg.locator("#eb-sync").is_visible():
        open_sync(pg); pg.check('#sync-pos input[data-sync-pos="QB"]'); pg.wait_for_timeout(200)
        box = pg.evaluate("() => { const d = document.getElementById('sync-dialog').getBoundingClientRect(), b = document.getElementById('sync-box'); return [d.left, d.right, d.top, d.bottom, innerWidth, innerHeight, b.scrollWidth - b.clientWidth, document.documentElement.scrollWidth - innerWidth]; }")
        ok(box[0] >= 0 and box[1] <= box[4] and box[2] >= 0 and box[3] <= box[5] and box[6] <= 1 and box[7] <= 1, f"390px: the preview fits the screen with no sideways scroll ({[round(x) for x in box]})")
        if os.environ.get("SHOTS"): pg.screenshot(path=os.path.join(os.environ["SHOTS"], "sync_phone_dark.png"))
    else:
        ok(False, "390px, signed in: the editor bar offers the sync")
    ctx.close()
    ok(not errs, f"No page errors: {errs[:3]}")
    br.close()

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
