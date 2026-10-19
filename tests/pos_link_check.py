"""Linked position order (Alan, Oct 19): a connected league can follow AM PPR's published position order.

Run from the repo root:  CHROMIUM=/path/to/chromium python3 tests/pos_link_check.py   (SHOTS=dir for screenshots,
REPORT=file.md for the before / after table)

Synthetic leagues only (league_hub_check's Alpha League: 12-team Superflex, TE premium, valued on AM SF PPR TE+; Beta
League: 10-team 1QB Half PPR, valued on AM PPR). Checks:
1. Off by default: nothing changes until the league is linked (the league's own board's order, values and tiers).
2. Linking through League settings → Position order → Follow AM PPR: every QB / RB / WR / TE position rank in the
   league equals the player's place in AM PPR's published order (matched by Sleeper ID); the league keeps its own value
   ladder and tiers per spot (Alpha League is in its board's native format, so the k-th RB gets exactly the k-th RB
   value and tier he'd have unlinked); values still fall strictly down each position; overall ranks follow value.
3. A published move up (RB8 → RB5) and down (WR3 → WR9) on AM PPR (served as the next deploy would serve it): the
   moved players take their new position ranks in the league, the players in between shift by one, every other
   position is unchanged, and the moved player's value is the league's value at his new spot (not AM PPR's).
4. Unpublished drafts never count: an AM PPR edit saved in this browser without publishing leaves the league as it was.
5. The AM SF PPR TE+ board is never touched (its block, its storage keys); the AM PPR board isn't either; the setting
   lives in spm_pos_link per league and survives a reload; Default unlinks; a 1QB league (already on AM PPR) follows its
   order exactly (no scoring-profile reordering); no page errors.
"""
import os, re, sys, json
HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "league_hub_check.py"), encoding="utf-8").read()
exec(src.split("failures = []")[0])   # make_league, LEAGUES, sleeper(), serve(), freeze()

failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)

INDEX = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
PPR_RE = re.compile(r"(const RANKINGS_CSV_PPR = `\n)(.*?)(`)", re.S)
SF_RE = re.compile(r"(const RANKINGS_CSV = `\n)(.*?)(`)", re.S)

def rows_of(block):
    lines = [l for l in block.strip().split("\n") if l.strip()]
    head = lines[0].split(",")
    return head, [dict(zip(head, l.split(","))) for l in lines[1:]]

def ppr_order(index):
    """Sleeper ID -> position rank on AM PPR as published in this index.html (overall rank sets the order)."""
    _, rows = rows_of(PPR_RE.search(index).group(2))
    out = {}
    for pos in ("QB", "RB", "WR", "TE"):
        g = sorted((r for r in rows if r["pos"] == pos), key=lambda r: int(r["rank"]))
        for i, r in enumerate(g): out[r["sleeper_id"]] = i + 1
    return out

def move_in_ppr(index, pos, frm, to):
    """index.html with AM PPR's pos{frm} moved to pos{to} (overall ranks of the spots in between rotate): a publish."""
    m = PPR_RE.search(index)
    head, rows = rows_of(m.group(2))
    g = sorted((r for r in rows if r["pos"] == pos), key=lambda r: int(r["rank"]))
    lo, hi = min(frm, to) - 1, max(frm, to)
    seg = g[lo:hi]; ranks = [r["rank"] for r in seg]
    seg = [seg[-1]] + seg[:-1] if to < frm else seg[1:] + [seg[0]]
    for r, rk in zip(seg, ranks): r["rank"] = rk
    for i, r in enumerate(sorted((r for r in rows if r["pos"] == pos), key=lambda r: int(r["rank"]))): r["pos_rank"] = str(i + 1)
    rows.sort(key=lambda r: int(r["rank"]))
    body = ",".join(head) + "\n" + "\n".join(",".join(r[h] for h in head) for r in rows) + "\n"
    return index[:m.start(2)] + body + index[m.end(2):]

def connect(pg, lid):
    pg.evaluate("() => { const b = document.createElement('button'); b.dataset.act = 'account'; document.getElementById('league-menu').append(b); b.click(); b.remove(); }")
    pg.wait_for_timeout(400)
    pg.fill("#sd-username", "tester"); pg.press("#sd-username", "Enter"); pg.wait_for_timeout(800)
    pg.locator(f"#sd-leagues [data-league='{lid}']").click(); pg.wait_for_timeout(1800)

def open_settings(pg):   # the league chip's menu has "League settings"; any [data-open-fmt] opens the same dialog
    pg.evaluate("() => { const b = document.createElement('button'); b.dataset.openFmt = ''; document.body.append(b); b.click(); b.remove(); }")
    pg.wait_for_timeout(300)

def set_link(pg, bid):
    open_settings(pg)
    pg.locator(f"#fmt-link [data-link='{bid}']").click(); pg.wait_for_timeout(150)
    hint = pg.inner_text("#fmt-link")
    pg.click("#fmt-apply"); pg.wait_for_timeout(1200)
    return hint

def ranks(pg):
    return pg.evaluate("() => SPM.leagueRanks()")

def by_pos(lr):
    out = {}
    for sid, x in lr["players"].items():
        if x["pos"] in ("QB", "RB", "WR", "TE") and x["posRank"] is not None: out.setdefault(x["pos"], []).append((x["posRank"], sid, x))
    return {k: sorted(v) for k, v in out.items()}

def follows(lr, order):
    """positions where the league's position ranks are exactly the AM PPR order among the players the league prices"""
    bad = []
    for pos, g in by_pos(lr).items():
        want = [sid for _, sid, _ in sorted(g, key=lambda t: (order.get(t[1], 10**6), t[0]))]
        got = [sid for _, sid, _ in g]
        if want != got: bad.append(pos)
    return bad

def ladder(lr):
    """(value, tier) at each position spot"""
    return {pos: [(x["value"], str(x["tier"])) for _, _, x in g] for pos, g in by_pos(lr).items()}

def same_ladder(a, b):
    """b's value at each spot is a's value at that spot with the holder's own scoring-profile nudge swapped (LG.factor:
    the league's scoring suits some players more than others; that nudge stays with the player), clamped under the spot
    above, within 1% (a nudged neighbour can shift where the clamp bites); tiers per spot identical. Returns the spots that differ."""
    bad = []
    for pos, ga in by_pos(a).items():
        gb = by_pos(b)[pos]; prev = None
        for i, ((_, _, x), (_, _, y)) in enumerate(zip(ga, gb)):
            exp = x["value"] / x["factor"] * y["factor"]
            fine = abs(y["value"] - exp) <= max(2, 0.01 * exp) or (prev is not None and y["value"] < exp and y["value"] < prev)
            if not fine or str(x["tier"]) != str(y["tier"]): bad.append((pos, i + 1, x["value"], y["value"], round(exp), x["tier"], y["tier"]))
            prev = y["value"]
    return bad

def strictly_down(lr):
    return [pos for pos, g in by_pos(lr).items() if any(b[2]["value"] > a[2]["value"] for a, b in zip(g, g[1:]))]

def keys(pg):
    return pg.evaluate("() => Object.fromEntries(Object.keys(localStorage).filter(k => k.startsWith('spm_')).map(k => [k, localStorage.getItem(k)]))")

port = serve()
SERVE = {"index": INDEX}
def index_route(route):
    route.fulfill(status=200, content_type="text/html; charset=utf-8", body=SERVE["index"])

report = []
with sync_playwright() as p:
    br = p.chromium.launch(**({"executable_path": os.environ["CHROMIUM"]} if os.environ.get("CHROMIUM") else {}))
    ctx = br.new_context(viewport={"width": 1440, "height": 1000})
    errs = []
    pg = ctx.new_page()
    freeze(pg, FRIDAY)
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.route("https://api.sleeper.app/**", sleeper)
    pg.route(re.compile(r"https://(sleepercdn\.com|a\.espncdn\.com|fonts\.(googleapis|gstatic)\.com|use\.typekit\.net)/.*"), lambda r: r.abort())
    pg.route(re.compile(rf"http://127\.0\.0\.1:{port}/(index\.html)?(\?.*)?(#.*)?$"), index_route)
    pg.goto(f"http://127.0.0.1:{port}/#rankings"); pg.wait_for_timeout(4500)

    # 1. off by default
    connect(pg, "L1")
    base = ranks(pg)
    ok(base["board"] == "sf-tep" and base["link"] is None, f"Alpha League (12-team SF TE+) is on AM SF PPR TE+, unlinked: {base['board']}, {base['link']}")
    _, sfrows = rows_of(SF_RE.search(INDEX).group(2))
    sf_pos = {r["sleeper_id"]: int(r["pos_rank"]) for r in sfrows if r["pos"] in ("QB", "RB", "WR", "TE")}
    off = [pos for pos, g in by_pos(base).items() if [x[1] for x in g] != [s for s, _ in sorted(((s, sf_pos.get(s, 10**6)) for _, s, _ in g), key=lambda t: t[1])]]
    ok(not off, f"Unlinked, the league's position order is AM SF PPR TE+'s (native format): {off}")
    order0 = ppr_order(INDEX)
    diff_pos = follows(base, order0)
    ok(len(diff_pos) >= 2, f"The two boards really disagree on order at {diff_pos} (the link has work to do)")
    sf_block0 = SF_RE.search(INDEX).group(2)
    keys0 = keys(pg)

    # 2. link to AM PPR
    hint = set_link(pg, "ppr")
    ok("follow" in hint.lower() and "AM PPR" in hint and "published" in hint, f"League settings explains the link: {hint[:160]!r}")
    lk = ranks(pg)
    ok(lk["link"] == "ppr" and lk["board"] == "sf-tep", f"Linked: values still on AM SF PPR TE+, order from AM PPR ({lk['board']}, {lk['link']})")
    ok(follows(lk, order0) == [], f"Every position follows AM PPR's published order: mismatches at {follows(lk, order0)}")
    sl = same_ladder(base, lk)
    ok(not sl, f"The league keeps its own value and tier at every position spot (the unlinked ladder; each player's own scoring nudge goes with him): {sl[:5]}")
    ok(strictly_down(lk) == [], f"Values fall strictly down each position: {strictly_down(lk)}")
    ov = sorted((x["rank"], x["value"]) for x in lk["players"].values() if x["rank"] is not None)
    ok(all(b[1] <= a[1] for a, b in zip(ov, ov[1:])), "Overall ranks follow the league-adjusted values")
    lv = pg.evaluate("() => { const r = [...document.querySelectorAll('#rank-body tr.player')].slice(0, 3).map(t => t.querySelector('.pl-name').textContent.trim()); return r; }")
    ok(len(lv) == 3, f"The League-adjusted board draws: {lv}")
    sample = {}
    for pos in ("QB", "WR", "RB", "TE"):   # the players whose position rank the link changes (first 8 per position)
        for rnk, sid, x in [t for t in by_pos(lk)[pos] if t[0] != base["players"][t[1]]["posRank"]][:8]:
            b0 = base["players"][sid]
            sample.setdefault(pos, []).append((x["name"], f"{pos}{b0['posRank']}", b0["value"], b0["rank"], f"{pos}{rnk}", x["value"], x["rank"], order0.get(sid)))

    # 3. a published move up and a published move down on AM PPR reach the league on the next load
    rb = {r: sid for r, sid, _ in by_pos(lk)["RB"]}
    wr = {r: sid for r, sid, _ in by_pos(lk)["WR"]}
    SERVE["index"] = move_in_ppr(move_in_ppr(INDEX, "RB", 8, 5), "WR", 3, 9)
    order1 = ppr_order(SERVE["index"])
    ok(order1[rb[8]] == 5 and order1[wr[3]] == 9, "The served AM PPR moves RB8 → RB5 and WR3 → WR9 (a publish)")
    pg.reload(); pg.wait_for_timeout(5000)
    mv = ranks(pg)
    ok(mv["link"] == "ppr", "The link survives a reload (spm_pos_link)")
    ok(follows(mv, order1) == [], f"After the publish every position follows the new AM PPR order: {follows(mv, order1)}")
    P = lambda lr, sid: lr["players"][sid]
    ok(P(mv, rb[8])["posRank"] == 5 and all(P(mv, rb[k])["posRank"] == k + 1 for k in (5, 6, 7)), "RB8 is now RB5 in the league; RB5–RB7 moved down one")
    ok(P(mv, wr[3])["posRank"] == 9 and all(P(mv, wr[k])["posRank"] == k - 1 for k in range(4, 10)), "WR3 is now WR9; WR4–WR9 moved up one")
    ok(all(P(mv, s)["posRank"] == P(lk, s)["posRank"] for s in rb.values() if P(lk, s)["posRank"] not in range(5, 9)), "Every other RB keeps his position rank")
    ok(all(P(mv, s)["posRank"] == P(lk, s)["posRank"] for pos in ("QB", "TE") for _, s, _ in by_pos(lk)[pos]), "QBs and TEs are unchanged")
    near = lambda a, b: abs(a["value"] - b["value"] / b["factor"] * a["factor"]) <= max(2, 0.01 * a["value"])
    ok(near(P(mv, rb[8]), P(lk, rb[5])) and near(P(mv, wr[3]), P(lk, wr[9])),
       f"The moved players take the league's value at their new spot (RB {P(mv, rb[8])['value']} = old RB5's {P(lk, rb[5])['value']}; WR {P(mv, wr[3])['value']} = old WR9's {P(lk, wr[9])['value']}), not AM PPR's")
    dl = same_ladder(lk, mv)
    ok(not dl, f"The league's value / tier ladder per spot is unchanged by the move: {dl[:6]}")
    ppr_val = {r["sleeper_id"]: int(r["value"]) for r in rows_of(PPR_RE.search(SERVE["index"]).group(2))[1]}
    ok(P(mv, rb[8])["value"] != ppr_val[rb[8]], f"…so RB5 in both doesn't mean the same value (league {P(mv, rb[8])['value']}, AM PPR {ppr_val[rb[8]]})")
    moved = (P(mv, rb[8])["name"], P(lk, rb[8])["posRank"], P(lk, rb[8])["value"], P(lk, rb[8])["rank"], P(mv, rb[8])["posRank"], P(mv, rb[8])["value"], P(mv, rb[8])["rank"])
    moved_wr = (P(mv, wr[3])["name"], P(lk, wr[3])["posRank"], P(lk, wr[3])["value"], P(lk, wr[3])["rank"], P(mv, wr[3])["posRank"], P(mv, wr[3])["value"], P(mv, wr[3])["rank"])
    if os.environ.get("SHOTS"):
        os.makedirs(os.environ["SHOTS"], exist_ok=True)
        pg.click("#tab-rankings"); pg.wait_for_timeout(300)
        pg.locator("#league-controls [data-view=league]").click(); pg.wait_for_timeout(500)
        pg.locator("[data-pos=RB]").first.click(); pg.wait_for_timeout(600)
        pg.screenshot(path=os.path.join(os.environ["SHOTS"], "linked_rb_dark.png"))
        open_settings(pg)
        pg.locator("#fmt-dialog").screenshot(path=os.path.join(os.environ["SHOTS"], "settings_dark.png"))
        pg.click("#fmt-cancel"); pg.wait_for_timeout(200)

    # 4. unpublished drafts never count (AM PPR as the edited board, a move saved without a token)
    SERVE["index"] = INDEX
    pg.add_init_script("window.__SPM_TEST_HOOKS = true;")
    pg.evaluate("() => { localStorage.setItem('spm_edit_board', 'ppr'); }")
    pg.reload(); pg.wait_for_timeout(5000)
    pre = ranks(pg)
    ok(pre["board"] == "sf-tep" and follows(pre, order0) == [], "With AM PPR being edited, the league follows its published order")
    sid9 = rb[9]
    did = pg.evaluate("sid => { const p = SPM.edit.board().find(x => x.sid === sid); SPM.edit.movePlayer(p.id, 2); SPM.edit.save(); return SPM.edit.board().find(x => x.sid === sid).posNum; }", sid9)
    ok(did == 2, f"The draft moved RB9 to RB2 on AM PPR (saved in this browser, not published): RB{did}")
    post = ranks(pg)
    ok(P(post, sid9)["posRank"] == P(pre, sid9)["posRank"] and follows(post, order0) == [], f"The unpublished move doesn't reach the league (still RB{P(post, sid9)['posRank']})")
    pg.evaluate("() => { SPM.edit.reset(); Object.keys(localStorage).filter(k => k.endsWith(':ppr')).forEach(k => localStorage.removeItem(k)); localStorage.removeItem('spm_edit_board'); }")
    pg.reload(); pg.wait_for_timeout(4500)

    # 5. nothing written to either board; Default unlinks; a 1QB league follows AM PPR exactly
    k1 = keys(pg)
    new = sorted(set(k1) - set(keys0)); changed = sorted(k for k in keys0 if k in k1 and keys0[k] != k1[k] and k not in ("spm_sleeper", "spm_fmt_src", "spm_rk_sort", "spm_view"))
    ok(new == ["spm_pos_link"] or set(new) <= {"spm_pos_link", "spm_format_src", "spm_rk_board"}, f"Only spm_pos_link is new in storage: {new}")
    ok(json.loads(k1.get("spm_pos_link", "{}")) == {"L1": "ppr"}, f"spm_pos_link = {k1.get('spm_pos_link')}")
    ok(not any(k.startswith(("spm_local_edits", "spm_value_touch", "spm_edit_session", "spm_local_base", "spm_publish_pending")) for k in k1), "No board edits were written (either board)")
    ok(pg.evaluate("() => RANKINGS_CSV.trim()") == sf_block0.strip(), "The AM SF PPR TE+ block is byte-identical")
    ok(pg.evaluate("() => RANKINGS_CSV_PPR.trim()") == PPR_RE.search(INDEX).group(2).strip(), "The AM PPR block is byte-identical")
    set_link(pg, "")
    un = ranks(pg)
    ok(un["link"] is None and ladder(un) == ladder(base) and all(un["players"][s]["posRank"] == base["players"][s]["posRank"] for s in base["players"]), "Default unlinks: back to the league's own order exactly")
    connect(pg, "L2")
    b2 = ranks(pg)
    ok(b2["board"] == "ppr" and b2["link"] is None, "Beta League (10-team 1QB Half PPR) is on AM PPR, unlinked")
    sticky = follows(b2, order0)
    set_link(pg, "ppr")
    l2 = ranks(pg)
    ok(follows(l2, order0) == [], f"Linked, Beta League follows AM PPR exactly (unlinked, scoring nudges reordered: {sticky or 'nothing'})")
    ok(strictly_down(l2) == [], "…with values still strictly down each position")
    ok(sorted(x["value"] for x in l2["players"].values()) == sorted(x["value"] for x in b2["players"].values()) or sticky,
       "Where nothing was reordered, linking changes no value")
    ok(json.loads(keys(pg)["spm_pos_link"]) == {"L2": "ppr"}, "Links are per league (Alpha's Default removed its entry, Beta's added)")
    ok(not errs, f"No page errors: {errs[:3]}")
    br.close()

if os.environ.get("REPORT"):
    lines = ["# Linked position order: before / after (synthetic Alpha League, 12-team Superflex TE+)", "",
             "Values, tiers and overall ranks come from the league's own board (AM SF PPR TE+) and format; the order inside each position comes from AM PPR's published rankings.", ""]
    for pos, rows in sample.items():
        lines += [f"## {pos}: players whose position rank changes when linked", "", "| Player | Unlinked | Value | Overall | Linked | Value | Overall | AM PPR rank |", "|---|---|---|---|---|---|---|---|"]
        lines += [f"| {n} | {a} | {v:,} | #{r} | {b} | {v2:,} | #{r2} | {pos}{o} |" for n, a, v, r, b, v2, r2, o in sorted(rows, key=lambda t: int(t[4][2:]))]
        lines.append("")
    lines += ["## A published move on AM PPR", "", "| Player | Before | Value | Overall | After publish | Value | Overall |", "|---|---|---|---|---|---|---|"]
    for n, a, v, r, b, v2, r2 in (moved, moved_wr):
        pos = "RB" if (n, a) == moved[:2] else "WR"
        lines.append(f"| {n} | {pos}{a} | {v:,} | #{r} | {pos}{b} | {v2:,} | #{r2} |")
    open(os.environ["REPORT"], "w").write("\n".join(lines) + "\n")
    print("report written to", os.environ["REPORT"])

print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
