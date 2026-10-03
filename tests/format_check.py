"""League-format check: do league settings actually reach the values?

Run from the repo root:  python3 tests/format_check.py
Needs Playwright for Python and a Chromium (set CHROMIUM=/path/to/chromium if Playwright's own isn't installed).

1. Runs SPM.formatCheck() in the page: Kittle rises with TE premium (none → + → ++), Josh Allen is worth far
   more in Superflex than 1QB, WR36 rises with more WR starters, RB30 rises with league size and FLEX spots,
   WR1 rises with points per catch, a league in the base format gives exactly the base values.
2. Connects a mock 12-team Superflex league with NO TE premium and checks the Trade Calculator uses its
   league-adjusted value for Kittle in both "No league" and league mode (never the base SPAM value),
   shows the Format adjustment table, and that a Custom format with TE Premium ++ raises his value.
3. Checks the base SPAM Board (Rankings, SPAM Board view) is unchanged throughout.
"""
import csv, functools, http.server, io, json, os, re, socketserver, sys, threading
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
rows = list(csv.DictReader(io.StringIO(re.search(r"RANKINGS_CSV\s*=\s*`(.*?)`", src, re.S).group(1).strip())))
sids = [r["sleeper_id"] for r in rows if r["sleeper_id"]][:144]
kittle = next(r for r in rows if r["player"] == "George Kittle")

# mock league: 12 teams, Superflex, Full PPR, no TE premium
rosters = [{"roster_id": i + 1, "owner_id": f"u{i+1}", "co_owners": [], "players": sids[i::12], "starters": [], "reserve": [], "taxi": [],
            "settings": {"wins": 2, "losses": 2, "ties": 0, "fpts": 400}} for i in range(12)]
users = [{"user_id": f"u{i+1}", "display_name": f"mgr{i+1}", "team_name": f"Team {i+1}", "avatar": ""} for i in range(12)]
league = {"league_id": "L1", "name": "Test League", "season": "2026", "status": "in_season", "total_rosters": 12,
          "roster_positions": ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "SUPER_FLEX"] + ["BN"] * 6,
          "scoring_settings": {"rec": 1, "pass_td": 4, "pass_yd": 0.04, "rush_yd": 0.1, "rec_yd": 0.1, "rush_td": 6, "rec_td": 6, "pass_int": -2, "fum_lost": -2},
          "settings": {"num_teams": 12, "type": 0}}
SL = {"source": "sleeper", "username": "mgr1", "userId": "u1", "displayName": "mgr1", "season": "2026",
      "leagues": [{"id": "L1", "name": "Test League", "season": "2026", "status": "in_season", "format": ""}],
      "activeId": "L1", "data": {"L1": {"league": league, "users": users, "rosters": rosters}}, "view": "league"}

def sleeper(route):
    """Mock Sleeper API: the test league, its users and rosters; empty lists for everything else."""
    path = route.request.url.split("/v1", 1)[-1].split("?")[0]
    body = {"/league/L1": league, "/league/L1/users": users, "/league/L1/rosters": rosters,
            "/state/nfl": {"season": "2026", "week": 5, "season_type": "regular"}}.get(path, [])
    route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

def serve():
    h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT)
    h.log_message = lambda *a: None
    srv = socketserver.TCPServer(("127.0.0.1", 0), h)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv.server_address[1]

failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)

num = lambda t: int(re.sub(r"[^\d]", "", t))

def board(pg):
    """Base SPAM Board as shown on Rankings (SPAM Board view): name -> value."""
    return pg.evaluate("""() => Object.fromEntries([...document.querySelectorAll('#rank-body tr.player')].map(tr =>
      [tr.querySelector('.pl-name').textContent.trim(), (tr.querySelector('.val .num') || tr.querySelector('.val .num-btn')).textContent.trim()]))""")

def open_settings(pg):
    """Open League settings the way every "League settings" / "Change" link does (data-open-fmt)."""
    pg.evaluate("() => { const b = document.createElement('button'); b.dataset.openFmt = ''; document.body.append(b); b.click(); b.remove(); }")

def calc_value(pg, name):
    return num(pg.locator("#roster-B .tc-pl", has_text=name).locator(".tc-pl-v").inner_text())

port = serve()
with sync_playwright() as p:
    kw = {"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}
    br = p.chromium.launch(**kw)
    errs = []
    def page(with_league):
        pg = br.new_page(viewport={"width": 1400, "height": 1000})
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.route("https://api.sleeper.app/**", sleeper)
        pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com)/.*"), lambda r: r.abort())
        init = "localStorage.clear();" + (f"localStorage.setItem('spm_sleeper', {json.dumps(json.dumps(SL))});localStorage.setItem('spm_tc_mode','none');" if with_league else "")
        pg.add_init_script(f"if (!sessionStorage.getItem('t')) {{ sessionStorage.setItem('t', '1'); {init} }}")
        pg.goto(f"http://127.0.0.1:{port}/#rankings"); pg.wait_for_timeout(2500)
        return pg

    # 1. the in-page self-test
    pg = page(False)
    base0 = board(pg)
    for c in pg.evaluate("() => SPM.formatCheck()"):
        ok(c["pass"], f'{c["check"]}: {c["values"]}')
    # weekly projections follow the league's scoring (one shared projection function)
    for c in pg.evaluate("() => SPM.projectionCheck()"):
        ok(c["pass"], f'Projection: {c["check"]}: {c["values"]}')
    pg.close()

    # 2. the calculator with a connected league that has no TE premium
    pg = page(True)
    pg.click("#tab-trade"); pg.wait_for_timeout(500)
    pg.evaluate("() => { const s = document.getElementById('tc-league'); s.value = 'none'; s.dispatchEvent(new Event('change', { bubbles: true })); }")
    pg.wait_for_timeout(400)
    pg.fill("#search-B", "George Kittle"); pg.wait_for_timeout(300); pg.keyboard.press("Enter"); pg.wait_for_timeout(500)
    v_none = calc_value(pg, "George Kittle")
    base_k = num(base0["George Kittle"])
    ok(v_none < base_k, f"No league mode, league without TE premium: Kittle {v_none} < base {base_k}")
    ok("test league" in pg.inner_text("#tc-badge").lower(), "Calculator says whose settings its values use: " + pg.inner_text("#tc-badge").strip())
    pg.evaluate("() => document.getElementById('tc-breakdown').open = true"); pg.wait_for_timeout(200)
    bd = pg.inner_text("#tc-breakdown-body")
    ok(all(x in bd.lower() for x in ["base spam value", "league-adjusted value", "te premium (+ → none)"]), "Value breakdown shows Base / TE premium / League-adjusted")
    m = re.search(r"George Kittle\s+([\d,]+)\s+(.*?)\s+([\d,]+)\s*$", [l for l in bd.splitlines() if "George Kittle" in l][0].replace("\t", " "))
    ok(m and num(m.group(1)) == base_k and num(m.group(3)) == v_none, f"Breakdown row: {m.group(0) if m else bd}")
    pg.evaluate("() => { const s = document.getElementById('tc-league'); s.value = 'L1'; s.dispatchEvent(new Event('change', { bubbles: true })); }")
    pg.wait_for_timeout(500)
    v_lg = calc_value(pg, "George Kittle")
    ok(v_lg == v_none, f"League mode uses the same league-adjusted value: {v_lg}")
    # custom format with TE premium ++ through the League settings dialog
    open_settings(pg); pg.wait_for_timeout(300)
    pg.click("[data-fmt-src=custom]"); pg.wait_for_timeout(200)
    pg.click("button[data-fmt=qb][data-v=sf]"); pg.click("button[data-fmt=tep][data-v='0']")
    pg.click("#fmt-apply"); pg.wait_for_timeout(700)
    v_c0 = calc_value(pg, "George Kittle")
    vals = [v_c0]
    for tep in ["0.5", "1"]:
        open_settings(pg); pg.wait_for_timeout(300)
        pg.click(f"button[data-fmt=tep][data-v='{tep}']"); pg.click("#fmt-apply"); pg.wait_for_timeout(700)
        vals.append(calc_value(pg, "George Kittle"))
    ok(vals[0] < vals[1] < vals[2], f"Calculator: Kittle with Custom format TE premium none → + → ++: {vals}")
    # 3. the base board never changes
    pg.click("#tab-rankings"); pg.wait_for_timeout(300)
    pg.evaluate("() => { const b = document.querySelector('[data-view=base]'); if (b) b.click(); }"); pg.wait_for_timeout(500)
    pg.close()
    pg = page(False)
    ok(board(pg) == base0, "Base SPAM Board unchanged")
    ok(not errs, f"No page errors {errs}")
    br.close()

print("\n" + ("All format checks passed." if not failures else f"{len(failures)} check(s) failed."))
sys.exit(1 if failures else 0)
