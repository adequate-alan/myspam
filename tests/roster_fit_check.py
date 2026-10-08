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
  5. a past trade opened from League > Transactions > Analyze trade, on three logs: simple (a later free-agent move), busy
     (Kelce traded on twice more incl. a 3-team trade, a waiver drop + commissioner add at the same moment, an unrelated
     move at the trade's own timestamp) and broken (a later trade missing from the log): exact rebuilds pass every check
     and give exactly case 4's read; the broken one is flagged approximate with the failing check named. Also: today's rosters already reflect the trade and a later
     free-agent move. The sides come from the transaction (Alpha received Hubbard + Kincaid), no wrong-side warning, the
     rosters are rebuilt to just before the trade (later moves undone, earlier ones kept), and the roster-adjusted read is
     exactly the one for those rosters (case 4); editing the trade leaves the historical view
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

T_TRADE = 1790000000000   # synthetic timestamps (ms)
def league_data(holes, history=False):
    a, b = list(ALPHA), list(BETA)
    if holes or history:   # Alpha has the weak RB2 / TE and Beta owns Hubbard + Kincaid (history: before the trade)
        a = [n for n in a if n not in (HUB, KIN)] + [WIL, KEL]; b = [n for n in b if n not in (WIL, KEL)] + [HUB, KIN]
    used = set(a + b)
    deep = [r["player"] for r in rows if r["sleeper_id"] and r["player"] not in used][-40:]
    a += deep[:3]; b += deep[3:6]; used |= set(deep[:6])
    rest = [r["player"] for r in rows if r["sleeper_id"] and r["player"] not in used][:150]
    teams = [a, b] + [rest[i::10] for i in range(10)]
    tx = {}
    if history:
        # pre-trade rosters (above) + the log; today's rosters = the log played forward. "busy" adds the cases the
        # rebuild has to get right: Kelce moving on twice more (a 2-team and a 3-team trade), a waiver drop and a
        # commissioner add at the same moment, and an unrelated move at the trade's own timestamp. "broken" serves the
        # same log minus one later trade, so today's rosters don't line up with it.
        fa = rest[-1]; teams[9] = [n for n in teams[9] if n != fa]
        T3, T4, T5, T6, T7 = teams[2], teams[3], teams[4], teams[5], teams[6]
        D = 86400e3
        def mv(i, typ, at, adds, drops, rids):
            return {"transaction_id": i, "type": typ, "status": "complete", "roster_ids": rids, "leg": 3 + int((at - T_TRADE) // D), "status_updated": at,
                    "adds": {sid[n]: r for n, r in adds.items()}, "drops": {sid[n]: r for n, r in drops.items()}, "draft_picks": [], "waiver_budget": []}
        log = [mv("990", "free_agent", T_TRADE - D, {}, {}, [2]),
               mv("1000", "trade", T_TRADE, {HUB: 1, KIN: 1, WIL: 2, KEL: 2}, {HUB: 2, KIN: 2, WIL: 1, KEL: 1}, [1, 2]),
               mv("1010", "free_agent", T_TRADE + D, {fa: 1}, {"Chris Bell": 1}, [1])]
        if history in ("busy", "broken"):
            log += [mv("1003", "free_agent", T_TRADE, {}, {T7[-1]: 7}, [7]),
                    mv("1020", "trade", T_TRADE + 2 * D, {KEL: 3, T3[0]: 2}, {KEL: 2, T3[0]: 3}, [2, 3]),
                    mv("1030", "trade", T_TRADE + 3 * D, {KEL: 4, T4[0]: 5, T5[0]: 3}, {KEL: 3, T4[0]: 4, T5[0]: 5}, [3, 4, 5]),
                    mv("1040", "waiver", T_TRADE + 4 * D, {}, {KEL: 4}, [4]),
                    mv("1041", "commissioner", T_TRADE + 4 * D, {KEL: 6}, {}, [6])]
        rid = {n: k + 1 for k, team in enumerate([a, b] + teams[2:]) for n in team}
        cur = {k + 1: list(team) for k, team in enumerate([a, b] + teams[2:])}
        for x in sorted(log[1:], key=lambda x: (x["status_updated"], len(x["transaction_id"]), x["transaction_id"])):   # play the log forward
            name = {sid[n]: n for n in sid}
            for s_, r in x["drops"].items(): cur[r] = [n for n in cur[r] if sid.get(n) != s_]
            for s_, r in x["adds"].items(): cur[r].append(name[s_])
        a, b = cur[1], cur[2]; teams[2:] = [cur[k] for k in range(3, 13)]
        served = [x for x in log if not (history == "broken" and x["transaction_id"] == "1020")]
        for x in served: tx.setdefault(x["leg"], []).append(x)
        teams[0], teams[1] = a, b
    names = ["Team Alpha", "Team Beta"] + [f"Team {i}" for i in range(3, 13)]
    rosters = [{"roster_id": i + 1, "owner_id": f"u{i+1}", "co_owners": [], "players": [sid[n] for n in t], "starters": [], "reserve": [], "taxi": [],
                "settings": {"wins": 2, "losses": 2, "ties": 0, "fpts": 400}} for i, t in enumerate(teams)]
    users = [{"user_id": f"u{i+1}", "display_name": f"mgr{i+1}", "metadata": {"team_name": names[i]}, "avatar": ""} for i in range(12)]
    league = {"league_id": "L1", "name": "Synthetic League", "season": "2026", "status": "in_season", "total_rosters": 12,
              "roster_positions": ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "SUPER_FLEX"] + ["BN"] * 6,
              "scoring_settings": {"rec": 1, "bonus_rec_te": 0.5, "pass_td": 4, "pass_yd": 0.04, "rush_yd": 0.1, "rec_yd": 0.1, "rush_td": 6, "rec_td": 6, "pass_int": -2, "fum_lost": -2},
              "settings": {"num_teams": 12, "type": 0}}
    return league, users, rosters, tx

h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT); h.log_message = lambda *a: None
srv = socketserver.TCPServer(("127.0.0.1", 0), h); threading.Thread(target=srv.serve_forever, daemon=True).start()
failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)

with sync_playwright() as p:
    kw = {"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}
    br = p.chromium.launch(**kw); errs = []

    def page(holes, history=False, hash="#trade"):
        league, users, rosters, tx = league_data(holes, history)
        SL = {"source": "sleeper", "username": "mgr1", "userId": "u1", "displayName": "mgr1", "season": "2026",
              "leagues": [{"id": "L1", "name": "Synthetic League", "season": "2026", "status": "in_season", "format": ""}],
              "activeId": "L1", "data": {"L1": {"league": league, "users": users, "rosters": rosters}}, "view": "league"}
        def sleeper(route):
            path = route.request.url.split("/v1", 1)[-1].split("?")[0]
            m = re.match(r"/league/L1/transactions/(\d+)$", path)
            body = tx.get(int(m.group(1)), []) if m else {"/league/L1": league, "/league/L1/users": users, "/league/L1/rosters": rosters,
                    "/state/nfl": {"season": "2026", "week": 5, "season_type": "regular"}}.get(path, [])
            route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
        pg = br.new_page(viewport={"width": 1400, "height": 1000})
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.route("https://api.sleeper.app/**", sleeper)
        pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.sleeper\.com|api\.github\.com|fonts\..*|use\.typekit\.net)/.*"), lambda r: r.abort())
        pg.route("**/data/market/flock.json", lambda r: r.abort())
        pg.add_init_script(f"if (!sessionStorage.getItem('t')) {{ sessionStorage.setItem('t', '1'); localStorage.clear(); localStorage.setItem('spm_sleeper', {json.dumps(json.dumps(SL))}); localStorage.setItem('spm_tc_mode', 'league'); }}")
        pg.goto(f"http://127.0.0.1:{srv.server_address[1]}/{hash}"); pg.wait_for_timeout(3000)
        if history: return pg
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
    # 5. the same trade from the league's transaction log: a simple log, a busy one, and one with a move missing
    def open_past(mode):
        pg = page(False, history=mode, hash="#league")
        pg.click("#tab-league"); pg.wait_for_timeout(600); pg.click("[data-lsub=tx]"); pg.wait_for_timeout(2500)
        pg.click("[data-tx-type=trade]"); pg.wait_for_timeout(300)
        while pg.locator("[data-tx-older]").count(): pg.click("[data-tx-older]"); pg.wait_for_timeout(300)
        btn = pg.locator(".th-card", has_text="Team Alpha").locator("[data-th-analyze]")
        if not btn.count(): pg.locator(".th-card", has_text="Team Alpha").locator("[data-th-full]").first.click(); pg.wait_for_timeout(300)
        btn.first.click(); pg.wait_for_timeout(1500)
        pg.evaluate("() => { const d = document.querySelector('#tc-hist details'); if (d) d.open = true; }"); pg.wait_for_timeout(200)
        pg.evaluate("() => { const b = document.querySelector('[data-th-copy]'); b && b.click(); }"); pg.wait_for_timeout(300)
        info = pg.evaluate("""() => { const h = document.getElementById('tc-hist');
          return { text: h.hidden ? '' : h.textContent.replace(/\\s+/g, ' ').trim(), approx: h.classList.contains('approx'),
                   bad: [...h.querySelectorAll('.th-checks .bad')].map(e => e.textContent.trim()), report: window.__thReport || '' }; }""")
        return pg, info
    for mode in ("simple", "busy"):
        pg, info = open_past(mode)
        s = state(pg)
        cards = pg.evaluate("() => ['A', 'B'].map(x => [...document.querySelectorAll('#roster-' + x + ' .tc-pl .tc-pl-name')].map(e => e.textContent.trim()))")
        m = re.search(r"Team Alpha ([+−]\d+\.\d)%.*Team Beta ([+−]\d+\.\d)%", s["gap"])
        hn = [float(x.replace("−", "-")) for x in m.groups()] if m else None
        ok(s["A"] == "1" and s["B"] == "2" and any(HUB in c for c in cards[0]) and any(WIL in c for c in cards[1]),
           f"[{mode}] Past trade: sides from the transaction (Alpha gets Hubbard + Kincaid, Beta gets Wilson + Kelce) {cards}")
        ok(not s["warn"], f"[{mode}] Past trade: no wrong-side warning ({s['warn'][:100]})")
        ok("Current evaluation" in info["text"] and "Rosters rebuilt exactly" in info["text"] and not info["approx"] and not info["bad"],
           f"[{mode}] Rebuild exact, every check passes {info['bad']} ({info['text'][:140]})")
        ok("At the time:" in info["text"], f"[{mode}] The transaction's own at-the-time read is shown and labelled")
        ok(hn is not None and abs(hn[0] - net) < 0.05, f"[{mode}] Roster-adjusted read is the one for the rosters at the time (Alpha {hn and hn[0]} vs {net})")
        rep = info["report"]
        ok("Team Alpha received: Chuba Hubbard, Dalton Kincaid" in rep and "Rebuild: exact" in rep and "!!" not in rep and "starters before:" in rep,
           f"[{mode}] Copy report: the record, the checks, the rebuilt rosters and the lineups ({len(rep)} chars)")
        if mode == "simple":
            meta = pg.evaluate("() => ['A', 'B'].map(x => [...document.querySelectorAll('#roster-' + x + ' .tc-pl-meta')].map(e => e.textContent.replace(/\\s+/g, ' ').trim()))")
            strip = pg.evaluate("() => document.getElementById('teamroster-A').textContent")
            ok(all("From Team Beta" in m for m in meta[0]) and all("From your team" in m for m in meta[1]), f"Past trade: each card says who sent the player, not today's owner {meta}")
            ok("Hubbard" in strip and "G. Wilson" not in strip, "Past trade: the partner's roster strip is Team Beta's roster at the time")
            ok("fills a weak RB spot" in s["page"], "Past trade: Hubbard fills Alpha's weak RB spot")
            if os.environ.get("SHOTS"): pg.locator("#tc-hist").screenshot(path=os.path.join(os.environ["SHOTS"], "past_trade_check.png"))
            pg.locator("#roster-B .tc-pl", has_text=KEL).locator("button").first.click(); pg.wait_for_timeout(600)   # remove Kelce: now a manual trade
            ok(pg.evaluate("() => document.getElementById('tc-hist').hidden"), "Editing the past trade ends the historical view")
        else:
            ok("Undone:" in rep and rep.count("Undone:") == 6, f"[busy] All six later moves listed as undone ({rep.count('Undone:')})")
        pg.close()
    pg, info = open_past("broken")
    ok(info["approx"] and "Approximate rebuild" in info["text"] and any("where the transaction says" in b for b in info["bad"]),
       f"[broken] A missing move is caught: approximate, with the failing check named {info['bad']}")
    ok("Rebuild: approximate" in info["report"] and "!!" in info["report"], "[broken] The copied report says approximate and marks the problem")
    ok("Approximate rosters" in state(pg)["gap"], "[broken] The roster-adjusted line itself is tagged Approximate rosters")
    if os.environ.get("SHOTS"): pg.locator("#tc-hist").screenshot(path=os.path.join(os.environ["SHOTS"], "past_trade_broken.png"))
    pg.close()
    ok(not errs, f"No page errors {errs}")
    br.close()

print("\n" + ("All roster-fit checks passed." if not failures else f"{len(failures)} check(s) failed."))
sys.exit(1 if failures else 0)
