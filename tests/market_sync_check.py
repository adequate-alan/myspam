"""Market sync bookkeeping (Alan, Oct 11): pipeline/build_market.py records when Adequate synced FantasyCalc, when the
values last changed, the provider's own update time when it sends one, and a failed attempt. No network, no browser:
synthetic FantasyCalc answers from a temp directory, the output written to a temp copy of data/market/redraft.json.

Run from the repo root:  python3 tests/market_sync_check.py
"""
import json, os, sys, tempfile, importlib.util
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("build_market", os.path.join(ROOT, "pipeline", "build_market.py"))
bm = importlib.util.module_from_spec(spec); spec.loader.exec_module(bm)

failures = []
def ok(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond: failures.append(msg)

tmp = tempfile.mkdtemp(prefix="market-sync-")
bm.OUT = os.path.join(tmp, "redraft.json")
src = os.path.join(tmp, "fc_{q}_{t}_{tep}_{ppr}.json")
def answers(bump=0):
    for q, t, tep, ppr in bm.FORMATS:
        rows = [{"player": {"sleeperId": str(1000 + i), "position": "WR"}, "value": 9000 - 100 * i + (bump if i == 0 else 0),
                 "overallRank": i + 1, "positionRank": i + 1, "trend30Day": i} for i in range(30)]
        json.dump(rows, open(src.format(q=q, t=t, tep=tep, ppr=ppr), "w"))
read = lambda: json.load(open(bm.OUT))
t0 = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)

answers()
bm.main(src, t0); d = read()
ok(d["updated"] == "2026-10-09T12:00:00Z" and d["changed"] == d["updated"], "First sync: synced and changed at the same time")
ok(d["provider_updated"] is None, "No provider timestamp in the answers: provider_updated stays null (never invented)")
ok(d["sync"]["ok"] is True and d["sync"]["formats"] == 12 and d["sync"]["of"] == 12, f"Sync record: ok, 12 of 12 formats {d['sync']}")

# same values, only the 30-day trend moved: synced again, values unchanged
for q, t, tep, ppr in bm.FORMATS:
    f = src.format(q=q, t=t, tep=tep, ppr=ppr); rows = json.load(open(f)); rows[3]["trend30Day"] = 99; json.dump(rows, open(f, "w"))
bm.main(src, t0 + timedelta(hours=8)); d = read()
ok(d["updated"] == "2026-10-09T20:00:00Z" and d["changed"] == "2026-10-09T12:00:00Z", f"Unchanged values: synced later, changed stays at the first sync {d['updated']} / {d['changed']}")

# a value moves: changed follows the sync
answers(bump=50)
bm.main(src, t0 + timedelta(hours=16)); d = read()
ok(d["changed"] == d["updated"] == "2026-10-10T04:00:00Z", "Changed values: changed = this sync")

# every call fails: the values and `updated` stay, the attempt is recorded as failed
before = read()
bm.main(os.path.join(tmp, "missing_{q}_{t}_{tep}_{ppr}.json"), t0 + timedelta(hours=24)); d = read()
ok(d["formats"] == before["formats"] and d["updated"] == before["updated"] and d["changed"] == before["changed"], "Failed sync keeps the values, the sync time and the change time")
ok(d["sync"]["ok"] is False and d["sync"]["attempted"] == "2026-10-10T12:00:00Z" and d["sync"]["error"], f"Failed sync is recorded with its time and error {d['sync']['attempted']}")

# the next good sync clears the failure; unchanged values keep the change time
bm.main(src, t0 + timedelta(hours=32)); d = read()
ok(d["sync"]["ok"] is True and d["changed"] == "2026-10-10T04:00:00Z", "Recovery: sync ok again, change time unchanged")

# a provider Last-Modified header is kept as the provider's update time
ok(bm.http_date("Sat, 10 Oct 2026 14:05:00 GMT") == "2026-10-10T14:05:00Z" and bm.http_date("garbage") is None, "Last-Modified headers parse to UTC; anything else is ignored")

# an older file without the new fields: the first sync with the same values treats `updated` as the change time
old = read(); old.pop("changed"); old.pop("sync"); old.pop("provider_updated"); json.dump(old, open(bm.OUT, "w"))
bm.main(src, t0 + timedelta(hours=40)); d = read()
ok(d["changed"] == old["updated"], "Migration: a file without `changed` keeps its old sync time as the change time")

# Half PPR (Oct 14, Flock market lists PR 3): four ppr=0.5 keys beside the Full PPR ones
ok(all(k in d["formats"] for k in ("q2_t12_half", "q1_t12_half", "q2_t10_half", "q1_t10_half")) and "q1_t12" in d["formats"], f"Half PPR keys written beside Full PPR: {sorted(d['formats'])}")
ok(bm.URL.format(q=1, t=12, ppr=0.5, tep="none").endswith("ppr=0.5&tep=none"), "Half PPR calls ask FantasyCalc for ppr=0.5")
# a file from before the Half PPR keys: their first sync with the same Full PPR values is not a change of values
prev = read(); [prev["formats"].pop(k) for k in list(prev["formats"]) if k.endswith("_half")]; prev["changed"] = "2026-10-01T00:00:00Z"; json.dump(prev, open(bm.OUT, "w"))
bm.main(src, t0 + timedelta(hours=48)); d = read()
ok(d["changed"] == "2026-10-01T00:00:00Z" and "q1_t12_half" in d["formats"], "Adding the Half PPR keys alone doesn't count as changed values")

print(f"\n{len(failures)} check(s) failed." if failures else "\nAll market sync checks passed.")
sys.exit(1 if failures else 0)
