"""Balance This Trade (Alan, Oct 21, Trade Calculator audit): every suggestion is ranked and labelled by the verdict
the calculator actually shows once it's added (verdictHead: valueRead with the average-starter floor), never by a
separate smaller-side %. Before, 20 of 23 clicked suggestions gave a different verdict than promised and one flipped
the winner. For four trades in league mode (both teams picked: suggestions from the giver's roster) and in No league
mode, each suggestion is clicked: the calculator's headline equals the promised one (and its gap), Undo restores it,
and no suggestion turns the trade into a win (7%+) for the side that was behind.
Synthetic 12-team Superflex league (Full PPR, TE+0.5), players picked by value from today's board.
Run from the repo root:  python3 tests/balance_check.py   (CHROMIUM=/path/to/chromium if needed)
"""
import csv, functools, http.server, io, json, os, re, socketserver, sys, threading
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
rows = list(csv.DictReader(io.StringIO(re.search(r"RANKINGS_CSV\s*=\s*`(.*?)`", src, re.S).group(1).strip())))
sid = {r["player"]: r["sleeper_id"] for r in rows if r["sleeper_id"]}
POS = {r["player"]: r["pos"] for r in rows}
VAL = {r["player"]: float(r["value"] or 0) for r in rows}
fails = 0
def ok(cond, msg):
    global fails
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: fails += 1

hd = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT); hd.log_message = lambda *a: None
srv = socketserver.TCPServer(("127.0.0.1", 0), hd); threading.Thread(target=srv.serve_forever, daemon=True).start()
PORT = srv.server_address[1]

# the board's own players by value: the trade examples follow whatever the live board says
by_val = sorted((r for r in rows if r["sleeper_id"] and VAL[r["player"]] > 0), key=lambda r: -VAL[r["player"]])
zeros = [r["player"] for r in rows if r["sleeper_id"] and VAL[r["player"]] == 0][:2]
def near(v, pos=None, skip=()):
    pool = [r["player"] for r in by_val if (pos is None or r["pos"] == pos) and r["player"] not in skip]
    return min(pool, key=lambda n: abs(VAL[n] - v))

def league_data(force):
    """force: {roster_index: [names]}; everyone else dealt by position in a snake so each team is realistic"""
    forced = {n for v in force.values() for n in v}
    teams = [list(force.get(i, [])) for i in range(12)]
    by = {pos: [r["player"] for r in sorted(rows, key=lambda r: int(r["pos_rank"])) if r["pos"] == pos and r["sleeper_id"] and r["player"] not in forced and VAL[r["player"]] > 0]
          for pos in ("QB", "RB", "WR", "TE")}
    for pos, k in {"QB": 3, "RB": 5, "WR": 6, "TE": 2}.items():
        i = 0
        for rnd in range(k):
            for t in (range(12) if rnd % 2 == 0 else range(11, -1, -1)):
                if sum(1 for n in teams[t] if POS[n] == pos) >= k: continue
                if i < len(by[pos]): teams[t].append(by[pos][i]); i += 1
    names = ["Team Alpha", "Team Beta"] + [f"Team {i}" for i in range(3, 13)]
    rosters = [{"roster_id": i + 1, "owner_id": f"u{i+1}", "co_owners": [], "players": [sid[n] for n in t], "starters": [], "reserve": [], "taxi": [],
                "settings": {"wins": 2, "losses": 2, "ties": 0, "fpts": 400}} for i, t in enumerate(teams)]
    users = [{"user_id": f"u{i+1}", "display_name": f"mgr{i+1}", "metadata": {"team_name": names[i]}, "avatar": ""} for i in range(12)]
    league = {"league_id": "L1", "name": "Synthetic League", "season": "2026", "status": "in_season", "total_rosters": 12,
              "roster_positions": ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "SUPER_FLEX"] + ["BN"] * 7,
              "scoring_settings": {"rec": 1, "bonus_rec_te": 0.5, "pass_td": 4, "pass_yd": 0.04, "rush_yd": 0.1, "rec_yd": 0.1, "rush_td": 6, "rec_td": 6, "pass_int": -2, "fum_lost": -2},
              "settings": {"num_teams": 12, "type": 0}}
    return league, users, rosters

def open_page(br, force):
    league, users, rosters = league_data(force)
    SL = {"source": "sleeper", "username": "mgr1", "userId": "u1", "displayName": "mgr1", "season": "2026",
          "leagues": [{"id": "L1", "name": "Synthetic League", "season": "2026", "status": "in_season", "format": ""}],
          "activeId": "L1", "data": {"L1": {"league": league, "users": users, "rosters": rosters}}, "view": "league"}
    def sleeper(route):
        path = route.request.url.split("/v1", 1)[-1].split("?")[0]
        body = {"/league/L1": league, "/league/L1/users": users, "/league/L1/rosters": rosters, "/state/nfl": {"season": "2026", "week": 7, "season_type": "regular"}}.get(path, [])
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
    pg = br.new_page(viewport={"width": 1400, "height": 1100})
    pg.errs = []; pg.on("pageerror", lambda e: pg.errs.append(str(e)))
    pg.route("https://api.sleeper.app/**", sleeper)
    pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|api\.sleeper\.com|api\.github\.com|fonts\..*|use\.typekit\.net)/.*"), lambda r: r.abort())
    pg.add_init_script(f"window.__SPM_TEST_HOOKS = true; if (!sessionStorage.getItem('t')) {{ sessionStorage.setItem('t', '1'); localStorage.clear(); localStorage.setItem('spm_sleeper', {json.dumps(json.dumps(SL))}); localStorage.setItem('spm_tc_mode', 'league'); }}")
    pg.goto(f"http://127.0.0.1:{PORT}/#trade"); pg.wait_for_function("typeof tradeModel === 'function'"); pg.wait_for_timeout(2500)
    setsel(pg, "tc-league", "L1"); pg.wait_for_timeout(800)
    setsel(pg, "team-A", "1"); setsel(pg, "team-B", "2"); pg.wait_for_timeout(400)
    return pg

def setsel(pg, id_, v):
    pg.evaluate("([id, v]) => { const s = document.getElementById(id); s.value = v; s.dispatchEvent(new Event('change', { bubbles: true })); }", [id_, v])
def add(pg, side, name):
    pg.fill(f"#search-{side}", name); pg.wait_for_timeout(250); pg.keyboard.press("Enter"); pg.wait_for_timeout(350)
def clear(pg):
    pg.evaluate("() => { const b = [...document.querySelectorAll('#panel-trade button')].find(x => x.textContent.trim() === 'Clear'); b && b.click(); }"); pg.wait_for_timeout(300)
def read(pg):
    return pg.evaluate("""() => { const t = id => { const e = document.getElementById(id); return e && !e.hidden ? e.textContent.replace(/\\s+/g, ' ').trim() : ''; };
      return { title: t('verdict-title'), gap: t('verdict-gap'), balBtn: !document.getElementById('balance-btn').hidden}; }""")

def trade(pg, A, B):
    clear(pg)
    for n in A: add(pg, "A", n)
    for n in B: add(pg, "B", n)
    return read(pg)

BIG = ("wins the trade", "win the trade", "clearly win", "steal", "robb")
def winner(title):
    """the side a headline names as ahead: A = Team Alpha / you, B = Team Beta / them"""
    t = title.lower()
    if t.startswith("team alpha") or "to team alpha" in t or t.startswith(("you win", "you clearly", "you're robbing")) or "to you" in t or "you're getting a steal" in t: return "A"
    if t.startswith("team beta") or "to team beta" in t or t.startswith(("they", "you're getting robbed")) or "to them" in t: return "B"
    return None

def click_through(pg, label):
    """every Balance suggestion: the verdict it promises is the verdict the calculator shows after the click"""
    r0 = read(pg); out = []
    if not r0["balBtn"]: return r0, out
    if pg.locator("#balance").is_hidden(): pg.click("#balance-btn"); pg.wait_for_timeout(300)
    for i in range(pg.locator("#balance-list button").count()):
        b = pg.locator("#balance-list button").nth(i)
        promise = re.sub(r"\s+", " ", b.locator(".bal-result").text_content()).strip().lstrip("→").strip()
        b.click(); pg.wait_for_timeout(450)
        r1 = read(pg)
        title, _, pct = promise.partition(" · ")
        out.append((promise, r1["title"]))
        ok(r1["title"] == title and (not pct or pct in r1["gap"] or (pct == "0.0%" and "even" in r1["gap"])), f"{label}: suggestion {i + 1} promises '{promise}', the calculator shows '{r1['title']}' ({r1['gap'][:70]})")
        w0, w1 = winner(r0["title"]), winner(r1["title"])
        ok(not (w0 and w1 and w1 != w0 and any(k in r1["title"].lower() for k in BIG)), f"{label}: suggestion {i + 1} doesn't hand the other side a win ('{r1['title']}')")
        if pg.locator("#bal-undo").is_visible(): pg.click("#bal-undo"); pg.wait_for_timeout(400)
        ok(read(pg)["title"] == r0["title"], f"{label}: Undo brings back '{r0['title']}'")
        if pg.locator("#balance").is_hidden() and pg.locator("#balance-btn").is_visible(): pg.click("#balance-btn"); pg.wait_for_timeout(300)
    return r0, out

with sync_playwright() as p:
    kw = {"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}
    br = p.chromium.launch(**kw)
    star = by_val[0]["player"]
    a1 = near(1460); b1 = near(960, skip=(a1,))
    a2 = near(5600, pos="WR", skip=(a1, b1)); b2 = near(4700, pos="WR", skip=(a1, b1, a2))
    p1 = near(VAL[star] * 0.48, skip=(star, a1, b1, a2, b2)); p2 = near(VAL[star] * 0.36, skip=(star, a1, b1, a2, b2, p1))
    a4 = near(1320, skip=(star, a1, b1, a2, b2, p1, p2)); b4 = near(1180, skip=(star, a1, b1, a2, b2, p1, p2, a4))
    TR = [(f"{a1} for {b1}", [a1], [b1]), (f"{a2} for {b2}", [a2], [b2]), (f"{star} for {p1} + {p2}", [star], [p1, p2]), (f"{a4} for {b4}", [a4], [b4])]
    force = {0: [b1, b2, p1, p2, b4], 1: [a1, a2, star, a4]}
    total, fair_seen = 0, {"league": 0, "none": 0}
    for mode in ("league", "none"):
        pg = open_page(br, force)
        if mode == "none": setsel(pg, "tc-league", "none"); pg.wait_for_timeout(600)
        for lab, A, B in TR:
            r0 = trade(pg, A, B)
            r0, sugs = click_through(pg, f"[{mode}] {lab} ({r0['title']})")
            total += len(sugs); fair_seen[mode] += sum(1 for s in sugs if s[1] in ("Fair trade", "Basically even"))
        ok(not pg.errs, f"[{mode}] no page errors ({pg.errs[:2]})")
        pg.close()
    ok(total >= 8, f"Balance offered suggestions to click through ({total})")

    # noFlip regression (Alan, Oct 21): trades whose best-gap add would overshoot into a win for the side that was behind.
    # With the guard switched off (test hook) such suggestions appear; with it on none does, nothing else is lost, and
    # the trade still gets suggestions whenever a non-flipping one exists
    def promises(pg):
        if not read(pg)["balBtn"]: return []
        if pg.locator("#balance").is_hidden(): pg.click("#balance-btn"); pg.wait_for_timeout(250)
        return [re.sub(r"\s+", " ", t).strip().lstrip("→").strip() for t in pg.locator("#balance-list .bal-result").all_text_contents()]
    def flips(t0, ps):
        w0 = winner(t0)
        return [x for x in ps if w0 and winner(x.split(" · ")[0]) not in (None, w0) and any(k in x.lower() for k in BIG)]
    used, CAND = set(), []
    for t in (8200, 7000, 6000, 5000, 4200, 3500, 2900, 2400, 1900, 1500):
        for r in (0.78, 0.86, 0.93):
            a = near(t, skip=used); used.add(a); b = near(t * r, skip=used); used.add(b); CAND.append((a, b))
    seen_flip = {"league": 0, "none": 0}
    for mode in ("league", "none"):
        pg = open_page(br, {0: [b for a, b in CAND], 1: [a for a, b in CAND]})
        if mode == "none": setsel(pg, "tc-league", "none"); pg.wait_for_timeout(600)
        for a, b in CAND:
            pg.evaluate("() => { window.__SPM_NOFLIP_OFF = true; }"); r0 = trade(pg, [a], [b]); off = promises(pg)
            pg.evaluate("() => { window.__SPM_NOFLIP_OFF = false; }"); r1 = trade(pg, [a], [b]); on = promises(pg)
            lab = f"[{mode}] noFlip {a} for {b} ({r0['title']})"
            f_off, f_on = flips(r0["title"], off), flips(r1["title"], on)
            if f_off:
                seen_flip[mode] += 1
                ok(not f_on, f"{lab}: without the guard {len(f_off)} suggestion(s) hand the other side a win ({f_off[0]}); with it none ({on})")
                keep = [x for x in off if x not in f_off]
                ok(bool(on) or not keep, f"{lab}: the guard leaves suggestions when a non-flipping one exists ({len(on)} of {len(keep)})")
                if on:   # a kept suggestion still shows exactly what it promises
                    pg.locator("#balance-list button").first.click(); pg.wait_for_timeout(450)
                    ok(read(pg)["title"] == on[0].split(" · ")[0], f"{lab}: the first guarded suggestion shows its promised verdict ({on[0]} / {read(pg)['title']})")
            else:   # nothing to guard: the guard changes nothing
                ok(not f_on and on == off, f"{lab}: no suggestion hands the other side a win, the same suggestions with and without the guard")
        ok(not pg.errs, f"[{mode}] noFlip run: no page errors ({pg.errs[:2]})")
        pg.close()
    print(f"     noFlip flip cases found without the guard: {seen_flip}")
    # league mode adds from the giver's own roster, where the closest add can overshoot; No league searches every player, so
    # a closer non-flipping add always ranks first and the guard is a safety net there (same lists with and without it)
    ok(seen_flip["league"] > 0, f"the regression set contains league trades that flip without the guard ({seen_flip})")
    ok(fair_seen["league"] > 0 and fair_seen["none"] > 0, f"Some suggestions really make the trade fair, in league and No league mode ({fair_seen})")
    br.close()
print(f"\n{fails} failure(s)")
sys.exit(1 if fails else 0)
