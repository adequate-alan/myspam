"""One positional order in both views (Alan, Oct 21): on a QB / RB / WR / TE tab the drag, the arrows and Move to rank
work in the AM Board view and in the League-adjusted view, through the same positional movement path (movePlayer), and
both views always show the same order inside a position. League-adjusted still derives its own values and its own
overall cross-position board; its All view stays read-only and its value cells aren't editable.

Checks, through the real UI unless noted:
  1. at the start every position tab lists the same players in the same order in both views (live board, several formats)
  2. League-adjusted WR tab: arrows, drag handles and rank buttons; values shown league-adjusted and not editable;
     League-adjusted All: no editor controls (the derived overall board isn't editable)
  3. League-adjusted Move to rank WR8 -> WR5 equals movePlayer on the AM Board (same draft, touched set, unsaved count);
     the popover's Overall mode is disabled there; switching to AM Board -> WR shows him WR5, same order
  4. the arrow in League-adjusted equals movePlayer(n - 1); a real mouse drag equals movePlayer to the chip's rank
     (a rank move: his tier is derived, never forced, since League-adjusted shows no tier bands)
  5. the reverse: an AM Board move shows in League-adjusted at once
  6. undoing every move restores the board exactly (nothing unsaved)
  7. Save (no token) -> reload -> League-adjusted still has the move; Cancel back to the saved board; Save + Publish
     against the in-memory GitHub (tests/gh_mock.py) publishes a League-adjusted move as one commit
  8. a league whose board isn't the edited board stays read-only in League-adjusted (with the Edit <board> switch)
  9. AM SF PPR TE+ following AM PPR's order (live page, order sync on): a within-position move from League-adjusted is
     refused exactly as on the AM Board
 10. phone (390px) and both themes: the controls are there, a League-adjusted arrow works, no sideways scroll
Runs on the frozen test board (tests/fixture_board.py) except 1 and 9. Nothing reaches GitHub or the files on disk.
Screenshots: SHOTS=dir python3 tests/positional_shared_check.py

Run from the repo root:  python3 tests/positional_shared_check.py   (CHROMIUM=/path/to/chromium if needed)
"""
import csv, functools, http.server, io, os, re, socketserver, sys, threading
from playwright.sync_api import sync_playwright
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fixture_board as FB
from gh_mock import Repo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
srv = socketserver.TCPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=ROOT))
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"
SHOTS = os.environ.get("SHOTS")
if SHOTS: os.makedirs(SHOTS, exist_ok=True)
# "Your settings": a League-adjusted view without a Sleeper league. A Superflex format is valued on AM SF PPR TE+ (the
# board the fixture page edits), a 1QB format on AM PPR (§2.16a)
FMT = "t10_qbsf_rec0.5_tep0"
FMT_1QB = "t10_qb1_rec0.5_tep0"
failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond: failures.append(msg)

STATE = """() => ({ csv: SPM.edit.draft(), board: SPM.edit.board().map(p => [p.id, p.rank, p.posNum, p.tier, p.value, p.source]).sort((a, b) => a[0] - b[0]),
  touched: SPM.edit.touched().sort(), unsaved: SPM.edit.unsaved() })"""
CSV_RE = re.compile(r"const RANKINGS_CSV = `\n([\s\S]*?)\n`;")
def rows_of(text): return {r["sleeper_id"]: r for r in csv.DictReader(io.StringIO(text))}
BLOCK = re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.sleeper\.(app|com)|use\.typekit\.net|fonts\.(googleapis|gstatic)\.com)/.*")

with sync_playwright() as pw:
    br = pw.chromium.launch(**({"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}))
    errs = []
    def new_ctx(fixture=True, width=1440, height=1000, theme=None, edit_board=None, gh=None, token=False):
        ctx = br.new_context(viewport={"width": width, "height": height}, **({"is_mobile": True, "has_touch": True} if width < 700 else {}))
        ctx.route("https://api.github.com/**", gh.handle if gh else (lambda r: r.abort()))
        ctx.route(BLOCK, lambda r: r.abort())
        if gh:
            ctx.route(re.compile(re.escape(BASE) + r"/(index\.html)?([?#].*)?$"), lambda r: r.fulfill(status=200, content_type="text/html; charset=utf-8", body=gh.read("index.html")))
            def data_file(r):
                body = gh.read("data/" + r.request.url.split("/data/")[1].split("?")[0])
                if body is None: r.fulfill(status=404, content_type="application/json", body=b"{}")
                else: r.fulfill(status=200, content_type="application/json", body=body)
            ctx.route(re.compile(re.escape(BASE) + r"/data/(rank_history\.json|injury_overrides\.json|rank_snapshots/[^/?]+\.json).*"), data_file)
        elif fixture: FB.route(ctx, BASE)
        init = "window.__SPM_TEST_HOOKS = true;"
        if theme: init += f"try {{ localStorage.setItem('spm_theme', '{theme}'); }} catch (e) {{}}"
        if edit_board: init += f"try {{ if (!sessionStorage.getItem('eb_set')) {{ localStorage.setItem('spm_edit_board', '{edit_board}'); sessionStorage.setItem('eb_set', '1'); }} }} catch (e) {{}}"
        if token: init += "try { localStorage.setItem('spm_editor_token', 'test-token'); } catch (e) {}"
        ctx.add_init_script(init)
        return ctx
    def open_page(ctx, fmt=FMT, extra=""):
        pg = ctx.new_page(); pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(BASE + f"/?fmt={fmt}{extra}#rankings"); pg.wait_for_selector("#rank-body tr.player"); pg.wait_for_timeout(2000)
        return pg
    def tab(pg, pos): pg.click(f"#pos-chips button:has-text('{pos}')"); pg.wait_for_timeout(350)
    def view(pg, v):   # AM Board ("base") or League-adjusted ("league"), the toolbar's switch
        pg.evaluate(f"document.querySelector('#league-controls [data-view={v}]').click()"); pg.wait_for_timeout(450)
    def lv(pg): return pg.evaluate("document.querySelector('#league-controls [data-view=league]').getAttribute('aria-pressed')") == "true"
    def order(pg): return [int(x) if x.isdigit() else x for x in pg.eval_on_selector_all("#rank-body tr.player", "e => e.map(x => x.dataset.id)")]
    def state(pg): return pg.evaluate(STATE)
    def same(a, b): return a["csv"] == b["csv"] and a["board"] == b["board"] and a["touched"] == b["touched"] and a["unsaved"] == b["unsaved"]
    def rowof(pg, pid): return pg.locator(f'#rank-body tr.player[data-id="{pid}"]')
    def at(pg, n): return order(pg)[n - 1]
    def posnum(pg, pid): return next(r[2] for r in state(pg)["board"] if r[0] == pid)
    def both_orders(pg, pos):
        keep = lv(pg); tab(pg, pos)
        view(pg, "league"); a = order(pg); view(pg, "base"); b = order(pg)
        view(pg, "league" if keep else "base"); return a, b
    def move_to(pg, pid, n):
        r = rowof(pg, pid); r.evaluate("el => el.scrollIntoView({ block: 'center' })"); pg.wait_for_timeout(80)
        r.locator(".rk-btn").click(); pg.wait_for_timeout(200)
        overall_off = pg.locator('#mv-pop .mv-mode[data-mode="overall"]').is_disabled()
        pg.fill("#mv-input", str(n)); pg.wait_for_timeout(120); pg.keyboard.press("Enter"); pg.wait_for_timeout(500)
        return overall_off
    def oracle(seq, fixture=True):   # the same moves on a fresh page, on the AM Board, through movePlayer (the arrows' path)
        c = new_ctx(fixture); p = open_page(c); view(p, "base")
        for pid, n in seq: p.evaluate(f"SPM.edit.movePlayer({pid}, {n})")
        p.wait_for_timeout(300); s = state(p); c.close(); return s
    def no_hscroll(pg): return pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    def shot(pg, name):
        if SHOTS: pg.screenshot(path=os.path.join(SHOTS, name + ".png"))

    # 1. the live board: the two views agree inside every position, in several formats
    ctx = new_ctx(fixture=False)
    for fmt in ["t10_qb1_rec0.5_tep0", "t12_qb1_rec1_tep1", "t8_qbsf_rec1_tep0", "t14_qb2_rec0_tep0.5"]:
        pg = open_page(ctx, fmt); diff = []
        for pos in ["QB", "RB", "WR", "TE"]:
            a, b = both_orders(pg, pos)
            if a != b: diff.append(pos)
        ok(not diff, f"Live board, {fmt}: League-adjusted and AM Board list every position in the same order ({diff or 'all agree'})")
        pg.close()
    ctx.close()

    # 2. what League-adjusted offers
    ctx = new_ctx(); pg = open_page(ctx); s0 = state(pg)
    ok(s0["unsaved"] == 0 and lv(pg), f"Fixture board loaded in League-adjusted view ({len(s0['board'])} players, nothing unsaved)")
    tab(pg, "All")
    ok(pg.locator("#rank-body .rk-btn").count() == 0 and pg.locator("#rank-body .arrow").count() == 0 and pg.locator("#rank-body .handle").count() == 0,
       "League-adjusted All: no arrows, handles or rank buttons (the derived overall board isn't editable)")
    ok("position tab" in pg.inner_text("#eb-hint"), "League-adjusted All: the editor bar says where to edit: " + pg.inner_text("#eb-hint"))
    tab(pg, "WR"); n_rows = pg.locator("#rank-body tr.player").count()
    ok(pg.locator("#rank-body .rk-btn").count() == n_rows and pg.locator("#rank-body .arrow[data-dir='1']").count() == n_rows and pg.locator("#rank-body .handle").count() == n_rows,
       f"League-adjusted WR: every row has a rank button, arrows and a drag handle ({n_rows} rows)")
    ok(pg.locator("#rank-body .num-btn").count() == 0, "League-adjusted WR: values are the league's own and aren't editable there")
    ok(pg.locator("#rank-body tr.tier-edit").count() == 0, "League-adjusted WR: no tier tools (tiers are edited on the AM Board)")
    ok("WR" in pg.inner_text("#eb-hint"), "League-adjusted WR: the editor bar hint: " + pg.inner_text("#eb-hint"))
    shot(pg, "league-wr-1440")

    # 3. Move to rank in League-adjusted equals movePlayer, and the AM Board shows the same order
    w8 = at(pg, 8)
    overall_off = move_to(pg, w8, 5); s1 = state(pg)
    ok(overall_off, "League-adjusted: the Move to rank popover's Overall mode is disabled")
    ok(at(pg, 5) == w8 and posnum(pg, w8) == 5, "League-adjusted Move to rank WR8 -> WR5: he's WR5 on screen and in the data")
    o1 = oracle([(w8, 5)])
    ok(same(s1, o1), "The League-adjusted move equals movePlayer(WR8 -> 5) on the AM Board (draft, touched, unsaved)")
    a, b = both_orders(pg, "WR")
    ok(a == b and b[4] == w8, "AM Board -> WR shows him WR5 too, every WR in the same order")
    shot(pg, "league-wr-moved-1440")

    # 4. the arrow and a real drag in League-adjusted
    tab(pg, "WR"); w12 = at(pg, 12)
    rowof(pg, w12).evaluate("el => el.scrollIntoView({ block: 'center' })"); pg.wait_for_timeout(80)
    rowof(pg, w12).hover(); rowof(pg, w12).locator(".arrow[data-dir='-1']").click(); pg.wait_for_timeout(500); s2 = state(pg)
    ok(at(pg, 11) == w12 and same(s2, oracle([(w8, 5), (w12, 11)])), "League-adjusted ▲ on WR12 equals movePlayer(WR12 -> 11)")
    w15, w9 = at(pg, 15), at(pg, 9)
    src = rowof(pg, w15); src.evaluate("el => el.scrollIntoView({ block: 'center' })"); pg.wait_for_timeout(100)
    h = src.locator(".handle").bounding_box(); t = rowof(pg, w9).bounding_box()
    pg.mouse.move(h["x"] + h["width"] / 2, h["y"] + h["height"] / 2); pg.mouse.down()
    steps = 14; y0 = h["y"] + h["height"] / 2; y1 = t["y"] + t["height"] * 0.25
    for i in range(1, steps + 1): pg.mouse.move(h["x"] + h["width"] / 2, y0 + (y1 - y0) * i / steps); pg.wait_for_timeout(16)
    chip = pg.inner_text(".drag-float .drag-rk") if pg.locator(".drag-float .drag-rk").count() else ""
    pg.mouse.up(); pg.wait_for_timeout(700); s3 = state(pg)
    m = re.search(r"WR(\d+)$", chip.strip())
    ok(m is not None and "Tier" not in chip, f"Drag chip in League-adjusted reads a rank move: {chip!r}")
    to = int(m.group(1)) if m else -1
    ok(at(pg, to) == w15 and same(s3, oracle([(w8, 5), (w12, 11), (w15, to)])), f"League-adjusted drag WR15 -> WR{to} equals movePlayer (no forced tier)")
    a, b = both_orders(pg, "WR"); ok(a == b, "After arrow and drag: both views list the WRs in the same order")

    # 5. the reverse: an AM Board move shows in League-adjusted
    view(pg, "base"); tab(pg, "RB"); r6 = at(pg, 6)
    r6row = rowof(pg, r6); r6row.evaluate("el => el.scrollIntoView({ block: 'center' })"); r6row.hover(); r6row.locator(".arrow[data-dir='1']").click(); pg.wait_for_timeout(500)
    view(pg, "league"); tab(pg, "RB")
    ok(at(pg, 7) == r6, "AM Board RB6 ▼ -> League-adjusted RB tab shows him RB7")
    a, b = both_orders(pg, "RB"); ok(a == b, "Both views list the RBs in the same order")
    ok(pg.locator(f'#rank-body tr.player[data-id="{r6}"] .val .num-btn').count() == 0, "League-adjusted still shows his league value (not editable)")

    # 6. undo everything, in League-adjusted
    tab(pg, "RB"); move_to(pg, r6, 6)
    tab(pg, "WR"); move_to(pg, w15, 15); move_to(pg, w12, 12); move_to(pg, w8, 8)
    ok(same(state(pg), s0), "Every move undone from League-adjusted: the board is exactly the starting board, nothing unsaved")
    ok(not errs, f"No page errors ({errs[:2]})")
    ctx.close()

    # 7. Save / reload / Cancel without a token, then Publish against the in-memory GitHub
    ctx = new_ctx(); pg = open_page(ctx); tab(pg, "WR"); w8 = at(pg, 8)
    move_to(pg, w8, 5)
    pg.click("#eb-save"); pg.wait_for_timeout(900)
    pg.reload(); pg.wait_for_selector("#rank-body tr.player"); pg.wait_for_timeout(2000); tab(pg, "WR")
    ok(lv(pg) and at(pg, 5) == w8 and state(pg)["unsaved"] == 0, "Saved in the browser from League-adjusted: after a reload he's still WR5 there, nothing unsaved")
    view(pg, "base"); tab(pg, "WR"); ok(at(pg, 5) == w8, "...and WR5 on the AM Board")
    view(pg, "league"); tab(pg, "WR"); s5 = state(pg)
    move_to(pg, at(pg, 20), 2); ok(state(pg)["unsaved"] > 0, "Another League-adjusted move is unsaved")
    pg.click("#eb-cancel"); pg.wait_for_timeout(500)
    ok(same(state(pg), s5) and at(pg, 5) == w8, "Cancel: back to the saved board")
    ctx.close()

    files = {"index.html": FB.html(), "data/injury_overrides.json": open(os.path.join(ROOT, "data/injury_overrides.json"), "rb").read(), **FB.files()}
    repo = Repo(dict(files)); fixture_rows = rows_of(FB.CSV)
    ctx = new_ctx(gh=repo, token=True); pg = open_page(ctx); tab(pg, "WR"); w8 = at(pg, 8)
    sid = next(k for k, r in fixture_rows.items() if r["pos"] == "WR" and r["pos_rank"] == "8")
    move_to(pg, w8, 5); n_commits = len(repo.log())
    pg.evaluate("() => { const t = document.getElementById('toast'); t.textContent = ''; t.hidden = true; }")
    pg.click("#eb-save")
    pg.wait_for_function("() => /Publish|Already live|Nothing to publish|Saved/.test(document.getElementById('toast').textContent)", timeout=20000)
    pg.wait_for_timeout(400); toast = pg.inner_text("#toast")
    live = rows_of(CSV_RE.search(repo.read("index.html").decode()).group(1))
    ok("Published" in toast and len(repo.log()) == n_commits + 1 and live[sid]["pos_rank"] == "5",
       f"Save with a token publishes the League-adjusted move as one commit, WR5 on the live board ({toast!r})")
    ok(repo.read("data/rank_history.json") != files["data/rank_history.json"], "The same commit wrote the ranking history")
    move_to(pg, w8, 8); pg.evaluate("() => { const t = document.getElementById('toast'); t.textContent = ''; t.hidden = true; }")
    pg.click("#eb-save"); pg.wait_for_function("() => /Publish|Already live|Saved/.test(document.getElementById('toast').textContent)", timeout=20000); pg.wait_for_timeout(400)
    back = rows_of(CSV_RE.search(repo.read("index.html").decode()).group(1))
    ok(back == fixture_rows, f"Moved back from League-adjusted and published: the live board equals the fixture board ({sum(1 for k in back if back[k] != fixture_rows.get(k))} rows differ)")
    ok(not errs, f"No page errors ({errs[:2]})")
    ctx.close()

    # 8. a league valued on another board than the one being edited stays read-only in League-adjusted
    ctx = new_ctx(); pg = open_page(ctx, FMT_1QB); tab(pg, "WR")
    ok(lv(pg) and pg.locator("#rank-body .arrow").count() == 0 and pg.locator("#rank-body .rk-btn").count() == 0,
       "Editing AM SF PPR TE+, League-adjusted on a 1QB format (valued on AM PPR): no editor controls on its WR tab")
    sw = pg.locator("#ed-switch")
    ok(not pg.locator("#ed-switch-wrap").is_hidden() and "AM PPR" in sw.inner_text(), "...and the Edit <board> switch names the league's board: " + (sw.inner_text() if sw.count() else ""))
    ctx.close()
    # 8b. editing AM PPR (overall tiers) with a 1QB format: League-adjusted position tabs edit AM PPR the same way
    ctx = new_ctx(fixture=False, edit_board="ppr"); pg = open_page(ctx, FMT_1QB); tab(pg, "RB")
    p0 = state(pg); r9 = at(pg, 9)
    ok(lv(pg) and pg.locator("#rank-body .arrow").count() > 0, "Editing AM PPR, League-adjusted RB tab of a 1QB format has the controls")
    move_to(pg, r9, 4)
    ok(at(pg, 4) == r9 and posnum(pg, r9) == 4, "AM PPR, League-adjusted Move to rank RB9 -> RB4")
    c = new_ctx(fixture=False, edit_board="ppr"); q = open_page(c, FMT_1QB); view(q, "base"); q.evaluate(f"SPM.edit.movePlayer({r9!r}, 4)"); q.wait_for_timeout(300)
    ok(same(state(pg), state(q)), "...equals movePlayer on the AM Board of AM PPR"); c.close()
    a, b = both_orders(pg, "RB"); ok(a == b, "AM PPR: both views list the RBs in the same order")
    move_to(pg, r9, 9); ok(same(state(pg), p0), "AM PPR: moved back, the board is exactly as it was")
    ctx.close()

    # 9. live page, order sync on: AM SF PPR TE+ refuses a within-position move from League-adjusted, as on the AM Board
    ctx = new_ctx(fixture=False, edit_board="sf-tep"); pg = open_page(ctx); tab(pg, "WR")
    s9 = state(pg); w3 = at(pg, 3)
    if pg.locator("#rank-body .arrow").count():
        rowof(pg, w3).hover(); rowof(pg, w3).locator(".arrow[data-dir='-1']").click(); pg.wait_for_timeout(500)
        ok(same(state(pg), s9) and at(pg, 3) == w3 and "AM PPR" in pg.inner_text("#toast"),
           "AM SF PPR TE+ in League-adjusted: a within-position move is refused (order follows AM PPR): " + pg.inner_text("#toast")[:90])
    else:
        ok(False, "AM SF PPR TE+ in League-adjusted: the WR tab has editor controls")
    ctx.close()

    # 10. phone and both themes
    for theme in ["light", "dark"]:
        ctx = new_ctx(width=390, height=844, theme=theme); pg = open_page(ctx, extra="&debug"); tab(pg, "WR")
        n = pg.locator("#rank-body tr.player").count()
        ok(lv(pg) and pg.locator("#rank-body .arrow[data-dir='1']").count() == n, f"Phone {theme}: League-adjusted WR rows have arrows ({n})")
        w4 = at(pg, 4); s = state(pg)
        rowof(pg, w4).evaluate("el => el.scrollIntoView({ block: 'center' })"); rowof(pg, w4).locator(".arrow[data-dir='-1']").tap(); pg.wait_for_timeout(500)
        ok(at(pg, 3) == w4 and state(pg)["unsaved"] > 0, f"Phone {theme}: a League-adjusted ▲ moves WR4 to WR3")
        ok(no_hscroll(pg), f"Phone {theme}: no sideways scroll")
        pg.evaluate("window.scrollTo(0, 0)"); shot(pg, f"league-wr-{theme}-390")
        view(pg, "base"); tab(pg, "WR"); ok(at(pg, 3) == w4, f"Phone {theme}: AM Board shows him WR3 too")
        ctx.close()
        ctx = new_ctx(theme=theme); pg = open_page(ctx); tab(pg, "WR")
        ok(no_hscroll(pg) and pg.locator("#rank-body .rk-btn").count() > 0, f"Desktop {theme}: League-adjusted WR has the controls, no sideways scroll")
        shot(pg, f"league-wr-{theme}-1440")
        ctx.close()
    ok(not errs, f"No page errors ({errs[:2]})")
    br.close()

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
