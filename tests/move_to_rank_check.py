"""Move to rank (Alan, Oct 14): an alternative to dragging for long-distance moves, never a second ranking system.

While the board can be reordered, the rank number in each row is a button that opens a small popover: type an overall
rank (the default on All) or a position rank (the default on a position tab; either can be picked), see where he is and
where that puts him, Move. Every check compares the popover's result with the arrows' own path (SPM.edit.moveOverall /
movePlayer, which the arrows and drag call), through the real UI:
  1. the button exists only where the arrows do (not in a production sort); the defaults per view
  2. a long overall move (#9 -> #35) equals moveOverall; moving back through the popover restores the board exactly
     (CSV, ranks, position ranks, tiers, values, Auto/Manual, touched set, nothing unsaved)
  3. an adjacent move equals the arrow; back exactly
  4. a position move (WR4 -> WR10, across a tier boundary) equals movePlayer: only the mover's value changes, his tier is
     derived (never pinned: a rank move, not a tier move), values stay strictly descending, ranks and position ranks stay
     1..N with nobody duplicated or lost; back exactly
  5. the other mode in each view (Overall from a position tab, a position rank from All)
  6. a scripted sequence of mixed direct moves equals the same sequence through the hooks, and the reverse sequence
     restores the board exactly
  7. typed input: 0, past the end, a fraction, a negative, empty and his own rank can't be applied (message, Move
     disabled, Enter does nothing); Escape, Cancel and a click outside change nothing; focus returns to the rank button
  8. keyboard only: Tab/Enter opens it, typing + Enter moves
  9. a direct move with other unsaved edits standing (a value edit, a tier move) leaves them intact, and undoing only the
     direct move leaves exactly those edits
 10. Save, reload, Cancel and Publish (in-memory GitHub, tests/gh_mock.py): the move persists across a reload with
     nothing unsaved, publishes as one commit whose board holds the move, and the reverse move publishes the fixture
     board back exactly; a move then Cancel returns to the saved board
Runs on the frozen test board (tests/fixture_board.py). Nothing reaches GitHub or the files on disk.

Run from the repo root:  python3 tests/move_to_rank_check.py   (CHROMIUM=/path/to/chromium if needed)
"""
import csv, functools, http.server, io, json, os, random, re, socketserver, sys, threading
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
failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond: failures.append(msg)

STATE = """() => ({ csv: SPM.edit.draft(), board: SPM.edit.board().map(p => [p.id, p.rank, p.posNum, p.tier, p.value, p.source]).sort((a, b) => a[0] - b[0]),
  touched: SPM.edit.touched().sort(), unsaved: SPM.edit.unsaved() })"""
CHECKS = """() => { const b = SPM.edit.board().sort((a, b) => a.rank - b.rank), out = { ranks: true, pos: true, desc: true, tiers: true, dup: true };
  b.forEach((p, i) => { if (p.rank !== i + 1) out.ranks = false; if (i && p.value > b[i - 1].value) out.desc = false; if (i && p.value === b[i - 1].value && p.value !== 0) out.desc = false; });
  const ids = new Set(b.map(p => p.id)); if (ids.size !== b.length) out.dup = false;
  for (const pos of ['QB', 'RB', 'WR', 'TE']) { const g = b.filter(p => p.pos === pos && p.posNum != null).sort((a, b) => a.posNum - b.posNum); let last = -1;
    g.forEach((p, i) => { if (p.posNum !== i + 1) out.pos = false; const t = Number(p.tier); if (!isFinite(t) || t >= 90) return; if (t < last) out.tiers = false; last = t; }); }
  return out; }"""
CSV_RE = re.compile(r"const RANKINGS_CSV = `\n([\s\S]*?)\n`;")
def rows_of(text): return {r["sleeper_id"]: r for r in csv.DictReader(io.StringIO(text))}

with sync_playwright() as pw:
    br = pw.chromium.launch(**({"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}))
    errs = []
    def new_ctx():
        ctx = br.new_context(viewport={"width": 1440, "height": 1000})
        ctx.route("https://api.github.com/**", lambda r: r.abort())
        ctx.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.sleeper\.(app|com)|use\.typekit\.net|fonts\.(googleapis|gstatic)\.com)/.*"), lambda r: r.abort())
        FB.route(ctx, BASE)
        ctx.add_init_script("window.__SPM_TEST_HOOKS = true;")
        return ctx
    def open_page(ctx):
        pg = ctx.new_page(); pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(BASE + "/#rankings"); pg.wait_for_selector("#rank-body tr.player"); pg.wait_for_timeout(2000)
        return pg
    def tab(pg, pos): pg.click(f"#pos-chips button:has-text('{pos}')"); pg.wait_for_timeout(350)
    def state(pg): return pg.evaluate(STATE)
    def same(a, b): return a["csv"] == b["csv"] and a["board"] == b["board"] and a["touched"] == b["touched"] and a["unsaved"] == b["unsaved"]
    def nodiff(a, b):   # players whose row differs (id, before, after)
        A = {r[0]: r for r in a["board"]}; return [(r[0], A.get(r[0]), r) for r in b["board"] if A.get(r[0]) != r]
    def rowof(pg, pid): return pg.locator(f'#rank-body tr.player[data-id="{pid}"]')
    def by_rank(pg, n): return int(pg.locator("#rank-body tr.player").nth(n - 1).get_attribute("data-id"))
    def open_pop(pg, pid):
        r = rowof(pg, pid); r.evaluate("el => el.scrollIntoView({ block: 'center' })"); pg.wait_for_timeout(80)
        r.locator(".rk-btn").click(); pg.wait_for_timeout(200)
    def mode(pg): return pg.evaluate("() => [...document.querySelectorAll('#mv-pop .mv-mode')].find(b => b.getAttribute('aria-checked') === 'true').dataset.mode")
    def pick_mode(pg, m): pg.click(f'#mv-pop .mv-mode[data-mode="{m}"]'); pg.wait_for_timeout(120)
    def move_to(pg, pid, n, m=None, via="enter"):   # the popover, as a person would use it
        open_pop(pg, pid)
        if m and mode(pg) != m: pick_mode(pg, m)
        pg.fill("#mv-input", str(n)); pg.wait_for_timeout(120)
        preview = pg.inner_text("#mv-to")
        if via == "enter": pg.keyboard.press("Enter")
        else: pg.click("#mv-apply")
        pg.wait_for_timeout(500); return preview
    def pop_open(pg): return pg.locator("#mv-pop").is_visible()
    def cancel(pg): pg.evaluate("SPM.edit.cancel()"); pg.wait_for_timeout(400)
    def hooks(pg, seq):   # the same moves through the arrows' functions
        for kind, pid, n in seq: pg.evaluate(f"SPM.edit.{'moveOverall' if kind == 'overall' else 'movePlayer'}({pid}, {n})")
        pg.wait_for_timeout(300)

    ctx = new_ctx(); pg = open_page(ctx)
    s0 = state(pg)
    ok(s0["unsaved"] == 0 and len(s0["board"]) > 200, f"Fixture board loaded: {len(s0['board'])} players, nothing unsaved")

    # 1. the button lives where the arrows do
    n_btn = pg.locator("#rank-body .rk-btn").count(); n_arrow = pg.locator("#rank-body tr.player .arrow[data-dir='1']").count()
    ok(n_btn == len(s0["board"]) and n_btn == n_arrow, f"Every reorderable row has a rank button ({n_btn}; arrows {n_arrow})")
    pg.select_option("#rk-sort", "ppg"); pg.wait_for_timeout(500)
    ok(pg.locator("#rank-body .rk-btn").count() == 0 and pg.locator("#rank-body .arrow").count() == 0, "No rank button in a production sort (editing is off there, like the arrows)")
    pg.select_option("#rk-sort", "spam"); pg.wait_for_timeout(500)
    p9 = by_rank(pg, 9); me9 = next(r for r in s0["board"] if r[0] == p9)
    open_pop(pg, p9)
    ok(pop_open(pg) and mode(pg) == "overall" and pg.input_value("#mv-input") == "9" and pg.evaluate("document.activeElement.id") == "mv-input",
       f"All view: the popover opens on Overall with his rank (#9) selected in a focused input; now: {pg.inner_text('#mv-now')!r}")
    ok(pg.locator("#mv-apply").is_disabled() and "already" in pg.inner_text("#mv-to"), "His own rank can't be applied: " + pg.inner_text("#mv-to"))
    ok(rowof(pg, p9).locator(".rk-btn").get_attribute("aria-expanded") == "true", "The rank button says it's expanded")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(150)
    ok(not pop_open(pg) and same(state(pg), s0) and pg.evaluate("document.activeElement.className") == "rk-btn", "Escape closes it, nothing changed, focus back on the rank button")
    tab(pg, "WR"); w4 = by_rank(pg, 4)
    open_pop(pg, w4)
    ok(pop_open(pg) and mode(pg) == "pos" and pg.text_content("#mv-mode-pos") == "WR rank" and pg.input_value("#mv-input") == "4",
       f"WR tab: the popover opens on WR rank with WR4 selected (open {pop_open(pg)}, mode {mode(pg) if pop_open(pg) else '-'}, label {pg.text_content("#mv-mode-pos")!r}, input {pg.input_value('#mv-input')!r})")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(100); tab(pg, "All")

    # 2. a long overall move equals the arrows' function; back restores exactly
    prev = move_to(pg, p9, 35)
    s1 = state(pg); r1 = next(r for r in s1["board"] if r[0] == p9)
    ok(r1[1] == 35 and "#35 overall" in prev, f"#9 -> #35 through the popover: now #{r1[1]} (preview {prev!r})")
    ok(not pop_open(pg) and pg.evaluate("document.activeElement.className") == "rk-btn" and pg.evaluate("document.activeElement.closest('tr').dataset.id") == str(p9),
       "After the move the popover is closed and the focus is on his rank in his new row")
    cancel(pg); hooks(pg, [("overall", p9, 35)]); s1h = state(pg)
    ok(same(s1, s1h), f"The popover's result equals moveOverall exactly ({len(nodiff(s1, s1h))} rows differ)")
    c = pg.evaluate(CHECKS); ok(all(c.values()), f"Ranks 1..N, position ranks 1..N, values strictly descending, tiers in one piece, nobody duplicated: {c}")
    changed = [d for d in nodiff(s0, s1) if d[1][4] != d[2][4]]
    ok(len(changed) == 1 and changed[0][0] == p9, f"Only the mover's value changed ({len(changed)} value changes: {[d[0] for d in changed][:5]})")
    cancel(pg); move_to(pg, p9, 35); prev = move_to(pg, p9, 9, via="click")
    ok(same(state(pg), s0), f"Moved back to #9 through the popover (Move button): the board is exactly the fixture board again, nothing unsaved ({len(nodiff(s0, state(pg)))} rows differ)")

    # 3. adjacent move equals the arrow
    move_to(pg, p9, 10); s_adj = state(pg); cancel(pg)
    rowof(pg, p9).evaluate("el => el.scrollIntoView({ block: 'center' })"); rowof(pg, p9).locator('.arrow[data-dir="1"]').click(force=True); pg.wait_for_timeout(400)
    ok(same(s_adj, state(pg)), "#9 -> #10 through the popover equals the down arrow exactly")
    cancel(pg); move_to(pg, p9, 10); move_to(pg, p9, 9)
    ok(same(state(pg), s0), "Adjacent move and back: exact")

    # 4. a position move across a tier boundary equals movePlayer: the tier is derived, not pinned
    tab(pg, "WR"); w4 = by_rank(pg, 4); t_before = next(r for r in s0["board"] if r[0] == w4)[3]
    prev = move_to(pg, w4, 10)
    s4 = state(pg); r4 = next(r for r in s4["board"] if r[0] == w4)
    ok(r4[2] == 10 and r4[3] != t_before and "WR10" in prev, f"WR4 -> WR10 through the popover: WR{r4[2]}, tier {t_before} -> {r4[3]} (derived from his new spot; preview {prev!r})")
    changed = [d for d in nodiff(s0, s4) if d[1][4] != d[2][4]]
    ok(len(changed) == 1 and changed[0][0] == w4, f"Only his value changed ({len(changed)} value changes)")
    c = pg.evaluate(CHECKS); ok(all(c.values()), f"Board consistent after the position move: {c}")
    cancel(pg); hooks(pg, [("pos", w4, 10)]); s4h = state(pg)
    ok(same(s4, s4h), f"Equals movePlayer exactly ({len(nodiff(s4, s4h))} rows differ)")
    sess = pg.evaluate("() => { const s = localStorage.getItem('spm_edit_session'); return s; }")
    cancel(pg); move_to(pg, w4, 10); move_to(pg, w4, 4)
    ok(same(state(pg), s0), f"WR10 -> WR4 back through the popover: exact ({len(nodiff(s0, state(pg)))} rows differ)")
    ok(pg.locator("#rank-body .rv-tag").count() == 0, "No 'Revalued' tag left once the move is undone")
    # a move inside his tier keeps the tier (no tier move hidden inside a rank move)
    move_to(pg, w4, 2); r = next(x for x in state(pg)["board"] if x[0] == w4)
    ok(r[2] == 2 and r[3] == t_before and rowof(pg, w4).locator(".rv-tag").count() == 1, f"WR4 -> WR2 stays in tier {t_before} and shows Revalued, like an arrow move")
    move_to(pg, w4, 4); ok(same(state(pg), s0), "WR2 -> WR4: exact")

    # 5. the other mode in each view
    prev = move_to(pg, w4, 60, m="overall"); s5 = state(pg); r = next(x for x in s5["board"] if x[0] == w4)
    cancel(pg); hooks(pg, [("overall", w4, 60)])
    ok(r[1] == 60 and same(s5, state(pg)) and "#60 overall" in prev, f"WR tab, Overall mode: #9 -> #60 equals moveOverall (preview {prev!r})")
    cancel(pg); move_to(pg, w4, 60, m="overall"); move_to(pg, w4, 9, m="overall"); ok(same(state(pg), s0), "and back: exact")
    tab(pg, "All"); prev = move_to(pg, w4, 12, m="pos"); s5 = state(pg); r = next(x for x in s5["board"] if x[0] == w4)
    cancel(pg); hooks(pg, [("pos", w4, 12)])
    ok(r[2] == 12 and same(s5, state(pg)) and "WR12" in prev, f"All view, WR rank mode: WR4 -> WR12 equals movePlayer (preview {prev!r})")
    cancel(pg); move_to(pg, w4, 12, m="pos"); move_to(pg, w4, 4, m="pos"); ok(same(state(pg), s0), "and back: exact")

    # 6. a sequence of mixed direct moves
    rnd = random.Random(14); board = sorted(s0["board"], key=lambda r: r[1])
    seq = []
    for k in range(14):
        p = board[rnd.randrange(5, 150)]
        if rnd.random() < 0.5: seq.append(("overall", p[0], rnd.randrange(1, 200)))
        else: seq.append(("pos", p[0], rnd.randrange(1, 25)))
    tab(pg, "All")
    for kind, pid, n in seq:
        cur = next(x for x in state(pg)["board"] if x[0] == pid)
        if (kind == "overall" and cur[1] == n) or (kind == "pos" and cur[2] == n): continue
        move_to(pg, pid, n, m=kind)
    s6 = state(pg); c = pg.evaluate(CHECKS)
    cancel(pg); hooks(pg, seq); s6h = state(pg)
    ok(same(s6, s6h) and all(c.values()), f"{len(seq)} mixed direct moves through the popover equal the same sequence through the hooks ({len(nodiff(s6, s6h))} rows differ); board consistent: {c}")
    cancel(pg)
    # the reverse: each move undone in reverse order, back to the slot he left (overall rank, or position rank)
    undo = []
    for kind, pid, n in seq:
        cur = next(x for x in state(pg)["board"] if x[0] == pid); undo.append((kind, pid, cur[1] if kind == "overall" else cur[2]))
        if (kind == "overall" and cur[1] == n) or (kind == "pos" and cur[2] == n): continue
        move_to(pg, pid, n, m=kind)
    for kind, pid, n in reversed(undo):
        cur = next(x for x in state(pg)["board"] if x[0] == pid)
        if (kind == "overall" and cur[1] == n) or (kind == "pos" and cur[2] == n): continue
        move_to(pg, pid, n, m=kind)
    ok(same(state(pg), s0), f"The reverse sequence restores the fixture board exactly ({len(nodiff(s0, state(pg)))} rows differ, {state(pg)['unsaved']} unsaved)")

    # 7. typed input
    p9 = by_rank(pg, 9); n_all = len(s0["board"])
    open_pop(pg, p9)
    for bad, why in [("0", "zero"), (str(n_all + 1), "past the end"), ("9.5", "a fraction"), ("-3", "negative"), ("", "empty"), ("9", "his own rank")]:
        pg.fill("#mv-input", bad); pg.wait_for_timeout(100)
        dis = pg.locator("#mv-apply").is_disabled(); msg = pg.inner_text("#mv-to")
        pg.keyboard.press("Enter"); pg.wait_for_timeout(200)
        ok(dis and pop_open(pg) and same(state(pg), s0), f"{why} ({bad!r}): Move disabled, Enter does nothing, nothing changed; says {msg!r}")
    pg.fill("#mv-input", "40"); pg.wait_for_timeout(100); pg.click("#mv-cancel"); pg.wait_for_timeout(150)
    ok(not pop_open(pg) and same(state(pg), s0) and pg.evaluate("document.activeElement.className") == "rk-btn", "Cancel with a valid rank typed: closed, nothing changed, focus back")
    open_pop(pg, p9); pg.fill("#mv-input", "40"); pg.mouse.click(1200, 120); pg.wait_for_timeout(200)
    ok(not pop_open(pg) and same(state(pg), s0), "A click outside closes it with nothing changed")
    open_pop(pg, p9); open_pop(pg, p9)
    ok(not pop_open(pg), "Clicking the same rank button again closes it")
    p12 = by_rank(pg, 12); open_pop(pg, p9); open_pop(pg, p12)
    ok(pop_open(pg) and pg.inner_text("#mv-name") == rowof(pg, p12).locator(".pl-name").inner_text() and rowof(pg, p9).locator(".rk-btn").get_attribute("aria-expanded") == "false",
       "Opening another row's popover moves it there and collapses the first button")
    pg.keyboard.press("Escape")

    # 8. keyboard only
    rowof(pg, p9).evaluate("el => el.scrollIntoView({ block: 'center' })")
    pg.evaluate(f"document.querySelector('#rank-body tr.player[data-id=\"{p9}\"] .rk-btn').focus()")
    pg.keyboard.press("Enter"); pg.wait_for_timeout(200)
    ok(pop_open(pg) and pg.evaluate("document.activeElement.id") == "mv-input", "Enter on the focused rank button opens the popover with the input focused")
    pg.keyboard.press("Tab"); pg.keyboard.press("Tab"); pg.keyboard.press("Tab"); pg.keyboard.press("Tab"); pg.keyboard.press("Tab")
    ok(pg.evaluate("!!document.activeElement.closest('#mv-pop')"), "Tab keeps the focus inside the popover")
    pg.focus("#mv-input"); pg.keyboard.press("Control+a"); pg.keyboard.type("25"); pg.keyboard.press("Enter"); pg.wait_for_timeout(500)
    r = next(x for x in state(pg)["board"] if x[0] == p9)
    ok(r[1] == 25 and not pop_open(pg), f"Typed 25, Enter: he is #{r[1]}")
    cancel(pg)

    # 9. with other unsaved edits standing
    tab(pg, "QB"); q = pg.evaluate("() => SPM.edit.board().filter(p => p.pos === 'QB').sort((a, b) => a.posNum - b.posNum).map(p => ({ id: p.id, name: p.name, tier: p.tier, posNum: p.posNum }))")
    edge_from = next((q[i - 1] for i in range(1, len(q)) if q[i]["tier"] != q[i - 1]["tier"] and int(q[i]["tier"]) < 90 and sum(1 for x in q if x["tier"] == q[i - 1]["tier"]) > 1), None)
    if edge_from:   # a same-rank tier move (the header action's path), covered through the UI by tier_boundary_check
        nxt = next(x["tier"] for x in q if x["posNum"] > edge_from["posNum"] and x["tier"] != edge_from["tier"])
        pg.evaluate(f"SPM.edit.movePlayer({edge_from['id']}, {edge_from['posNum']}, {nxt})"); pg.wait_for_timeout(400)
        if pg.locator("#ed-warn").is_visible(): pg.click('#ed-warn [data-ed="close"]')
    tab(pg, "All"); p20 = by_rank(pg, 20); v20 = next(x for x in state(pg)["board"] if x[0] == p20)[4]
    pg.evaluate(f"SPM.edit.applyValue({p20}, {v20 - 7})"); pg.wait_for_timeout(300)
    s9 = state(pg)
    ok(s9["unsaved"] >= 1 and next(x for x in s9["board"] if x[0] == p20)[4] == v20 - 7, f"Deliberate edits standing: a value edit (#20: {v20} -> {v20 - 7}){' and a tier move (' + edge_from['name'] + ')' if edge_from else ''}, {s9['unsaved']} unsaved")
    p40 = by_rank(pg, 40); move_to(pg, p40, 120); s9b = state(pg)
    r = next(x for x in s9b["board"] if x[0] == p40)
    ok(r[1] == 120 and next(x for x in s9b["board"] if x[0] == p20)[4] == v20 - 7 and (not edge_from or next(x for x in s9b["board"] if x[0] == edge_from["id"])[3] == next(x for x in s9["board"] if x[0] == edge_from["id"])[3]),
       "A direct move (#40 -> #120) leaves the value edit and the tier move intact")
    move_to(pg, p40, 40)
    ok(same(state(pg), s9), f"Undoing only the direct move leaves exactly the deliberate edits ({len(nodiff(s9, state(pg)))} rows differ)")
    cancel(pg); ok(same(state(pg), s0), "Cancel: back to the fixture board")
    ok(not errs, f"No page errors ({errs[:2]})")
    ctx.close()

    # 10. Save, reload, Cancel, Publish against the in-memory GitHub
    files = {"index.html": FB.html(), "data/injury_overrides.json": open(os.path.join(ROOT, "data/injury_overrides.json"), "rb").read(), **FB.files()}
    repo = Repo(dict(files))
    def gh_ctx(token=True):
        ctx = br.new_context(viewport={"width": 1440, "height": 1000})
        ctx.route("https://api.github.com/**", repo.handle)
        ctx.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.sleeper\.(app|com)|use\.typekit\.net|fonts\.(googleapis|gstatic)\.com)/.*"), lambda r: r.abort())
        ctx.route(re.compile(re.escape(BASE) + r"/(index\.html)?([?#].*)?$"), lambda r: r.fulfill(status=200, content_type="text/html; charset=utf-8", body=repo.read("index.html")))
        def data_file(r):
            body = repo.read("data/" + r.request.url.split("/data/")[1].split("?")[0])
            if body is None: r.fulfill(status=404, content_type="application/json", body=b"{}")
            else: r.fulfill(status=200, content_type="application/json", body=body)
        ctx.route(re.compile(re.escape(BASE) + r"/data/(rank_history\.json|injury_overrides\.json|rank_snapshots/[^/?]+\.json).*"), data_file)
        ctx.add_init_script("window.__SPM_TEST_HOOKS = true;")
        if token: ctx.add_init_script("try { localStorage.setItem('spm_editor_token', 'test-token'); } catch (e) {}")
        return ctx
    def save(pg):
        pg.evaluate("() => { const t = document.getElementById('toast'); t.textContent = ''; t.hidden = true; }")
        pg.click("#eb-save")
        pg.wait_for_function("() => /Publish|Already live|Nothing to publish|Saved/.test(document.getElementById('toast').textContent)", timeout=20000)
        pg.wait_for_timeout(400); return pg.inner_text("#toast")
    fixture_rows = rows_of(FB.CSV)
    ctx = gh_ctx(); pg = open_page(ctx); g0 = state(pg)
    p9 = by_rank(pg, 9); move_to(pg, p9, 35); g1 = state(pg)
    pg.evaluate("SPM.edit.cancel()"); pg.wait_for_timeout(400); ok(same(state(pg), g0), "Move then Cancel: the saved board is back")
    move_to(pg, p9, 35); n_commits = len(repo.log())
    t = save(pg)
    ok("Published" in t and len(repo.log()) == n_commits + 1, f"Save publishes the direct move as one commit: {t!r}")
    live = rows_of(CSV_RE.search(repo.read("index.html").decode()).group(1))
    sid9 = next(k for k, r in fixture_rows.items() if int(r["rank"]) == 9)
    ok(live[sid9]["rank"] == "35" and sorted(int(r["rank"]) for r in live.values()) == list(range(1, len(live) + 1)), "The published board has him at #35 with ranks 1..N")
    pg.reload(); pg.wait_for_selector("#rank-body tr.player"); pg.wait_for_timeout(2000); g2 = state(pg)
    ok(g2["unsaved"] == 0 and g2["board"] == g1["board"] and next(x for x in g2["board"] if x[0] == p9)[1] == 35, "After a reload the published board shows the move with nothing unsaved")
    move_to(pg, p9, 9); t = save(pg)
    back = rows_of(CSV_RE.search(repo.read("index.html").decode()).group(1))
    ok("Published" in t and back == fixture_rows, f"Moved back to #9 and published: the live board equals the fixture board exactly ({sum(1 for k in back if back[k] != fixture_rows.get(k))} rows differ)")
    pg.reload(); pg.wait_for_selector("#rank-body tr.player"); pg.wait_for_timeout(2000)
    ok(same(state(pg), g0), "Reloaded: exactly the starting board, nothing unsaved")
    ctx.close()
    # saved in this browser without a token, reloaded, then undone
    ctx = gh_ctx(token=False); pg = open_page(ctx); g0 = state(pg); p9 = by_rank(pg, 9)
    move_to(pg, p9, 50); t = save(pg)
    pg.reload(); pg.wait_for_selector("#rank-body tr.player"); pg.wait_for_timeout(2000); g3 = state(pg)
    ok(next(x for x in g3["board"] if x[0] == p9)[1] == 50 and g3["unsaved"] == 0 and "Saved" in t, f"No token: saved in the browser, still #50 after a reload ({t!r})")
    move_to(pg, p9, 9); save(pg); pg.reload(); pg.wait_for_selector("#rank-body tr.player"); pg.wait_for_timeout(2000)
    loc = pg.evaluate("() => [localStorage.getItem('spm_local_edits'), localStorage.getItem('spm_edit_session'), localStorage.getItem('spm_value_touch')]")
    ok(same(state(pg), g0) and all(not x or x in ("{}", "[]") for x in loc), f"Moved back and saved: the board is the published one again and the browser holds no edits ({loc})")
    ok(not errs, f"No page errors ({errs[:2]})")
    ctx.close(); br.close()

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
