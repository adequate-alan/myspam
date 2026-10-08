"""Trade Calculator roster-fit check (Oct 10: a trade entered with the sides reversed read "+0.0% roster-adjusted,
basically even": each team "received" players it already owned, gave nothing it owned, and fitValues forced the net to 0).

Synthetic 12-team Superflex league (Full PPR, TE premium +0.5); Team Alpha owns Hubbard + Kincaid, Team Beta owns
Wilson + Kelce. Checks:
  1. reversed entry (Alpha "gets" its own Hubbard + Kincaid): a clear warning naming the players and the roster they're
     already on, a Flip players button, and NO roster-adjusted read (never a fake "+0.0%")
  2. Flip players: the warning goes, the teams stay, the roster-adjusted read comes back with real numbers
  3. a team that gives nothing it owns (a hypothetical add): no roster-adjusted read
  4. filling real lineup holes is credited: a team with a weak RB2 and a weak TE that receives Hubbard + Kincaid gets
     a clearly positive roster-adjusted net, with "fills a weak RB spot"
Run from the repo root:  python3 tests/roster_fit_check.py   (CHROMIUM=/path/to/chromium if needed)
"""
import csv, functools, http.server, io, json, os, re, socketserver, sys, threading
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
rows = list(csv.DictReader(io.StringIO(re.search(r"RANKINGS_CSV\s*=\s*`(.*?)`", src, re.S).group(1).strip())))
sid = {r["player"]: r["sleeper_id"] for r in rows if r["sleeper_id"]}
ALPHA = ["Dak Prescott", "Daniel Jones", "Fernando Mendoza", "Chase Brown", "Chuba Hubbard", "Jacorey Croskey-Merritt", "Chris Olave",
         "Tetairoa McMillan", "Malik Nabers", "Chris Bell", "Dalton Kincaid", "Tyler Higbee"]
BETA = ["Josh Allen", "Jared Goff", "Jalon Daniels", "Ashton Jeanty", "Kyren Williams", "Will Shipley", "Zay Flowers", "Garrett Wilson",
        "Dontayvion Wicks", "Ja'Kobi Lane", "George Kittle", "Travis Kelce"]
HUB, KIN, WIL, KEL = "Chuba Hubbard", "Dalton Kincaid", "Garrett Wilson", "Travis Kelce"

def league_data(holes):
    a, b = list(ALPHA), list(BETA)
    if holes:   # Alpha has the weak RB2 / TE and Beta owns Hubbard + Kincaid
        a = [n for n in a if n not in (HUB, KIN)] + [WIL, KEL]; b = [n for n in b if n not in (WIL, KEL)] + [HUB, KIN]
    used = set(a + b)
    deep = [r["player"] for r in rows if r["sleeper_id"] and r["player"] not in used][-40:]
    a += deep[:3]; b += deep[3:6]; used |= set(deep[:6])
    rest = [r["player"] for r in rows if r["sleeper_id"] and r["player"] not in used][:150]
    teams = [a, b] + [rest[i::10] for i in range(10)]
    names = ["Team Alpha", "Team Beta"] + [f"Team {i}" for i in range(3, 13)]
    rosters = [{"roster_id": i + 1, "owner_id": f"u{i+1}", "co_owners": [], "players": [sid[n] for n in t], "starters": [], "reserve": [], "taxi": [],
                "settings": {"wins": 2, "losses": 2, "ties": 0, "fpts": 400}} for i, t in enumerate(teams)]
    users = [{"user_id": f"u{i+1}", "display_name": f"mgr{i+1}", "metadata": {"team_name": names[i]}, "avatar": ""} for i in range(12)]
    league = {"league_id": "L1", "name": "Synthetic League", "season": "2026", "status": "in_season", "total_rosters": 12,
              "roster_positions": ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "SUPER_FLEX"] + ["BN"] * 6,
              "scoring_settings": {"rec": 1, "bonus_rec_te": 0.5, "pass_td": 4, "pass_yd": 0.04, "rush_yd": 0.1, "rec_yd": 0.1, "rush_td": 6, "rec_td": 6, "pass_int": -2, "fum_lost": -2},
              "settings": {"num_teams": 12, "type": 0}}
    return league, users, rosters

h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT); h.log_message = lambda *a: None
srv = socketserver.TCPServer(("127.0.0.1", 0), h); threading.Thread(target=srv.serve_forever, daemon=True).start()
failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)

with sync_playwright() as p:
    kw = {"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}
    br = p.chromium.launch(**kw); errs = []

    def page(holes):
        league, users, rosters = league_data(holes)
        SL = {"source": "sleeper", "username": "mgr1", "userId": "u1", "displayName": "mgr1", "season": "2026",
              "leagues": [{"id": "L1", "name": "Synthetic League", "season": "2026", "status": "in_season", "format": ""}],
              "activeId": "L1", "data": {"L1": {"league": league, "users": users, "rosters": rosters}}, "view": "league"}
        def sleeper(route):
            path = route.request.url.split("/v1", 1)[-1].split("?")[0]
            body = {"/league/L1": league, "/league/L1/users": users, "/league/L1/rosters": rosters,
                    "/state/nfl": {"season": "2026", "week": 5, "season_type": "regular"}}.get(path, [])
            route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
        pg = br.new_page(viewport={"width": 1400, "height": 1000})
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.route("https://api.sleeper.app/**", sleeper)
        pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.sleeper\.com|api\.github\.com|fonts\..*|use\.typekit\.net)/.*"), lambda r: r.abort())
        pg.route("**/data/market/flock.json", lambda r: r.abort())
        pg.add_init_script(f"if (!sessionStorage.getItem('t')) {{ sessionStorage.setItem('t', '1'); localStorage.clear(); localStorage.setItem('spm_sleeper', {json.dumps(json.dumps(SL))}); localStorage.setItem('spm_tc_mode', 'league'); }}")
        pg.goto(f"http://127.0.0.1:{srv.server_address[1]}/#trade"); pg.wait_for_timeout(3000)
        pg.evaluate("""() => { const set = (id, v) => { const s = document.getElementById(id); s.value = v; s.dispatchEvent(new Event('change', { bubbles: true })); };
          set('tc-league', 'L1'); }"""); pg.wait_for_timeout(1200)
        pg.evaluate("""() => { const set = (id, v) => { const s = document.getElementById(id); s.value = v; s.dispatchEvent(new Event('change', { bubbles: true })); };
          set('team-A', '1'); set('team-B', '2'); }"""); pg.wait_for_timeout(500)
        return pg

    def add(pg, side, name):
        pg.fill(f"#search-{side}", name); pg.wait_for_timeout(250); pg.keyboard.press("Enter"); pg.wait_for_timeout(400)

    def state(pg):
        return pg.evaluate("""() => { const w = document.getElementById('tc-warn'), g = document.getElementById('verdict-gap');
          return { warn: w.hidden ? '' : w.textContent.replace(/\\s+/g, ' ').trim(), flip: !w.hidden && !!w.querySelector('[data-tc-flip]'),
                   gap: g.hidden ? '' : g.textContent.replace(/\\s+/g, ' ').trim(), A: document.getElementById('team-A').value, B: document.getElementById('team-B').value,
                   page: document.getElementById('panel-trade') ? document.getElementById('panel-trade').textContent : document.body.textContent }; }""")

    # 1. reversed entry: Alpha "gets" Hubbard + Kincaid (its own), Beta "gets" Wilson + Kelce (its own)
    pg = page(False)
    for n in (HUB, KIN): add(pg, "A", n)
    for n in (WIL, KEL): add(pg, "B", n)
    s = state(pg)
    ok("already on Team Alpha's roster" in s["warn"] and "Chuba Hubbard" in s["warn"] and "already on Team Beta's roster" in s["warn"],
       f"Reversed sides: the warning names the players and the roster they're already on ({s['warn'][:150]})")
    ok(s["flip"], "Reversed sides: a Flip players button")
    ok("Roster-adjusted" not in s["gap"] and "+0.0%" not in s["gap"], f"Reversed sides: no roster-adjusted read, never a fake +0.0% ({s['gap'][:120]})")
    # 2. Flip players: teams stay, players change sides, the analysis comes back
    pg.click("#tc-warn [data-tc-flip]"); pg.wait_for_timeout(600)
    s = state(pg)
    nets = re.findall(r"([+−]\d+\.\d)%", s["gap"].split("Roster-adjusted:")[-1]) if "Roster-adjusted" in s["gap"] else []
    ok(not s["warn"] and s["A"] == "1" and s["B"] == "2", "Flip players: the warning goes and the team pickers stay")
    ok(len(nets) == 2 and not all(n in ("+0.0", "−0.0") for n in nets), f"Flip players: a real roster-adjusted read for both teams ({s['gap'][:140]})")
    pg.close()
    # 3. a team that gives nothing it owns (hypothetical add): no roster-adjusted read
    pg = page(False)
    add(pg, "A", WIL)
    s = state(pg)
    ok("+0.0%" not in s["gap"] and "Roster-adjusted" not in s["gap"], f"One-sided trade (Alpha gives nothing): no fake roster-adjusted net ({s['gap'][:120]})")
    pg.close()
    # 4. real lineup holes: Alpha (weak RB2 + TE) receives Hubbard + Kincaid for Wilson + Kelce
    pg = page(True)
    for n in (HUB, KIN): add(pg, "A", n)
    for n in (WIL, KEL): add(pg, "B", n)
    s = state(pg)
    m = re.search(r"Team Alpha ([+−]\d+\.\d)%", s["gap"])
    net = float(m.group(1).replace("−", "-")) if m else None
    ok(not s["warn"], "Hole-filling trade: entered the right way round, no warning")
    ok(net is not None and net >= 5, f"Hole-filling trade: Team Alpha's roster-adjusted net is clearly positive ({net})")
    ok("fills a weak RB spot" in s["page"], "Hole-filling trade: Hubbard is credited with filling a weak RB spot")
    pg.close()
    ok(not errs, f"No page errors {errs}")
    br.close()

print("\n" + ("All roster-fit checks passed." if not failures else f"{len(failures)} check(s) failed."))
sys.exit(1 if failures else 0)
