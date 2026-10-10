"""Drag-and-drop check (Alan, Oct 10: the drag felt laggy; this is the performance pass's regression test).
Drives real mouse drags on the Rankings board and checks both the result and how it runs:
  - drops land exactly where the "#a → #b" chip said (All tab, position tab, onto a tier header), ranks stay 1..N
  - Escape cancels and leaves the board untouched; repeated drags work
  - the floating row stays under the cursor (grab point anchored, no easing), also while the page auto-scrolls
  - the first frame after a drop already shows the row in its new slot with its new number (no frozen float)
  - no long tasks while grabbing or moving, and no whole-page restyle on grab (normal CPU speed; the limits are
    loose so a slow CI box doesn't fail it, but the old regressions blow straight through them)

Run from the repo root:  python3 tests/drag_check.py   (CHROMIUM=/path/to/chromium if needed)
"""
import functools, http.server, os, re, socketserver, sys, threading, time
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
srv = socketserver.TCPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=ROOT))
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_address[1]}/#rankings"
failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)

INSTR = r"""() => {
  const W = window.__dc = { lt: [], anchor: [], on: false, lastY: null, grab: null };
  const og = Element.prototype.getBoundingClientRect; W.og = og;
  new PerformanceObserver(l => { for (const e of l.getEntries()) if (W.on) W.lt.push(Math.round(e.duration)); }).observe({ entryTypes: ["longtask"] });
  document.addEventListener("pointermove", e => { W.lastY = e.clientY; }, true);
  const loop = () => {
    const f = document.querySelector(".drag-float");
    if (W.on && f && W.lastY != null) { const top = og.call(f).top; if (W.grab == null) W.grab = W.lastY - top; W.anchor.push(Math.abs(W.lastY - top - W.grab)); }
    requestAnimationFrame(loop);
  };
  requestAnimationFrame(loop);
}"""
ROWS = "() => [...document.querySelectorAll('#rank-body tr.player')].map(r => ({ id: r.dataset.id, rk: ((r.querySelector('td.rk .rk-btn') || r.querySelector('td.rk')).firstChild || {}).nodeValue }))"

with sync_playwright() as p:
    kw = {"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}
    br = p.chromium.launch(**kw); errs = []
    pg = br.new_page(viewport={"width": 1440, "height": 900})
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.sleeper\.(app|com)|api\.github\.com|fonts\..*|use\.typekit\.net)/.*"), lambda r: r.abort())
    pg.route("**/data/market/flock.json", lambda r: r.abort())
    pg.goto(URL); pg.wait_for_selector("#rank-body tr.player .handle"); pg.wait_for_timeout(2500)
    cdp = pg.context.new_cdp_session(pg); cdp.send("Performance.enable")
    pg.evaluate(INSTR)
    def metric(k): return next(m["value"] for m in cdp.send("Performance.getMetrics")["metrics"] if m["name"] == k)
    def grab(idx, block="center"):
        pg.evaluate(f"document.querySelectorAll('#rank-body tr.player')[{idx}].scrollIntoView({{block: '{block}'}})"); pg.wait_for_timeout(150)
        x, y = pg.evaluate(f"(() => {{ const r = window.__dc.og.call(document.querySelectorAll('#rank-body tr.player')[{idx}].querySelector('.handle')); return [r.left + r.width / 2, r.top + r.height / 2]; }})()")
        pg.evaluate("() => { const W = window.__dc; W.lt = []; W.anchor = []; W.grab = null; W.on = true; }")
        pg.mouse.move(x, y); pg.mouse.down()
        return x, y
    def move(x, y, dy, n, ms=12):
        for i in range(n):
            y += dy / n; pg.mouse.move(x, y); time.sleep(ms / 1000)
        return y
    def chip(): return pg.evaluate("() => (document.querySelector('.drag-rk') || {}).textContent || null")
    def stop(): return pg.evaluate("() => { const W = window.__dc; W.on = false; return { lt: W.lt, anchor: Math.max(0, ...W.anchor) }; }")
    def seq(rows): return all(r["rk"] == str(k + 1) for k, r in enumerate(rows))

    # 1. grab: no whole-page restyle, no long task, nothing moves until the pointer does
    pg.click("#pos-chips button:has-text('All')"); pg.wait_for_timeout(400)
    before = pg.evaluate(ROWS)
    s0 = metric("RecalcStyleDuration")
    x, y = grab(20); y = move(x, y, 6, 2)
    pg.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
    grab_style = (metric("RecalcStyleDuration") - s0) * 1000
    ok(pg.locator(".drag-float").count() == 1 and chip() == "#21", f"Grab after a few px: floating row up, chip '{chip()}' (nothing moves yet)")
    ok(grab_style < 40, f"Grab restyles only the drag elements: {grab_style:.1f}ms of style work (a body class restyled all ~9,000 elements: 50–100ms)")
    ok(not pg.evaluate("document.body.classList.contains('is-dragging')"), "No class on <body> while dragging")
    # 2. slow move across 1-2 rows, back and forth over a boundary: the slot doesn't flicker
    seen = []
    for i in range(30):
        y += 59 * 0.55 / 10 * (1 if (i // 10) % 2 == 0 else -1); pg.mouse.move(x, y); time.sleep(0.016); seen.append(chip())
    flips = sum(1 for a, b in zip(seen, seen[1:]) if a != b)
    ok(flips <= 2, f"Slow moves around a row boundary: the target changes {flips}× in 30 moves (hysteresis, no jitter)")
    # 3. Escape cancels: board unchanged
    pg.keyboard.press("Escape"); pg.mouse.up(); pg.wait_for_timeout(300)
    r = stop()
    ok(pg.evaluate(ROWS) == before and pg.locator(".drag-float, .drop-line, .drag-shield").count() == 0, "Escape cancels: board unchanged, drag visuals removed")
    ok(not r["lt"], f"No long tasks while grabbing and moving: {r['lt']}")
    ok(r["anchor"] <= 1, f"Grab point stays under the cursor every frame (max drift {r['anchor']:.1f}px)")
    # 4. fast drag down 8 rows and drop: lands where the chip said, first frame already shows it
    # (5 rows from mid-screen: the drag ends clear of the bottom auto-scroll zone, so the target can't drift on release)
    x, y = grab(30); y = move(x, y, 6, 2); y = move(x, y, 59 * 5, 20, 8)
    pg.wait_for_timeout(100)
    c = chip(); target = int(c.split("#")[-1]); did = pg.evaluate("document.querySelector('.drag-float tr.player').dataset.id")
    # the probe is armed by the pointerup itself: the first frame painted after the release
    pg.evaluate("() => { window.__first = null; document.addEventListener('pointerup', () => { const t0 = performance.now(); requestAnimationFrame(() => { const rows = [...document.querySelectorAll('#rank-body tr.player')]; const i = rows.findIndex(r => r.dataset.id === '" + did + "'); window.__first = { ms: performance.now() - t0, i: i + 1, rk: (rows[i].querySelector('td.rk .rk-btn') || rows[i].querySelector('td.rk')).firstChild.nodeValue, float: !!document.querySelector('.drag-float') }; }); }, { capture: true, once: true }); }")
    pg.mouse.up(); pg.wait_for_timeout(1200)
    r = stop(); first = pg.evaluate("window.__first"); after = pg.evaluate(ROWS)
    i = next(k for k, row in enumerate(after) if row["id"] == did)
    ok(target > 31, f"Fast drag down: chip '{c}'")
    ok(first and not first["float"] and first["i"] == target and first["rk"] == str(target), f"First frame after the drop ({first and round(first['ms'])}ms): row already at #{first and first['i']} showing '{first and first['rk']}', no frozen float")
    ok(i + 1 == target and after[i]["rk"] == str(target) and seq(after), f"After the commit he is #{i + 1} (chip said #{target}), ranks run 1..{len(after)}")
    ok(r["anchor"] <= 1, f"Fast drag: grab point anchored (max drift {r['anchor']:.1f}px)")
    # 5. auto-scroll near the bottom edge: the page scrolls, the row stays under the cursor, the target keeps updating
    x, y = grab(40); y = move(x, y, 6, 2); sy0 = pg.evaluate("scrollY"); c0 = chip()
    y = move(x, y, 880 - y, 20, 10); time.sleep(1.0); c1 = chip(); sy1 = pg.evaluate("scrollY")
    pg.keyboard.press("Escape"); pg.mouse.up(); pg.wait_for_timeout(300); r = stop()
    ok(sy1 > sy0 + 100 and c1 != c0, f"Auto-scroll: page scrolled {sy1 - sy0:.0f}px, target {c0} → {c1}")
    ok(r["anchor"] <= 1, f"Auto-scroll keeps the grab point under the cursor (max drift {r['anchor']:.1f}px)")
    ok(not [t for t in r["lt"] if t > 100], f"No long tasks over 100ms while auto-scrolling: {r['lt']}")
    # 6. repeated drags back to back (each drop commits before the next grab)
    okrep = True
    for k in range(3):
        x, y = grab(50); y = move(x, y, 6, 2); y = move(x, y, -59 * 2, 10); t = int(chip().split("#")[-1]); pg.mouse.up(); pg.wait_for_timeout(700); stop()
        rows = pg.evaluate(ROWS); okrep = okrep and seq(rows) and rows[t - 1]["rk"] == str(t)
    ok(okrep, "Three drags in a row: each lands on its chip's rank, ranks stay 1..N")
    # 7. position tab: drop onto a tier header moves him into that tier
    pg.click("#pos-chips button:has-text('WR')"); pg.wait_for_timeout(500)
    info = pg.evaluate("""() => { const rows = [...document.querySelectorAll('#rank-body tr')]; const heads = rows.filter(r => r.classList.contains('tier-edit'));
      const h = heads[3]; const last = [...document.querySelectorAll('#rank-body tr.player')].filter(r => !r.querySelector('.tier-tag'))[30];
      return { tier: h.dataset.tier, id: last.dataset.id }; }""")
    idx = pg.evaluate(f"[...document.querySelectorAll('#rank-body tr.player')].findIndex(r => r.dataset.id === '{info['id']}')")
    x, y = grab(idx); y = move(x, y, -6, 2)
    hy = pg.evaluate(f"(() => {{ const h = document.querySelector('#rank-body tr.tier-edit[data-tier=\"{info['tier']}\"]'); h.scrollIntoView({{block: 'center'}}); const r = window.__dc.og.call(h); return r.top + r.height / 2; }})()")
    pg.wait_for_timeout(100); y = move(x, y, hy - y, 20, 10); pg.wait_for_timeout(100)
    on_head = pg.evaluate("!!document.querySelector('#rank-body tr.tier-edit.drop-before')"); c = chip()
    pg.mouse.up(); pg.wait_for_timeout(1200); stop()
    tier_now = pg.evaluate(f"""(() => {{ let t = null; for (const r of document.querySelectorAll('#rank-body tr')) {{ if (r.classList.contains('tier-edit')) t = r.dataset.tier; if (r.dataset.id === '{info['id']}') return t; }} }})()""")
    ok(on_head and tier_now == info["tier"], f"Position tab: dropped on the tier {info['tier']} header (chip '{c}') → now in tier {tier_now}")
    pg.click("#pos-chips button:has-text('All')"); pg.wait_for_timeout(400)
    ok(seq(pg.evaluate(ROWS)), "Overall ranks still run 1..N after every drag")
    ok(not errs, f"No page errors {errs}")
    br.close()

print("\n" + ("All drag checks passed." if not failures else f"{len(failures)} check(s) failed."))
sys.exit(1 if failures else 0)
