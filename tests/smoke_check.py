"""Release smoke test (Phase 1 reliability): the page starts and every main screen renders, in about 20 seconds. CI runs
it for every release, including rankings-only publishes, which skip the full suite when the code already passed it.

Run from the repo root:  CHROMIUM=/path/to/chromium python3 tests/smoke_check.py

Checks: no page errors; the board shows every player in RANKINGS_CSV; the page's own pre-publish checks pass on the
rankings it was served; the ranking-history snapshot of the served rankings equals the board's (the publish code uses
the first for the history it commits); every tab renders in light and dark mode; no same-origin file the page asks for
is missing (except optional ones); league-free screens show their empty states instead of failing.
"""
import csv, functools, http.server, io, os, re, socketserver, sys, threading
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
N = len(list(csv.DictReader(io.StringIO(re.search(r"const RANKINGS_CSV = `\n([\s\S]*?)\n`;", src)[1]))))
OPTIONAL = re.compile(r"/data/(projections\.json|props/)")

class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
srv = socketserver.TCPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=ROOT))
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"

failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)

with sync_playwright() as p:
    br = p.chromium.launch(**({"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}))
    for scheme in ("dark", "light"):
        ctx = br.new_context(viewport={"width": 1440, "height": 1000}, color_scheme=scheme)
        pg = ctx.new_page(); errs, missing = [], []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("response", lambda r: missing.append(r.url) if r.url.startswith(BASE) and r.status >= 400 and not OPTIONAL.search(r.url) else None)
        pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.sleeper\.(app|com)|api\.github\.com|use\.typekit\.net|fonts\.(googleapis|gstatic)\.com)/.*"), lambda r: r.abort())
        pg.goto(BASE + "/#rankings"); pg.wait_for_selector("#rank-body tr.player"); pg.wait_for_timeout(1500)
        pg.click("#pos-chips button:has-text('All')"); pg.wait_for_timeout(300)
        rows = pg.locator("#rank-body tr.player").count()
        ok(rows == N, f"[{scheme}] The board shows every player ({rows} of {N})")
        r = pg.evaluate("""async () => { const t = await (await fetch('index.html', { cache: 'no-store' })).text();
          const csv = SPM.extractRankings(t).csv;
          return { errs: SPM.validateRankings(csv), same: JSON.stringify(SPM.snapshotOf(csv)) === JSON.stringify(SPM.rankingSnapshot()) }; }""")
        ok(not r["errs"], f"[{scheme}] The served rankings pass the pre-publish checks {r['errs'][:3]}")
        ok(r["same"], f"[{scheme}] The history snapshot of the served rankings equals the board's")
        tabs = [t for t in ["myteam", "league", "finder", "trade", "rankings"] if pg.is_visible(f"#tab-{t}")]   # league tabs need a league
        ok(tabs[-1:] == ["rankings"] and "trade" in tabs, f"[{scheme}] Main tabs without a league: {tabs}")
        for tab in tabs:
            pg.click(f"#tab-{tab}"); pg.wait_for_timeout(500)
            shown = pg.evaluate(f"() => {{ const el = document.getElementById('panel-{tab}') || document.querySelector('[id^=panel-{tab}]'); return !!el && !el.hidden && el.innerText.trim().length > 0; }}")
            ok(shown, f"[{scheme}] The {tab} tab renders")
        pg.locator("#rank-body tr.player .pl-name").first.click(); pg.wait_for_timeout(1000)
        ok(pg.evaluate("() => document.getElementById('player-modal').open"), f"[{scheme}] A player page opens")
        ok(not errs, f"[{scheme}] No page errors {errs[:3]}")
        ok(not missing, f"[{scheme}] No missing same-origin files {missing[:3]}")
        ctx.close()
    br.close()

print(f"\n{len(failures)} check(s) failed." if failures else "\nAll smoke checks passed.")
sys.exit(1 if failures else 0)
