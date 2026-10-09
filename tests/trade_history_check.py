"""Trade history: AM value at the time vs AM value today (Alan, Oct 8). Synthetic league and synthetic ranking
history only; no real league data belongs in the repo.

Run from the repo root:  CHROMIUM=/path/to/chromium python3 tests/trade_history_check.py   (SHOTS=/dir for screenshots)

Checks:
1. A trade after AM values existed shows both snapshots: "AM at trade" from the latest entry at or before the trade
   (an update published an hour after it is never used; the card labels it "Then · <date> AM values") and "Now · Current AM values" from today's base AM values, plus a
   how-it-aged line.
2. The breakdown lists each player's rank, position rank, tier and value at the time, today's value and the change.
3. A trade before any AM value says "No AM value existed at the time of this trade" and only shows today.
4. A trade where only some players had a value then gives no at-the-time verdict (never today's value labeled as then).
5. Draft picks and FAAB stay listed, unvalued. Three-team trades show each team's net in both snapshots. No page errors.
"""
import os, re, sys, json
from datetime import datetime, timezone
HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "league_hub_check.py"), encoding="utf-8").read()
exec(src.split("failures = []")[0])   # make_league, LEAGUES, sleeper(), serve()

failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)
SHOTS = os.environ.get("SHOTS")
iso = lambda ms: datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
DAY = 86400e3

R = L1["rosters"]
a1, a2 = R[0]["players"][4], R[0]["players"][6]      # team 1 sends
b1 = R[1]["players"][3]                              # team 2 sends
c1, d1 = R[2]["players"][5], R[3]["players"][5]
e1, f1 = R[4]["players"][5], R[5]["players"][5]
g1, g2, g3 = R[6]["players"][5], R[7]["players"][5], R[8]["players"][5]
T_HIST, T_PRE, T_PART, T_3 = NOW - 10 * DAY, NOW - 40 * DAY, NOW - 12 * DAY, NOW - 9 * DAY
# synthetic history: everyone first valued 30 days ago; a1/a2/b1 re-valued 2 days before the trade, and b1 again an hour AFTER it
first = NOW - 30 * DAY
hist = {"note": "synthetic", "version": 2, "players": {}}
def add(sid, ms, rank, pr, tier, v): hist["players"].setdefault(sid, []).append([iso(ms), rank, pr, tier, v, "M"])
for sid, rk in [(a1, 20), (a2, 60), (b1, 15), (c1, 40), (e1, 50), (f1, 55), (g1, 70), (g2, 75), (g3, 80)]: add(sid, first, rk, 9, 3, 3000 - rk * 10)
add(a1, T_HIST - 2 * DAY, 18, 7, 2, 6100); add(a2, T_HIST - 2 * DAY, 58, 22, 4, 2400); add(b1, T_HIST - 2 * DAY, 12, 5, 2, 8500)
add(b1, T_HIST + 3600e3, 30, 11, 3, 4000)   # published after the trade: must never count as "at the time"
# d1 has no history: the partial trade
L1["tx"] = {2: [
    {"transaction_id": "th1", "type": "trade", "status": "complete", "roster_ids": [1, 2], "leg": 2, "status_updated": T_HIST,
     "adds": {b1: 1, a1: 2, a2: 2}, "drops": {b1: 2, a1: 1, a2: 1}, "draft_picks": [{"season": "2027", "round": 1, "roster_id": 1, "owner_id": 2, "previous_owner_id": 1}],
     "waiver_budget": [{"sender": 2, "receiver": 1, "amount": 15}]},
    {"transaction_id": "th3", "type": "trade", "status": "complete", "roster_ids": [7, 8, 9], "leg": 2, "status_updated": T_3,
     "adds": {g1: 8, g2: 9, g3: 7}, "drops": {g1: 7, g2: 8, g3: 9}, "draft_picks": [], "waiver_budget": []}],
  1: [{"transaction_id": "thp", "type": "trade", "status": "complete", "roster_ids": [3, 4], "leg": 1, "status_updated": T_PART,
       "adds": {c1: 4, d1: 3}, "drops": {c1: 3, d1: 4}, "draft_picks": [], "waiver_budget": []},
      {"transaction_id": "th0", "type": "trade", "status": "complete", "roster_ids": [5, 6], "leg": 1, "status_updated": T_PRE,
       "adds": {e1: 6, f1: 5}, "drops": {e1: 5, f1: 6}, "draft_picks": [], "waiver_budget": []}]}

port = serve()
with sync_playwright() as p:
    br = p.chromium.launch(**({"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}))
    for theme in ("dark", "light"):
        errs = []
        pg = br.new_page(viewport={"width": 1440, "height": 1000})
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.route("https://api.sleeper.app/**", sleeper)
        pg.route("**/data/rank_history.json*", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(hist)))
        pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|fonts\.(googleapis|gstatic)\.com)/.*"), lambda r: r.abort())
        pg.add_init_script(f"try {{ localStorage.setItem('spm_theme', '{theme}'); }} catch (e) {{}}")
        pg.goto(f"http://127.0.0.1:{port}/#rankings"); pg.wait_for_timeout(4500)
        today = pg.evaluate("() => SPM.rankingSnapshot()")
        pg.evaluate("() => { const b = document.createElement('button'); b.dataset.act = 'account'; document.getElementById('league-menu').append(b); b.click(); b.remove(); }")
        pg.wait_for_timeout(400)
        pg.fill("#sd-username", "tester"); pg.press("#sd-username", "Enter"); pg.wait_for_timeout(800)
        pg.locator("#sd-leagues [data-league='L1']").click(); pg.wait_for_timeout(1500)
        pg.click("#tab-league"); pg.wait_for_timeout(500)
        pg.click("[data-lsub=tx]"); pg.wait_for_timeout(2000)
        pg.click("[data-tx-type=trade]"); pg.wait_for_timeout(300)
        while pg.locator("[data-tx-older]").count(): pg.click("[data-tx-older]"); pg.wait_for_timeout(300)
        cards = pg.locator(".th-card")
        def idx(team):
            for i in range(cards.count()):
                if f"Alpha League Team {team} " in " ".join(cards.nth(i).inner_text().split()) + " ": return i
            return 0
        I = {"hist": idx(2), "three": idx(7), "part": idx(4), "pre": idx(6)}
        txt = lambda k: " ".join(cards.nth(I[k]).inner_text().split())
        ok(cards.count() == 4, f"[{theme}] four trades listed ({cards.count()})")
        if theme == "dark":
            # 1. the two-team trade after AM existed: Team 1 got b1 (8,500 then), Team 2 got a1 + a2 (6,100 + 2,400 then)
            c = txt("hist")
            print("   card:", c[:400])
            ok("THEN" in c.upper() and "NOW" in c.upper() and "AM VALUES" in c.upper() and "CURRENT AM VALUES" in c.upper(), "Both snapshots shown on the compact card as Then / Now with the values they use")
            ok("8,500" in c and "6,100" in c and "2,400" in c and "4,000" not in c, "At the time = the entry before the trade, never the update an hour after it")
            ok(cards.nth(I["hist"]).locator(".th-verdict small").inner_text().upper() == "THEN", "The headline verdict is labeled Then (the at-the-time verdict)")
            aged = cards.nth(I["hist"]).locator(".th-aged").inner_text()
            ok(any(k in aged for k in ("at the time", "then", "initial value")), f"How it aged: {aged}")
            ok("$15 FAAB" in c and "2027 Round 1" in c, "Draft pick and FAAB stay listed")
            cards.nth(I["hist"]).locator("[data-th-full]").click(); pg.wait_for_timeout(300)
            full = " ".join(cards.nth(I["hist"]).locator(".th-full").inner_text().split())
            print("   history:", full[:600])
            nb1 = today[b1][3]
            ok(f"#12 · " in full and "Tier 2 at trade" in full and f"8,500 → {nb1:,}" in full, "Breakdown: rank, position rank, tier and value at the time → today")
            d = nb1 - 8500
            ok(("+" if d > 0 else "−" if d < 0 else "±") + f"{abs(d):,}" in full, f"Per-player change shown ({d:+,})")
            ok("Not valued" in full and "published at or before the trade" in full, "Picks not valued; snapshot rule spelled out")
            ok("At the time:" in full and "Today:" in full, "Both verdicts in the breakdown")
            # 3-team
            c3 = txt("three")
            ok("THEN" in c3.upper() and c3.count("Team 7") >= 3 and ("+" in c3 and "−" in c3 or "Basically" in c3), "Three-team trade: each team's net in both snapshots")
            # partial and pre-AM
            cp, c0 = txt("part"), txt("pre")
            ok("Not every player had an AM value at the time" in cp and "NOW" in cp.upper() and cards.nth(I["part"]).locator(".th-verdict small").inner_text().upper() == "NOW", "Partial history: no at-the-time verdict")
            ok("No AM value existed at the time of this trade" in c0 and cards.nth(I["pre"]).locator(".th-tag.pre").count() == 1, "Pre-AM trade says no AM value existed, shows today only")
            ok(cards.nth(I["pre"]).locator(".th-verdict small").inner_text().upper() == "NOW", "Pre-AM headline verdict is labeled Now")
        if SHOTS:
            cards.nth(I["hist"]).scroll_into_view_if_needed()
            pg.screenshot(path=os.path.join(SHOTS, f"trade_history_{theme}.png"), full_page=False)
            pg.set_viewport_size({"width": 390, "height": 900}); pg.wait_for_timeout(400)
            cards.nth(I["hist"]).scroll_into_view_if_needed()
            pg.screenshot(path=os.path.join(SHOTS, f"trade_history_{theme}_phone.png"), full_page=False)
        ok(pg.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1"), f"[{theme}] no horizontal page scroll")
        ok(not errs, f"[{theme}] no page errors {errs[:2]}")
        pg.close()
    br.close()
print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
