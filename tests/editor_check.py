"""Editor check (Architecture C, Oct 12): an edit changes only the player it acts on. Moving a player revalues him for his
new spot (the moved player adapts); everyone who only shifted keeps his value. A value you type is his value when it fits
his rank; when it doesn't, nothing changes until you pick Move to #N, Use maximum/minimum value at current rank, or Cancel.
No typed / custom state anywhere. Nothing is published (no token).

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
    others = [n for n in set(r["name"] for r in board0) if n != mover["name"]]
    v0 = {r["name"]: r["v"] for r in board0}; v1 = {r["name"]: r["v"] for r in board1}
    ok(all(v0[n] == v1[n] for n in others), f"Nobody else's value changed ({sum(v0[n] != v1[n] for n in others)} changed)")
    ok(pg.locator(".custom-pill, .auto-btn, .valbar.custom").count() == 0, "No CUSTOM pill, Auto/Reset button or striped bar anywhere")
    pg.click("#eb-cancel"); pg.wait_for_timeout(600)
    # 2. a value that fits his rank: only he changes, no notice
    rows = overall()
    k = next(i for i in range(60, 150) if rows[i - 1]["v"] - rows[i]["v"] >= 4 and rows[i]["v"] - rows[i + 1]["v"] >= 4)
    who = rows[k]; newv = who["v"] + 2
    pg.locator(f'#rank-body tr.player[data-id="{who["id"]}"] .num-btn').click(); pg.wait_for_timeout(200)
    pg.fill(".val-input", str(newv)); pg.press(".val-input", "Enter"); pg.wait_for_timeout(600)
    after = pg.evaluate(ROWS); va = {r["name"]: r["v"] for r in after}; vb = {r["name"]: r["v"] for r in rows}
    ok(not pg.locator("#ed-warn").is_visible() and va[who["name"]] == newv and all(va[n] == vb[n] for n in vb if n != who["name"]),
       f"A value that fits (#{k + 1} {who['name']} {who['v']} → {newv}) is kept exactly, nobody else changes, no notice")
    pg.click("#eb-cancel"); pg.wait_for_timeout(600)
    # 3. a value that doesn't fit: explained, nothing changes until a choice
    rows3 = overall(); far = rows3[100]; hi = rows3[40]["v"] - 1
    def type_value(r, v):
        pg.locator(f'#rank-body tr.player[data-id="{r["id"]}"] .num-btn').click(); pg.wait_for_timeout(200)
        pg.fill(".val-input", str(v)); pg.press(".val-input", "Enter"); pg.wait_for_timeout(700)
    type_value(far, hi)
    warn = pg.inner_text("#ed-warn") if pg.locator("#ed-warn").is_visible() else ""
    same = {r["name"]: r["v"] for r in pg.evaluate(ROWS)} == {r["name"]: r["v"] for r in rows3}
    ok(f"does not fit at #101" in warn and "fits around #42" in warn and "Move to #42" in warn and "Use maximum value at current rank" in warn and "Cancel" in warn and same,
       f"{hi:,} for #101 {far['name']}: explained, board unchanged until a choice: {warn[:150]!r}")
    pg.click('#ed-warn [data-ed="close"]'); pg.wait_for_timeout(400)
    ok({r["name"]: r["v"] for r in pg.evaluate(ROWS)} == {r["name"]: r["v"] for r in rows3} and not pg.locator("#ed-warn").is_visible(), "Cancel: nothing changed")
    type_value(far, hi); pg.click('#ed-warn [data-ed="move-fit"]'); pg.wait_for_timeout(800)
    rows4 = pg.evaluate(ROWS); me = next(i for i, r in enumerate(rows4) if r["name"] == far["name"])
    vals = [r["v"] for r in rows4]; vb = {r["name"]: r["v"] for r in rows3}
    ok(me == 41 and rows4[me]["v"] == hi and all(vals[i] < vals[i - 1] or vals[i] == 0 for i in range(1, len(vals)))
       and all(r["v"] == vb[r["name"]] for r in rows4 if r["name"] != far["name"]), f"Move to #42: now #{me + 1} at exactly {rows4[me]['v']:,}, nobody else changed, values strictly down the board")
    pg.click("#eb-cancel"); pg.wait_for_timeout(600)
    type_value(far, hi); pg.click('#ed-warn [data-ed="use-limit"]'); pg.wait_for_timeout(800)
    rows5 = pg.evaluate(ROWS); me = next(i for i, r in enumerate(rows5) if r["name"] == far["name"])
    ok(me == 100 and rows5[me]["v"] == rows3[99]["v"] - 1, f"Use maximum value at current rank: #{me + 1} at {rows5[me]['v']:,} (#100 is {rows3[99]['v']:,})")
    pg.click("#eb-cancel"); pg.wait_for_timeout(600)
    low = rows3[160]["v"]; type_value(far, low)
    warn = pg.inner_text("#ed-warn") if pg.locator("#ed-warn").is_visible() else ""
    ok("Use minimum value at current rank" in warn, f"A value too low offers the minimum at his rank: {warn[:120]!r}")
    pg.click('#ed-warn [data-ed="close"]'); pg.wait_for_timeout(300)
    ok(not errs, f"No page errors {errs}")
    br.close()
print("\n" + ("All editor checks passed." if not failures else f"{len(failures)} check(s) failed."))
sys.exit(1 if failures else 0)
