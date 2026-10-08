"""Untrusted text from a league can't run script (Phase 1 security). Every manager in a Sleeper league controls their own
team name, display name and avatar, and a commissioner controls the league and division names; any of it reaches every
visitor who connects that league, on a page that may hold an editor's GitHub token. This loads a synthetic league whose
every free-text field is a script-injection payload, visits every tab and League sub-tab (plus the player drawer, the
calculator and the Trade Finder), and checks that no payload ran and no injected element exists.

Run from the repo root:  CHROMIUM=/path/to/chromium python3 tests/xss_check.py
"""
import csv, functools, http.server, io, json, os, re, socketserver, sys, threading, time
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
rows = list(csv.DictReader(io.StringIO(re.search(r"RANKINGS_CSV\s*=\s*`(.*?)`", src, re.S).group(1).strip())))
sids = [r["sleeper_id"] for r in rows if r["sleeper_id"]]
NOW = int(time.time() * 1000)

def payload(tag):   # markup, attribute and quote breakouts; each sets window.__xss if it ever runs
    return [f'<img src=x onerror="window.__xss=\'{tag}\'">',
            f'"><svg onload="window.__xss=\'{tag}\'">',
            f"'><img src=x onerror=window.__xss='{tag}'>",
            f'</script><script>window.__xss="{tag}"</script>',
            f'javascript:window.__xss="{tag}"']

TEAMS = 10
P = lambda tag, i: payload(tag)[i % 5]
users = [{"user_id": f"u{i+1}", "display_name": P("display", i), "username": P("username", i),
          "avatar": f'x" onerror="window.__xss=\'avatar{i}\'', "metadata": {"team_name": P("team", i), "avatar": f'https://example.invalid/a.png" onerror="window.__xss=\'mavatar{i}\''}}
         for i in range(TEAMS)]
pool = sids[:TEAMS * 12]
rosters = [{"roster_id": i + 1, "owner_id": f"u{i+1}", "co_owners": [], "players": pool[i::TEAMS], "starters": pool[i::TEAMS][:8], "reserve": [], "taxi": [],
            "settings": {"wins": i % 4, "losses": 3 - i % 4, "ties": 0, "fpts": 380 + i, "fpts_against": 390, "division": 1 + i % 2}, "metadata": {"streak": P("streak", i)}} for i in range(TEAMS)]
league = {"league_id": "X1", "name": P("league", 0), "season": "2026", "status": "in_season", "total_rosters": TEAMS,
          "roster_positions": ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "SUPER_FLEX"] + ["BN"] * 6,
          "scoring_settings": {"rec": 1, "pass_td": 4, "pass_yd": 0.04, "rush_yd": 0.1, "rush_td": 6, "rec_yd": 0.1, "rec_td": 6},
          "settings": {"num_teams": TEAMS, "leg": 4, "waiver_budget": 100, "divisions": 2, "playoff_teams": 4, "playoff_week_start": 15},
          "metadata": {"division_1": P("division", 0), "division_2": P("division", 1), "division_1_avatar": 'https://example.invalid/d.png" onerror="window.__xss=\'davatar\''}}
free = sids[TEAMS * 12: TEAMS * 12 + 3]
tx = [{"transaction_id": "t1", "type": "trade", "status": "complete", "roster_ids": [1, 2], "leg": 4, "status_updated": NOW - 86400e3,
       "adds": {rosters[1]["players"][3]: 1, rosters[0]["players"][4]: 2}, "drops": {rosters[1]["players"][3]: 2, rosters[0]["players"][4]: 1}, "draft_picks": [], "waiver_budget": []},
      {"transaction_id": "w1", "type": "waiver", "status": "complete", "roster_ids": [3], "leg": 4, "status_updated": NOW - 3600e3, "adds": {free[0]: 3}, "drops": None, "settings": {"waiver_bid": 5}},
      {"transaction_id": "w2", "type": "waiver", "status": "failed", "roster_ids": [4], "leg": 4, "status_updated": NOW - 3600e3, "adds": {free[0]: 4}, "drops": None,
       "settings": {"waiver_bid": 4}, "metadata": {"notes": P("notes", 0)}}]
mx = [{"roster_id": r["roster_id"], "matchup_id": i // 2 + 1, "points": 50 + i, "starters": r["starters"], "players": r["players"], "players_points": {}, "starters_points": []} for i, r in enumerate(rosters)]

def sleeper(route):
    path = route.request.url.split("/v1", 1)[-1].split("?")[0]
    body = []
    if path == "/state/nfl": body = {"season": "2026", "league_season": "2026", "week": 4, "display_week": 4, "season_type": "regular"}
    elif path.startswith("/user/") and "/leagues/" in path: body = [league]
    elif path.startswith("/user/"): body = {"user_id": "u1", "username": "tester", "display_name": P("me", 0)}
    elif path == "/league/X1": body = league
    elif path == "/league/X1/users": body = users
    elif path == "/league/X1/rosters": body = rosters
    elif path.startswith("/league/X1/transactions/"): body = tx if path.endswith("/4") else []
    elif path.startswith("/league/X1/matchups/"): body = mx
    route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
srv = socketserver.TCPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=ROOT))
threading.Thread(target=srv.serve_forever, daemon=True).start()

failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)

with sync_playwright() as p:
    br = p.chromium.launch(**({"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}))
    pg = br.new_page(viewport={"width": 1440, "height": 1000}); errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("dialog", lambda d: (errs.append("dialog: " + d.message), d.dismiss()))
    pg.route("https://api.sleeper.app/**", sleeper)
    pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|example\.invalid|api\.sleeper\.com|use\.typekit\.net|fonts\.(googleapis|gstatic)\.com)/.*"), lambda r: r.abort())
    pg.add_init_script("try { localStorage.setItem('spm_editor_token', 'ghp_canary_token_0000000000000000'); } catch (e) {}")
    pg.goto(f"http://127.0.0.1:{srv.server_address[1]}/#rankings"); pg.wait_for_timeout(2500)
    pg.evaluate("() => { const b = document.createElement('button'); b.dataset.act = 'account'; document.getElementById('league-menu').append(b); b.click(); b.remove(); }")
    pg.wait_for_timeout(400)
    pg.fill("#sd-username", "tester"); pg.press("#sd-username", "Enter"); pg.wait_for_timeout(800)
    pg.locator("#sd-leagues [data-league='X1']").click(); pg.wait_for_timeout(2000)
    ok("X1" in pg.evaluate("() => localStorage.getItem('spm_sleeper') || ''"), "The hostile league is connected")

    def probe(where):
        r = pg.evaluate("""() => ({ x: window.__xss || null,
          inj: [...document.querySelectorAll('img[src="x"], svg[onload], script')].filter(e => e.tagName !== 'SCRIPT' || /__xss/.test(e.textContent)).length,
          hrefs: [...document.querySelectorAll('a[href^="javascript:" i]')].length })""")
        ok(not r["x"] and not r["inj"] and not r["hrefs"], f"{where}: no payload ran, no injected element or javascript: link {r}")
    visible = 0
    for tab in ["rankings", "myteam", "league", "finder", "trade"]:
        pg.click(f"#tab-{tab}"); pg.wait_for_timeout(900)
        if tab == "league":
            for sub in ["power", "standings", "matchups", "rosters", "tx", "waivers"]:
                pg.click(f"[data-lsub={sub}]"); pg.wait_for_timeout(900)
                if sub == "power":   # expand a team's roster board
                    t = pg.locator(".pr-row, [data-team-row]").first
                    if t.count(): t.click(); pg.wait_for_timeout(500)
                if sub == "matchups":
                    b = pg.locator("button:has-text('Show lineups')").first
                    if b.count(): b.click(); pg.wait_for_timeout(500)
                if sub == "tx":
                    b = pg.locator("[data-bids]").first
                    if b.count(): b.click(); pg.wait_for_timeout(500)
                visible += pg.evaluate("() => (document.body.innerText.match(/onerror=|onload=/g) || []).length")
                probe(f"League · {sub}")
                pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
        else:
            visible += pg.evaluate("() => (document.body.innerText.match(/onerror=|onload=/g) || []).length")
            probe(tab)
    # team pickers and dropdown menus (SpamSelect) render team names too
    pg.click("#tab-trade"); pg.wait_for_timeout(500)
    for b in pg.locator(".dd-btn:visible").all()[:4]:
        try: b.click(); pg.wait_for_timeout(250); pg.keyboard.press("Escape")
        except Exception: pass
    probe("Calculator team menus")
    pg.click("#tab-rankings"); pg.wait_for_timeout(500)
    pg.locator("#rank-body tr.player .pl-name").first.click(); pg.wait_for_timeout(1200)
    probe("Player drawer")
    # control: the detector does catch a payload that really runs
    pg.evaluate("""() => document.body.insertAdjacentHTML('beforeend', '<img id="ctl" src="x" onerror="window.__xss=\\'control\\'">')"""); pg.wait_for_timeout(600)
    ok(pg.evaluate("() => window.__xss") == "control", "Detector self-test: an injected payload that runs is caught")
    pg.evaluate("() => { delete window.__xss; document.getElementById('ctl').remove(); }")
    ok(visible > 0, f"The payloads are shown as plain text ({visible} visible occurrences), not parsed as HTML")
    ok(not errs, f"No page errors or dialogs {errs[:3]}")
    br.close()

print(f"\n{len(failures)} check(s) failed." if failures else "\nAll injection checks passed.")
sys.exit(1 if failures else 0)
