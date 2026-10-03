"""League hub check: every League tab renders from the selected (mock) Sleeper league, and switching leagues
refreshes them. All league data here is synthetic; no real league data belongs in the repo.

Run from the repo root:  python3 tests/league_hub_check.py   (CHROMIUM=/path/to/chromium if needed)
Optional: SHOTS=/some/dir saves screenshots of each tab.
"""
import csv, functools, http.server, io, json, os, re, socketserver, sys, threading, time
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.environ.get("SHOTS")
src = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
rows = list(csv.DictReader(io.StringIO(re.search(r"RANKINGS_CSV\s*=\s*`(.*?)`", src, re.S).group(1).strip())))
sids = [r["sleeper_id"] for r in rows if r["sleeper_id"]]
name_of = {r["sleeper_id"]: r["player"] for r in rows}
NOW = int(time.time() * 1000)

def make_league(lid, name, teams, positions, scoring):
    pool = [x for x in sids if x != "7600"][:teams * 12]   # Pat Freiermuth (PIT, played Thursday of week 4) stays available
    rosters = [{"roster_id": i + 1, "owner_id": f"{lid}u{i+1}", "co_owners": [], "players": pool[i::teams], "starters": [], "reserve": [], "taxi": [],
                "settings": {"wins": (i * 7) % 4, "losses": 3 - (i * 7) % 4, "ties": 0, "fpts": 380 + 9 * i, "fpts_against": 400 - 5 * i}, "metadata": {"streak": "2W" if i % 2 else "1L"}} for i in range(teams)]
    users = [{"user_id": f"{lid}u{i+1}", "display_name": f"manager{i+1}", "metadata": {"team_name": f"{name} Team {i+1}"}} for i in range(teams)]
    league = {"league_id": lid, "name": name, "season": "2026", "status": "in_season", "total_rosters": teams, "roster_positions": positions,
              "scoring_settings": scoring, "settings": {"num_teams": teams, "type": 0, "waiver_type": 2, "waiver_clear_days": 2, "waiver_budget": 100, "leg": 4}}
    slots = [p for p in positions if p not in ("BN", "IR", "TAXI")]
    for r in rosters: r["starters"] = r["players"][:len(slots)]
    free = sids[teams * 12: teams * 12 + 6]
    tx = {1: [{"transaction_id": f"{lid}t1", "type": "trade", "status": "complete", "roster_ids": [1, 2], "leg": 1, "status_updated": NOW - 20 * 86400e3,
               "adds": {rosters[1]["players"][3]: 1, rosters[0]["players"][4]: 2}, "drops": {rosters[1]["players"][3]: 2, rosters[0]["players"][4]: 1}, "draft_picks": [], "waiver_budget": []}],
          4: [{"transaction_id": f"{lid}w1", "type": "waiver", "status": "complete", "roster_ids": [3], "leg": 4, "status_updated": NOW - 86400e3,
               "adds": {free[0]: 3}, "drops": {rosters[2]["players"][11]: 3}, "settings": {"waiver_bid": 12}},
              {"transaction_id": f"{lid}w2", "type": "waiver", "status": "failed", "roster_ids": [4], "leg": 4, "status_updated": NOW - 86400e3, "adds": {free[0]: 4}, "drops": None, "settings": {"waiver_bid": 9}},
              {"transaction_id": f"{lid}w3", "type": "waiver", "status": "failed", "roster_ids": [5], "leg": 4, "status_updated": NOW - 86400e3, "adds": {free[0]: 5}, "drops": None, "settings": {"waiver_bid": 3}},
              {"transaction_id": f"{lid}w4", "type": "waiver", "status": "failed", "roster_ids": [6], "leg": 4, "status_updated": NOW - 86400e3, "adds": {free[0]: 6}, "drops": None, "settings": {"waiver_bid": 12}, "metadata": {"notes": "Lost on waiver priority."}},
              {"transaction_id": f"{lid}f1", "type": "free_agent", "status": "complete", "roster_ids": [1], "leg": 4, "status_updated": NOW - 3600e3, "adds": {free[1]: 1}, "drops": None},
              {"transaction_id": f"{lid}d1", "type": "free_agent", "status": "complete", "roster_ids": [6], "leg": 4, "status_updated": NOW - 7200e3, "adds": None, "drops": {rosters[5]["players"][11]: 6}}]}
    # rosters as they are after these moves: team 3 claimed free[0] and dropped its last player, team 1 added free[1]
    rosters[2]["players"] = rosters[2]["players"][:11] + [free[0]]
    rosters[0]["players"] = rosters[0]["players"] + [free[1]]
    rosters[5]["players"] = rosters[5]["players"][:11]   # team 6 dropped its last player
    rosters[0]["settings"]["waiver_budget_used"] = 40      # Sleeper's own FAAB used for team 1
    # team 5 has two players on IR (still on the roster, as on Sleeper)
    rosters[4]["reserve"] = rosters[4]["players"][2:4]
    mx = []
    for i, r in enumerate(rosters):
        pts = {s: round(3 + (j * 1.7 + i * 2.3) % 20, 2) for j, s in enumerate(r["starters"])}
        mx.append({"roster_id": r["roster_id"], "matchup_id": i // 2 + 1, "points": round(sum(pts.values()), 2), "starters": r["starters"],
                   "starters_points": list(pts.values()), "players": r["players"], "players_points": pts})
    return {"league": league, "users": users, "rosters": rosters, "tx": tx, "mx": mx, "free": free}

SF = ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "SUPER_FLEX"] + ["BN"] * 6
L1 = make_league("L1", "Alpha League", 12, SF, {"rec": 1, "pass_td": 4, "pass_yd": 0.04, "pass_int": -2, "rush_yd": 0.1, "rush_td": 6, "rec_yd": 0.1, "rec_td": 6, "fum_lost": -2, "bonus_rec_te": 0.5})
L2 = make_league("L2", "Beta League", 10, ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX"] + ["BN"] * 6, {"rec": 0.5, "pass_td": 4, "pass_yd": 0.04, "pass_int": -2, "rush_yd": 0.1, "rush_td": 6, "rec_yd": 0.1, "rec_td": 6, "fum_lost": -2})
LEAGUES = {"L1": L1, "L2": L2}

def sleeper(route):
    path = route.request.url.split("/v1", 1)[-1].split("?")[0]
    body = []
    m = re.match(r"/league/(\w+)(/.*)?$", path)
    if path == "/state/nfl": body = {"season": "2026", "league_season": "2026", "week": 4, "display_week": 4, "season_type": "regular"}
    elif path.startswith("/user/") and "/leagues/" in path: body = [x["league"] for x in LEAGUES.values()]
    elif path.startswith("/user/"): body = {"user_id": "L1u1", "username": "tester", "display_name": "tester"}
    elif m and m.group(1) in LEAGUES:
        L, rest = LEAGUES[m.group(1)], m.group(2) or ""
        if rest == "": body = L["league"]
        elif rest == "/users": body = L["users"]
        elif rest == "/rosters": body = L["rosters"]
        elif rest.startswith("/transactions/"): body = L["tx"].get(int(rest.rsplit("/", 1)[1]), [])
        elif rest in ("/matchups/3", "/matchups/4"): body = L["mx"]
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

port = serve()
with sync_playwright() as p:
    kw = {"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}
    br = p.chromium.launch(**kw)
    errs = []
    pg = br.new_page(viewport={"width": 1440, "height": 1000})
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.route("https://api.sleeper.app/**", sleeper)
    pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com)/.*"), lambda r: r.abort())
    pg.goto(f"http://127.0.0.1:{port}/#rankings"); pg.wait_for_timeout(2000)
    base_board = pg.evaluate("() => SPM.rankingSnapshot ? JSON.stringify(SPM.rankingSnapshot()) : ''")
    # connect through the UI: username -> pick league
    pg.wait_for_timeout(2500)   # the update check may reload the page once
    # open the Sleeper connect dialog through the league menu's own "account" action
    pg.evaluate("() => { const b = document.createElement('button'); b.dataset.act = 'account'; document.getElementById('league-menu').append(b); b.click(); b.remove(); }")
    pg.wait_for_timeout(400)
    pg.fill("#sd-username", "tester"); pg.press("#sd-username", "Enter"); pg.wait_for_timeout(800)
    pg.locator("#sd-leagues [data-league='L1']").click(); pg.wait_for_timeout(1500)
    ok("tester" in pg.evaluate("() => localStorage.getItem('spm_sleeper') || ''"), "League data is kept in this browser's localStorage")

    # Superflex league vs a saved 1QB custom format (the Oct 4 "QB values collapsed" report)
    def qb_values():
        pg.click("#tab-rankings"); pg.wait_for_timeout(500)
        return pg.evaluate("""() => Object.fromEntries([...document.querySelectorAll('#rank-body tr.player')].map(tr => [(tr.querySelector('.pos-col .pos') || {}).textContent, tr.querySelector('.val .num, .val .num-btn').textContent.replace(/\\D/g, '')]).filter(([k]) => k && k.startsWith('QB')).map(([k, v]) => [k, Number(v)]))""")
    sf = qb_values()
    ok(pg.locator("#fmt-override").is_hidden() and "custom" not in pg.inner_text("#lc-format").lower(), "Superflex league on its own settings: no custom-format notice")
    pg.evaluate("() => { const b = document.createElement('button'); b.dataset.openFmt = ''; document.body.append(b); b.click(); b.remove(); }"); pg.wait_for_timeout(300)
    pg.click("[data-fmt-src=custom]"); pg.click("button[data-fmt=qb][data-v='1']"); pg.click("#fmt-apply"); pg.wait_for_timeout(800)
    one = qb_values()
    ok("custom" in pg.inner_text("#lc-format").lower() and pg.locator("#fmt-override").is_visible(), "A custom 1QB format shows in the league chip and as a notice on every tab")
    ok(sf["QB12"] > 2 * one["QB12"] and sf["QB20"] > 3 * one["QB20"], f"Superflex QB values are far above the custom 1QB ones: QB12 {sf['QB12']} vs {one['QB12']}, QB20 {sf['QB20']} vs {one['QB20']}")
    pg.click("[data-use-league]"); pg.wait_for_timeout(800)
    back = qb_values()
    ok(back == sf and pg.locator("#fmt-override").is_hidden(), "One click goes back to the league's own Superflex values")
    checks = pg.evaluate("() => SPM.formatCheck()")
    for c in checks:
        ok(c["pass"], "formatCheck: " + c["check"] + " " + str(c["values"])[:160])

    pg.click("#tab-league"); pg.wait_for_timeout(600)
    tabs = pg.locator("[data-lsub]").all_inner_texts()
    ok(tabs == ["Power Rankings", "Standings", "Matchups", "Transactions", "Waiver Wire"], f"League sub-tabs: {tabs}")
    ok(pg.locator("[data-lsub=power][aria-pressed=true]").count() == 1, "Power Rankings is the default")
    nav = [t.strip() for t in pg.locator(".tabs [role=tab]").all_inner_texts() if t.strip()]
    ok(nav == ["Rankings", "My Team", "League", "Trade Finder", "Trade Calculator"], f"Main nav: {nav}")
    ok(pg.locator(".pr-item").count() == 12, "Power rankings list all 12 teams")
    pg.locator(".pr-item .pr-row").nth(2).click(); pg.wait_for_timeout(400)
    ok(pg.locator(".pr-item.open .tx-board").count() == 1, "Clicking a team row expands its roster inline")
    if SHOTS: pg.screenshot(path=f"{SHOTS}/hub_power.png", full_page=False)
    # IR players: listed at the bottom of the expanded team, badged IR, not in the position columns or the score
    ir_names = [name_of[x] for x in L1["rosters"][4]["reserve"]]
    row5 = pg.locator(".pr-item", has=pg.locator(".pr-name", has_text="Alpha League Team 5"))
    score_before = row5.locator(".pr-score").inner_text()
    row5.locator(".pr-row").click(); pg.wait_for_timeout(400)
    inactive = row5.locator(".tx-pl.inactive")
    ok(inactive.count() == 2 and all(n in row5.locator(".tx-inactive").inner_text() for n in ir_names), f"Expanded team lists both IR players at the bottom: {ir_names}")
    ok(all(t.strip() == "IR" for t in inactive.locator(".tx-role").all_inner_texts()), "IR players carry an IR badge")
    board = row5.locator(".tx-board").inner_text()
    ok(not any(n in board for n in ir_names), "IR players are not in the position columns (not starters or bench)")
    ok(row5.locator(".pr-score").inner_text() == score_before, "Team score is the same with the team expanded")
    if SHOTS: row5.screenshot(path=f"{SHOTS}/hub_ir.png")

    pg.click("[data-lsub=standings]"); pg.wait_for_timeout(400)
    st = pg.inner_text(".st-table thead")
    ok("SPAM POWER RANK" in st.upper() and "MANAGER" in st.upper() and "DIFFERENCE" in st.upper(), "Standings show manager, SPAM Power Rank and the difference")
    ok(pg.locator(".st-table tbody tr").count() == 12, "Standings list all teams")
    if SHOTS: pg.screenshot(path=f"{SHOTS}/hub_standings.png")

    pg.click("[data-lsub=matchups]"); pg.wait_for_timeout(1500)
    ok(pg.locator(".mx-card").count() == 6, f"Week 4 shows 6 matchups ({pg.locator('.mx-card').count()})")
    card = pg.locator(".mx-card").first
    ok(card.locator(".mx-pr").count() == 2 and card.locator(".mx-score").count() == 2, "Each side: SPAM PR badge and a big score")
    projs = card.locator(".mx-proj").all_inner_texts()
    ok(len(projs) == 2 and all(re.search(r"PROJ\s+\d+\.\d", t.upper()) for t in projs), f"Projected score under each score: {projs}")
    pcts = [int(t.rstrip('%')) for t in card.locator(".mx-pct").all_inner_texts()]
    ok(len(pcts) == 2 and sum(pcts) == 100 and "PROJECTED MATCHUP" in card.inner_text().upper(), f"Projected matchup bar: {pcts}")
    ok("WIN PROBABILITY" not in pg.inner_text("#league-body").upper() and "TOP PLAYERS" not in pg.inner_text("#league-body").upper(), "No win probability label and no top-players clutter")
    ok("PROJECTIONS: SPAM" in pg.inner_text(".mx-source").upper(), "Data source line: Scores Sleeper · Projections SPAM")
    card.locator(".mx-show").click(); pg.wait_for_timeout(400)
    ok(pg.locator(".mx-card.open .mx-lineup").count() == 2, "Show lineups expands both starting lineups side by side")
    ok(pg.locator(".mx-card.open .mx-table tr").count() >= 16, "Lineups list every starter")
    ok(pg.locator(".mx-card.open .mx-pts.up b").count() >= 10, "Upcoming starters show their projection")
    if SHOTS: pg.screenshot(path=f"{SHOTS}/hub_matchups.png", full_page=True)
    pg.evaluate("() => { const s = document.getElementById('mx-week'); s.value = '3'; s.dispatchEvent(new Event('change', { bubbles: true })); }"); pg.wait_for_timeout(1200)
    ok(pg.locator(".mx-card.final").count() == 6 and pg.locator(".mx-res.win").count() >= 5 and pg.locator(".mx-bar").count() == 0, "A past week: final scores, the winner marked, no projection bar")
    pg.click("[data-mx-week='4']"); pg.wait_for_timeout(800)

    pg.click("[data-lsub=tx]"); pg.wait_for_timeout(1500)
    ok(pg.locator(".th-feed > article").count() == 4, f"Transactions: 1 trade + 1 waiver claim + 1 add + 1 drop ({pg.locator('.th-feed > article').count()})")
    tx_filters = pg.locator("[data-tx-type]").all_inner_texts()
    ok(tx_filters == ["All", "Trades", "Waiver Wire"], f"Transaction filters: {tx_filters}")
    tags = sorted(t.strip().lower() for t in pg.locator(".mv-card .mv-tag:not(.bidders)").all_inner_texts())
    ok(tags == ["drop", "free agent", "waiver claim"], f"Each move card says what it was: {tags}")
    ok(pg.locator(".mv-bidders").first.inner_text().strip().lower() == "4 bidders", "Waiver claim counts 4 bidders from the failed claims")
    ok(pg.locator(".mv-card.waiver .th-head .mv-bidders").count() == 1 and pg.locator(".mv-card.waiver .mv-faab .mv-bidders").count() == 0, "Bidder count sits beside WAIVER CLAIM at the top, FAAB stays with the claim")
    rail = pg.locator(".tx-rail")
    ok(rail.is_visible() and pg.evaluate("() => document.querySelector('.tx-rail').getBoundingClientRect().left > document.querySelector('.tx-feed').getBoundingClientRect().right"), "League Activity rail sits beside the feed on desktop")
    faab = [" ".join(x.split()) for x in rail.locator(".rail-card").first.locator("li").all_inner_texts()]
    left = [int(re.search(r"\$(\d+)", x).group(1)) for x in faab]
    ok(len(faab) == 12 and left == sorted(left, reverse=True), f"FAAB remaining for all 12 teams, highest first: {faab[:3]} … {faab[-2:]}")
    ok(any("Team 1" in x and "$60" in x for x in faab) and any("Team 3" in x and "$88" in x for x in faab), "FAAB uses Sleeper's budget used, else winning bids in the log")
    ok(rail.locator("li.mine").count() >= 1, "Your team is highlighted in the rail")
    act = rail.locator(".rail-card").nth(1).inner_text()
    ok("WEEK 4" in act.upper() and "1 claim" in act and "1 drop" in act, f"Most active this week with a summary line: {' '.join(act.split())[:90]}")
    top = rail.locator(".rail-card").nth(2).inner_text()
    ok("$12" in top and name_of[L1["free"][0]] in top, "Top waiver claims for the week")
    pg.locator(".mv-bidders").first.click(); pg.wait_for_timeout(300)
    ok(pg.locator("#bids-dialog").is_visible(), "Clicking the bidder count opens the bids")
    bids = [" | ".join(x.split()) for x in pg.locator("#bids-dialog .bids-list li").all_inner_texts()]
    print("   bids:", bids)
    ok(len(bids) == 4 and bids[0].startswith("$12") and "WON" in bids[0].upper() and "Team | 3" in bids[0], "Winner first, even when tied at the top bid")
    ok("TIE-BREAK" in bids[1].upper() and "$12" in bids[1] and "OUTBID" in bids[2].upper() and bids[2].startswith("$9") and bids[3].startswith("$3"), "Tie shown as lost tie-break, then outbid bids high to low")
    ok("tie at $12" in pg.inner_text("#bids-dialog").lower(), "The tie is explained, without inventing a waiver priority")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
    ok(not pg.locator("#bids-dialog").is_visible(), "Escape closes the bids")
    pg.locator(".mv-bidders").first.click(); pg.wait_for_timeout(200); pg.mouse.click(10, 10); pg.wait_for_timeout(200)
    ok(not pg.locator("#bids-dialog").is_visible(), "Clicking outside closes the bids")
    pg.locator(".mv-bidders").first.click(); pg.wait_for_timeout(200); pg.click("#bids-close"); pg.wait_for_timeout(200)
    ok(not pg.locator("#bids-dialog").is_visible(), "The X closes the bids")
    fw = pg.evaluate("() => document.querySelector('.tx-feed').getBoundingClientRect().width")
    ok(fw <= 960, f"Transactions feed stays compact on desktop ({fw:.0f}px)")
    ok(pg.locator(".mv-card.free_agent .mv-body.one").count() == 1 and pg.locator(".mv-card.drop .mv-body.one .mv-col.add").count() == 0, "An add with no drop and a drop with no add collapse the empty side")
    ok("$12" in pg.inner_text(".mv-card.waiver"), "Waiver claim shows the FAAB bid")
    ok(pg.locator(".mv-card.waiver .mv-col.drop li").count() == 1, "Waiver claim shows the drop")
    ok(pg.locator(".th-tag.pre").count() == 1, "An old trade is labeled Pre-SPAM")
    pg.click("[data-tx-type=trade]"); pg.wait_for_timeout(300)
    ok(pg.locator(".th-feed > article").count() == 1 and pg.locator("[data-th-analyze]").count() == 1, "Trades filter shows the trade with Analyze trade")
    pg.click("[data-tx-type=moves]"); pg.wait_for_timeout(300)
    ok(pg.locator(".th-feed > article.mv-card").count() == 3 and pg.locator(".th-feed > article").count() == 3, "Waiver Wire filter shows the claim, the add and the drop (no trades)")
    pg.click("[data-tx-type=all]"); pg.wait_for_timeout(300)
    pg.evaluate("() => { const s = document.getElementById('tx-week'); s.value = '1'; s.dispatchEvent(new Event('change', { bubbles: true })); }"); pg.wait_for_timeout(300)
    ok(pg.locator(".th-feed > article").count() == 1, "Week filter")
    pg.evaluate("() => { const s = document.getElementById('tx-week'); s.value = 'all'; s.dispatchEvent(new Event('change', { bubbles: true })); }"); pg.wait_for_timeout(300)
    pg.evaluate("() => { const s = document.getElementById('tx-team'); s.value = '3'; s.dispatchEvent(new Event('change', { bubbles: true })); }"); pg.wait_for_timeout(300)
    ok(pg.locator(".th-feed > article").count() == 1, "Team filter")
    pg.evaluate("() => { const s = document.getElementById('tx-team'); s.value = 'all'; s.dispatchEvent(new Event('change', { bubbles: true })); }"); pg.wait_for_timeout(300)
    if SHOTS: pg.screenshot(path=f"{SHOTS}/hub_tx.png")

    pg.click("[data-lsub=waivers]"); pg.wait_for_timeout(800)
    n_fa = pg.locator("#fa-body tr.player").count()
    ok(n_fa > 20, f"Waiver Wire lists available players ({n_fa})")
    names = pg.locator("#fa-body tr.player .pl-name").all_inner_texts()
    ok(name_of.get(L1["free"][0]) not in names, "A player claimed on waivers isn't listed as available")
    ok(pg.locator(".fa-fit-t").count() == n_fa, "Each available player shows where he'd fit on your team")
    ok(pg.locator(".fa-avail.waivers").count() >= 1, "A recently dropped player shows as on waivers")
    head = [h.strip().upper() for h in pg.locator("#fa-head th").all_inner_texts()]
    ok(head == ["RK", "PLAYER", "POS", "WK 4", "RECENT FORM", "MATCHUP", "SZN RK", "FPTS", "PPG", "FIT"], f"Waiver Wire columns: {head}")
    ok(pg.locator("#fa-body .val, #fa-body .valbar").count() == 0, "No SPAM value column or value bar on Waiver Wire")
    projs = [t.strip().split("\n")[0] for t in pg.locator("#fa-body td.fa-proj").all_inner_texts()]
    ok(all(re.fullmatch(r"\d+\.\d|—|Bye|Out|DNP", t) for t in projs) and "0.0" not in projs[:5] and sum(bool(re.fullmatch(r"\d+\.\d", t)) for t in projs) > 10, f"Weekly projections shown (— when missing, never a fake zero): {projs[:8]}")
    ranks = [int(t) for t in pg.locator("#fa-body td.rk").all_inner_texts() if t.strip().isdigit()]
    ok(ranks == sorted(ranks), "Sorted by SPAM rank by default")
    fw = pg.evaluate("() => document.getElementById('fa-wrap').getBoundingClientRect().width")
    ok(fw <= 1180, f"Waiver table stays compact on desktop ({fw:.0f}px)")
    for opt in ["proj", "form", "ppg", "matchup", "posrank"]:
        pg.evaluate(f"() => {{ const s = document.getElementById('fa-sort'); s.value = '{opt}'; s.dispatchEvent(new Event('change', {{ bubbles: true }})); }}"); pg.wait_for_timeout(250)
        ok(pg.locator("#fa-body tr.player").count() == n_fa, f"Sort by {opt}")
    pg.evaluate("() => { const s = document.getElementById('fa-sort'); s.value = 'proj'; s.dispatchEvent(new Event('change', { bubbles: true })); }"); pg.wait_for_timeout(250)
    pv = [float(t.split("\n")[0]) for t in pg.locator("#fa-body td.fa-proj").all_inner_texts() if re.fullmatch(r"\d+\.\d", t.strip().split("\n")[0])]
    ok(pv == sorted(pv, reverse=True), "Projection sort is highest first")
    # a player whose team already played this week (Thursday) shows Final + his points, never Bye
    import json as _j
    stats = _j.load(open(os.path.join(ROOT, "data/stats/2026.json")))
    played = sorted(t for t, rows in stats["schedule"].items() if any(r[0] == stats["through_week"] and r[4] is not None for r in rows))
    early = next((r for r in pg.locator("#fa-body tr.player").all() if r.locator(".pl-head").inner_text().split()[-1] in played), None)
    if early is None:
        print("   (no available player from a team that already played this week; skipped)")
    else:
        cell, mx = early.locator("td.fa-proj").inner_text().upper(), early.locator("td.fa-wk").inner_text().upper()
        ok("FINAL" in cell and "BYE" not in cell and "FINAL" in mx and "BYE" not in mx, f"Already played this week: Final, not Bye ({early.locator('.pl-name').inner_text()}: {' '.join(cell.split())} | {' '.join(mx.split())})")
        early.locator(".pl-name").click(); pg.wait_for_timeout(1500)
        tw = pg.locator(".pm-right .tw-card").inner_text().upper()
        ok("FINAL" in tw and "BYE" not in tw, f"Player modal This week shows the played game as Final: {' '.join(tw.split())[:80]}")
        pg.keyboard.press("Escape"); pg.wait_for_timeout(300)
    pg.evaluate("() => { const s = document.getElementById('fa-sort'); s.value = 'rank'; s.dispatchEvent(new Event('change', { bubbles: true })); }"); pg.wait_for_timeout(250)
    pg.locator("#fa-fitsort").check(force=True); pg.wait_for_timeout(300)
    ranks2 = [int(t) for t in pg.locator("#fa-body td.rk").all_inner_texts() if t.strip().isdigit()]
    ok(sorted(ranks2) == sorted(ranks) and ranks2 != ranks and abs(ranks2.index(ranks[0])) <= 3, "My team fit nudges starters up without reshuffling the list")
    pg.locator("#fa-fitsort").uncheck(force=True); pg.wait_for_timeout(300)
    if SHOTS: pg.screenshot(path=f"{SHOTS}/hub_waivers.png")

    # switch league: every League tab follows
    pg.evaluate("() => { const b = document.querySelector('#league-menu [data-league=\"L2\"]') || (() => { const x = document.createElement('button'); x.dataset.league = 'L2'; document.getElementById('league-menu').append(x); return x; })(); b.click(); }")
    pg.wait_for_timeout(2000)
    ok("beta league" in pg.inner_text(".lg-eyebrow").lower(), "Switching leagues updates the League hub without a reload")
    pg.click("[data-lsub=power]"); pg.wait_for_timeout(400)
    ok(pg.locator(".pr-item").count() == 10, "Power Rankings now show the other league's 10 teams")
    pg.click("[data-lsub=tx]"); pg.wait_for_timeout(1500)
    ok("Beta League Team" in pg.inner_text("#league-body"), "Transactions now come from the other league")
    pg.reload(); pg.wait_for_timeout(2000)
    ok(json.loads(pg.evaluate("() => localStorage.getItem('spm_sleeper')"))["activeId"] == "L2", "The selected league persists across refreshes")
    after = pg.evaluate("() => SPM.rankingSnapshot ? JSON.stringify(SPM.rankingSnapshot()) : ''")
    ok(after == base_board, "Base SPAM Board unchanged by any league data")
    # live matchups: the browser clock at Sunday 2:30 PM ET of week 4 (1:00 PM games in progress)
    saved = pg.evaluate("() => localStorage.getItem('spm_sleeper')")
    pg2 = br.new_page(viewport={"width": 1440, "height": 1000})
    pg2.on("pageerror", lambda e: errs.append(str(e)))
    pg2.clock.install(time="2026-10-04T18:30:00Z")
    pg2.route("https://api.sleeper.app/**", sleeper)
    pg2.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com)/.*"), lambda r: r.abort())
    pg2.add_init_script(f"if (!sessionStorage.getItem('t')) {{ sessionStorage.setItem('t', '1'); localStorage.setItem('spm_sleeper', {json.dumps(saved)}); }}")
    pg2.goto(f"http://127.0.0.1:{port}/#league"); pg2.wait_for_timeout(2500)
    pg2.evaluate("() => { const x = document.createElement('button'); x.dataset.league = 'L1'; document.getElementById('league-menu').append(x); x.click(); }"); pg2.wait_for_timeout(2000)
    pg2.click("#tab-league"); pg2.wait_for_timeout(300); pg2.click("[data-lsub=matchups]"); pg2.wait_for_timeout(1800)
    ok(pg2.locator(".mx-card.live").count() >= 1 and pg2.locator(".mx-state.live").count() >= 1, f"Sunday afternoon: matchups are live ({pg2.locator('.mx-card.live').count()})")
    lp = pg2.locator(".mx-card.live .mx-proj").first.inner_text().upper()
    ok("LIVE PROJ" in lp, f"Live projection label: {lp}")
    ok(re.search(r"\d+ played · \d+ active · \d+ remaining", pg2.inner_text(".mx-card.live .mx-left-row")) is not None, "Players played / active / remaining")
    pg2.locator(".mx-card.live .mx-show").first.click(); pg2.wait_for_timeout(400)
    ok(pg2.locator(".mx-card.open .mx-pts.live").count() >= 1 and pg2.locator(".mx-card.open .mx-livetag").count() >= 1, "Live starters show LIVE points with their projection")
    if SHOTS: pg2.screenshot(path=f"{SHOTS}/hub_matchups_live.png", full_page=True)
    ok(not errs, f"No page errors {errs}")
    br.close()

print("\n" + ("All league hub checks passed." if not failures else f"{len(failures)} check(s) failed."))
sys.exit(1 if failures else 0)
