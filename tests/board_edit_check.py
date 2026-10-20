"""Editing, publishing and history per ranking set (Alan, Oct 14: "getting the PPR editor working independently").

The page's real editor and publishing code runs against an in-memory GitHub repository (tests/gh_mock.py) holding this
checkout's index.html and both boards' history and snapshot files; the page is served from that repository, so a
reload shows what was published. Nothing touches GitHub or the files on disk.

Run from the repo root:  CHROMIUM=/path/to/chromium python3 tests/board_edit_check.py

Checks:
1. The switch: on the Rankings tab, showing AM PPR offers "Edit AM PPR"; it reloads with AM PPR as the edited board,
   the editor bar names it, and SPM.boardCheck() still passes with AM PPR active.
2. AM PPR edits are its own: an arrow move changes only the two players' ranks and the mover's value, is stored only
   under the board's ":ppr" keys (the original spm_* keys untouched), and moving back restores the board exactly with
   nothing unsaved.
3. Overall tiers on the All view: a tier-header action moves a player across a boundary at the same rank (his tier and
   value change, nobody else's rank or tier), and the reverse action restores the board exactly.
4. A value edit that fits his rank is kept exactly.
5. Publish: one commit ("AM PPR rankings edit by @…"), changing only the RANKINGS_CSV_PPR block of index.html (the
   RANKINGS_CSV block and everything else byte-identical) plus data/boards/ppr/rank_history.json (one new event, every
   earlier entry kept) and data/boards/ppr/rank_snapshots/<YYYY-MM>.json (one new snapshot equal to the published
   board); the AM SF PPR TE+ history and snapshots are untouched. A reload shows the published AM PPR board with
   nothing pending.
6. Back on AM SF PPR TE+ ("Edit AM SF PPR TE+"): a move publishes only RANKINGS_CSV and the original history and
   snapshot files; the AM PPR block and its files are untouched. No page errors.
"""
import csv, functools, http.server, io, json, os, re, socketserver, sys, threading
from playwright.sync_api import sync_playwright
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gh_mock import Repo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def rd(p): return open(os.path.join(ROOT, p), "rb").read()
FILES = {"index.html": rd("index.html"), "data/rank_history.json": rd("data/rank_history.json"),
         "data/injury_overrides.json": rd("data/injury_overrides.json")}
for d in ("data/rank_snapshots", "data/boards/ppr/rank_snapshots"):
    for f in os.listdir(os.path.join(ROOT, d)): FILES[f"{d}/{f}"] = rd(f"{d}/{f}")
FILES["data/boards/ppr/rank_history.json"] = rd("data/boards/ppr/rank_history.json")
SF_FILES = [p for p in FILES if p == "data/rank_history.json" or p.startswith("data/rank_snapshots/")]
PPR_FILES = [p for p in FILES if p.startswith("data/boards/ppr/")]

def block_re(name): return re.compile(rb"(const " + name.encode() + rb" = `\n)([\s\S]*?)(\n`;)")
SF_RE, PPR_RE = block_re("RANKINGS_CSV"), block_re("RANKINGS_CSV_PPR")
def block(html, rx): return rx.search(html)[2].decode()
def outside(html, rx): m = rx.search(html); return html[:m.start(2)] + html[m.end(2):]
def table(text):
    rows = list(csv.reader(io.StringIO(text))); h = rows[0]
    return {r[h.index("sleeper_id")]: {k: r[h.index(k)] for k in ("rank", "pos_rank", "tier", "value")} for r in rows[1:]}

failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)

class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
srv = socketserver.TCPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=ROOT))
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"

BOARD = """() => SPM.edit.board().map(p => [String(p.sid), p.rank, p.posNum, String(p.tier), Math.round(p.value)])"""
ROWS = """() => [...document.querySelectorAll('#rank-body tr.player')].map(tr => ({ id: tr.dataset.id, name: tr.querySelector('.pl-name').textContent.trim() }))"""

repo = Repo(dict(FILES))
with sync_playwright() as p:
    br = p.chromium.launch(**({"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}))
    errs = []
    ctx = br.new_context(viewport={"width": 1440, "height": 1000})
    pg = ctx.new_page(); pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.route("https://api.github.com/**", repo.handle)
    pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.sleeper\.(app|com)|use\.typekit\.net|fonts\.(googleapis|gstatic)\.com)/.*"), lambda r: r.abort())
    pg.route(re.compile(re.escape(BASE) + r"/(index\.html)?([?#].*)?$"), lambda r: r.fulfill(status=200, content_type="text/html; charset=utf-8", body=repo.read("index.html")))
    pg.route(re.compile(re.escape(BASE) + r"/data/(rank_history\.json|rank_snapshots/|boards/ppr/).*"), lambda r: (lambda b: r.fulfill(status=200, content_type="application/json", body=b) if b is not None else r.fulfill(status=404, body=""))(
        repo.read(r.request.url.split(BASE + "/")[1].split("?")[0])))
    pg.add_init_script("try { window.__SPM_TEST_HOOKS = true; localStorage.setItem('spm_editor_token', 'test-token'); } catch (e) {}")

    def load():
        pg.wait_for_selector("#rank-body tr.player"); pg.wait_for_timeout(1800)
    def all_tab():
        pg.click("#pos-chips button:has-text('All')"); pg.wait_for_timeout(300)
    def pick_board(bid):
        pg.evaluate("bid => { const s = document.getElementById('rk-board'); s.value = bid; s.dispatchEvent(new Event('change', { bubbles: true })); }", bid)
        pg.wait_for_timeout(700)
    def board(): return pg.evaluate(BOARD)
    def keys(): return {k: pg.evaluate("k => localStorage.getItem(k)", k) for k in pg.evaluate("() => Object.keys(localStorage)")}
    def arrow(name, d):
        pg.locator("#rank-body tr.player", has_text=name).first.locator(f'.arrow[data-dir="{d}"]').click(force=True); pg.wait_for_timeout(400)
    def unsaved(): return pg.inner_text("#eb-count").strip()
    def save():
        pg.evaluate("() => { const t = document.getElementById('toast'); t.textContent = ''; t.hidden = true; }")
        pg.click("#eb-save")
        pg.wait_for_function("() => /Publish|Already live|Nothing to publish|Saved/.test(document.getElementById('toast').textContent)", timeout=20000)
        pg.wait_for_timeout(300); return pg.inner_text("#toast")
    def edge_buttons():
        return pg.evaluate("""() => [...document.querySelectorAll('#rank-body [data-tier-act=edge]')].map(b => ({ id: b.dataset.id, to: b.dataset.to, text: b.textContent }))""")
    def click_edge(pid, to):
        pg.evaluate("([id, to]) => document.querySelector(`#rank-body [data-tier-act=edge][data-id='${id}'][data-to='${to}']`).click()", [pid, to]); pg.wait_for_timeout(600)

    # 1. the switch
    pg.goto(BASE + "/#rankings"); load()
    ok(pg.evaluate("() => SPM.boards().active") == "sf-tep", "Starts editing AM SF PPR TE+")
    if pg.locator("#league-controls [data-view=base]").is_visible(): pg.click("#league-controls [data-view=base]"); pg.wait_for_timeout(400)
    pick_board("ppr")
    ok(pg.locator("#ed-switch").is_visible() and "Edit AM PPR" in pg.inner_text("#ed-switch"), "Showing AM PPR offers Edit AM PPR")
    sf_keys0 = {k: v for k, v in keys().items() if k.startswith("spm_") and ":" not in k and k not in ("spm_rk_board", "spm_edit_board", "spm_rk_sort")}
    with pg.expect_navigation(): pg.click("#ed-switch")
    load()
    ok(pg.evaluate("() => SPM.boards().active") == "ppr", "Edit AM PPR reloads with AM PPR as the edited board")
    ok(pg.locator("#editor-bar").is_visible() and "AM PPR" in pg.inner_text("#eb-board"), f"The editor bar names it: {pg.inner_text('#eb-board')!r}")
    ok(pg.locator("#ed-switch-wrap").is_hidden(), "No switch while the edited board is shown")
    bc = pg.evaluate("async () => (await SPM.boardCheck()).filter(c => !c.pass).map(c => c.check)")
    ok(not bc, f"SPM.boardCheck() passes with AM PPR active {bc[:3]}")
    all_tab()
    start = board(); rows = pg.evaluate(ROWS)
    ok(len(start) == 260 and len(rows) == 260, f"AM PPR board: {len(start)} players, {len(rows)} rows")
    pub = table(block(repo.read("index.html"), PPR_RE))
    ok(all(pub[s][k] == str(v) for s, *vals in start for k, v in zip(("rank", "pos_rank", "tier", "value"), vals)), "The edited board is the published RANKINGS_CSV_PPR exactly")

    # 2. an arrow move and its undo
    mover, above = rows[49]["name"], rows[48]["name"]
    arrow(mover, -1); mid = board()
    diff = [(a, b) for a, b in zip(sorted(start), sorted(mid)) if a != b]
    ranks = {(a[1], b[1]) for a, b in diff}
    vals = [(a, b) for a, b in diff if a[4] != b[4]]
    ok(len(diff) == 2 and ranks == {(50, 49), (49, 50)}, f"Arrow move: only the two players' ranks change {[(a[1], b[1]) for a, b in diff][:4]}")
    ok(len(vals) == 1 and vals[0][0][1] == 50, f"Only the mover's value changes {[(a[4], b[4]) for a, b in vals]}")
    k = keys()
    ok(k.get("spm_local_edits:ppr") or k.get("spm_value_touch:ppr") or k.get("spm_edit_session:ppr") or unsaved() != "All saved",
       f"The move is AM PPR's ({unsaved()!r})")
    sf_now = {kk: v for kk, v in k.items() if kk.startswith("spm_") and ":" not in kk and kk not in ("spm_rk_board", "spm_edit_board", "spm_rk_sort")}
    ok(sf_now == sf_keys0, f"The original spm_* keys are untouched: {sorted(set(sf_now) ^ set(sf_keys0))[:4]}")
    arrow(mover, 1)
    ok(board() == start and unsaved() == "All saved", f"Moving back restores AM PPR exactly, nothing unsaved ({unsaved()!r})")

    # 3. overall tiers on the All view: a same-rank tier move and its reverse
    eb = edge_buttons()
    ok(len(eb) >= 2, f"The All view offers tier-boundary actions on AM PPR ({len(eb)})")
    e = eb[len(eb) // 2]
    pl = pg.evaluate("id => { const p = SPM.edit.board().find(p => String(p.id) === String(id)); return [String(p.sid), p.rank, String(p.tier)]; }", e["id"])
    click_edge(e["id"], e["to"])
    tm = board(); d = [(a, b) for a, b in zip(sorted(start), sorted(tm)) if a != b]
    me = [b for a, b in d if a[0] == pl[0]]
    others = [(a, b) for a, b in d if a[0] != pl[0] and (a[1:4] != b[1:4] or abs(a[4] - b[4]) > 5)]
    ok(me and me[0][1] == pl[1] and me[0][3] == e["to"], f"{e['text']}: same rank, Tier {pl[2]} → {me[0][3] if me else '?'}")
    ok(not others, f"Nobody else changes rank or tier, or value beyond a tail step {others[:2]}")
    back = next((x for x in edge_buttons() if x["id"] == e["id"] and x["to"] == pl[2]), None)
    ok(back is not None, "The reverse action is offered")
    if back: click_edge(back["id"], back["to"])
    ok(board() == start and unsaved() == "All saved", f"The reverse tier move restores AM PPR exactly ({unsaved()!r})")

    # 4. a value edit that fits
    srt = sorted(start, key=lambda r: r[1])
    i = next(j for j in range(100, 140) if srt[j - 1][4] - srt[j][4] > 4 and srt[j][4] - srt[j + 1][4] > 4)
    vid, newv = srt[i][0], srt[i][4] + 2
    vname = pg.evaluate("s => SPM.edit.board().find(p => String(p.sid) === s).name", vid)
    pg.locator("#rank-body tr.player", has_text=vname).first.locator(".num-btn").click(); pg.wait_for_timeout(200)
    pg.fill(".val-input", str(newv)); pg.press(".val-input", "Enter"); pg.wait_for_timeout(600)
    ve = {r[0]: r for r in board()}
    ok(ve[vid][4] == newv and ve[vid][1] == srt[i][1], f"Value edit kept exactly: {vname} {srt[i][4]} → {ve[vid][4]}")
    arrow(mover, -1)

    # 5. publish
    head0 = repo.head; before = repo.read("index.html"); n0 = len(repo.log())
    msg = save()
    after = repo.read("index.html"); new = repo.log()[n0:]
    ok("Published and confirmed" in msg and repo.head != head0, f"AM PPR publish confirmed ({msg[:90]!r})")
    ok(len(new) == 1 and new[0].startswith("AM PPR rankings edit by @tester"), f"One commit naming the board: {[m.splitlines()[0] for m in new]}")
    ok(outside(outside(before, PPR_RE), SF_RE) == outside(outside(after, PPR_RE), SF_RE), "index.html: only the two rankings blocks can change (the code byte-identical)")
    want_sf = pg.evaluate("([p, s]) => SPM.syncOrder(p, s)", [block(after, PPR_RE), block(before, SF_RE)])
    ok(block(after, SF_RE) == (want_sf["csv"] if want_sf["moved"] else block(before, SF_RE)),
       f"RANKINGS_CSV changes only by following AM PPR's new position order ({len(want_sf['moved'])} players: {[m['name'] for m in want_sf['moved']][:4]})")
    pa = table(block(after, PPR_RE)); end = board()
    ok(all(pa[s][k] == str(v) for s, *vals in end for k, v in zip(("rank", "pos_rank", "tier", "value"), vals)), "The published block is the edited board")
    ok(pa[vid]["value"] == str(newv), f"The value edit is published ({pa[vid]['value']})")
    ch = [p for p in FILES if repo.read(p, head0) != repo.read(p)]
    newfiles = [p for p in ("data/boards/ppr/rank_snapshots/2026-10.json", "data/rank_snapshots/2026-10.json") if repo.read(p, head0) is None and repo.read(p) is not None]
    if want_sf["moved"]:
        sev = json.loads(repo.read("data/rank_history.json"))["events"][-1]
        ok(sev.get("src") == "O" and sev.get("from") == "ppr" and len(sev["ranking"]) == len(want_sf["moved"]),
           f"AM SF PPR TE+ history: one event from the AM PPR publish (src O) with {len(want_sf['moved'])} ranking changes")
    else:
        ok(not [p for p in SF_FILES if p in ch], f"AM SF PPR TE+ history and snapshots untouched {[p for p in SF_FILES if p in ch]}")
    hb, ha = json.loads(repo.read("data/boards/ppr/rank_history.json", head0)), json.loads(repo.read("data/boards/ppr/rank_history.json"))
    ok(len(ha["events"]) == len(hb["events"]) + 1 and ha["events"][:-1] == hb["events"], f"AM PPR history: one new event, earlier events kept ({len(hb['events'])} → {len(ha['events'])})")
    ok(all(ha["players"].get(s, [])[:len(l)] == l for s, l in hb["players"].items()), "Every earlier AM PPR history entry kept")
    ev = ha["events"][-1]; sp = f"data/boards/ppr/rank_snapshots/{ev['ts'][:7]}.json"
    sb, sa = repo.read(sp, head0), repo.read(sp)
    olds = json.loads(sb)["snapshots"] if sb else []; news = json.loads(sa)["snapshots"]
    ok(len(news) == len(olds) + 1 and news[:-1] == olds and news[-1]["ts"] == ev["ts"], "AM PPR snapshots: exactly one new snapshot at the publish time")
    snap = news[-1]["players"]
    ok(all(snap[s] == [int(pa[s]["rank"]), int(pa[s]["pos_rank"]), int(pa[s]["tier"]), int(pa[s]["value"])] for s in pa if s), "The snapshot equals the published AM PPR board")
    ok(not newfiles or newfiles == ["data/boards/ppr/rank_snapshots/2026-10.json"], f"No snapshot written to the AM SF folder {newfiles}")
    ok(not keys().get("spm_local_edits:ppr") or keys().get("spm_local_edits:ppr") in ("{}", None), "AM PPR browser edits cleared after the publish")
    pg.reload(); load(); all_tab()
    ok(pg.evaluate("() => SPM.boards().active") == "ppr" and board() == end and unsaved() == "All saved", "A reload shows the published AM PPR board, nothing pending")

    # 6. back to the original board
    pick_board("sf-tep")
    ok(pg.locator("#ed-switch").is_visible() and "Edit AM SF PPR TE+" in pg.inner_text("#ed-switch"), "Showing AM SF PPR TE+ offers Edit AM SF PPR TE+")
    with pg.expect_navigation(): pg.click("#ed-switch")
    load(); all_tab()
    ok(pg.evaluate("() => SPM.boards().active") == "sf-tep", "Back to editing AM SF PPR TE+")
    sb = sorted(board(), key=lambda r: r[1]); spos = pg.evaluate("() => Object.fromEntries(SPM.edit.board().map(p => [String(p.sid), [p.name, p.pos]]))")
    k = next(i for i in range(59, 120) if spos[sb[i][0]][1] != spos[sb[i - 1][0]][1])   # the order across positions stays editable (Oct 19)
    s_mover = spos[sb[k][0]][0]
    arrow(s_mover, -1)
    head1 = repo.head; b1 = repo.read("index.html"); n1 = len(repo.log())
    msg = save(); a1 = repo.read("index.html"); new = repo.log()[n1:]
    ok("Published and confirmed" in msg and len(new) == 1 and new[0].startswith("Rankings edit by @tester"), f"AM SF PPR TE+ publish: {[m.splitlines()[0] for m in new]}")
    ok(outside(b1, SF_RE) == outside(a1, SF_RE), "index.html: only the RANKINGS_CSV block changed (RANKINGS_CSV_PPR byte-identical)")
    ok(not pg.evaluate("([p, s]) => SPM.syncOrder(p, s).moved.length", [block(a1, PPR_RE), block(a1, SF_RE)]), "…and it still follows AM PPR's position order")
    ch1 = [p for p in FILES if repo.read(p, head1) != repo.read(p)] + [p for p in ("data/boards/ppr/rank_snapshots/2026-10.json",) if repo.read(p, head1) != repo.read(p)]
    ok(not [p for p in PPR_FILES if p in ch1], f"AM PPR history and snapshots untouched {[p for p in PPR_FILES if p in ch1]}")
    ok("data/rank_history.json" in ch1, "The AM SF PPR TE+ history got the publish")
    ok(not errs, f"No page errors: {errs[:3]}")
    br.close()

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
