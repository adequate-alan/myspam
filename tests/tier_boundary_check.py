"""Tier moves vs rank moves (Alan, Oct 13): a tier is a valuation grouping, not a ranking move.

On the QB tab (Dak Prescott QB5 Tier 3, Joe Burrow QB6 Tier 3, Jared Goff QB7 Tier 4) demoting Burrow into Tier 4 keeps
him QB6, now first in Tier 4 ahead of Goff (QB7); promoting Goff into Tier 3 keeps him QB7. Checks, through the UI:
  1. the Tier 4 header offers "Burrow -> Tier 4" and "Goff -> Tier 3"; nothing that would empty a tier (Lamar alone in
     Tier 2, Allen alone in Tier 1)
  2. both header actions keep every rank and position rank, change only his tier (and only his value), and the reverse
     action restores the board exactly (CSV, values, touched set, nothing unsaved)
  3. real mouse drags: Burrow onto the Tier 4 header, Goff just above it, and back; the chip says it's a tier move;
     picking a player up and putting him down where he was changes nothing (also Lamar, alone in his tier)
  4. the arrows stay rank moves: Burrow down swaps him with Goff, up restores the board exactly
  5. Save, reload, reverse; a tier move then Cancel goes back to the saved board
  6. every tier boundary at QB, RB, WR and TE, both directions, applied and reversed
Nothing is published (GitHub is blocked; no token).

Run from the repo root:  python3 tests/tier_boundary_check.py   (CHROMIUM=/path/to/chromium if needed)
"""
import functools, http.server, os, socketserver, sys, threading
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=ROOT); h.log_message = lambda *a: None
srv = socketserver.TCPServer(("127.0.0.1", 0), h); threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"
failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg, flush=True)
    if not cond: failures.append(msg)

STATE = """() => ({ csv: SPM.edit.draft(), board: SPM.edit.board().map(p => [p.id, p.rank, p.posNum, p.tier, p.value, p.source]).sort((a, b) => a[0] - b[0]),
  touched: SPM.edit.touched().sort(), unsaved: SPM.edit.unsaved() })"""
QB = "() => SPM.edit.board().filter(p => p.pos === 'QB' && p.posNum != null).sort((a, b) => a.posNum - b.posNum).map(p => ({ id: p.id, name: p.name, posNum: p.posNum, rank: p.rank, tier: p.tier, value: p.value }))"
CONTIG = """() => { const bad = []; for (const pos of ['QB', 'RB', 'WR', 'TE']) { let last = -1;
  for (const p of SPM.edit.board().filter(q => q.pos === pos && q.posNum != null).sort((a, b) => a.posNum - b.posNum)) {
    const t = Number(p.tier); if (!isFinite(t) || t >= 90) continue; if (t < last) bad.push(pos + p.posNum); last = t; } } return bad; }"""

with sync_playwright() as pw:
    br = pw.chromium.launch(**({"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}))
    ctx = br.new_context(viewport={"width": 1440, "height": 1000})
    writes = []
    ctx.route("https://api.github.com/**", lambda r: (writes.append(r.request.method), r.abort()))
    ctx.route("https://*.sleepercdn.com/**", lambda r: r.abort())
    ctx.add_init_script("window.__SPM_TEST_HOOKS = true;")
    pg = ctx.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))

    def load():
        pg.goto(BASE + "/#rankings"); pg.wait_for_selector("#rank-body tr.player"); pg.wait_for_timeout(2500)
        pg.click("#pos-chips button:has-text('QB')"); pg.wait_for_timeout(500)
    def state(): return pg.evaluate(STATE)
    def qb(): return {p["name"]: p for p in pg.evaluate(QB)}
    def same(a, b): return a["csv"] == b["csv"] and a["board"] == b["board"] and a["touched"] == b["touched"] and a["unsaved"] == b["unsaved"]
    def diff_vals(a, b):   # players whose rank, position rank, tier or value differ
        A = {r[0]: r for r in a["board"]}; return [(r, A.get(r[0])) for r in b["board"] if A.get(r[0]) != r]
    def close_warn():
        if pg.locator("#ed-warn").is_visible(): pg.click('#ed-warn [data-ed="close"]'); pg.wait_for_timeout(150)
    def edge(name_from, tier):   # the header button that moves a player across a tier boundary
        loc = pg.locator(f'#rank-body tr.tier-edit button[data-tier-act="edge"][data-to="{tier}"]', has_text=name_from)
        return loc
    warn = {"last": ""}
    def click_edge(name_from, tier):
        b = edge(name_from, tier); b.first.scroll_into_view_if_needed(); b.first.locator("xpath=ancestor::tr").hover(); b.first.click(); pg.wait_for_timeout(500)
        warn["last"] = pg.inner_text("#ed-warn") if pg.locator("#ed-warn").is_visible() else ""; close_warn()
    def handle_center(name):
        pid = qb()[name]["id"]; row = pg.locator(f'#rank-body tr.player[data-id="{pid}"]'); row.scroll_into_view_if_needed(); pg.wait_for_timeout(100)
        b = row.locator(".handle").bounding_box(); return b["x"] + b["width"] / 2, b["y"] + b["height"] / 2
    def drag_to(name, y_of, steps=15):   # y_of(): the target y, measured after the drag has started
        x, y = handle_center(name); pg.mouse.move(x, y); pg.mouse.down()
        pg.mouse.move(x, y + 6); pg.wait_for_timeout(30)
        ty = y_of(); y0 = y + 6
        for i in range(1, steps + 1): pg.mouse.move(x, y0 + (ty - y0) * i / steps); pg.wait_for_timeout(16)
        chip = pg.evaluate("() => (document.querySelector('.drag-rk') || {}).textContent || null")
        pg.mouse.up(); pg.wait_for_timeout(900); close_warn(); return chip
    def header_box(tier):
        return pg.evaluate(f"() => {{ const r = document.querySelector('#rank-body tr.tier-edit[data-tier=\"{tier}\"]').getBoundingClientRect(); return {{ top: r.top, bot: r.bottom }}; }}")
    def row_box(name):
        pid = qb()[name]["id"]
        return pg.evaluate(f"() => {{ const r = document.querySelector('#rank-body tr.player[data-id=\"{pid}\"]').getBoundingClientRect(); return {{ top: r.top, bot: r.bottom, mid: (r.top + r.bottom) / 2 }}; }}")

    load()
    q = qb()
    ok([q[n]["posNum"] for n in ("Dak Prescott", "Joe Burrow", "Jared Goff")] == [5, 6, 7] and [q[n]["tier"] for n in ("Dak Prescott", "Joe Burrow", "Jared Goff")] == ["3", "3", "4"],
       "Starting board: Prescott QB5 T3, Burrow QB6 T3, Goff QB7 T4")
    ref = state()

    # 1. the header actions
    ok(edge("Burrow", "4").count() == 1 and edge("Goff", "3").count() == 1, "The Tier 4 header offers 'Burrow → Tier 4' and 'Goff → Tier 3'")
    ok(edge("Jackson", "1").count() == 0 and edge("Jackson", "3").count() == 0 and edge("Allen", "2").count() == 0,
       "No action that would empty a tier (Lamar alone in Tier 2, Allen alone in Tier 1)")
    t4 = edge("Burrow", "4").first.get_attribute("title")
    ok("stays QB6" in (t4 or ""), f"The action says he keeps his rank ({t4!r})")

    # 2. demote Burrow, promote him back; promote Goff, demote him back
    click_edge("Burrow", "4"); q = qb(); after = state(); warn_after_move = warn["last"]
    ch = diff_vals(ref, after)
    ok(q["Joe Burrow"]["posNum"] == 6 and q["Joe Burrow"]["tier"] == "4" and q["Jared Goff"]["posNum"] == 7 and q["Jared Goff"]["tier"] == "4" and q["Joe Burrow"]["rank"] == 25,
       f"Burrow → Tier 4: still QB6 (#{q['Joe Burrow']['rank']}), first in Tier 4 ahead of Goff (QB7)")
    ok([r[0][0] for r in ch] == [q["Joe Burrow"]["id"]], f"Only Burrow changed (tier {ch[0][1][3] if ch else '?'} → {ch[0][0][3] if ch else '?'}, value {ch[0][1][4] if ch else '?'} → {ch[0][0][4] if ch else '?'}); every rank unchanged")
    ok(q["Joe Burrow"]["value"] < q["Dak Prescott"]["value"] and q["Joe Burrow"]["value"] > q["Jared Goff"]["value"], "His value still sits between Prescott and Goff")
    ok(pg.evaluate(CONTIG) == [], "Tiers stay in one piece at every position")
    toast = pg.inner_text("#toast") if pg.locator("#toast").is_visible() else ""
    ok(warn_after_move == "" and "Joe Burrow moved to Tier 4" in toast and "QB6 unchanged" in toast and "5,760 →" in toast,
       f"A valid tier move gets a short confirmation, no rank suggestion (toast {toast!r}, notice {warn_after_move!r})")
    ok(after["unsaved"] == 1 and pg.locator(f'#rank-body tr.player[data-id="{q["Joe Burrow"]["id"]}"] .rv-tag').count() == 1, "One unsaved change, Burrow tagged Revalued")
    ok(edge("Burrow", "3").count() == 1, "The Tier 4 header now offers 'Burrow → Tier 3'")
    click_edge("Burrow", "3")
    ok(same(ref, state()), f"Burrow → Tier 3 again: the board is exactly as before {diff_vals(ref, state())[:2]}")

    click_edge("Goff", "3"); q = qb(); after = state(); ch = diff_vals(ref, after)
    ok(q["Jared Goff"]["posNum"] == 7 and q["Jared Goff"]["tier"] == "3" and q["Joe Burrow"]["tier"] == "3" and q["Jared Goff"]["rank"] == 28,
       f"Goff → Tier 3: still QB7 (#{q['Jared Goff']['rank']}), last in Tier 3")
    ok([r[0][0] for r in ch] == [q["Jared Goff"]["id"]], f"Only Goff changed (value {ch[0][1][4] if ch else '?'} → {ch[0][0][4] if ch else '?'})")
    click_edge("Goff", "4")
    ok(same(ref, state()), "Goff → Tier 4 again: the board is exactly as before")

    # the conflict notice (only for a real ordering conflict; no boundary move on today's board has one, so it's rendered
    # directly): Move to #N, keep at the current rank with the max/min value, Cancel undoes the tier move exactly
    click_edge("Burrow", "4")
    bid = qb()["Joe Burrow"]["id"]
    pg.evaluate(f"() => SPM.edit.tierNotice({bid}, '3', 5760)"); pg.wait_for_timeout(200)
    w = pg.inner_text("#ed-warn") if pg.locator("#ed-warn").is_visible() else ""
    ok("breaks the value order" in w and "Move to #" in w and "Keep at #25" in w and "Cancel" in w, f"A genuine conflict explains it and offers Move / Keep at #25 / Cancel ({w[:90]!r})")
    pg.click('#ed-warn [data-ed="tier-cancel"]'); pg.wait_for_timeout(500); close_warn()
    ok(same(ref, state()), "Cancel on the conflict notice undoes the tier move exactly")

    # 3. real mouse drags
    chip = drag_to("Joe Burrow", lambda: (lambda b: (b["top"] + b["bot"]) / 2)(header_box("4")))
    q = qb(); demoted = state()
    ok(chip and "QB6" in chip and "Tier 3" in chip and "Tier 4" in chip and "QB7" not in chip, f"Dragging Burrow onto the Tier 4 header reads as a tier move (chip {chip!r})")
    ok(q["Joe Burrow"]["posNum"] == 6 and q["Joe Burrow"]["tier"] == "4" and q["Jared Goff"]["posNum"] == 7, "Dropped there: Burrow QB6, first in Tier 4; Goff QB7")
    chip = drag_to("Joe Burrow", lambda: header_box("4")["top"] - 8)
    ok(chip and "Tier 4" in chip and "Tier 3" in chip and same(ref, state()), f"Dragged back just above the Tier 4 header (chip {chip!r}): the board is exactly as before")
    chip = drag_to("Jared Goff", lambda: header_box("4")["top"] - 8)
    q = qb()
    ok(chip and "QB7" in chip and "Tier 3" in chip and q["Jared Goff"]["posNum"] == 7 and q["Jared Goff"]["tier"] == "3", f"Dragging Goff just above the Tier 4 header: still QB7, now in Tier 3 (chip {chip!r})")
    chip = drag_to("Jared Goff", lambda: (lambda b: (b["top"] + b["bot"]) / 2)(header_box("4")))
    ok(same(ref, state()), f"Dragged back onto the Tier 4 header (chip {chip!r}): exactly as before")
    for n in ("Joe Burrow", "Jared Goff", "Lamar Jackson"):
        chip = drag_to(n, lambda n=n: row_box(n)["mid"] + 2)
        ok(same(ref, state()) and chip and "→" not in chip, f"{n} picked up and put down where he was: nothing changes (chip {chip!r})")
    # a drag past Goff is still a rank move
    drag_to("Joe Burrow", lambda: row_box("Jared Goff")["bot"] - 4)
    q = qb()
    ok(q["Joe Burrow"]["posNum"] == 7 and q["Jared Goff"]["posNum"] == 6, "Dragged past Goff: a rank move (Burrow QB7, Goff QB6)")
    pg.evaluate("SPM.edit.cancel()"); pg.wait_for_timeout(400)
    ok(same(ref, state()), "Cancel: back to the board as it was")

    # 4. the arrows stay rank moves
    bid = qb()["Joe Burrow"]["id"]
    pg.locator(f'#rank-body tr.player[data-id="{bid}"] .arrow[data-dir="1"]').evaluate("b => b.click()"); pg.wait_for_timeout(500)
    q = qb()
    ok(q["Joe Burrow"]["posNum"] == 7 and q["Jared Goff"]["posNum"] == 6 and q["Jared Goff"]["tier"] == "4", "Burrow ▼: swaps ranks with Goff (Burrow QB7, Goff QB6)")
    pg.locator(f'#rank-body tr.player[data-id="{bid}"] .arrow[data-dir="-1"]').evaluate("b => b.click()"); pg.wait_for_timeout(500)
    ok(same(ref, state()), "Burrow ▲: the board is exactly as before")

    # 5. Save, reload, reverse; Cancel after a tier move
    click_edge("Burrow", "4"); demoted = state()
    pg.evaluate("SPM.edit.save()"); pg.wait_for_timeout(600)
    load(); q = qb(); s = state()
    ok(q["Joe Burrow"]["posNum"] == 6 and q["Joe Burrow"]["tier"] == "4" and s["csv"] == demoted["csv"] and s["board"] == demoted["board"], "After a reload the saved tier move is still there (QB6, Tier 4, same value)")
    click_edge("Prescott", "4")   # (the Tier 4 boundary is now between Prescott and Burrow)
    pg.evaluate("SPM.edit.cancel()"); pg.wait_for_timeout(400)
    s = state(); ok(s["csv"] == demoted["csv"] and s["board"] == demoted["board"], "An unsaved tier move, then Cancel: back to the saved board")
    click_edge("Burrow", "3"); s = state()
    ok(s["csv"] == ref["csv"] and s["board"] == ref["board"] and s["touched"] == [], "Reversed after the reload: the published board exactly, nothing touched")
    pg.evaluate("SPM.edit.save()"); pg.wait_for_timeout(600)
    load(); ok(same(ref, state()), "Saved and reloaded: nothing left unsaved, the published board")

    # 6. every boundary, both directions
    bad, n = [], 0
    for pos in ("QB", "RB", "WR", "TE"):
        pg.click(f"#pos-chips button:has-text('{pos}')"); pg.wait_for_timeout(400)
        start = state()
        acts = pg.evaluate("""() => [...document.querySelectorAll('#rank-body tr.tier-edit button[data-tier-act="edge"]')].map(b => ({ id: Number(b.dataset.id), to: b.dataset.to, from: b.closest('tr').dataset.tier }))""")
        for a in acts:
            n += 1
            before = pg.evaluate(f"() => SPM.edit.board().find(p => p.id === {a['id']})")
            pg.locator(f'#rank-body tr.tier-edit button[data-tier-act="edge"][data-id="{a["id"]}"][data-to="{a["to"]}"]').evaluate("b => b.click()"); pg.wait_for_timeout(250)
            if pg.locator("#ed-warn").is_visible(): bad.append(f"{pos} {a['id']} → T{a['to']}: notice {pg.inner_text('#ed-warn')[:60]!r}")
            close_warn()
            mid = state(); now = pg.evaluate(f"() => SPM.edit.board().find(p => p.id === {a['id']})")
            others = [r for r in diff_vals(start, mid) if r[0][0] != a["id"]]
            if now["tier"] != a["to"] or now["rank"] != before["rank"] or now["posNum"] != before["posNum"] or others or pg.evaluate(CONTIG):
                bad.append(f"{pos} {before['name']} → T{a['to']}: tier {now['tier']} rank {before['rank']}→{now['rank']}, {len(others)} others changed")
            back = before["tier"]
            pg.locator(f'#rank-body tr.tier-edit button[data-tier-act="edge"][data-id="{a["id"]}"][data-to="{back}"]').evaluate("b => b.click()"); pg.wait_for_timeout(250); close_warn()
            if not same(start, state()): bad.append(f"{pos} {before['name']} back to T{back}: not restored {diff_vals(start, state())[:2]}")
    ok(n >= 30 and not bad, f"{n} boundary moves at QB/RB/WR/TE: rank kept, only the mover changed, no rank suggestion, tiers in one piece, reversed exactly {bad[:3]}")

    ok(not [m for m in writes if m != "GET"], f"Nothing was published ({len(writes)} GitHub requests, none writing)")
    ok(not errs, f"No page errors {errs[:2]}")
    br.close()

print("\n" + ("All tier boundary checks passed." if not failures else f"{len(failures)} check(s) failed."))
sys.exit(1 if failures else 0)
