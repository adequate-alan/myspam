"""Playoff bracket (Alan, Nov 10): League → Standings → Bracket, the playoff picture if the season ended today.

Synthetic 12-team leagues only (the visitor u1 owns roster 11 in L1), mocked Sleeper API. Checks:
  1. Divisions (L1, 6 teams, 3 divisions): seeds = division winners first in record order, then the best records,
     ties on points for; a 4-5 division winner is the 3 seed above 5-4 wild cards; seeds 1 and 2 have a Bye;
     first-round games 4 vs 5 and 3 vs 6 follow Sleeper's own bracket (mocked /winners_bracket); semifinals read
     "Winner of 4 vs 5" / "Winner of 3 vs 6"; the 3rd and 5th place games; weeks from playoff_week_start;
     "tiebreak on PF" only on seeds decided on points for; the cards: first team out (with its points-for rank),
     notable (the low division winner), your team (games behind); the seeding rule line and "Updated after Week 9"
  2. No divisions and no Sleeper bracket (L2): the standard bracket built from the seeds (4, 6 and 8 teams: byes,
     pairings 1 vs lowest, 3rd place; 5th place only with two first-round games); "Table / Bracket" toggle
  3. Playoffs underway: Sleeper's results mark winners and losers and the title reads "Playoff bracket"
  4. a team opens in Power Rankings; the table views still work; both themes at 1440 and 390 with no sideways
     scroll; no page errors
Screenshots go to SHOTS=dir when set. Run from the repo root:  python3 tests/bracket_check.py
"""
import functools, http.server, json, os, re, socketserver, threading
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.environ.get("SHOTS")

# (wins, losses, pf, division): rosters 1–12
L1_REC = {1: (7, 2, 1247.7, 2), 2: (6, 3, 1293.9, 3), 3: (5, 4, 1181.2, 3), 4: (5, 4, 1144.7, 3), 5: (5, 4, 1060.5, 2),
          6: (4, 5, 1252.6, 2), 7: (4, 5, 1244.8, 1), 8: (4, 5, 1147.4, 3), 9: (4, 5, 1040.7, 1), 10: (4, 5, 988.1, 2),
          11: (3, 6, 1123.3, 1), 12: (3, 6, 1067.5, 1)}
L1_SEEDS = [1, 2, 7, 3, 4, 5]
L1_BRACKET = [{"m": 1, "r": 1, "t1": 3, "t2": 4}, {"m": 2, "r": 1, "t1": 5, "t2": 7},
              {"m": 3, "r": 2, "t1": 1, "t2_from": {"w": 1}}, {"m": 4, "r": 2, "t1": 2, "t2_from": {"w": 2}},
              {"m": 5, "r": 2, "p": 5, "t1_from": {"l": 1}, "t2_from": {"l": 2}},
              {"m": 6, "r": 3, "p": 1, "t1_from": {"w": 3}, "t2_from": {"w": 4}},
              {"m": 7, "r": 3, "p": 3, "t1_from": {"l": 3}, "t2_from": {"l": 4}}]
for m in L1_BRACKET:
    for k in ("t1", "t2", "w", "l"): m.setdefault(k, None)

def league(lid, rec, divs=None, spots=6, start=15):
    rosters = [{"roster_id": i, "owner_id": "u1" if (lid == "L1" and i == 11) or (lid == "L2" and i == 2) else f"o{i}", "co_owners": [], "players": [], "starters": [],
                "reserve": [], "taxi": [], "settings": {"wins": w, "losses": l, "ties": 0, "fpts": int(pf), "fpts_decimal": round(pf % 1 * 100),
                "fpts_against": 1100, "division": dv if divs else None}} for i, (w, l, pf, dv) in rec.items()]
    users = [{"user_id": r["owner_id"], "display_name": r["owner_id"], "metadata": {"team_name": f"{'My Team' if r['owner_id'] == 'u1' else 'Team'} {lid}-{r['roster_id']}"}, "avatar": ""} for r in rosters]
    meta = {f"division_{k}": n for k, n in (divs or {}).items()}
    lg = {"league_id": lid, "name": f"League {lid}", "season": "2026", "status": "in_season", "total_rosters": 12, "metadata": meta,
          "roster_positions": ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "SUPER_FLEX"] + ["BN"] * 6,
          "scoring_settings": {"rec": 1, "pass_td": 4, "pass_yd": 0.04, "rush_yd": 0.1, "rec_yd": 0.1, "rush_td": 6, "rec_td": 6},
          "settings": {"num_teams": 12, "type": 0, "playoff_teams": spots, "playoff_week_start": start, "playoff_round_type": 0,
                       "divisions": len(divs) if divs else 0, "leg": 10}}
    return [lg, users, rosters]

L2_REC = {i: (9 - (i + 1) // 2, (i + 1) // 2, 1300 - 10 * i, 0) for i in range(1, 13)}   # ties on record broken by PF
DIVS = {1: "Swamp", 2: "East", 3: "North"}

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

    def page(data, bracket=None, theme="dark", width=1440):
        lg, us, ro = data; lid = lg["league_id"]
        SL = {"source": "sleeper", "username": "u1", "userId": "u1", "displayName": "u1", "season": "2026",
              "leagues": [{"id": lid, "name": lg["name"], "season": "2026", "status": "in_season", "format": ""}],
              "activeId": lid, "data": {lid: {"league": lg, "users": us, "rosters": ro}}, "view": "league"}
        def sleeper(route):
            path = route.request.url.split("/v1", 1)[-1].split("?")[0]
            body = []
            m = re.match(r"/league/(L\d)(/users|/rosters|/winners_bracket)?$", path)
            if m and m.group(2) == "/winners_bracket":
                if bracket is None: return route.fulfill(status=404, body="null")
                body = bracket
            elif m: body = data[{None: 0, "/users": 1, "/rosters": 2}[m.group(2)]]
            elif path == "/state/nfl": body = {"season": "2026", "week": 10, "display_week": 10, "season_type": "regular"}
            elif path == "/user/u1/leagues/nfl/2026": body = [lg]
            route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
        pg = br.new_page(viewport={"width": width, "height": 900})
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.route("https://api.sleeper.app/**", sleeper)
        pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.sleeper\.com|api\.github\.com|fonts\..*|use\.typekit\.net)/.*"), lambda r: r.abort())
        pg.add_init_script(f"if (!sessionStorage.getItem('t')) {{ sessionStorage.setItem('t', '1'); localStorage.clear(); localStorage.setItem('spm_sleeper', {json.dumps(json.dumps(SL))}); localStorage.setItem('spm_theme', '{theme}'); }}")
        pg.goto(f"http://127.0.0.1:{srv.server_address[1]}/#league"); pg.wait_for_timeout(1800)
        pg.click('[data-lsub="standings"]'); pg.wait_for_timeout(300)
        pg.click('[data-st-view="bracket"]'); pg.wait_for_timeout(900)
        return pg

    def read(pg):
        return pg.evaluate("""() => {
          const t = el => el ? el.textContent.replace(/\\s+/g, ' ').trim() : '';
          const side = x => ({ rid: x.dataset.standingTeam || null, seed: t(x.querySelector('.br-seed')), txt: t(x.querySelector('.br-nm')), cls: x.className });
          return { cols: [...document.querySelectorAll('.br-col')].map(c => ({ h: t(c.querySelector('.br-h')), games: [...c.querySelectorAll('.br-match')].map(m => [...m.querySelectorAll('.br-team')].map(side)) })),
            place: [...document.querySelectorAll('.br-place-g')].map(g => ({ h: t(g.querySelector('.br-h')), sides: [...g.querySelectorAll('.br-team')].map(side) })),
            third: t(document.querySelector('.br-last .br-sub')),
            cards: [...document.querySelectorAll('.br-card')].map(c => [t(c.querySelector('.br-k')), t(c.querySelector('p'))]),
            title: t(document.querySelector('.br-title')), rule: t(document.querySelector('.br-rule')), stamp: t(document.querySelector('.br-stamp')),
            src: t(document.querySelector('.br-src')), sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth };
        }""")

    # 1: divisions, Sleeper's bracket
    pg = page(league("L1", L1_REC, DIVS), L1_BRACKET)
    B = read(pg)
    seeds = {s["rid"]: s["seed"] for c in B["cols"] for g in c["games"] for s in g if s["rid"]}
    ok([int(seeds[str(r)]) for r in L1_SEEDS] == [1, 2, 3, 4, 5, 6], f"seeds: division winners 1–3 in record order, then the best records on PF ({seeds})")
    ok(len(seeds) == 6, "exactly the six playoff teams appear")
    ok(B["title"] == "If the playoffs started today", f"title ({B['title']!r})")
    ok("division winners seeded 1–3 · wild cards seeded by record, ties by points for" in B["rule"] and "top 2 seeds on a bye" in B["rule"], f"seeding rule line ({B['rule']!r})")
    ok(B["stamp"] == "Updated after Week 9 games", f"stamp ({B['stamp']!r})")
    r1 = B["cols"][0]
    ok(B["cols"][0]["h"].startswith("First round") and "Week 15" in r1["h"] and "Week 16" in B["cols"][1]["h"] and B["cols"][2]["h"].startswith("Championship") and "Week 17" in B["cols"][2]["h"], f"round names and weeks ({[c['h'] for c in B['cols']]})")
    byes = [g for g in r1["games"] if any("Bye" in s["txt"] for s in g)]
    ok(sorted(g[0]["rid"] for g in byes) == ["1", "2"], "seeds 1 and 2 get a Bye card")
    games = [sorted(int(s["seed"]) for s in g) for g in r1["games"] if g not in byes]
    ok(sorted(games) == [[3, 6], [4, 5]], f"first round 4 vs 5 and 3 vs 6 ({games})")
    semi = [[s["txt"] if not s["rid"] else s["seed"] for s in g] for g in B["cols"][1]["games"]]
    ok(sorted(semi) == [["1", "Winner of 4 vs 5"], ["2", "Winner of 3 vs 6"]], f"semifinals ({semi})")
    ok(all(not s["rid"] and "semifinal" in s["txt"] for g in B["cols"][2]["games"] for s in g), f"the final waits on the semifinals ({[s['txt'] for g in B['cols'][2]['games'] for s in g]})")
    ok("3rd place" in B["third"] and "Week 17" in B["third"], f"3rd place game in Week 17 ({B['third']!r})")
    ok(len(B["place"]) == 1 and "5th place" in B["place"][0]["h"] and "Week 16" in B["place"][0]["h"] and sorted(s["txt"] for s in B["place"][0]["sides"]) == ["Loser of 3 vs 6", "Loser of 4 vs 5"], f"5th place game ({B['place']})")
    sub = {s["rid"]: s["txt"] for c in B["cols"][:1] for g in c["games"] for s in g if s["rid"]}
    ok("Swamp winner · tiebreak on PF" in sub["7"], f"the 4-5 division winner shows his PF tiebreak ({sub['7']!r})")
    ok("East winner" in sub["1"] and "tiebreak" not in sub["1"], f"a clear division winner has no tiebreak note ({sub['1']!r})")
    ok("Wild card · tiebreak on PF" in sub["3"] and "Wild card · tiebreak on PF" in sub["4"] and "tiebreak" not in sub["5"], f"wild cards: 4 and 5 seeds on PF, the 6 seed clear of the first team out ({sub['3']!r}, {sub['5']!r})")
    cards = dict(B["cards"])
    ok("Team L1-6" in cards.get("First team out", "") and "4-5" in cards["First team out"] and "PF 1,252.6" in cards["First team out"] and "(2nd-most points)" in cards["First team out"], f"first team out card ({cards.get('First team out')!r})")
    ok("Team L1-7 is the 3 seed at 4-5 by winning the Swamp, ahead of 3 wild cards with a better record." == cards.get("Notable"), f"notable card ({cards.get('Notable')!r})")
    ok("My Team L1-11" in cards.get("Your team", "") and "Out today" in cards["Your team"] and "11th in the standings" in cards["Your team"] and "2 games behind the last spot" in cards["Your team"] and "1 behind the Swamp lead" in cards["Your team"], f"your team card ({cards.get('Your team')!r})")
    ok("Sleeper's bracket" in B["src"], f"source line ({B['src']!r})")
    ok(B["sw"] <= B["cw"], "no sideways scroll at 1440")
    if SHOTS: os.makedirs(SHOTS, exist_ok=True); pg.screenshot(path=os.path.join(SHOTS, "bracket-dark-1440.png"), full_page=True)
    # a team opens in Power Rankings
    pg.click('.br-team[data-standing-team="2"]'); pg.wait_for_timeout(600)
    ok(pg.evaluate("() => !!document.querySelector('.pr-item[data-rid=\"2\"].open, .pr-item[data-rid=\"2\"] .pr-expand, .pr-item.open[data-rid=\"2\"]')") or pg.evaluate("() => document.querySelector('[data-lsub=\"power\"]').getAttribute('aria-pressed') === 'true' || document.querySelector('[data-lsub=\"power\"]').classList.contains('active')"), "clicking a team opens Power Rankings on it")
    pg.click('[data-lsub="standings"]'); pg.wait_for_timeout(300)
    ok(pg.locator(".br-wrap").count() == 1, "Standings remembers the Bracket view")
    pg.click('[data-st-view="div"]'); pg.wait_for_timeout(300)
    ok(pg.locator(".st-table tr.st-div").count() == 3 and pg.locator(".br-wrap").count() == 0, "By division brings the table back")
    pg.click('[data-st-view="league"]'); pg.wait_for_timeout(300)
    ok(pg.locator(".st-table tr.st-row").count() == 12, "League shows the full table")
    pg.close()

    # 1b: both themes, phone
    for theme, w in (("light", 1440), ("light", 390), ("dark", 390)):
        pg = page(league("L1", L1_REC, DIVS), L1_BRACKET, theme, w)
        B = read(pg)
        ok(B["sw"] <= B["cw"] and len(B["cols"]) == 3, f"{theme} {w}: renders with no sideways scroll ({B['sw']} / {B['cw']})")
        if w == 390:
            ov = pg.evaluate("() => [...document.querySelectorAll('.br-team')].filter(e => e.scrollWidth > e.clientWidth + 1).length")
            ok(ov == 0, f"{theme} {w}: no team row overflows ({ov})")
        if SHOTS: pg.screenshot(path=os.path.join(SHOTS, f"bracket-{theme}-{w}.png"), full_page=True)
        pg.close()

    # 2: no divisions, no Sleeper bracket: the standard bracket from the seeds
    for spots, exp_r1, exp_byes, fifth in ((6, [[3, 6], [4, 5]], [1, 2], True), (4, [[1, 4], [2, 3]], [], False), (8, [[1, 8], [2, 7], [3, 6], [4, 5]], [], False)):
        pg = page(league("L2", L2_REC, None, spots), None)
        B = read(pg)
        r1 = B["cols"][0]
        byes = sorted(int(g[0]["seed"]) for g in r1["games"] if any("Bye" in s["txt"] for s in g))
        games = sorted(sorted(int(s["seed"]) for s in g) for g in r1["games"] if not any("Bye" in s["txt"] for s in g))
        ok(games == exp_r1 and byes == exp_byes, f"{spots} teams: first round {games}, byes {byes}")
        seeds = {s["rid"]: int(s["seed"]) for c in B["cols"] for g in c["games"] for s in g if s["rid"]}
        ok(all(seeds[str(i)] == i for i in range(1, min(spots, 4) + 1)), f"{spots} teams: seeded by record, ties on PF")
        ok(len(B["cols"]) == {4: 2, 6: 3, 8: 3}[spots], f"{spots} teams: {len(B['cols'])} rounds")
        ok("3rd place" in B["third"], f"{spots} teams: 3rd place game")
        ok(bool(B["place"]) == fifth, f"{spots} teams: 5th place game {'shown' if fifth else 'not generated'}")
        ok(B["rule"].endswith("seeded by record, ties by points for"), f"{spots} teams: rule without divisions ({B['rule']!r})")
        ok("Standard bracket" in B["src"], f"{spots} teams: source line names the standard bracket")
        ok(pg.locator('[data-st-view]').all_text_contents() == ["Table", "Bracket"], "no divisions: Table / Bracket toggle")
        if spots == 6:
            cards = dict(B["cards"])
            ok(cards.get("Your team", "").find("Out today") < 0 and "seed" in cards.get("Your team", ""), f"a playoff team's card names his seed ({cards.get('Your team')!r})")
        pg.close()

    # 3: playoffs underway (Sleeper results)
    done = [dict(m) for m in L1_BRACKET]
    done[0].update(w=3, l=4); done[1].update(w=7, l=5); done[2].update(t2=3); done[3].update(t2=7)
    done[4].update(t1=4, t2=5)
    rec = {k: (v[0] + 5, v[1] + 0, v[2], v[3]) for k, v in L1_REC.items()}   # 14 games played
    pg = page(league("L1", rec, DIVS), done)
    B = read(pg)
    r1 = [g for g in B["cols"][0]["games"] if not any("Bye" in s["txt"] for s in g)]
    won = sorted(s["rid"] for g in r1 for s in g if " won" in s["cls"]); lost = sorted(s["rid"] for g in r1 for s in g if " lost" in s["cls"])
    ok(won == ["3", "7"] and lost == ["4", "5"], f"results: winners and losers marked ({won}, {lost})")
    semi = sorted(sorted(s["rid"] for s in g) for g in B["cols"][1]["games"])
    ok(semi == [["1", "3"], ["2", "7"]], f"semifinals fill from the results ({semi})")
    ok(B["title"] == "Playoff bracket" and not any(k in ("First team out", "Notable") for k, _ in B["cards"]), f"after the regular season: Playoff bracket, no projection cards ({B['title']!r})")
    pg.close()
    br.close()

ok(not errs, f"no page errors ({errs[:3]})")
print(f"\n{'FAILED' if failures else 'OK'}: {len(failures)} failure(s)")
raise SystemExit(1 if failures else 0)
