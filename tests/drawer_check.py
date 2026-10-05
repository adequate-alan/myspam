"""Player drawer check (Alan, Oct 5): on desktop/tablet a player opens in a right-side drawer beside the Rankings
board (no backdrop, page stays scrollable and clickable, another player swaps in place, Escape closes, the board's
scroll position never moves); on phones it stays a full-screen modal sheet.

Run from the repo root:  python3 tests/drawer_check.py   (CHROMIUM=/path/to/chromium if needed)
"""
import functools, http.server, os, re, socketserver, sys, threading
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
h = functools.partial(Quiet, directory=ROOT)
srv = socketserver.TCPServer(("127.0.0.1", 0), h); threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_address[1]}/#rankings"
failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)

STATE = """() => { const m = document.getElementById('player-modal'), r = m.getBoundingClientRect();
  return { open: m.open, drawer: m.classList.contains('drawer'), modal: m.matches(':modal'), x: r.left, w: r.width, h: r.height,
    y: scrollY, name: (document.getElementById('pm-name') || {}).textContent, back: (document.querySelector('.pm-back') || {}).textContent || '',
    cur: [...document.querySelectorAll('#rank-body tr.pp-current .pl-name')].map(e => e.textContent), locked: document.documentElement.classList.contains('modal-open') }; }"""
CLICK = "i => document.querySelectorAll('#rank-body [data-player]')[i].click()"
NAME = "i => document.querySelectorAll('#rank-body [data-player]')[i].closest('tr').querySelector('.pl-name').textContent"
with sync_playwright() as p:
    kw = {"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}
    br = p.chromium.launch(**kw); errs = []
    for vw in (1440, 900):
        pg = br.new_page(viewport={"width": vw, "height": 900}); pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.sleeper\.app|api\.github\.com)/.*"), lambda r: r.abort())
        pg.goto(URL); pg.wait_for_timeout(3500)
        pg.evaluate("window.scrollTo(0, 600)"); pg.wait_for_timeout(200)
        first = pg.evaluate(NAME, 20); pg.evaluate(CLICK, 20); pg.wait_for_timeout(1500)
        s = pg.evaluate(STATE)
        ok(s["open"] and s["drawer"] and not s["modal"] and not s["locked"], f"{vw}px: opens as a non-modal drawer, page not scroll-locked")
        ok(440 <= s["w"] <= 520 and abs(s["x"] + s["w"] - vw) < 2 and s["h"] >= 899, f"{vw}px: drawer {s['w']:.0f}px wide, full height, on the right edge")
        ok(s["y"] == 600 and s["name"] == first and s["cur"] == [first], f"{vw}px: board scroll kept (600 -> {s['y']}), {first} highlighted on the board")
        second = pg.evaluate(NAME, 24); pg.evaluate(CLICK, 24); pg.wait_for_timeout(600)
        s = pg.evaluate(STATE)
        ok(s["open"] and s["name"] == second and first in s["back"] and s["y"] == 600 and s["cur"] == [second], f"{vw}px: clicking {second} on the board swaps the drawer in place (back to {first})")
        pg.mouse.move(100, 500); pg.mouse.wheel(0, 500); pg.wait_for_timeout(400)
        ok(pg.evaluate("scrollY") > 600 and pg.evaluate(STATE)["open"], f"{vw}px: the board still scrolls with the drawer open")
        if vw == 1440:
            # Weekly points chart (Alan, Oct 5): week + opponent labels, summary, avg line, BYE/OUT instead of 0.0,
            # projected weeks drawn differently from finals
            pg.click("[data-pp-tab=overview]"); pg.wait_for_timeout(600)
            wk = pg.evaluate("""() => { const c = document.querySelector('#player-body .wk-chart'); if (!c) return null;
              const tips = [...c.querySelectorAll('.hit')].map(h => h.dataset.tip);
              return { tips, xs: [...c.querySelectorAll('.wk-x')].map(t => t.textContent), opp: c.querySelectorAll('.wk-opp').length,
                sum: document.querySelector('#player-body .wk-sum').textContent, avg: !!c.querySelector('.ref-label') && c.querySelector('.ref-label').textContent,
                fin: c.querySelectorAll('.wk-pt:not(.proj):not(.live)').length, proj: c.querySelectorAll('.wk-pt.proj').length,
                marks: [...c.querySelectorAll('.wk-mark')].map(t => t.textContent) }; }""")
            ok(wk and wk["xs"] and wk["xs"][0] == "W1" and wk["opp"] > 0 and len(wk["tips"]) == len(wk["xs"]), f"Weekly points: one column per week with W# and opponent ({wk and wk['xs']})")
            ok(wk and all(k in wk["sum"] for k in ("Avg", "High", "Low")) and wk["avg"].startswith("Season avg"), f"Weekly points: summary '{wk and wk['sum']}' and season-average line")
            ok(wk and wk["fin"] > 0 and all(("pts" in t) or ("Proj" in t) or ("Bye" in t) or ("OUT" in t) or ("pending" in t) or ("Live" in t) or ("No projection" in t) for t in wk["tips"]), "Weekly points: every week's tooltip says points, projection, Live, Bye or OUT")
            ok(wk and not any(" 0.0 pts" in t and "OUT" in t for t in wk["tips"]) and all(m in ("BYE", "OUT", "—") for m in wk["marks"]), f"Weekly points: missed weeks show BYE/OUT, never 0.0 ({wk and wk['marks']})")
        pg.keyboard.press("Escape"); pg.wait_for_timeout(300)
        s = pg.evaluate(STATE)
        ok(not s["open"] and s["cur"] == [], f"{vw}px: Escape closes the drawer and clears the highlight")
        pg.close()
    # Compare (Alan, Oct 5): temporary board Compare mode + position-aware table
    pg = br.new_page(viewport={"width": 1440, "height": 1000}); pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.sleeper\.app|api\.github\.com)/.*"), lambda r: r.abort())
    pg.goto(URL); pg.wait_for_timeout(3500)
    pg.click("[data-pos=RB]"); pg.wait_for_timeout(400)
    ok(pg.locator("#rank-body .cmp-pick").count() == 0, "Compare: no pick controls during normal browsing")
    pg.evaluate("document.querySelectorAll('#rank-body [data-player]')[0].click()"); pg.wait_for_timeout(1500)
    a_name = pg.inner_text("#pm-name")
    pg.evaluate("window.scrollTo(0, 400)"); pg.wait_for_timeout(200)
    pg.click("[data-pm-compare]"); pg.wait_for_timeout(400)
    ok(pg.is_visible("#cmp-banner") and a_name in pg.inner_text("#cmp-banner") and pg.locator("#rank-body .cmp-pick").count() > 5 and pg.evaluate("scrollY") == 400,
       f"Compare: mode shows a banner for {a_name} and pick circles, scroll kept")
    ok(pg.locator("#pm-pick").count() == 1, "Compare: the drawer's search is still there")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(300)
    ok(not pg.is_visible("#cmp-banner") and pg.evaluate("document.getElementById('player-modal').open") and pg.locator("#rank-body .cmp-pick").count() == 0,
       "Compare: Escape leaves Compare mode first, the drawer stays open")
    pg.click("[data-pm-compare]"); pg.wait_for_timeout(400)
    b_name = pg.locator("#rank-body tr.cmp-row .pl-name").nth(2).inner_text()
    pg.locator("#rank-body tr.cmp-row .pl-name").nth(2).click(); pg.wait_for_timeout(800)
    secs = pg.evaluate("[...document.querySelectorAll('.cmp-sec-h')].map(r => r.textContent)")
    labels = pg.evaluate("[...document.querySelectorAll('.cmp-table th')].map(r => r.textContent)")
    ok(pg.inner_text("#pm-name") == a_name and b_name.split()[-1].upper() in pg.locator(".cmp-head").nth(1).inner_text().upper() and not pg.is_visible("#cmp-banner"),
       f"Compare: clicking {b_name} on the board makes him Player B and opens Compare")
    ok(secs[:2] == ["Value & Production", "Efficiency"] and "Target share" in labels and "Rush attempts / game" in labels and "Snap share" in labels and "Targets" not in labels,
       f"Compare: RB vs RB uses RB usage rows ({secs})")
    pg.click("[data-cmp-lens=usage]"); pg.wait_for_timeout(300)
    ok(pg.evaluate("document.querySelector('.cmp-sec-h').textContent") == "Usage & Role", "Compare: the Usage lens leads with Usage & Role")
    pg.click("[data-pm-swap]"); pg.wait_for_timeout(300)
    ok(pg.inner_text("#pm-name") != a_name and pg.evaluate("document.querySelector('[data-cmp-lens][aria-pressed=true]').dataset.cmpLens") == "usage", "Compare: Swap reverses the players and keeps the lens")
    pg.click("[data-pm-compare]"); pg.wait_for_timeout(300)
    pg.fill("#pm-pick", "Puka"); pg.wait_for_timeout(400)
    pg.click("[data-pm-pick]"); pg.wait_for_timeout(600)
    labels = pg.evaluate("[...document.querySelectorAll('.cmp-table th')].map(r => r.textContent)")
    ok("Opportunities / game" in labels and "Rush attempts / game" not in labels and "Different positions" in pg.inner_text(".cmp"),
       "Compare: RB vs WR (picked by search) falls back to shared metrics")
    ok(pg.locator(".cmp-table td.cmp-win").count() >= 1 and pg.locator(".cmp-sum p").count() >= 1, "Compare: subtle row leaders and a data-based summary")
    pg.close()
    # Injury context (Alan, Oct 5): a game he left early with an injury keeps counting in PPG but is marked everywhere
    pg = br.new_page(viewport={"width": 1440, "height": 1000}); pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.sleeper\.app|api\.github\.com)/.*"), lambda r: r.abort())
    pg.goto(URL); pg.wait_for_timeout(3500)
    hit = pg.evaluate("""async () => { const d = await (await fetch('data/stats/2026.json')).json();
      const board = new Set([...document.querySelectorAll('#rank-body .pl-name')].map(e => e.textContent.trim()));
      for (const [sid, rows] of Object.entries(d.short || {})) { const pl = d.players[sid];
        if (pl && board.has(pl.n) && pl.g.length >= 3) return { name: pl.n, week: rows[0][0], games: pl.g.length }; }
      return null; }""")
    if not hit:
        ok(True, "Injury context: no injury-shortened game for a ranked player in this season's file yet (skipped)")
    else:
        pg.fill("#rank-search", hit["name"]); pg.wait_for_timeout(400)
        pg.evaluate("document.querySelector('#rank-body [data-player]').click()"); pg.wait_for_timeout(1500)
        head = pg.inner_text(".pm-stats"); cells = pg.inner_text(".ov-grid"); summ = pg.inner_text(".wk-sum")
        tips = pg.evaluate("[...document.querySelectorAll('.wk-chart .hit')].map(h => h.dataset.tip)")
        ok("injury-shortened" in head and "injury-shortened" in summ and f"{hit['games']} G" in head,
           f"Injury context: {hit['name']} keeps {hit['games']} games in PPG and says one was injury-shortened")
        ok(any(f"Week {hit['week']} " in t and "Left early" in t for t in tips) and pg.locator(".wk-chart .wk-inj").count() >= 1,
           f"Injury context: Weekly Points marks Week {hit['week']} (marker + 'Left early — injury' tooltip)")
        pg.click("[data-pp-tab=log]"); pg.wait_for_timeout(400)
        ok(pg.locator(".gl-table .inj-tag").count() >= 1 and "injury-shortened" in pg.inner_text(".gl-table tfoot"), "Injury context: Game Log tags the game and the footer counts it")
    pg.close()
    pg = br.new_page(viewport={"width": 390, "height": 844}); pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.sleeper\.app|api\.github\.com)/.*"), lambda r: r.abort())
    pg.goto(URL); pg.wait_for_timeout(3500)
    pg.evaluate(CLICK, 3); pg.wait_for_timeout(1200)
    s = pg.evaluate(STATE)
    ok(s["open"] and not s["drawer"] and s["modal"] and s["w"] == 390, "Phone: full-screen modal sheet")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(300)
    ok(not pg.evaluate(STATE)["open"], "Phone: Escape closes the sheet")
    ok(not errs, f"No page errors {errs[:3]}")
    br.close()
print(f"{len(failures)} check(s) failed." if failures else "All drawer checks passed.")
sys.exit(1 if failures else 0)
