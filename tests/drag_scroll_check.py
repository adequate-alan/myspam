"""Auto-scroll while dragging (Alan, Oct 11: dragging CeeDee Lamb down from #9, the board kept scrolling on its own and
he ended up at #138). Root cause: the drag listened for pointer moves and the release only on the board, through the
handle's pointer capture. Any redraw of the board mid-drag (a league sync, the ranking history or market data arriving)
replaced the dragged row, the capture was lost, and from then on the drag heard neither the pointer nor the release:
auto-scroll kept running at the last pointer position until Escape. Also, the speed was per frame (≈940px/s at 60Hz,
twice that at 120Hz). Now: moves and the release are heard on the window, the board isn't redrawn during a drag (the
redraw runs after it), a move with no button down or the window losing focus cancels the drag, and the speed is
time-based (60 → 720px/s across a 72px zone, a late frame counts at most 50ms).

Run from the repo root:  CHROMIUM=/path/to/chromium python3 tests/drag_scroll_check.py

Real mouse drags. Checks:
 1. holding near the bottom edge scrolls, at a capped speed; deeper in the zone is faster than at its start
 2. moving away from the edge stops it at once; moving back to the middle doesn't restart it
 3. releasing stops it and ends the drag; Escape cancels and stops it, the board unchanged and nothing unsaved
 4. a board redraw in the middle of a drag (what broke it): moving away still stops scrolling, and the release still
    ends the drag
 4b. redraws asked for during a drag: none happens during it, they're merged into one after the drop or cancel, the
    drop is kept and a change made mid-drag (a search) shows once the drag ends
 5. the window losing focus cancels the drag and stops scrolling
 6. no animation loop left after a drag; five drags in a row scroll at the same speed (no stacked loops)
 7. a long drag from #9 toward #138 stays controllable: it stops when the pointer leaves the edge, and the player lands
    on the rank the "#a → #b" chip showed
 8. the top edge scrolls up, and stops the same way
 9. with the player drawer open the same holds
10. ranks stay 1..N and the data stays consistent after every drop; no page errors
"""
import functools, http.server, os, re, socketserver, sys, threading, time
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
srv = socketserver.TCPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=ROOT))
threading.Thread(target=srv.serve_forever, daemon=True).start()
failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)

H = 900
with sync_playwright() as p:
    br = p.chromium.launch(**({"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}))
    pg = br.new_page(viewport={"width": 1440, "height": H})
    errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.sleeper\.(app|com)|api\.github\.com|fonts\..*|use\.typekit\.net)/.*"), lambda r: r.abort())
    pg.route("**/data/market/flock.json", lambda r: r.abort())
    pg.goto(f"http://127.0.0.1:{srv.server_address[1]}/#rankings"); pg.wait_for_selector("#rank-body tr.player .handle"); pg.wait_for_timeout(3000)
    pg.click("#pos-chips button:has-text('All')"); pg.wait_for_timeout(400)

    sy = lambda: pg.evaluate("window.scrollY")
    active = lambda: pg.locator(".drag-float").count() == 1
    chip = lambda: pg.evaluate("() => (document.querySelector('.drag-rk') || {}).textContent || null")
    snap = lambda: pg.evaluate("() => JSON.stringify(SPM.rankingSnapshot())")
    def ranks_ok():
        r = pg.evaluate("() => [...document.querySelectorAll('#rank-body tr.player')].map(t => (t.querySelector('td.rk').firstChild || {}).nodeValue)")
        return all(x == str(i + 1) for i, x in enumerate(r))
    def scrolled(ms):
        a = sy(); pg.wait_for_timeout(ms); return sy() - a
    def grab(idx, top=False):
        if top: pg.evaluate(f"document.querySelectorAll('#rank-body tr.player')[{idx}].scrollIntoView({{block: 'center'}})")
        else: pg.evaluate("window.scrollTo(0, 0)")
        pg.wait_for_timeout(250)
        x, y = pg.evaluate(f"(() => {{ const r = document.querySelectorAll('#rank-body tr.player')[{idx}].querySelector('.handle').getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; }})()")
        pg.mouse.move(x, y); pg.mouse.down()
        return x, y
    def glide(x, y0, y1, n=15):
        for i in range(n): pg.mouse.move(x, y0 + (y1 - y0) * (i + 1) / n); time.sleep(0.01)
        return y1
    def speed(ms=600):   # sampled in the page, frame by frame, so test latency can't skew it
        a = pg.evaluate("""ms => new Promise(r => { const a = []; let t0 = 0; const f = t => { if (!t0) t0 = t; a.push([t, scrollY]);
          if (t - t0 < ms) requestAnimationFrame(f); else r(a); }; requestAnimationFrame(f); })""", ms)
        return (a[-1][1] - a[0][1]) / max(1e-3, (a[-1][0] - a[0][0]) / 1000)

    # 1–3: bottom edge, move away, back to the middle, release
    before = snap()
    x, y = grab(8)
    y = glide(x, y, H - 50)                     # start of the zone
    slow = speed()
    y = glide(x, y, H - 4, 4)                   # at the edge
    fast = speed()
    ok(0 < slow < fast <= 800, f"Holding near the bottom edge scrolls: {round(slow)} px/s at the zone's start, {round(fast)} px/s at the edge (cap 720)")
    y = glide(x, y, 450, 6); pg.wait_for_timeout(60)
    away = scrolled(700)
    ok(away == 0, f"Moving away from the edge stops scrolling at once ({away}px in 0.7s)")
    y = glide(x, y, 430, 3); again = scrolled(600)
    ok(again == 0, f"Moving around the middle doesn't restart it ({again}px)")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
    after_esc = scrolled(600); pg.mouse.up(); pg.wait_for_timeout(200)
    ok(not active() and after_esc == 0 and snap() == before and pg.inner_text("#eb-count").strip() == "All saved",
       f"Escape cancels the drag and stops scrolling; the board is unchanged and nothing is unsaved ({after_esc}px)")
    x, y = grab(8); y = glide(x, y, H - 6); pg.wait_for_timeout(400)
    c = chip(); pg.mouse.up(); pg.wait_for_timeout(250)
    rel = scrolled(700)
    ok(not active() and rel == 0, f"Releasing at the edge stops scrolling and ends the drag ({rel}px after release, chip {c!r})")
    pg.wait_for_timeout(400)
    ok(ranks_ok(), "Ranks 1..N after the drop")

    # 4: a board redraw mid-drag (the live bug)
    x, y = grab(8); y = glide(x, y, H - 6); pg.wait_for_timeout(300)
    pg.evaluate("document.getElementById('rank-search').dispatchEvent(new Event('input'))")   # redraw request
    pg.wait_for_timeout(100)
    y = glide(x, y, 450, 6); pg.wait_for_timeout(60)
    mid = scrolled(700)
    c = chip(); pg.mouse.up(); pg.wait_for_timeout(300)
    post = scrolled(700)
    ok(mid == 0 and not active() and post == 0,
       f"A board redraw mid-drag: moving away still stops scrolling ({mid}px) and the release still ends the drag ({post}px after, active {active()})")
    pg.wait_for_timeout(400)
    ok(ranks_ok(), "Ranks 1..N after a drag that had a redraw waiting")

    # 4b: redraws asked for during a drag wait, are merged into one, and run after the drag (drop or cancel), from the
    # current data: the drop is kept, and a change made mid-drag (here a search) shows once the drag ends
    COUNT = """() => { if (window.__ro) window.__ro.disconnect(); window.__renders = 0; const o = new MutationObserver(rs => { window.__renders += rs.length; });
      o.observe(document.getElementById('rank-count'), { childList: true }); window.__ro = o; }"""
    renders = lambda: pg.evaluate("() => { window.__ro.takeRecords().forEach(() => window.__renders++); return window.__renders; }")
    pg.evaluate(COUNT)
    # (the pointer stays out of the auto-scroll zone here: the page scrolling on after the chip is read made the landing
    # spot a race, Oct 12; auto-scroll is checked on its own above and below)
    x, y = grab(8, top=True); y = glide(x, y, y + 3.4 * 59, 8)
    for _ in range(3): pg.evaluate("document.getElementById('rank-search').dispatchEvent(new Event('input'))")
    pg.wait_for_timeout(200)
    during = renders(); c = chip(); want = int(re.search(r"→\s*#(\d+)", c).group(1))
    pid = pg.evaluate("document.querySelectorAll('.drag-float tr.player')[0].dataset.id")
    pg.mouse.up(); pg.wait_for_timeout(700)
    after = renders() - during
    landed = pg.evaluate(f"(() => {{ const r = document.querySelector('#rank-body tr.player[data-id=\"{pid}\"]'); return r ? Number(r.querySelector('td.rk').firstChild.nodeValue) : null; }})()")
    unsaved = pg.inner_text("#eb-count").strip()
    ok(during == 0 and after == 1 and landed == want and ranks_ok() and unsaved != "All saved",
       f"3 redraws asked for mid-drag: none during the drag, {after} after the drop (merged); the drop is kept (#{landed}, chip #{want}), ranks 1..N, edit unsaved ({unsaved})")
    pg.evaluate(COUNT)
    x, y = grab(8); y = glide(x, y, y + 2.4 * 59, 6)
    target = pg.evaluate("document.querySelectorAll('#rank-body tr.player')[40].querySelector('.pl-name').textContent.trim()")
    pg.evaluate(f"() => {{ const q = document.getElementById('rank-search'); q.value = {target!r}; for (let i = 0; i < 3; i++) q.dispatchEvent(new Event('input')); }}")
    pg.wait_for_timeout(200)
    during = renders(); shown_during = pg.locator("#rank-body tr.player").count()
    pg.keyboard.press("Escape"); pg.mouse.up(); pg.wait_for_timeout(400)
    after = renders() - during; shown = pg.evaluate("() => [...document.querySelectorAll('#rank-body tr.player .pl-name')].map(e => e.textContent.trim())")
    ok(during == 0 and shown_during > 100 and after == 1 and shown == [target],
       f"A search typed mid-drag waits ({shown_during} rows during the drag) and shows once Escape ends it: {after} redraw, rows {shown}")
    pg.fill("#rank-search", ""); pg.wait_for_timeout(300)
    pg.click("#eb-cancel"); pg.wait_for_timeout(400)
    ok(ranks_ok() and pg.inner_text("#eb-count").strip() == "All saved", "Cancel changes restores the board after those drags")

    # 5: losing focus cancels
    before = snap()
    x, y = grab(8); y = glide(x, y, H - 6); pg.wait_for_timeout(200)
    pg.evaluate("window.dispatchEvent(new Event('blur'))"); pg.wait_for_timeout(100)
    blur = scrolled(600); pg.mouse.up(); pg.wait_for_timeout(300)
    ok(not active() and blur == 0 and snap() == before, f"The window losing focus cancels the drag and stops scrolling, board unchanged ({blur}px)")

    # 6: no loop left; repeated drags scroll at the same speed
    speeds = []
    for k in range(5):
        x, y = grab(4 + k); y = glide(x, y, H - 20, 8)
        speeds.append(speed(500))
        pg.keyboard.press("Escape"); pg.mouse.up(); pg.wait_for_timeout(200)
    raf = pg.evaluate("""() => new Promise(r => { let n = 0; const o = window.requestAnimationFrame; window.requestAnimationFrame = f => { n++; return o(f); };
      setTimeout(() => { window.requestAnimationFrame = o; r(n); }, 600); })""")
    ok(max(speeds) <= min(speeds) * 1.25 + 30, f"Five drags in a row scroll at the same speed (no stacked loops): {[round(s) for s in speeds]} px/s")
    ok(raf == 0, f"No animation loop left running after the drags ({raf} frame requests in 600ms)")

    # 7: the long drag, #9 toward #138
    x, y = grab(8); y = glide(x, y, H - 4, 8)
    reached, t0 = None, time.time()
    while time.time() - t0 < 25:
        c = chip(); m = re.search(r"→\s*#(\d+)", c or "")
        if m and int(m.group(1)) >= 130: reached = int(m.group(1)); break
        pg.wait_for_timeout(100)
    y = glide(x, y, 450, 4); pg.wait_for_timeout(60)
    stopped = scrolled(600)
    c = chip(); want = int(re.search(r"→\s*#(\d+)", c).group(1)) if c and "→" in c else None
    pid = pg.evaluate("document.querySelectorAll('.drag-float tr.player')[0].dataset.id")
    took = round(time.time() - t0, 1)
    pg.mouse.up(); pg.wait_for_timeout(600)
    landed = pg.evaluate(f"(() => {{ const r = document.querySelector('#rank-body tr.player[data-id=\"{pid}\"]'); return r ? Number(r.querySelector('td.rk').firstChild.nodeValue) : null; }})()")
    ok(reached and stopped == 0, f"Long drag from #9: reached #{reached} in {took}s at the edge, and stopped as soon as the pointer left it ({stopped}px)")
    ok(want is not None and landed == want and ranks_ok(), f"He lands where the chip showed: chip {c!r}, landed #{landed}; ranks 1..N")
    pg.click("#eb-cancel"); pg.wait_for_timeout(400)

    # 8: top edge
    x, y = grab(150, top=True)
    head = pg.evaluate("document.querySelector('#panel-rankings thead').getBoundingClientRect().bottom")
    y = glide(x, y, head + 6, 10)
    up = speed(600)
    y = glide(x, y, 500, 5); pg.wait_for_timeout(60)
    still = scrolled(600)
    pg.keyboard.press("Escape"); pg.mouse.up(); pg.wait_for_timeout(300)
    ok(up < -50 and still == 0, f"The top edge scrolls up ({round(up)} px/s) and stops when the pointer leaves it ({still}px)")

    # 9: with the player drawer open
    pg.evaluate("window.scrollTo(0, 0)"); pg.wait_for_timeout(200)
    pg.evaluate("() => document.querySelectorAll('#rank-body tr.player')[3].querySelector('.pl-name').click()"); pg.wait_for_timeout(1200)
    drawer = pg.evaluate("() => document.getElementById('player-modal').open")
    x, y = grab(6); y = glide(x, y, H - 6); dragging = active()
    sp = speed(400)
    y = glide(x, y, 450, 5); pg.wait_for_timeout(60); st = scrolled(600)
    pg.mouse.up(); pg.wait_for_timeout(300); pa = scrolled(500)
    ok(drawer and dragging and 50 < sp <= 800 and st == 0 and pa == 0 and not active(), f"Drawer open: edge scroll {round(sp)} px/s, stops when leaving the edge ({st}px) and on release ({pa}px)")
    pg.wait_for_timeout(400)
    ok(ranks_ok(), "Ranks 1..N at the end")
    ok(not errs, f"No page errors {errs[:3]}")
    br.close()
print(f"\n{len(failures)} check(s) failed." if failures else "\nAll auto-scroll checks passed.")
sys.exit(1 if failures else 0)
