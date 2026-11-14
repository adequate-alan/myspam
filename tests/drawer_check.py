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
        head = pg.inner_text(".pm-key") + " " + pg.inner_text(".pm-prodrk[aria-label]")   # AM rank + value and ROS PPG in the key figures (Oct 12); PPG, games and the injury note in the FPTS / PPG line under them
        cells = pg.inner_text(".ov-grid"); summ = pg.inner_text(".wk-sum")
        tips = pg.evaluate("[...document.querySelectorAll('.wk-chart .hit')].map(h => h.dataset.tip)")
        ok("injury-shortened" in head and "injury-shortened" in summ and f"{hit['games']} G" in head,
           f"Injury context: {hit['name']} keeps {hit['games']} games in PPG and says one was injury-shortened")
        ok(any(f"Week {hit['week']} " in t and "Left early" in t for t in tips) and pg.locator(".wk-chart .wk-inj").count() >= 1,
           f"Injury context: Weekly Points marks Week {hit['week']} (marker + 'Left early — injury' tooltip)")
        pg.click("[data-pp-tab=log]"); pg.wait_for_timeout(400)
        ok(pg.locator(".gl-table .inj-tag").count() >= 1 and "injury-shortened" in pg.inner_text(".gl-table tfoot"), "Injury context: Game Log tags the game and the footer counts it")
    pg.close()
    # Section tab row (Alan, Nov 14): ten sections never fit the drawer and a regular mouse couldn't scroll the row, so
    # reaching Practice Report meant clicking the last visible tab again and again. The wheel, a drag and the chevrons
    # now scroll it; scrolling never selects a section; any section is one click away.
    BAR = """() => { const b = document.querySelector('#player-body .pp-tabwrap > .pp-tabs'), w = b.parentElement, br = b.getBoundingClientRect();
      const vis = c => { const e = w.querySelector('.pp-tabnav.' + c), cs = getComputedStyle(e); return cs.visibility === 'visible' && cs.opacity !== '0'; };
      const sc = document.querySelector('#player-modal .pm-panel'), on = b.querySelector('[aria-selected=true]'), or = on.getBoundingClientRect(), f = document.activeElement, fr = f.getBoundingClientRect();
      const L = w.classList.contains('more-l'), R = w.classList.contains('more-r'), lo = br.left + (L ? 52 : 0) - 1, hi = br.right - (R ? 52 : 0) + 1;
      return { left: Math.round(b.scrollLeft), max: Math.round(b.scrollWidth - b.clientWidth), L, R, tab: on.dataset.ppTab, panel: Math.round(sc.scrollTop), page: Math.round(scrollY),
        onIn: or.left >= lo && or.right <= hi, focus: f.dataset.ppTab || '', focusIn: fr.left >= lo && fr.right <= hi,
        shown: [vis('l'), vis('r')], tabs: [...b.querySelectorAll('[role=tab]')].map(t => t.textContent.trim()), navTab: [...w.querySelectorAll('.pp-tabnav')].map(e => e.tabIndex),
        selected: b.querySelectorAll('[aria-selected=true]').length, cx: br.left + br.width / 2, cy: br.top + br.height / 2 }; }"""
    ALL = ["Overview", "Game Log", "Schedule", "Stats", "Fantasy Performance", "Ranking History", "Trade Value", "Depth Chart", "Practice Report", "Compare"]
    for vw, theme in ((1440, "dark"), (1024, "light"), (900, "dark")):
        pg = br.new_page(viewport={"width": vw, "height": 900}); pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.sleeper\.app|api\.github\.com)/.*"), lambda r: r.abort())
        pg.add_init_script(f"try {{ localStorage.setItem('spm_theme', '{theme}'); }} catch (e) {{}}")
        pg.goto(URL); pg.wait_for_timeout(3500)
        pg.evaluate(CLICK, 5); pg.wait_for_timeout(1500)
        T = f"Tabs {vw}px {theme}: "
        s = pg.evaluate(BAR)
        ok(s["tabs"] == ALL and s["max"] > 100, T + f"all ten sections are in the row, which is wider than the drawer by {s['max']}px")
        ok(s["tab"] == "overview" and s["left"] == 0 and s["R"] and not s["L"] and s["shown"] == [False, True], T + "at the start only the right chevron shows")
        ok(s["navTab"] == [-1, -1] and pg.locator("#player-body [role=tablist] .pp-tabnav").count() == 0, T + "the chevrons are outside the tablist and the keyboard's tab order")
        # mouse wheel over the row scrolls it sideways, to the end, without selecting anything or moving the page
        pg.mouse.move(s["cx"], s["cy"]); pg.wait_for_timeout(400)
        pg.mouse.wheel(0, 120); pg.wait_for_timeout(150)
        a = pg.evaluate(BAR)
        ok(0 < a["left"] < a["max"] and a["L"] and a["R"] and a["tab"] == "overview", T + f"one wheel notch scrolls the row ({a['left']}px), both chevrons show, Overview stays selected")
        for _ in range(8): pg.mouse.wheel(0, 120); pg.wait_for_timeout(60)
        a = pg.evaluate(BAR)
        ok(a["left"] == a["max"] and a["L"] and not a["R"], T + "the wheel reaches the end: only the left chevron shows")
        ok(a["tab"] == "overview" and a["selected"] == 1 and a["panel"] == 0 and a["page"] == s["page"], T + "scrolling the row selected nothing and moved neither the drawer nor the page")
        # at the end the wheel is handed back (after the spin that got there has stopped): the drawer scrolls
        pg.wait_for_timeout(600); pg.mouse.wheel(0, 240); pg.wait_for_timeout(250)
        b = pg.evaluate(BAR)
        ok(b["panel"] > 0 and b["left"] == b["max"], T + f"at the row's end the wheel scrolls the drawer again ({b['panel']}px)")
        pg.evaluate("document.querySelector('#player-modal .pm-panel').scrollTop = 0"); pg.wait_for_timeout(400)
        # one click from Overview to Practice Report, and the row doesn't jump back
        pg.click("#player-body [data-pp-tab=practice]"); pg.wait_for_timeout(500)
        c = pg.evaluate(BAR)
        ok(c["tab"] == "practice" and c["onIn"], T + "Overview to Practice Report is one click after scrolling")
        ok(abs(c["left"] - c["max"]) <= 60, T + f"selecting it keeps the row where it was ({a['left']} -> {c['left']}), not back at the start")
        pg.click("#player-body [data-pp-tab=compare]"); pg.wait_for_timeout(500)
        c = pg.evaluate(BAR)
        ok(c["tab"] == "compare" and c["onIn"] and c["left"] == c["max"], T + "Compare, the last section, is selected and fully in view")
        # wheel up scrolls back; at the start it's handed back too
        pg.mouse.move(c["cx"], c["cy"]); pg.wait_for_timeout(400)
        for _ in range(10): pg.mouse.wheel(0, -120); pg.wait_for_timeout(60)
        d = pg.evaluate(BAR)
        ok(d["left"] == 0 and d["tab"] == "compare" and not d["L"] and d["R"], T + "wheeling back reaches the start with Compare still selected")
        # the chevron pages the row without selecting
        pg.click("#player-body .pp-tabnav.r"); pg.wait_for_timeout(700)
        e = pg.evaluate(BAR)
        ok(e["left"] > 100 and e["tab"] == "compare" and e["L"], T + f"the right chevron pages the row ({e['left']}px) and selects nothing")
        e1 = e["left"]
        while e["L"]:
            pg.click("#player-body .pp-tabnav.l"); pg.wait_for_timeout(700); e = pg.evaluate(BAR)
        pg.wait_for_timeout(300); e = pg.evaluate(BAR)
        ok(e["left"] == 0 and e["tab"] == "compare" and e["shown"] == [False, True], T + f"the left chevron pages back ({e1} -> 0) and then hides")
        # a mouse drag pans the row and its release selects nothing; a plain click still selects
        box = pg.locator("#player-body [data-pp-tab=schedule]").bounding_box(); x0, y0 = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        pg.mouse.move(x0, y0); pg.mouse.down(); pg.mouse.move(x0 - 60, y0, steps=4); pg.mouse.move(x0 - 150, y0 + 3, steps=6)
        mid = pg.evaluate("document.querySelector('#player-body .pp-tabs').classList.contains('dragging')")
        pg.mouse.up(); pg.wait_for_timeout(300)
        g = pg.evaluate(BAR)
        ok(mid and 140 <= g["left"] <= 160 and g["tab"] == "compare", T + f"dragging the row pans it ({g['left']}px) and doesn't select the tab under the pointer")
        ok(not pg.evaluate("document.querySelector('#player-body .pp-tabs').classList.contains('dragging')"), T + "the drag ends on release")
        pg.click("#player-body [data-pp-tab=stats]"); pg.wait_for_timeout(500)
        g2 = pg.evaluate(BAR)
        ok(g2["tab"] == "stats" and g2["onIn"], T + "a plain click after a drag selects as usual")
        box = pg.locator("#player-body [data-pp-tab=perf]").bounding_box(); x0, y0 = box["x"] + 6, box["y"] + box["height"] / 2
        pg.mouse.move(x0, y0); pg.mouse.down(); pg.mouse.move(x0 + 3, y0); pg.mouse.up(); pg.wait_for_timeout(500)
        ok(pg.evaluate(BAR)["tab"] == "perf", T + "a press that moves under 5px is still a click")
        # keyboard: arrows move the focus, the focused tab is brought fully into view, Enter selects
        if pg.locator("#player-body [data-pm-compare][aria-pressed=true]").count(): pg.click("#player-body [data-pm-compare]"); pg.wait_for_timeout(300)   # close the compare search: it takes the focus on every redraw
        pg.focus("#player-body [role=tab][aria-selected=true]")
        seen = []
        for _ in range(5):
            pg.keyboard.press("ArrowRight"); pg.wait_for_timeout(120); k = pg.evaluate(BAR); seen.append((k["focus"], k["focusIn"], k["tab"]))
        ok([f for f, _, _ in seen] == ["history", "value", "depth", "practice", "compare"] and all(i and t == "perf" for _, i, t in seen), T + f"arrow keys walk the tabs, each fully in view, without selecting ({seen})")
        pg.keyboard.press("Home"); pg.wait_for_timeout(120); k = pg.evaluate(BAR)
        ok(k["focus"] == "overview" and k["focusIn"] and k["left"] == 0, T + "Home focuses Overview and the row returns to the start")
        pg.keyboard.press("ArrowRight"); pg.keyboard.press("Enter"); pg.wait_for_timeout(500); k = pg.evaluate(BAR)
        ok(k["tab"] == "log" and k["focus"] == "log", T + f"Enter selects the focused tab and the focus stays on it ({k['tab']}, {k['focus']})")
        # the page under the drawer is unaffected
        pg.mouse.move(100, 500); pg.wait_for_timeout(400); y = pg.evaluate("scrollY"); pg.mouse.wheel(0, 400); pg.wait_for_timeout(400)
        ok(pg.evaluate("scrollY") > y, T + "the board still scrolls under the pointer")
        pg.close()
    # a touch swipe scrolls the row natively and selects nothing (tablet drawer)
    ctx = br.new_context(viewport={"width": 820, "height": 1100}, has_touch=True); pg = ctx.new_page(); pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.sleeper\.app|api\.github\.com)/.*"), lambda r: r.abort())
    pg.goto(URL); pg.wait_for_timeout(3500)
    pg.evaluate(CLICK, 5); pg.wait_for_timeout(1500)
    s = pg.evaluate(BAR)
    cdp = ctx.new_cdp_session(pg); x0 = s["cx"] + 120
    cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x0, "y": s["cy"]}]})
    for i in range(1, 11):
        cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": x0 - i * 25, "y": s["cy"]}]}); pg.wait_for_timeout(16)
    cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []}); pg.wait_for_timeout(500)
    t = pg.evaluate(BAR)
    ok(t["left"] > 150 and t["tab"] == "overview" and t["L"], f"Tabs touch 820px: a swipe scrolls the row natively ({t['left']}px) and selects nothing")
    pg.tap("#player-body [data-pp-tab=practice]"); pg.wait_for_timeout(500)
    t = pg.evaluate(BAR)
    ok(t["tab"] == "practice" and t["onIn"], "Tabs touch 820px: a tap selects Practice Report, fully in view")
    ctx.close()
    pg = br.new_page(viewport={"width": 390, "height": 844}); pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.sleeper\.app|api\.github\.com)/.*"), lambda r: r.abort())
    pg.goto(URL); pg.wait_for_timeout(3500)
    pg.evaluate(CLICK, 3); pg.wait_for_timeout(1200)
    s = pg.evaluate(STATE)
    ok(s["open"] and not s["drawer"] and s["modal"] and s["w"] == 390, "Phone: full-screen modal sheet")
    ph = pg.evaluate("""() => { const b = document.querySelector('#player-body'); return { wrap: !!b.querySelector('.pp-tabwrap'),
      row: [...b.querySelectorAll('.pp-tabs-phone [data-pp-tab]')].map(e => e.textContent.trim()), more: !!b.querySelector('[data-pp-more]'),
      sheet: [...b.querySelectorAll('.pp-sheet [data-pp-tab]')].map(e => e.textContent.trim()), over: b.querySelector('.pp-tabs').scrollWidth - b.querySelector('.pp-tabs').clientWidth }; }""")
    ok(not ph["wrap"] and ph["more"] and ph["row"] + ph["sheet"] == ALL and ph["over"] <= 1, f"Phone: three sections and More in a row that needs no scrolling, the other seven in the sheet ({ph['row']} + {len(ph['sheet'])})")
    pg.click("[data-pp-more]"); pg.wait_for_timeout(300); pg.click(".pp-sheet [data-pp-tab=practice]"); pg.wait_for_timeout(500)
    ok(pg.evaluate("(document.querySelector('#player-body .pr-wrap, #player-body .pm-body') || {}).id !== undefined") and "Practice" in pg.inner_text("#pp-tab-more"), "Phone: Overview to Practice Report is two taps (More, then the section)")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(300)
    ok(not pg.evaluate(STATE)["open"], "Phone: Escape closes the sheet")
    ok(not errs, f"No page errors {errs[:3]}")
    br.close()
print(f"{len(failures)} check(s) failed." if failures else "All drawer checks passed.")
sys.exit(1 if failures else 0)
