"""De'Von Achane's AM SF PPR TE+ value corrected from 6 to 0 (Alan, Nov 14). No browser.

He has been in the Out for season tier on AM SF PPR TE+ since October but still carried a value of 6 (AM PPR had 0).
Alan approved the correction on its own: value 0, position rank (RB77) and tier (Out for season) unchanged. Values run
strictly down the overall board and only 0s tie, so his overall spot moved from #263 to #266, under the three
placeholder quarterbacks worth 5, 4 and 3 (McCord, Beck, Richardson), who each moved up one. Nothing else changed.

Run from the repo root:  python3 tests/out_value_check.py

  A. The history event (pinned; history is append-only): one value edit, 6 -> 0, and four overall rank changes.
  B. The board snapshot at the event against the one before it: only Achane's value differs; only those four overall
     ranks differ; every position rank and tier is the same; AM PPR's files have no event at that time.
  C. Today's boards: while Achane is in Out for season on AM SF PPR TE+ his value is 0 (the 6 never comes back); a
     player in Out for season with a value on either board is listed as information, never a failure.
"""
import csv, io, json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TS, SID, OUT_TIER = "2026-11-14T08:19:00.000Z", "9226", 99
MOVES = {"9226": (263, 266), "12494": (264, 263), "13272": (265, 264), "9229": (266, 265)}
load = lambda *p: json.load(open(os.path.join(ROOT, *p), encoding="utf-8"))
FAILS = []


def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def board(name):
    src = open(os.path.join(ROOT, "index.html"), encoding="utf-8").read()
    rows = list(csv.DictReader(io.StringIO(re.search(r"const %s = `\n([\s\S]*?)\n`;" % name, src).group(1))))
    return {r["sleeper_id"]: r for r in rows}


# A. the event
hist = load("data", "rank_history.json")
evs = [e for e in hist["events"] if e["ts"] == TS]
ok(len(evs) == 1 and evs[0]["src"] == "M", "A. one publish event at the correction's time")
ev = evs[0] if evs else {"manual": [], "ranking": [], "auto": [], "repriced": None}
ok(ev["manual"] == [[SID, "6", "0"]], "A. the event's only value edit is Achane 6 -> 0")
ok(sorted((r[0], r[1], r[2]) for r in ev["ranking"]) == sorted((k, a, b) for k, (a, b) in MOVES.items())
   and all(r[3] == r[4] for r in ev["ranking"]), "A. four overall rank changes, no tier change")
ok(ev["auto"] == [] and ev["repriced"] == 1, "A. exactly one value changed on the board")
mine = hist["players"][SID]
at = [e for e in mine if e[0] == TS]
ok(len(at) == 1 and at[0][1:] == [266, 77, OUT_TIER, 0, "M", "RV"], "A. Achane's entry: #266, RB77, Out for season, 0")
prev = [e for e in mine if e[0] < TS][-1]
ok(prev[2:5] == [77, OUT_TIER, 6], "A. his entry before it: RB77, Out for season, 6")

# B. the snapshot
snaps = load("data", "rank_snapshots", "2026-11.json")["snapshots"]
i = next((k for k, s in enumerate(snaps) if s["ts"] == TS), None)
ok(i is not None and i > 0, "B. a board snapshot at the event")
if i:
    a, b = snaps[i - 1]["players"], snaps[i]["players"]
    ok(set(a) == set(b), "B. the same players")
    ok({k for k in a if a[k][3] != b[k][3]} == {SID} and (a[SID][3], b[SID][3]) == (6, 0), "B. only Achane's value differs")
    ok({k: (a[k][0], b[k][0]) for k in a if a[k][0] != b[k][0]} == MOVES, "B. only the four overall ranks differ")
    ok(all(a[k][1:3] == b[k][1:3] for k in a), "B. every position rank and tier unchanged")
    ok(sorted(v[0] for v in b.values()) == list(range(1, len(b) + 1)), "B. overall ranks run 1..N")
    order = sorted(b.values(), key=lambda v: v[0])
    ok(all(x[3] > y[3] or (x[3] == 0 and y[3] == 0) for x, y in zip(order, order[1:])), "B. values strictly down the board, only 0s tie")
ppr = load("data", "boards", "ppr", "rank_history.json")
ok(not any(e["ts"] == TS for e in ppr["events"]), "B. no AM PPR event: the correction is on AM SF PPR TE+ only")

# C. today's boards
sf, pp = board("RANKINGS_CSV"), board("RANKINGS_CSV_PPR")
me = sf.get(SID)
ok(me is not None and (int(me["tier"]) != OUT_TIER or int(me["value"]) == 0), "C. Achane in Out for season on AM SF PPR TE+ has value 0")
for label, rows in (("AM SF PPR TE+", sf), ("AM PPR", pp)):
    odd = [f"{r['player']} {r['value']}" for r in rows.values() if int(r["tier"]) == OUT_TIER and int(r["value"] or 0) != 0]
    print(f"INFO C. {label}: " + ("every Out for season player is at 0" if not odd else "Out for season with a value: " + ", ".join(odd)))

print(f"\n{'ALL PASS' if not FAILS else str(len(FAILS)) + ' FAILED'}")
sys.exit(1 if FAILS else 0)
