"""Trade Finder: Target a player / Find targets (Alan, Oct 8). Synthetic leagues only (the same mock league as
tests/league_hub_check.py); no real league data belongs in the repo.

Run from the repo root:  CHROMIUM=/path/to/chromium python3 tests/trade_target_check.py   (SHOTS=/dir for screenshots)

Checks:
1. Mode switch: Shop my players · Target a player · Find targets · Any team; Target defaults to Slight edge.
2. Target a player: the search lists only other teams' players; the header shows owner, AM value, league-adjusted value,
   market value, the AM-vs-market gap, his value to his owner and both teams' rooms.
3. Offers: you receive the target from his owner and send only your own players; every idea favors you by the
   Slight edge range (3-10%), says "edge/value for you" (never "steal"), carries a confidence label, before → after
   impact for both teams and a reason for each side; 3-for-2 is offered only against a pair.
4. Find targets lists players on other rosters with reasons; "See offers" opens Target a player for that player.
5. The player drawer's button reads "Target in Trade Finder" for another team's player and opens Target a player.
6. Shop my players is unchanged. No page errors.
"""
import os, re, sys, json
HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "league_hub_check.py"), encoding="utf-8").read()
exec(src.split("failures = []")[0])   # make_league, LEAGUES, sleeper(), serve()

failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)
SHOTS = os.environ.get("SHOTS")

port = serve()
with sync_playwright() as p:
    br = p.chromium.launch(**({"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}))
    errs = []
    pg = br.new_page(viewport={"width": 1440, "height": 1000})
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.route("https://api.sleeper.app/**", sleeper)
    pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|fonts\.(googleapis|gstatic)\.com)/.*"), lambda r: r.abort())
    pg.goto(f"http://127.0.0.1:{port}/#rankings"); pg.wait_for_timeout(4500)
    pg.evaluate("() => { const b = document.createElement('button'); b.dataset.act = 'account'; document.getElementById('league-menu').append(b); b.click(); b.remove(); }")
    pg.wait_for_timeout(400)
    pg.fill("#sd-username", "tester"); pg.press("#sd-username", "Enter"); pg.wait_for_timeout(800)
    pg.locator("#sd-leagues [data-league='L1']").click(); pg.wait_for_timeout(1500)
    mine = set(L1["rosters"][0]["players"])

    pg.click("#tab-finder"); pg.wait_for_timeout(1000)
    labels = pg.locator("#tf-src button").all_inner_texts()
    ok(labels == ["Shop my players", "Target a player", "Find targets", "Any team"], f"Modes: {labels}")
    ok(pg.locator(".tf-card").count() > 0 and pg.locator(".tf-tcard").count() == 0, "Shop my players still shows the classic cards")

    # Target a player
    pg.click("#tf-src [data-src='target']"); pg.wait_for_timeout(400)
    ok(pg.eval_on_selector("#tf-goal", "s => s.value") == "edge", "Target a player defaults to Slight edge")
    target_sid = L1["rosters"][3]["players"][0]   # team 4's best player
    tname = name_of[target_sid]
    pg.fill("#tf-q", tname.split()[-1]); pg.wait_for_timeout(400)
    hits = pg.eval_on_selector_all("#tf-results [data-tf-pick]", "bs => bs.map(b => b.dataset.tfPick)")
    ok(hits and not (set(hits) & mine), f"Search lists only other teams' players ({len(hits)} hits)")
    pg.evaluate(f"() => document.querySelector('#tf-results [data-tf-pick=\"{target_sid}\"]').click()"); pg.wait_for_timeout(2500)
    intel = pg.inner_text(".tf-intel") if pg.locator(".tf-intel").count() else ""
    ok(all(k in intel.upper() for k in ("OWNED BY", "AM VALUE", "LEAGUE-ADJUSTED", "MARKET", "AM VS MARKET")) and "Alpha League Team 4" in intel, "Target header: owner, AM value, league-adjusted, market, AM vs market")
    ok(("for them" in intel or "bench" in intel.lower()) and "needs" in intel.lower() or "strong at" in intel.lower(), "Target header: his value to his owner and both teams' rooms")
    ok(pg.locator(".tf-intel .tf-credit").count() == 1, "FantasyCalc is credited with a link where market values show")
    cards = pg.locator(".tf-tcard").all()
    good, n32, bad = True, 0, []
    for c in cards:
        recv = c.locator(".tf-side").nth(0).inner_text(); send_ids = c.evaluate("e => [...e.querySelectorAll('.tf-side')[1].querySelectorAll('[data-player]')].map(x => x.dataset.player)")
        verdict = c.locator(".tf-verdict-big").inner_text().upper()
        size = c.locator(".tf-size").get_attribute("title").strip().lower()   # badge reads "Send 3 · Get 2"; the title keeps "3-for-2"
        if size == "3-for-2": n32 += 1
        if size.startswith("3-") and size != "3-for-2": bad.append(size)
        cond = (tname in recv and set(send_ids) <= mine and ("EDGE FOR YOU" in verdict or "VALUE FOR YOU" in verdict) and "STEAL" not in verdict
                and c.locator(".tf-pill.conf").count() == 1 and c.locator(".tf-impact .tfm").count() >= 2 and c.locator(".tf-why2").count() >= 2
                and "POWER #" in c.locator(".tf-impact").inner_text().upper())
        if not cond: bad.append(verdict)
        good = good and cond
    ok(len(cards) > 0 and good, f"Target offers: {len(cards)} ideas, you receive him, send only your players, edge for you, confidence, impact, both reasons {bad[:3]}")
    ok(not [b for b in bad if b.startswith("3-")], f"3-for-2 only against a pair ({n32} shown)")
    if SHOTS: pg.screenshot(path=f"{SHOTS}/finder_target.png", full_page=True)

    # Find targets
    pg.click("#tf-src [data-src='discover']"); pg.wait_for_timeout(1500)
    d = pg.locator(".tf-dcard").all()
    ok(len(d) > 0 and all(x.locator(".tf-dtags span").count() >= 1 for x in d), f"Find targets: {len(d)} players with reasons")
    first = d[0].locator("[data-tf-target]").get_attribute("data-tf-target") if d else None
    ok(first and first not in mine, "Find targets only suggests other teams' players")
    if SHOTS: pg.screenshot(path=f"{SHOTS}/finder_discover.png", full_page=True)
    if d:
        d[0].locator("[data-tf-target]").click(); pg.wait_for_timeout(2500)
        ok(pg.eval_on_selector("#tf-src [aria-pressed='true']", "b => b.dataset.src") == "target" and pg.locator(".tf-intel").count() == 1, "See offers opens Target a player for him")

    # Drawer: another team's player
    pg.click("#tab-rankings"); pg.wait_for_timeout(500)
    other = L1["rosters"][5]["players"][0]
    pg.evaluate(f"() => document.querySelector('#rank-body [data-player=\"{other}\"]').click()"); pg.wait_for_timeout(1500)
    bt = pg.inner_text(f"[data-find-trades='{other}']")
    ok(bt == "Target in Trade Finder", f"Drawer button for another team's player: {bt!r}")
    pg.click(f"[data-find-trades='{other}']"); pg.wait_for_timeout(2500)
    ok(pg.eval_on_selector("#tf-src [aria-pressed='true']", "b => b.dataset.src") == "target" and name_of[other] in pg.inner_text(".tf-intel"), "It opens Target a player for him")
    ok(not errs, f"No page errors {errs[:2]}")
print(f"\n{len(failures)} check(s) failed." if failures else "\nAll Trade Finder target checks passed.")
sys.exit(1 if failures else 0)
