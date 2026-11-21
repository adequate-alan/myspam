"""Positional changes on both formats, asked once at publish (Alan, Nov 20: "ask when you publish a manual positional
ranking change, not every time you drag a player"; "nothing should propagate without my explicit confirmation").

Runs the real editor and publishing code against an in-memory GitHub repository (tests/gh_mock.py) holding this
checkout's index.html and both boards' history and snapshot files. Nothing touches GitHub or the files on disk.

Run from the repo root:  CHROMIUM=/path/to/chromium python3 tests/board_apply_check.py     (SHOTS=dir saves screenshots)

Checks:
A. AM PPR → AM SF PPR TE+, one move (WR12 → WR8): no prompt while editing; the prompt opens once at publish with Both
   formats suggested and nothing committed; the preview shows the mover before and after on both boards; the planned SF
   board equals the same move made by hand in the SF editor (an oracle page); Cancel publishes nothing and keeps the
   edits; Both formats is ONE commit with both blocks, both histories and both snapshots; only the mover's value changes
   on SF and it is SF's own (never AM PPR's); every SF QB and TE row is untouched; history events (SF: src M, from ppr)
   and snapshots equal the published boards; a reload of either board shows it published with nothing unsaved.
B. AM SF PPR TE+ → AM PPR, several moves at two positions in one publish: one prompt, the planned AM PPR board equals
   the same moves made by hand there, one commit, players who weren't moved keep AM PPR's own order.
C. This board only: the plain publish; the other board's block, history and snapshots are byte-identical.
D. No prompt without a positional change: a value edit, an overall move between players of other positions, Out for
   season. The test switch (window.__SPM_APPLY_OFF) never asks.
E. Conflicts: a mover who is Out for season on the other board is never moved and is named with the reason (alone: Both
   formats is off; with another mover: the other still applies); unpublished edits of the other board in this browser
   switch Both formats off; a preview that no longer matches what is live (the other board changed on GitHub) writes
   nothing on either board and the next prompt shows the fresh preview; a refused commit changes no file; a lost answer
   is settled for both boards with no second commit.
F. The optional full position order sync is still offered on SF, separately.
G. Phone and dark theme: the prompt fits the screen. No page errors.
"""
import csv, functools, http.server, io, json, os, re, socketserver, sys, threading
from playwright.sync_api import sync_playwright
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gh_mock import Repo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.environ.get("SHOTS")
def rd(p): return open(os.path.join(ROOT, p), "rb").read()
FILES = {"index.html": rd("index.html"), "data/rank_history.json": rd("data/rank_history.json"),
         "data/injury_overrides.json": rd("data/injury_overrides.json"), "data/boards/ppr/rank_history.json": rd("data/boards/ppr/rank_history.json")}
for d in ("data/rank_snapshots", "data/boards/ppr/rank_snapshots"):
    for f in os.listdir(os.path.join(ROOT, d)): FILES[f"{d}/{f}"] = rd(f"{d}/{f}")
SF_FILES = [f for f in FILES if f.startswith("data/rank_")]
PPR_FILES = [f for f in FILES if f.startswith("data/boards/ppr/")]

def block_re(name): return re.compile(rb"(const " + name.encode() + rb" = `\n)([\s\S]*?)(\n`;)")
RX = {"sf-tep": block_re("RANKINGS_CSV"), "ppr": block_re("RANKINGS_CSV_PPR")}
LABEL = {"sf-tep": "AM SF PPR TE+", "ppr": "AM PPR"}
OWN = {"sf-tep": SF_FILES, "ppr": PPR_FILES}
HIST = {"sf-tep": "data/rank_history.json", "ppr": "data/boards/ppr/rank_history.json"}
def block(html, b): return RX[b].search(html)[2].decode()
def outside(html):
    for rx in RX.values(): m = rx.search(html); html = html[:m.start(2)] + html[m.end(2):]
    return html
F = ("rank", "pos_rank", "tier", "value", "source")
def table(text):
    rows = list(csv.reader(io.StringIO(text.strip()))); h = rows[0]
    return {r[h.index("sleeper_id")]: dict(zip(h, r)) for r in rows[1:]}
def core(text): return {s: tuple(str(r[f]).strip() for f in F) for s, r in table(text).items()}
def order(text, pos): return [s for s, r in sorted(table(text).items(), key=lambda kv: int(kv[1]["rank"])) if r["pos"] == pos]

failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)

class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
srv = socketserver.TCPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=ROOT))
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"

with sync_playwright() as p:
    br = p.chromium.launch(**({"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}))
    errs = []
    repo = Repo(dict(FILES))
    def page(board, token=True, repo_=None, off=False, viewport=None, theme=None, pre=""):
        rp = repo_ or repo
        ctx = br.new_context(viewport=viewport or {"width": 1440, "height": 1000})
        pg = ctx.new_page(); pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.route("https://api.github.com/**", rp.handle)
        pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.sleeper\.(app|com)|use\.typekit\.net|fonts\.(googleapis|gstatic)\.com)/.*"), lambda r: r.abort())
        pg.route(re.compile(re.escape(BASE) + r"/(index\.html)?([?#].*)?$"), lambda r: r.fulfill(status=200, content_type="text/html; charset=utf-8", body=rp.read("index.html")))
        pg.route(re.compile(re.escape(BASE) + r"/data/(rank_history\.json|rank_snapshots/|boards/ppr/).*"), lambda r: (lambda b: r.fulfill(status=200, content_type="application/json", body=b) if b is not None else r.fulfill(status=404, body=""))(
            rp.read(r.request.url.split(BASE + "/")[1].split("?")[0])))
        init = "window.__SPM_TEST_HOOKS = true;" + (" window.__SPM_APPLY_OFF = true;" if off else "")
        first = f" localStorage.setItem('spm_edit_board', '{board}'); localStorage.setItem('spm_rk_board', '{board}');" + pre
        if token: first += " localStorage.setItem('spm_editor_token', 'test-token');"
        if theme: first += f" localStorage.setItem('spm_theme', '{theme}');"
        pg.add_init_script("try { " + init + " if (!sessionStorage.getItem('i0')) { sessionStorage.setItem('i0', '1'); " + first + " } } catch (e) {}")
        pg.goto(BASE + "/#rankings"); pg.wait_for_selector("#rank-body tr.player"); pg.wait_for_timeout(1800)
        return pg
    POS = lambda pg, pos: pg.evaluate("pos => SPM.edit.board().filter(p => p.pos === pos && p.posNum != null && Number(p.tier) < 90 && p.value > 0).sort((a, b) => a.posNum - b.posNum).map(p => [p.id, String(p.sid), p.name, p.rank, Math.round(p.value), String(p.tier)])", pos)
    move = lambda pg, pid, n: (pg.evaluate("([id, n]) => SPM.edit.movePlayer(id, n)", [pid, n]), pg.wait_for_timeout(350))
    dlg = lambda pg: pg.evaluate("() => document.getElementById('apply-dialog').open")
    DONE = "/Published|Publish failed|Publish stopped|Already live|Nothing to publish|Nothing was published|not confirmed|already had/"
    def press(pg):   # Save (or Publish when there is nothing new to save): returns "prompt" or the toast
        pg.evaluate("() => { const t = document.getElementById('toast'); t.textContent = ''; t.hidden = true; }")
        pg.click("#eb-publish" if pg.is_disabled("#eb-save") else "#eb-save")
        pg.wait_for_function("() => document.getElementById('apply-dialog').open || " + DONE + ".test(document.getElementById('toast').textContent)", timeout=30000)
        pg.wait_for_timeout(300)
        return "prompt" if dlg(pg) else pg.inner_text("#toast")
    def answer(pg, where=None, btn="#apply-confirm"):
        pg.evaluate("() => { const t = document.getElementById('toast'); t.textContent = ''; t.hidden = true; }")
        if where: pg.check(f"#apply-{where}")
        pg.click(btn)
        pg.wait_for_function("() => " + DONE + ".test(document.getElementById('toast').textContent)", timeout=30000)
        pg.wait_for_timeout(400); return pg.inner_text("#toast")
    plan = lambda pg: pg.evaluate("() => SPM.applyPlan()")
    def oracle(other, steps, repo_=None):   # the same moves made by hand in the other board's own editor, unpublished
        og = page(other, token=False, repo_=repo_)
        for sid, to in steps:
            pid = og.evaluate("sid => SPM.edit.board().find(p => String(p.sid) === sid).id", sid); move(og, pid, to)
        out = og.evaluate("() => SPM.edit.draft()"); og.context.close(); return out
    def shot(pg, name):
        if SHOTS: os.makedirs(SHOTS, exist_ok=True); pg.screenshot(path=os.path.join(SHOTS, name + ".png"))
    def last_event(b): return json.loads(repo.read(HIST[b]))["events"][-1]
    def snap_ok(b):   # the board's newest snapshot is the published block, stamped with the publish event's time
        d = "data/rank_snapshots/" if b == "sf-tep" else "data/boards/ppr/rank_snapshots/"
        ev = last_event(b); s = json.loads(repo.read(f"{d}{ev['snap']}.json"))["snapshots"][-1]; t = table(block(repo.read("index.html"), b))
        return s["ts"] == ev["ts"] and len(s["players"]) == len(t) and all(s["players"].get(sid) == [int(r["rank"]), int(r["pos_rank"]), int(r["tier"]), int(r["value"])] for sid, r in t.items())

    # ---------- A. AM PPR → AM SF PPR TE+, one move
    pg = page("ppr")
    wr = POS(pg, "WR"); mv = wr[11]
    ok(pg.evaluate("() => SPM.boards().active") == "ppr", "A: AM PPR is the edited board")
    n0 = len(repo.log()); snap0 = {f: repo.read(f) for f in FILES}
    move(pg, mv[0], 8)
    ok(not dlg(pg), "A: no prompt while editing (a move alone never asks)")
    move(pg, mv[0], 9); move(pg, mv[0], 8)
    ok(not dlg(pg), "A: …also not after several moves of the same player")
    r = press(pg)
    ok(r == "prompt" and len(repo.log()) == n0, "A: the prompt opens at publish, and nothing is committed before the answer")
    txt = pg.inner_text("#apply-dialog")
    ok("Apply positional changes to both formats?" .lower() in txt.lower() and "WR positional order on AM PPR" in txt, "A: it names the position and the board ('You've changed the WR positional order on AM PPR')")
    ok(pg.is_checked("#apply-both") and not pg.is_checked("#apply-only") and "suggested" in txt.lower(), "A: Both formats is the suggested, preselected option")
    ok("AM PPR only" in txt and "Keep AM SF PPR TE+ unchanged" in txt, "A: the other option is 'AM PPR only · Keep AM SF PPR TE+ unchanged'")
    ok(pg.inner_text("#apply-confirm") == "Publish to both formats", "A: the button says what it will do (Publish to both formats)")
    pl = plan(pg)
    ok(pl["positions"] == ["WR"] and [m["sid"] for m in pl["movers"]] == [mv[1]] and [m["sid"] for m in pl["applied"]] == [mv[1]], f"A: one mover, {mv[2]}, on both boards (not the players he passed)")
    a = pl["applied"][0]; box = pg.inner_text("#apply-box")
    ok(mv[2] in box and f"#{a['from']['rank']} · WR{a['from']['pos_rank']}" in box and f"#{a['to']['rank']} · WR{a['to']['pos_rank']}" in box and f"{a['from']['value']:,} → {a['to']['value']:,}" in box,
       f"A: the preview shows him before and after on AM SF PPR TE+ (#{a['from']['rank']} WR{a['from']['pos_rank']} {a['from']['value']:,} → #{a['to']['rank']} WR{a['to']['pos_rank']} {a['to']['value']:,})")
    s = pl["movers"][0]
    ok(f"#{s['from']['rank']} · WR12" in box and f"#{s['to']['rank']} · WR8" in box and f"{s['from']['value']:,} → {s['to']['value']:,}" in box, "A: …and before and after on AM PPR")
    shot(pg, "prompt-desktop-light")
    pg.click("#apply-toggle"); ok(pg.locator("#apply-box").is_hidden(), "A: 'Preview changes before publishing' folds the preview away"); pg.click("#apply-toggle")
    sf0 = block(repo.read("index.html"), "sf-tep"); ppr0 = block(repo.read("index.html"), "ppr")
    orc = oracle("sf-tep", pl["steps"])
    ok(core(orc) == core(pl["csv"]), "A: the planned SF board equals the same move made by hand in the SF editor (rank, position rank, tier, value, source of every player)")
    c0, c1 = core(sf0), core(pl["csv"])
    chg = [x for x in c0 if c0[x][3] != c1[x][3]]
    ok(chg == [mv[1]] or all(abs(int(c0[x][3]) - int(c1[x][3])) <= 1 for x in chg if x != mv[1]), f"A: on SF only the mover's value changes ({len(chg)} value(s))")
    ok(all(c0[x][2] == c1[x][2] and c0[x][4] == c1[x][4] for x in c0 if x != mv[1]), "A: nobody else's tier or Manual / Auto changes on SF")
    t0 = table(sf0); qbte = [x for x in t0 if t0[x]["pos"] in ("QB", "TE")]
    ok(all(c0[x][1:] == c1[x][1:] for x in qbte), f"A: every SF QB and TE keeps his position rank, tier and value ({len(qbte)} players: the Superflex and TE-premium ladders are untouched)")
    msg = answer(pg, btn="#apply-cancel")
    ok("Nothing was published" in msg and len(repo.log()) == n0 and all(repo.read(f) == snap0[f] for f in FILES), "A: Cancel publishes nothing on either board")
    ok(POS(pg, "WR")[7][0] == mv[0] and not pg.is_disabled("#eb-publish"), "A: …and the edit is still saved in this browser, ready to publish")
    r = press(pg); ok(r == "prompt" and pg.is_checked("#apply-both"), "A: Publish asks again (once per publish)")
    before = repo.read("index.html")
    msg = answer(pg)
    after = repo.read("index.html"); new = repo.log()[n0:]
    ok("Published and confirmed" in msg and "1 player also moved on AM SF PPR TE+" in msg, f"A: Both formats publishes ({msg[:110]!r})")
    ok(len(new) == 1 and new[0].startswith("AM PPR rankings edit by @tester") and "positional changes on AM SF PPR TE+ (1 player)" in new[0].splitlines()[0], f"A: ONE commit for both boards ({new[0].splitlines()[0]!r})")
    ok(outside(before) == outside(after), "A: nothing outside the two rankings blocks changes")
    ok(core(block(after, "sf-tep")) == core(orc), "A: the published SF block equals the move made by hand")
    ok(order(block(after, "ppr"), "WR")[7] == mv[1] and order(block(after, "sf-tep"), "WR")[7] == mv[1], f"A: {mv[2]} is WR8 on both boards")
    vp, vs = table(block(after, "ppr"))[mv[1]]["value"], table(block(after, "sf-tep"))[mv[1]]["value"]
    ok(vs == str(a["to"]["value"]) and vs != vp, f"A: his SF value is SF's own ({vs}), not AM PPR's ({vp})")
    ok(all(repo.read(f) != snap0[f] for f in HIST.values()), "A: both boards' histories are written in that commit")
    es, ep = last_event("sf-tep"), last_event("ppr")
    ok(es["ts"] == ep["ts"] and es["src"] == "M" and es.get("from") == "ppr" and not ep.get("from"), f"A: one publish time on both; the SF event is a manual move marked as coming from AM PPR (src {es['src']}, from {es.get('from')})")
    ok(any(str(x[0] if isinstance(x, list) else x.get("id", "")) == mv[1] or mv[1] in json.dumps(x) for x in es["ranking"]), "A: the SF event lists the mover's ranking change")
    ok(snap_ok("sf-tep") and snap_ok("ppr"), "A: both snapshots equal the published boards at the publish time")
    ok(pg.evaluate("() => SPM.edit.unsaved()") == 0 and pg.is_disabled("#eb-publish"), "A: nothing is left unsaved or unpublished")
    pg.reload(); pg.wait_for_selector("#rank-body tr.player"); pg.wait_for_timeout(1500)
    ok(POS(pg, "WR")[7][0] == mv[0] and pg.evaluate("() => SPM.edit.unsaved()") == 0 and core(pg.evaluate("() => SPM.edit.draft()")) == core(block(after, "ppr")), "A: after a reload AM PPR shows the published board")
    pg.context.close()
    pg = page("sf-tep")
    ok(core(pg.evaluate("() => SPM.edit.draft()")) == core(block(after, "sf-tep")) and pg.evaluate("() => SPM.edit.unsaved()") == 0 and pg.is_disabled("#eb-publish"),
       "A: the SF editor opens on the published SF board with nothing unsaved")

    # ---------- B. AM SF PPR TE+ → AM PPR, several moves at two positions in one publish
    ok(pg.locator("#eb-sync").is_visible(), "F: the optional full 'Sync order from AM PPR' is still offered on SF, separately")
    rb, te = POS(pg, "RB"), POS(pg, "TE")
    n0 = len(repo.log()); ppr1 = block(repo.read("index.html"), "ppr")
    move(pg, rb[14][0], 10); move(pg, rb[3][0], 6); move(pg, te[8][0], 5)
    ok(not dlg(pg), "B: three moves, no prompt yet")
    r = press(pg); pl = plan(pg); txt = pg.inner_text("#apply-dialog")
    ok(r == "prompt" and pl["positions"] == ["RB", "TE"] and "RB and TE positional order on AM SF PPR TE+" in txt and "AM SF PPR TE+ only" in txt, "B: one prompt for the whole publish, naming RB and TE on AM SF PPR TE+")
    ok({m["sid"] for m in pl["movers"]} == {rb[14][1], rb[3][1], te[8][1]}, f"B: the movers are the three players moved ({[m['name'] for m in pl['movers']]})")
    ok(not pl["blocked"] and len(pl["applied"]) + len(pl["skipped"]) == 3, f"B: Both formats is offered ({len(pl['applied'])} applied, {len(pl['skipped'])} left in place)")
    orc = oracle("ppr", pl["steps"])
    ok(core(orc) == core(pl["csv"]), "B: the planned AM PPR board equals the same moves made by hand in the AM PPR editor")
    applied = {m["sid"] for m in pl["applied"]}
    for pos in ("QB", "RB", "WR", "TE"):
        o0, o1 = [x for x in order(ppr1, pos) if x not in applied], [x for x in order(pl["csv"], pos) if x not in applied]
        ok(o0 == o1, f"B: {pos}s who weren't moved keep AM PPR's own order")
    src_new = pg.evaluate("() => SPM.edit.draft()")
    for m in pl["applied"]:
        so, do = order(src_new, m["pos"]), order(pl["csv"], m["pos"]); i = so.index(m["sid"])
        prev = next((x for x in reversed(so[:i]) if x in do), None)
        ok(prev is None or do.index(prev) < do.index(m["sid"]), f"B: on AM PPR {m['name']} sits behind the player he now follows on SF")
    c0, c1 = core(ppr1), core(pl["csv"])
    ok(all(abs(int(c0[x][3]) - int(c1[x][3])) <= 1 for x in c0 if x not in applied), "B: on AM PPR only the movers' values change (others at most a whole-point step)")
    tp = table(src_new)
    ok(all(str(m["to"]["value"]) != tp[m["sid"]]["value"] or m["to"]["value"] == m["from"]["value"] for m in pl["applied"]), "B: no mover takes his SF value on AM PPR")
    before = repo.read("index.html"); msg = answer(pg); after = repo.read("index.html"); new = repo.log()[n0:]
    ok("Published and confirmed" in msg and len(new) == 1 and new[0].startswith("Rankings edit by @tester") and "positional changes on AM PPR" in new[0], f"B: ONE commit ({new[0].splitlines()[0]!r})")
    ok(core(block(after, "ppr")) == core(orc) and core(block(after, "sf-tep")) == core(src_new), "B: both published blocks are exactly the previewed boards")
    es, ep = last_event("sf-tep"), last_event("ppr")
    ok(es["ts"] == ep["ts"] and ep.get("from") == "sf-tep" and ep["src"] == "M" and snap_ok("sf-tep") and snap_ok("ppr"), "B: histories and snapshots of both boards are written and equal the boards (AM PPR's event: from sf-tep)")
    pg.context.close()

    # ---------- C. This board only
    pg = page("ppr"); wr = POS(pg, "WR")
    n0 = len(repo.log()); before = repo.read("index.html"); keep = {f: repo.read(f) for f in SF_FILES}
    move(pg, wr[20][0], 18)
    r = press(pg); pg.check("#apply-only"); pg.wait_for_timeout(150)
    ok(r == "prompt" and pg.inner_text("#apply-confirm") == "Publish AM PPR only" and "unchanged with AM PPR only" in pg.inner_text("#apply-box"), "C: picking AM PPR only says so on the button and in the preview")
    msg = answer(pg); after = repo.read("index.html"); new = repo.log()[n0:]
    ok("Published and confirmed" in msg and "AM SF PPR TE+" not in msg and len(new) == 1 and "AM SF PPR TE+" not in new[0], f"C: the plain AM PPR publish ({new[0].splitlines()[0]!r})")
    ok(block(after, "sf-tep") == block(before, "sf-tep") and all(repo.read(f) == keep[f] for f in SF_FILES), "C: the SF block, history and snapshots are byte-identical")
    ok(order(block(after, "ppr"), "WR")[17] == wr[20][1], "C: the move is live on AM PPR")

    # ---------- D. no prompt without a positional change
    n0 = len(repo.log())
    b = pg.evaluate("() => SPM.edit.board().filter(p => p.value > 400 && Number(p.tier) < 90).sort((x, y) => x.rank - y.rank).map(p => [p.id, p.pos, p.rank, Math.round(p.value), p.name])")
    i = next(k for k in range(20, len(b) - 3) if b[k][1] != b[k + 1][1] and b[k][3] - b[k + 1][3] > 3)
    pg.evaluate("([id, r]) => SPM.edit.moveOverall(id, r)", [b[i + 1][0], b[i][2]]); pg.wait_for_timeout(400)
    r = press(pg)
    ok(r != "prompt" and "Published and confirmed" in r and len(repo.log()) == n0 + 1, f"D: an overall move between players of other positions ({b[i + 1][4]} past {b[i][4]}) publishes without asking")
    j = next(k for k in range(30, len(b) - 3) if b[k - 1][3] - b[k][3] > 4 and b[k][3] - b[k + 1][3] > 4)
    pg.evaluate("([id, v]) => SPM.edit.applyValue(id, v)", [b[j][0], b[j][3] - 1]); pg.wait_for_timeout(400)
    r = press(pg) if pg.evaluate("() => SPM.edit.unsaved()") else "skipped"
    ok(r != "prompt", f"D: a value edit publishes without asking ({r[:40]!r})")
    pg.context.close()
    out_sid = None
    pg = page("sf-tep"); wr = POS(pg, "WR"); out = wr[30]; out_sid = out[1]
    pg.evaluate("id => SPM.edit.sendOut(id)", out[0]); pg.wait_for_timeout(500)
    keep = {f: repo.read(f) for f in PPR_FILES}; before = repo.read("index.html")
    r = press(pg)
    ok(r != "prompt" and "Published and confirmed" in r and block(repo.read("index.html"), "ppr") == block(before, "ppr") and all(repo.read(f) == keep[f] for f in PPR_FILES),
       f"D: Out for season ({out[2]} on SF) is a status, not an order change: no prompt, AM PPR untouched")
    pg.context.close()
    pg = page("ppr", off=True); wr = POS(pg, "WR"); n0 = len(repo.log()); before = repo.read("index.html")
    k = next(i for i, x in enumerate(wr) if x[1] != out_sid and i > 40)
    move(pg, wr[k][0], k); r = press(pg)
    ok(r != "prompt" and "Published and confirmed" in r and block(repo.read("index.html"), "sf-tep") == block(before, "sf-tep"), "D: the test switch never asks and publishes this board only")
    pg.context.close()

    # ---------- E. conflicts
    pg = page("ppr"); wr = POS(pg, "WR"); n0 = len(repo.log())
    io_ = next(i for i, x in enumerate(wr) if x[1] == out_sid)
    move(pg, wr[io_][0], io_ - 2)   # the player who is Out for season on SF moves up three spots on AM PPR
    r = press(pg); pl = plan(pg); txt = pg.inner_text("#apply-dialog")
    ok(r == "prompt" and not pl["applied"] and [s_["sid"] for s_ in pl["skipped"]] == [out_sid] and "Out for season on AM SF PPR TE+" in pl["skipped"][0]["why"], f"E: a mover who is Out for season on SF is never moved there ({pl['skipped'][0]['why'] if pl['skipped'] else pl})")
    ok(pg.is_disabled("#apply-both") and pg.is_checked("#apply-only") and pl["skipped"][0]["name"] in pg.inner_text("#apply-flag") and pg.inner_text("#apply-confirm") == "Publish AM PPR only", "E: …Both formats is switched off and the reason names him")
    before = repo.read("index.html"); msg = answer(pg)
    ok("Published and confirmed" in msg and block(repo.read("index.html"), "sf-tep") == block(before, "sf-tep"), "E: …and the publish is AM PPR's alone")
    wr = POS(pg, "WR"); io_ = next(i for i, x in enumerate(wr) if x[1] == out_sid)
    move(pg, wr[io_][0], io_ + 3); move(pg, wr[5][0], 4)
    r = press(pg); pl = plan(pg)
    ok(r == "prompt" and [m["sid"] for m in pl["applied"]] == [wr[5][1]] and [s_["sid"] for s_ in pl["skipped"]] == [out_sid] and not pl["blocked"] and not pg.is_disabled("#apply-both"),
       "E: with a second mover Both formats stays on: he applies, the Out for season player is left in place")
    ok(pl["skipped"][0]["name"] in pg.inner_text("#apply-flag") and "Not applied on AM SF PPR TE+" in pg.inner_text("#apply-box"), "E: …and the prompt flags it instead of forcing a rank")
    sfb = block(repo.read("index.html"), "sf-tep"); msg = answer(pg); sfa = block(repo.read("index.html"), "sf-tep")
    ok("Published and confirmed" in msg and table(sfa)[out_sid] == table(sfb)[out_sid] and table(sfa)[wr[5][1]]["pos_rank"] == str(pl["applied"][0]["to"]["pos_rank"]) != table(sfb)[wr[5][1]]["pos_rank"],
       f"E: published: his SF row is untouched, the other mover is WR{pl['applied'][0]['to']['pos_rank']} on SF")

    # unpublished edits of the other board in this browser
    wr = POS(pg, "WR"); move(pg, wr[24][0], 23)
    pg.evaluate("() => localStorage.setItem('spm_local_edits', JSON.stringify({ 'x|wr': { rank: '1' } }))")
    r = press(pg)
    ok(r == "prompt" and pg.is_disabled("#apply-both") and "unpublished AM SF PPR TE+ edits" in pg.inner_text("#apply-flag"), "E: unpublished SF edits in this browser switch Both formats off, with the reason")
    pg.evaluate("() => localStorage.removeItem('spm_local_edits')")
    n0 = len(repo.log()); msg = answer(pg, btn="#apply-cancel")
    # a stale preview: the other board changes on GitHub while the prompt is open
    r = press(pg); pl = plan(pg)
    ok(r == "prompt" and not pg.is_disabled("#apply-both") and len(pl["applied"]) == 1, "E: with those gone Both formats is offered again")
    html = repo.read("index.html"); sfb = block(html, "sf-tep"); t = table(sfb); msid = pl["applied"][0]["sid"]
    rows = sfb.split("\n"); h = rows[0].split(","); vi = h.index("value")
    vals = {int(r_["value"]) for r_ in t.values()}; v0 = int(t[msid]["value"]); v1 = v0 - 1 if v0 - 1 not in vals else v0 + 1
    li = next(i for i, ln in enumerate(rows) if ln.split(",")[h.index("sleeper_id")] == msid) if all('"' not in ln for ln in rows) else None
    if li is None:
        rr = list(csv.reader(io.StringIO(sfb))); li = next(i for i, x in enumerate(rr) if x[h.index("sleeper_id")] == msid); cells = rr[li]
    else: cells = rows[li].split(",")
    assert v1 not in vals
    cells[vi] = str(v1); buf = io.StringIO(); csv.writer(buf, lineterminator="").writerow(cells); rows[li] = buf.getvalue()
    m = RX["sf-tep"].search(html); repo.commit_file("index.html", html[:m.start(2)] + "\n".join(rows).encode() + html[m.end(2):], "SF value changed elsewhere")
    n0 = len(repo.log()); snap0 = {f: repo.read(f) for f in FILES}
    msg = answer(pg)
    ok("changed since this preview" in msg and "nothing was published on either board" in msg and len(repo.log()) == n0 and all(repo.read(f) == snap0[f] for f in FILES), f"E: a stale preview writes nothing on either board ({msg[:90]!r})")
    r = press(pg); pl2 = plan(pg)
    ok(r == "prompt" and pl2["applied"][0]["from"]["value"] == v1 and f"{v1:,}" in pg.inner_text("#apply-box"), f"E: the next prompt shows the fresh preview (his SF value now {v1:,})")
    # a refused commit
    repo.faults["patch"] = 500; msg = answer(pg); repo.faults.clear()
    ok("Publish failed" in msg and len(repo.log()) == n0 and all(repo.read(f) == snap0[f] for f in FILES), "E: a commit GitHub refuses leaves both blocks and every history and snapshot file unchanged")
    # a lost answer: the commit landed, the browser never heard
    r = press(pg); repo.faults["offline_after_patch"] = True; msg = answer(pg); repo.faults.clear()
    landed = len(repo.log()) == n0 + 1
    ok("not confirmed" in msg and landed and pg.evaluate("() => (JSON.parse(localStorage.getItem('spm_publish_pending:ppr') || 'null') || {}).twin") == "sf-tep",
       f"E: offline right after the commit: 'not confirmed', and the pending record names both boards ({msg[:60]!r})")
    live = repo.read("index.html")
    pg.evaluate("() => { const t = document.getElementById('toast'); t.textContent = ''; t.hidden = true; }")
    pg.click("#eb-publish"); pg.wait_for_function("() => " + DONE + ".test(document.getElementById('toast').textContent)", timeout=30000); pg.wait_for_timeout(400)
    msg = pg.inner_text("#toast")
    ok("Already live" in msg and len(repo.log()) == n0 + 1 and not dlg(pg), f"E: the next Publish settles it: no second commit, no second prompt ({msg[:60]!r})")
    ok(core(pg.evaluate("() => SPM.edit.draft()")) == core(block(live, "ppr")) and pg.evaluate("() => SPM.edit.unsaved()") == 0, "E: …this board shows what landed")
    ok(core(pg.evaluate("() => SPM.boardBlock('sf-tep')")) == core(block(live, "sf-tep")), "E: …and so does the page's copy of the SF board")
    ok(order(block(live, "sf-tep"), "WR").index(msid) == pl2["applied"][0]["to"]["pos_rank"] - 1 and snap_ok("sf-tep") and snap_ok("ppr"), "E: both boards landed together, with their snapshots")
    pg.context.close()

    # ---------- G. phone and dark theme
    for name, vp, theme in (("phone-light", {"width": 390, "height": 800}, "light"), ("phone-dark", {"width": 390, "height": 800}, "dark"), ("desktop-dark", {"width": 1440, "height": 1000}, "dark")):
        pg = page("ppr", viewport=vp, theme=theme); wr = POS(pg, "WR")
        move(pg, wr[15][0], 12); move(pg, wr[9][0], 12)
        if pg.locator("#eb-save").is_visible(): r = press(pg)
        else: pg.evaluate("() => document.getElementById('eb-save').click()"); pg.wait_for_function("() => document.getElementById('apply-dialog').open", timeout=30000); r = "prompt"
        box = pg.evaluate("() => { const d = document.getElementById('apply-dialog'), r = d.getBoundingClientRect(); const bx = document.getElementById('apply-box'); const wide = [...d.querySelectorAll('*')].filter(e => { const q = e.getBoundingClientRect(); return q.width > 0 && (q.right > r.right + 1 || q.left < r.left - 1); }).length + (bx.scrollWidth > bx.clientWidth + 1 ? 1 : 0); return { l: r.left, r: r.right, t: r.top, b: r.bottom, w: innerWidth, h: innerHeight, wide, sx: document.documentElement.scrollWidth, theme: document.documentElement.getAttribute('data-theme') }; }")
        ok(r == "prompt" and box["l"] >= 0 and box["r"] <= box["w"] + 0.5 and box["t"] >= 0 and box["b"] <= box["h"] + 0.5 and box["wide"] == 0 and box["sx"] <= box["w"],
           f"G: {name}: the prompt fits the screen with nothing cut off ({box})")
        ok(box["theme"] == theme, f"G: {name}: theme is {theme}")
        btn = pg.evaluate("() => { const b = document.getElementById('apply-confirm').getBoundingClientRect(); return b.bottom <= innerHeight && b.top >= 0 && b.height >= 32; }")
        ok(btn, f"G: {name}: the publish button is on screen")
        shot(pg, "prompt-" + name)
        pg.context.close()

    ok(not errs, f"No page errors {errs[:3]}")
    br.close()
srv.shutdown()
print(f"\n{len(failures)} failed" if failures else "\nAll board apply checks passed.")
sys.exit(1 if failures else 0)
