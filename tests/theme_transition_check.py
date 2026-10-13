"""Theme switch (Alan, Oct 13): light <-> dark is one coordinated 200ms crossfade, never a freeze-then-snap.

Run from the repo root:  CHROMIUM=/path/to/chromium python3 tests/theme_transition_check.py

Before: every element got `transition: … 0.25s !important` for 320ms (html.theme-anim *), so a switch built ~11k CSS
transitions on the ~9,700-element board: 1.5–2.5s of style work, the 320ms timer fired mid-freeze and the page cut
straight to the new theme (9s on a phone-speed CPU). Now setTheme flips data-theme inside a View Transition (one
snapshot crossfade on the compositor, so everything changes at the same moment) with every element's own transition
off for that style pass (theme-switching).

Checks: the first paint has the right theme for saved light / dark and the device setting, and nothing animates on
load; a switch runs one View Transition with a 200ms crossfade of the whole page (same duration and easing for the
old and new pictures), starts no CSS transition anywhere, flips data-theme, aria and theme-color, clears its classes
when done and is remembered after a reload; both directions; a quick run of clicks ends on the right theme with the
classes cleared; reduced motion and browsers without View Transitions switch instantly, also with no transitions;
another tab's change follows; every main tab, the player drawer (desktop), the player sheet (phone, a modal dialog),
an open dropdown and a hover card all end in the new theme's colors; the main-thread cost stays near a plain token
swap (no per-element transitions); no page errors.
"""
import functools, http.server, os, re, socketserver, sys, threading
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
srv = socketserver.TCPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=ROOT))
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"
EXT = re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.sleeper\.(app|com)|api\.github\.com|use\.typekit\.net|fonts\.(googleapis|gstatic)\.com)/.*")
BG = {"dark": "rgb(8, 9, 11)", "light": "rgb(236, 238, 242)"}   # --bg per theme (DESIGN.md)

failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)

# Spy installed before the page's scripts: records each View Transition, the CSS transitions alive after the
# swap's style pass, and the crossfade animations' timing.
SPY = """(() => {
  window.__tt = { vts: [], log: [] };
  const o = document.startViewTransition && document.startViewTransition.bind(document);
  if (!o) return;
  document.startViewTransition = (cb) => {
    const rec = { t0: performance.now() }; window.__tt.vts.push(rec);
    const vt = o(() => { cb(); document.body.offsetHeight;
      rec.style = performance.now() - rec.t0;
      rec.transitions = document.getAnimations().filter(a => a instanceof CSSTransition).length;
      rec.cls = document.documentElement.className; });
    vt.ready.then(() => { const as = document.getAnimations().filter(a => a.effect && String(a.effect.pseudoElement || '').startsWith('::view-transition'));
      rec.fades = as.map(a => [a.effect.pseudoElement, a.effect.getTiming().duration, getComputedStyle(document.documentElement, a.effect.pseudoElement).animationTimingFunction]); }).catch(() => {});
    vt.finished.then(() => { rec.done = performance.now() - rec.t0; setTimeout(() => { rec.after = document.documentElement.className; }, 30); });
    return vt;
  };
})();"""
NOVT = "delete Document.prototype.startViewTransition;"

def page(br, scheme="dark", width=1440, saved=None, init=(), reduced=False, mobile=False):
    ctx = br.new_context(viewport={"width": width, "height": 900 if width > 800 else 820}, color_scheme=scheme,
                         reduced_motion="reduce" if reduced else "no-preference", is_mobile=mobile, has_touch=mobile)
    if saved: ctx.add_init_script(f"try {{ if (!sessionStorage.getItem('tt-seeded')) {{ localStorage.setItem('spm_theme', '{saved}'); sessionStorage.setItem('tt-seeded', '1'); }} }} catch (e) {{}}")
    for s in init: ctx.add_init_script(s)
    pg = ctx.new_page(); errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.route(EXT, lambda r: r.abort())
    pg.goto(BASE + "/#rankings"); pg.wait_for_selector("#rank-body tr.player"); pg.wait_for_timeout(1200)
    return ctx, pg, errs

theme = lambda pg: pg.evaluate("document.documentElement.getAttribute('data-theme')")
bg = lambda pg, sel="body": pg.evaluate(f"getComputedStyle(document.querySelector({sel!r})).backgroundColor")
def surface(pg, sel):   # the first painted background inside an overlay (a dialog itself can be transparent)
    return pg.evaluate("""(sel) => { for (const e of [document.querySelector(sel), ...document.querySelectorAll(sel + ' *')]) {
      const c = getComputedStyle(e).backgroundColor; if (c && c !== 'rgba(0, 0, 0, 0)' && c !== 'transparent') return c; } return null; }""", sel)
def toggle(pg, wait=700):
    try: pg.click("#theme-toggle", timeout=1500)
    except Exception: pg.evaluate("document.getElementById('theme-toggle').click()")   # an open drawer can cover the header toggle
    pg.wait_for_timeout(wait)
def vts(pg): return pg.evaluate("window.__tt.vts")
# CSS transitions still running after a switch, leaving out the pointer resting on the toggle (its hover fill and title card)
LEFT = "document.getAnimations().filter(a => a instanceof CSSTransition && !a.effect.target.closest('#theme-toggle, #hc')).length"

with sync_playwright() as p:
    br = p.chromium.launch(**({"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}))

    # 1. First paint: the theme is set before the body exists and nothing animates on load
    probe = """(() => { document.addEventListener('readystatechange', () => {}, { once: true });
      const seen = () => { window.__first = { theme: document.documentElement.getAttribute('data-theme'), body: !!document.body }; };
      new MutationObserver((m, o) => { if (document.body) { seen(); o.disconnect(); } }).observe(document, { childList: true, subtree: true }); })();"""
    for scheme, saved, want in [("dark", "light", "light"), ("light", "dark", "dark"), ("light", None, "light"), ("dark", None, "dark")]:
        ctx, pg, errs = page(br, scheme=scheme, saved=saved, init=[probe])
        first = pg.evaluate("window.__first")
        ok(first and first["theme"] == want, f"First paint: device {scheme}, saved {saved or 'none'} -> {want} before the body is parsed ({first})")
        ok(bg(pg) == BG[want], f"First paint: page background is the {want} token ({bg(pg)})")
        ok(pg.evaluate("!document.documentElement.classList.contains('theme-switching') && !document.documentElement.classList.contains('theme-vt')"),
           f"First paint ({want}): no theme-switch classes on load")
        ok(not errs, f"First paint ({want}): no page errors {errs[:2]}")
        ctx.close()

    # 2. A switch: one coordinated crossfade, no CSS transitions, both directions, persisted
    ctx, pg, errs = page(br, init=[SPY])
    ok(pg.evaluate("typeof document.startViewTransition") == "function", "This Chromium has View Transitions")
    raw = []
    for _ in range(3):   # the plain token swap's style cost on this machine, for scale
        raw.append(pg.evaluate("""() => { const h = document.documentElement, a = h.getAttribute('data-theme'); document.body.offsetHeight;
          const t0 = performance.now(); h.setAttribute('data-theme', a === 'light' ? 'dark' : 'light'); document.body.offsetHeight;
          const t = performance.now() - t0; h.setAttribute('data-theme', a); document.body.offsetHeight; return t; }"""))
    raw_ms = sorted(raw)[1]
    for frm, to in [("dark", "light"), ("light", "dark"), ("dark", "light"), ("light", "dark")]:
        ok(theme(pg) == frm, f"{frm} -> {to}: starts {frm}")
        n = len(vts(pg)); toggle(pg)
        rec = (vts(pg) + [None])[n]
        ok(rec is not None and len(vts(pg)) == n + 1, f"{frm} -> {to}: one View Transition per click")
        if rec:
            ok(rec.get("transitions") == 0, f"{frm} -> {to}: no CSS transitions started by the swap ({rec.get('transitions')})")
            ok("theme-switching" in rec.get("cls", "") and "theme-vt" in rec.get("cls", ""), f"{frm} -> {to}: element transitions are off during the swap")
            fades = rec.get("fades") or []
            olds = [f for f in fades if "old(root)" in f[0]]; news = [f for f in fades if "new(root)" in f[0]]
            ok(olds and news and all(f[1] == 200 for f in olds + news), f"{frm} -> {to}: the whole page crossfades in 200ms ({fades})")
            ok(len({f[2] for f in olds + news}) == 1 and "cubic-bezier(0.4, 0, 0.2, 1)" in {f[2] for f in olds} and not [f for f in fades if "root" not in f[0]],
               f"{frm} -> {to}: old and new pictures share one easing, nothing else animates on its own")
            ok(rec.get("after") == "" or "theme-" not in (rec.get("after") or ""), f"{frm} -> {to}: classes cleared when done ({rec.get('after')!r})")
            print(f"     swap style pass {rec.get('style', 0):.0f}ms (plain token swap {raw_ms:.0f}ms), finished {rec.get('done', 0):.0f}ms after the click")
            ok(rec.get("style", 1e9) < 3 * raw_ms + 150, f"{frm} -> {to}: the swap costs about a plain token swap ({rec.get('style', 0):.0f}ms vs {raw_ms:.0f}ms)")
        ok(theme(pg) == to and bg(pg) == BG[to], f"{frm} -> {to}: data-theme and the page background are {to}")
        ok(pg.evaluate("localStorage.getItem('spm_theme')") == to, f"{frm} -> {to}: remembered")
        ok(pg.get_attribute("#theme-toggle", "aria-pressed") == str(to == "light").lower()
           and pg.get_attribute("#theme-toggle", "aria-label") == f"Switch to {'dark' if to == 'light' else 'light'} mode", f"{frm} -> {to}: toggle label and state")
        ok(pg.get_attribute("#theme-color", "content") == ("#F7F7F8" if to == "light" else "#08090B"), f"{frm} -> {to}: browser theme-color")
    toggle(pg); pg.reload(); pg.wait_for_selector("#rank-body tr.player")
    ok(theme(pg) == "light" and bg(pg) == BG["light"], "Reload keeps the switched theme")
    # a quick run of clicks: the last one wins, nothing left behind
    pg.evaluate("() => { for (let i = 0; i < 5; i++) document.getElementById('theme-toggle').click(); }"); pg.wait_for_timeout(900)
    ok(theme(pg) == "dark" and bg(pg) == BG["dark"], f"Five quick clicks from light end in dark ({theme(pg)})")
    ok(pg.evaluate("!/theme-(switching|vt)/.test(document.documentElement.className)"), "Five quick clicks: classes cleared")
    for _ in range(6):   # spaced repeats
        toggle(pg, 260)
    pg.wait_for_timeout(500)
    ok(theme(pg) == "dark" and pg.evaluate("!/theme-(switching|vt)/.test(document.documentElement.className)"), "Six switches 260ms apart: back to dark, clean")
    ok(not errs, f"Switching: no page errors {errs[:2]}")

    # 3. Every main tab, an open dropdown, a hover card and the drawer follow the switch
    for tab in [t for t in ["myteam", "league", "finder", "trade", "rankings"] if pg.is_visible(f"#tab-{t}")]:
        pg.click(f"#tab-{tab}"); pg.wait_for_timeout(300)
        for want in ("light", "dark"):
            toggle(pg, 600)
            ok(theme(pg) == want and bg(pg) == BG[want] and pg.evaluate(LEFT) == 0,
               f"{tab}: switches to {want} with nothing left animating")
    sel = pg.locator(".dd-btn:visible").first
    if sel.count():
        sel.click(); pg.wait_for_timeout(200)
        menu_before = pg.evaluate("(() => { const m = document.querySelector('.dd-menu:not([hidden])'); return m ? getComputedStyle(m).backgroundColor : null; })()")
        toggle(pg, 600)
        menu_after = pg.evaluate("(() => { const m = document.querySelector('.dd-menu:not([hidden])'); return m ? getComputedStyle(m).backgroundColor : null; })()")
        ok(menu_before is None or menu_after is None or menu_before != menu_after, f"Open dropdown follows the switch ({menu_before} -> {menu_after})")
        pg.keyboard.press("Escape"); toggle(pg, 600)
    pg.hover("#rank-body tr.player td.val, #rank-body tr.player .val"); pg.wait_for_timeout(600)
    if pg.evaluate("!!document.querySelector('#hc.on, #hc[data-open], #hc:not([hidden])')"):
        a = bg(pg, "#hc"); pg.evaluate("document.getElementById('theme-toggle').click()"); pg.wait_for_timeout(600)
        ok(bg(pg, "#hc") != a, f"Hover card follows the switch ({a} -> {bg(pg, '#hc')})"); pg.evaluate("document.getElementById('theme-toggle').click()"); pg.wait_for_timeout(600)
    pg.mouse.move(5, 5)
    pg.locator("#rank-body tr.player .pl-name").nth(1).click(); pg.wait_for_timeout(900)
    ok(pg.evaluate("document.getElementById('player-modal').open"), "Drawer open")
    d0 = surface(pg, "#player-modal"); n = len(vts(pg)); toggle(pg)
    ok(len(vts(pg)) == n + 1 and (vts(pg)[n] or {}).get("transitions") == 0, "Drawer open: one crossfade, no CSS transitions")
    ok(surface(pg, "#player-modal") != d0 and pg.evaluate("document.getElementById('player-modal').open"), f"Drawer follows the switch and stays open ({d0} -> {surface(pg, '#player-modal')})")
    toggle(pg)
    ok(surface(pg, "#player-modal") == d0, "Drawer back to its first theme")
    ok(not errs, f"Tabs, overlays, drawer: no page errors {errs[:2]}")
    ctx.close()

    # 4. Phone: the player page is a modal sheet (top layer); the crossfade covers it too
    ctx, pg, errs = page(br, width=390, mobile=True, init=[SPY])
    pg.locator("#rank-body tr.player .pl-name").nth(1).click(); pg.wait_for_timeout(900)
    ok(pg.evaluate("document.getElementById('player-modal').matches(':modal')"), "Phone: the player sheet is modal")
    d0 = surface(pg, "#player-modal")
    pg.evaluate("document.getElementById('theme-toggle').click()"); pg.wait_for_timeout(700)   # the toggle sits under the sheet: switch from code, as another tab would
    rec = (vts(pg) or [{}])[-1]
    ok(theme(pg) == "light" and surface(pg, "#player-modal") != d0 and rec.get("transitions") == 0, f"Phone sheet open: switches with no CSS transitions ({theme(pg)}, {d0} -> {surface(pg, '#player-modal')}, {rec})")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(300)
    toggle(pg)
    ok(theme(pg) == "dark" and bg(pg) == BG["dark"], "Phone: switches back from the header toggle")
    ok(not errs, f"Phone: no page errors {errs[:2]}")
    ctx.close()

    # 5. Reduced motion and no View Transitions: instant, still no transitions, classes cleared
    for label, kw in [("Reduced motion", {"reduced": True, "init": [SPY]}), ("No View Transitions", {"init": [NOVT, SPY]})]:
        ctx, pg, errs = page(br, **kw)
        pg.hover("#theme-toggle"); pg.wait_for_timeout(400)   # the toggle's own hover fill isn't part of the switch
        pg.evaluate("""() => { window.__tr = 0; document.addEventListener('transitionrun', () => window.__tr++, true); }""")
        pg.click("#theme-toggle")
        ok(theme(pg) == "light" and bg(pg) == BG["light"], f"{label}: the theme changes at once")
        pg.wait_for_timeout(400)
        ok(not vts(pg), f"{label}: no crossfade")
        ok(pg.evaluate("window.__tr") == 0, f"{label}: no CSS transitions run ({pg.evaluate('window.__tr')})")
        ok(pg.evaluate("!/theme-(switching|vt)/.test(document.documentElement.className)"), f"{label}: classes cleared")
        ok(not errs, f"{label}: no page errors {errs[:2]}")
        ctx.close()

    # 6. Another tab changes the theme: this one follows
    ctx, pg, errs = page(br, init=[SPY])
    other = ctx.new_page(); other.route(EXT, lambda r: r.abort())
    other.goto(BASE + "/#rankings"); other.wait_for_selector("#rank-body tr.player"); other.click("#theme-toggle"); other.wait_for_timeout(500)
    pg.wait_for_timeout(600)
    ok(theme(pg) == "light" and bg(pg) == BG["light"], "Another tab's switch is followed here")
    ok(pg.evaluate("!/theme-(switching|vt)/.test(document.documentElement.className)"), "Another tab's switch: classes cleared")
    ok(not errs, f"Another tab: no page errors {errs[:2]}")
    ctx.close()

    # 7. With a (synthetic) league: My Team, every League sub-tab, Trade Finder and the calculator, drawer open from My Team
    hub = {"__file__": os.path.join(ROOT, "tests", "league_hub_check.py"), "__name__": "hub"}; exec(open(os.path.join(ROOT, "tests", "league_hub_check.py"), encoding="utf-8").read().split("failures = []")[0], hub)
    ctx = br.new_context(viewport={"width": 1440, "height": 1000}, color_scheme="dark"); ctx.add_init_script(SPY)
    pg = ctx.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.route("https://api.sleeper.app/**", hub["sleeper"]); pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.github\.com|api\.sleeper\.com|use\.typekit\.net|fonts\.(googleapis|gstatic)\.com)/.*"), lambda r: r.abort())
    pg.goto(BASE + "/#rankings"); pg.wait_for_selector("#rank-body tr.player"); pg.wait_for_timeout(2500)
    pg.evaluate("() => { const b = document.createElement('button'); b.dataset.act = 'account'; document.getElementById('league-menu').append(b); b.click(); b.remove(); }")
    pg.wait_for_timeout(400); pg.fill("#sd-username", "tester"); pg.press("#sd-username", "Enter"); pg.wait_for_timeout(800)
    pg.locator("#sd-leagues [data-league='L1']").click(); pg.wait_for_timeout(1500)
    def both(where):
        for want in ("light", "dark"):
            n = len(vts(pg)); toggle(pg, 650); rec = (vts(pg) + [{}])[n]
            ok(theme(pg) == want and bg(pg) == BG[want] and rec.get("transitions") == 0
               and pg.evaluate(LEFT) == 0,
               f"{where}: switches to {want} in one crossfade, no CSS transitions ({theme(pg)}, {rec.get('transitions')}, " +
               str(pg.evaluate("document.getAnimations().filter(a => a instanceof CSSTransition && !a.effect.target.closest('#theme-toggle, #hc')).map(a => (a.effect.target.id || a.effect.target.className) + ':' + a.transitionProperty).slice(0, 4)")) + ")")
    for tab in ["myteam", "finder", "trade"]:
        ok(pg.is_visible(f"#tab-{tab}"), f"League connected: {tab} tab shown")
        pg.click(f"#tab-{tab}"); pg.wait_for_timeout(700); both(tab)
    pg.click("#tab-league"); pg.wait_for_timeout(700)
    for sub in pg.evaluate("[...document.querySelectorAll('[data-lsub]')].map(b => b.dataset.lsub)"):
        pg.click(f"[data-lsub='{sub}']"); pg.wait_for_timeout(600); both(f"League · {sub}")
    pg.click("#tab-myteam"); pg.wait_for_timeout(600)
    pg.locator("#panel-myteam .pl-name").first.click(); pg.wait_for_timeout(900)
    ok(pg.evaluate("document.getElementById('player-modal').open"), "My Team: drawer open")
    d0 = surface(pg, "#player-modal"); both("My Team with the drawer open")
    toggle(pg, 650); ok(surface(pg, "#player-modal") != d0 and pg.evaluate("document.getElementById('player-modal').open"), "My Team drawer follows the switch and stays open")
    toggle(pg, 650)
    ok(not errs, f"League screens: no page errors {errs[:2]}")
    ctx.close()
    br.close()

print(f"\n{len(failures)} check(s) failed." if failures else "\nAll theme transition checks passed.")
sys.exit(1 if failures else 0)
