"""Playoff odds: which games are still to decide (Alan, Nov 10). League → Standings' Playoff odds simulate only the
games the records don't include yet, read from the league's own matchups: each team's record counts its first g
scheduled games in week order (a bye has no game), so a game is already counted once both teams' records reach it.
Never Sleeper's current week, which lags a day behind the records after a week is processed (Nov 10: AFL's odds
replayed Week 9 a second time, "6 games left" with 5 to play).

Synthetic 12-team league (three divisions of four, 6 playoff spots, playoffs from Week 15), mocked Sleeper API, a
round-robin schedule where the higher roster id always scores more. Scenarios:
  A. Tuesday, week processed, Sleeper still on Week 9: records through Week 9 → 5 games left each
  B. Thursday night: Week 10 under way (some points in), records through Week 9 → Week 10 still counts: 5 left
  C. Monday night after the last game, before Sleeper processes it: records through Week 8, Week 9 final →
     Week 9 decided by its points (the winner's win is certain), 6 left; teams with a Week 9 bye: 5 left
  D. Sleeper moves to Week 10, nothing scored yet: 5 left
  every scenario has a bye in Week 12 for rosters 3 and 4 (they and their Week 12 opponents have one game fewer left) and checks: each team's games left,
  the odds add up to the 6 spots, projected wins = wins so far + every game left exactly once, and the weakest
  division always sends a team (division winners get in automatically).
Run from the repo root:  python3 tests/playoff_odds_check.py
"""
import functools, http.server, json, os, re, socketserver, threading
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IDS = list(range(1, 13))
DIV = {i: (i - 1) // 4 + 1 for i in IDS}          # 1–4 Swamp (the weakest), 5–8 East, 9–12 North
BYES = {12: (3, 4)}                                # week: the two rosters off that week

def schedule(w, byes):
    rot = [IDS[0]] + (IDS[1:][-(w % 11):] + IDS[1:][:-(w % 11)] if w % 11 else IDS[1:])
    pairs = [(rot[k], rot[-1 - k]) for k in range(6)]
    off = byes.get(w, ())
    return [p for p in pairs if not set(p) & set(off)], [r for p in pairs for r in p if r in off]

def score(r, w): return 100 + 3 * r + w             # higher roster id always wins

def build(rec_through, pts_through, partial=None, byes=None):
    byes = {**BYES, **(byes or {})}
    W = {i: [0, 0] for i in IDS}; PF = {i: 0.0 for i in IDS}
    for w in range(1, rec_through + 1):
        for a, b in schedule(w, byes)[0]:
            PF[a] += score(a, w); PF[b] += score(b, w)
            win, lose = (a, b) if score(a, w) > score(b, w) else (b, a)
            W[win][0] += 1; W[lose][1] += 1
    mx = {}
    for w in range(1, 15):
        pairs, off = schedule(w, byes)
        def pts(r):
            if w <= pts_through: return score(r, w)
            if partial and w == partial[0] and r in partial[1]: return score(r, w)
            return 0
        mx[w] = [{"roster_id": r, "matchup_id": k + 1, "points": pts(r), "starters": []} for k, p in enumerate(pairs) for r in p] + \
                [{"roster_id": r, "matchup_id": None, "points": 0, "starters": []} for r in off]
    rosters = [{"roster_id": i, "owner_id": "u1" if i == 11 else f"o{i}", "co_owners": [], "players": [], "starters": [], "reserve": [], "taxi": [],
                "settings": {"wins": W[i][0], "losses": W[i][1], "ties": 0, "fpts": int(PF[i]), "fpts_decimal": 0, "fpts_against": 1100, "division": DIV[i]}} for i in IDS]
    users = [{"user_id": r["owner_id"], "display_name": r["owner_id"], "metadata": {"team_name": f"Team {r['roster_id']}"}, "avatar": ""} for r in rosters]
    lg = {"league_id": "L1", "name": "League L1", "season": "2026", "status": "in_season", "total_rosters": 12,
          "metadata": {"division_1": "Swamp", "division_2": "East", "division_3": "North"},
          "roster_positions": ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "SUPER_FLEX"] + ["BN"] * 6,
          "scoring_settings": {"rec": 1, "pass_td": 4, "pass_yd": 0.04, "rush_yd": 0.1, "rec_yd": 0.1, "rush_td": 6, "rec_td": 6},
          "settings": {"num_teams": 12, "type": 0, "playoff_teams": 6, "playoff_week_start": 15, "playoff_round_type": 0, "divisions": 3, "leg": 10}}
    return lg, users, rosters, mx, byes

class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
srv = socketserver.TCPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=ROOT)); threading.Thread(target=srv.serve_forever, daemon=True).start()
failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)

with sync_playwright() as p:
    kw = {"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}
    br = p.chromium.launch(**kw); errs = []

    def odds(display_week, rec_through, pts_through, partial=None, byes=None):
        lg, users, rosters, mx, byes_ = build(rec_through, pts_through, partial, byes)
        SL = {"source": "sleeper", "username": "u1", "userId": "u1", "displayName": "u1", "season": "2026",
              "leagues": [{"id": "L1", "name": "League L1", "season": "2026", "status": "in_season", "format": ""}],
              "activeId": "L1", "data": {"L1": {"league": lg, "users": users, "rosters": rosters}}, "view": "league"}
        def sleeper(route):
            path = route.request.url.split("/v1", 1)[-1].split("?")[0]
            body = []
            m = re.match(r"/league/L1/matchups/(\d+)$", path)
            if m: body = mx.get(int(m.group(1)), [])
            elif path == "/league/L1": body = lg
            elif path == "/league/L1/users": body = users
            elif path == "/league/L1/rosters": body = rosters
            elif path == "/state/nfl": body = {"season": "2026", "week": display_week, "display_week": display_week, "season_type": "regular"}
            elif path == "/user/u1/leagues/nfl/2026": body = [lg]
            route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
        pg = br.new_page(viewport={"width": 1440, "height": 900})
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.route("https://api.sleeper.app/**", sleeper)
        pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.sleeper\.com|api\.github\.com|fonts\..*|use\.typekit\.net)/.*"), lambda r: r.abort())
        pg.add_init_script(f"if (!sessionStorage.getItem('t')) {{ sessionStorage.setItem('t', '1'); localStorage.clear(); localStorage.setItem('spm_sleeper', {json.dumps(json.dumps(SL))}); }}")
        pg.goto(f"http://127.0.0.1:{srv.server_address[1]}/#league"); pg.wait_for_timeout(1800)
        pg.click('[data-lsub="standings"]'); pg.wait_for_timeout(300)
        pg.click('[data-st-view="league"]'); pg.wait_for_timeout(1500)
        rows = pg.evaluate("() => [...document.querySelectorAll('.st-table tr.st-row')].map(r => [r.dataset.standingTeam, (r.querySelector('.st-odds') || {}).title || ''])")
        pg.close()
        out = {}
        for rid, tip in rows:
            m = re.match(r"([\d.]+)% of .* projected ([\d.]+) wins · (\d+) games? left", tip)
            out[int(rid)] = (float(m.group(1)) / 100, float(m.group(2)), int(m.group(3))) if m else None
        return out, rosters, byes_

    def check(name, res, rosters, exp_left):
        ok(all(res.get(i) for i in IDS), f"{name}: every team has odds")
        if not all(res.get(i) for i in IDS): return
        left = {i: res[i][2] for i in IDS}
        ok(left == exp_left, f"{name}: games left per team {left}")
        tot = sum(res[i][0] for i in IDS)
        ok(abs(tot - 6) <= 0.01, f"{name}: odds add up to the 6 playoff spots ({tot:.3f})")
        w = sum(r["settings"]["wins"] for r in rosters)
        ok(abs(sum(res[i][1] for i in IDS) - (w + sum(left.values()) / 2)) <= 0.6, f"{name}: projected wins = wins so far + each game left once ({sum(res[i][1] for i in IDS):.1f} vs {w + sum(left.values()) / 2})")
        sw = sum(res[i][0] for i in IDS if DIV[i] == 1)
        ok(sw >= 0.999, f"{name}: the weakest division always sends its winner ({sw:.3f})")
        return res

    # expected games left, straight from the schedule: every game from the first week the records don't include
    def games_left(first, byes):
        return {i: sum(1 for w in range(first, 15) for pr in schedule(w, {**BYES, **byes})[0] if i in pr) for i in IDS}
    five = games_left(10, {})
    ok(sorted(set(five.values())) == [4, 5], f"the Week 12 bye leaves four teams a game short ({five})")
    A, ro, _ = odds(9, 9, 9);                       check("A Tuesday, Sleeper still on Week 9", A, ro, five)
    B, ro, _ = odds(10, 9, 9, partial=(10, [1, 5, 9, 12])); check("B Thursday, Week 10 under way", B, ro, five)
    C, ro, _ = odds(9, 8, 9, byes={9: (1, 2)})
    exp_c = games_left(9, {9: (1, 2)})
    ok(exp_c[1] == five[1] and exp_c[5] == five[5] + 1, "C: the Week 9 bye teams have no Week 9 game to play")
    check("C Monday night, Week 9 final but not processed", C, ro, exp_c)
    if all(C.get(i) for i in IDS):
        pairs = schedule(9, {**BYES, 9: (1, 2)})[0]
        won = [max(a, b) for a, b in pairs]
        ok(all(C[r][1] >= ro[r - 1]["settings"]["wins"] + 1 - 0.05 for r in won), "C: each Week 9 winner by points has that win counted (exactly once)")
    D, ro, _ = odds(10, 9, 9);                      check("D Sleeper on Week 10, nothing scored", D, ro, five)
    if all(A.get(i) for i in IDS) and all(D.get(i) for i in IDS):
        ok(all(abs(A[i][0] - D[i][0]) < 1e-9 for i in IDS), "A and D (the same games left) give identical odds")

ok(not errs, f"no page errors ({errs[:3]})")
print(f"\nOK: {len(failures)} failure(s)" if not failures else f"\nFAILED: {len(failures)} failure(s)")
raise SystemExit(1 if failures else 0)
