"""Editor check: moving a player re-values him. A typed (published) value is cleared when he moves to a new spot or tier,
and the model recomputes it from the new rank, his projection and his tiermates; nothing is published (no token).

Run from the repo root:  python3 tests/editor_check.py   (CHROMIUM=/path/to/chromium if needed)
"""
import functools, http.server, os, re, socketserver, sys, threading
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT); h.log_message = lambda *a: None
srv = socketserver.TCPServer(("127.0.0.1", 0), h); threading.Thread(target=srv.serve_forever, daemon=True).start()
failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)

ROWS = """() => [...document.querySelectorAll('#rank-body tr.player')].map(tr => ({ id: tr.dataset.id, name: tr.querySelector('.pl-name').textContent.trim(),
  pos: (tr.querySelector('.pos-col .pos') || {}).textContent, tier: tr.dataset.tier || (tr.closest('tbody') && null),
  v: Number(tr.querySelector('.val .num, .val .num-btn').textContent.replace(/\\D/g, '')) }))"""
with sync_playwright() as p:
    kw = {"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}
    br = p.chromium.launch(**kw); errs = []
    pg = br.new_page(viewport={"width": 1440, "height": 1000})
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.route("https://api.github.com/**", lambda r: r.abort())
    pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.sleeper\.app)/.*"), lambda r: r.abort())
    pg.goto(f"http://127.0.0.1:{srv.server_address[1]}/#rankings"); pg.wait_for_timeout(4500)
    TIERED = """() => [...document.querySelectorAll('#rank-body tr')].reduce((o, tr) => { if (tr.dataset.tier && !tr.classList.contains('player')) o.t = tr.dataset.tier;
      if (tr.classList.contains('player')) o.rows.push({ id: tr.dataset.id, name: tr.querySelector('.pl-name').textContent.trim(), tier: tr.dataset.tier || o.t,
        v: Number(tr.querySelector('.val .num, .val .num-btn').textContent.replace(/\\D/g, '')) }); return o; }, { t: null, rows: [] }).rows"""
    def overall():
        pg.click("#pos-chips button:has-text('All')"); pg.wait_for_timeout(300)
        return pg.evaluate(ROWS)
    def ordered(rows): return all(rows[i]["v"] <= rows[i - 1]["v"] for i in range(1, len(rows)))
    # 1. tier move in a position tab: the top WR of a lower tier moves up into the tier above
    board0 = overall()
    pg.click("#pos-chips button:has-text('WR')"); pg.wait_for_timeout(400)
    wr = pg.evaluate(TIERED)
    i = next(k for k in range(1, len(wr)) if wr[k]["tier"] != wr[k - 1]["tier"] and k > 8)
    mover, above, below = wr[i], wr[i - 2], wr[i - 1]   # after the move he sits between these two (both in the upper tier)
    pg.locator(f'#rank-body tr.player[data-id="{mover["id"]}"] .arrow[data-dir="-1"]').click(force=True); pg.wait_for_timeout(700)
    wr2 = pg.evaluate(TIERED); me = next(r for r in wr2 if r["name"] == mover["name"]); k = wr2.index(me)
    toast = pg.inner_text("#toast") if pg.locator("#toast").is_visible() else ""
    ok(me["tier"] == below["tier"] and wr2[k - 1]["name"] == above["name"] and wr2[k + 1]["name"] == below["name"], f"{mover['name']} joins tier {below['tier']} between {above['name']} and {below['name']}")
    ok(wr2[k + 1]["v"] <= me["v"] <= wr2[k - 1]["v"] and me["v"] > mover["v"], f"Revalued from the tier: {mover['v']} → {me['v']} (neighbours {wr2[k - 1]['v']} / {wr2[k + 1]['v']}); toast {toast!r}")
    ok(pg.locator(f'#rank-body tr.player[data-id="{mover["id"]}"] .rv-tag').count() == 1 and pg.locator(f'#rank-body tr.player[data-id="{mover["id"]}"] .custom-pill').count() == 0, "Row says 'Revalued from tier', not CUSTOM")
    board1 = overall(); r0 = next(i for i, r in enumerate(board0) if r["name"] == mover["name"]); r1 = next(i for i, r in enumerate(board1) if r["name"] == mover["name"])
    jumped = [r["pos"] for r in board0[r1:r0] if r["pos"] != "WR"]
    ok(r1 < r0 and ordered(board1), f"Re-ranked on the overall board by value: #{r0 + 1} → #{r1 + 1}, over {len(jumped)} non-WRs; values still follow rank")
    # 2. a typed value is kept when he moves, with a "Recalculate from tier" option
    r55 = board1[55]; target = r55["name"]
    pg.locator(f'#rank-body tr.player[data-id="{r55["id"]}"] .num-btn').click(); pg.wait_for_timeout(200)
    pg.fill(".val-input", str(r55["v"] + 1)); pg.press(".val-input", "Enter"); pg.wait_for_timeout(600)
    for _ in range(12):
        pg.locator("#rank-body tr.player", has_text=target).first.locator('.arrow[data-dir="1"]').click(force=True); pg.wait_for_timeout(250)
    v2 = {r["name"]: r["v"] for r in pg.evaluate(ROWS)}
    note = pg.inner_text("#ed-warn") if pg.locator("#ed-warn").is_visible() else ""
    ok(v2[target] == r55["v"] + 1 and "kept your typed value" in note and pg.locator("[data-bend-recalc]").count() == 1, f"Moving {target} keeps his typed value {v2[target]} and offers Recalculate from tier")
    pg.click("[data-bend-recalc]"); pg.wait_for_timeout(600)
    rows2 = pg.evaluate(ROWS); v3 = {r["name"]: r["v"] for r in rows2}
    ok(v3[target] < v2[target] and ordered(rows2), f"Recalculate from tier: {v2[target]} → {v3[target]}, board in order")
    # typing a value far above his rank bends players outside his tier: warn and offer the rank where it fits
    pg.reload(); pg.wait_for_timeout(4500)
    rows3 = pg.evaluate(ROWS)
    far = rows3[100]; hi = rows3[40]["v"]
    pg.locator(f'#rank-body tr.player[data-id="{far["id"]}"] .num-btn').click(); pg.wait_for_timeout(200)
    pg.fill(".val-input", str(hi)); pg.press(".val-input", "Enter"); pg.wait_for_timeout(700)
    warn = pg.inner_text("#ed-warn") if pg.locator("#ed-warn").is_visible() else ""
    ok(far["name"] in warn and "fits around" in warn and pg.locator("[data-bend-move]").count() == 1, f"Typing {hi} for {far['name']} (#{101}) warns and offers a fitting rank: {warn[:140]!r}")
    pg.click("[data-bend-move]"); pg.wait_for_timeout(700)
    rows4 = pg.evaluate(ROWS); me = next(i for i, r in enumerate(rows4) if r["name"] == far["name"])
    vals = [r["v"] for r in rows4]
    ok(me < 60 and rows4[me]["v"] == hi and all(vals[i] <= vals[i - 1] for i in range(1, len(vals))), f"Move him there: now #{me + 1} keeping {rows4[me]['v']}, board still in order")
    # a typed value that fits his spot gives no warning
    near = rows4[120]
    pg.locator(f'#rank-body tr.player[data-id="{near["id"]}"] .num-btn').click(); pg.wait_for_timeout(200)
    pg.fill(".val-input", str(near["v"] + 1)); pg.press(".val-input", "Enter"); pg.wait_for_timeout(600)
    ok(not pg.locator("#ed-warn").is_visible(), "A typed value that fits his spot gives no warning")
    ok(not errs, f"No page errors {errs}")
    br.close()
print("\n" + ("All editor checks passed." if not failures else f"{len(failures)} check(s) failed."))
sys.exit(1 if failures else 0)
