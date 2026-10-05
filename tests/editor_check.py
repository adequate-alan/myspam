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
    # give a mid-board player a typed value that fits his spot (his own value + 1), then move him
    r0 = pg.evaluate(ROWS)[55]; target = r0["name"]
    pg.locator(f'#rank-body tr.player[data-id="{r0["id"]}"] .num-btn').click(); pg.wait_for_timeout(200)
    pg.fill(".val-input", str(r0["v"] + 1)); pg.press(".val-input", "Enter"); pg.wait_for_timeout(600)
    ok(target is not None, f"Typed a value for {target}")
    before = {r["name"]: r["v"] for r in pg.evaluate(ROWS)}
    pg.locator("#rank-body tr.player", has_text=target).first.locator('.arrow[data-dir="-1"]').click(force=True); pg.wait_for_timeout(600)
    after_rows = pg.evaluate(ROWS); after = {r["name"]: r["v"] for r in after_rows}
    toast = pg.inner_text("#toast") if pg.locator("#toast").is_visible() else ""
    ok(after[target] >= before[target] and target in toast, f"Moving {target} up never lowers his typed value: {before[target]} → {after[target]} ({toast!r})")
    vals = [r["v"] for r in after_rows]
    inv = [(after_rows[i - 1]["name"], vals[i - 1], after_rows[i]["name"], vals[i]) for i in range(1, len(vals)) if vals[i] > vals[i - 1]]
    ok(not inv, f"Board values still never rise down the ranks ({inv[:3]})")
    # moved down several spots: the typed value no longer fits, so it's recalculated (lower, never higher)
    for _ in range(12):
        pg.locator("#rank-body tr.player", has_text=target).first.locator('.arrow[data-dir="1"]').click(force=True); pg.wait_for_timeout(250)
    rows2 = pg.evaluate(ROWS); v2 = {r["name"]: r["v"] for r in rows2}
    ok(v2[target] < before[target] and "recalculated" in pg.inner_text("#toast"), f"Moving {target} down 12 spots recalculates his value lower: {before[target]} → {v2[target]}")
    vals = [r["v"] for r in rows2]
    ok(all(vals[i] <= vals[i - 1] for i in range(1, len(vals))), "Board values still never rise down the ranks after the moves")
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
