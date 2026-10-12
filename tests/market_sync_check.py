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
src = os.path.join(tmp, "fc_{q}_{t}_{tep}.json")
def answers(bump=0):
    for q, t, tep in bm.FORMATS:
        rows = [{"player": {"sleeperId": str(1000 + i), "position": "WR"}, "value": 9000 - 100 * i + (bump if i == 0 else 0),
                 "overallRank": i + 1, "positionRank": i + 1, "trend30Day": i} for i in range(30)]
        json.dump(rows, open(src.format(q=q, t=t, tep=tep), "w"))
read = lambda: json.load(open(bm.OUT))
t0 = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)

answers()
bm.main(src, t0); d = read()
ok(d["updated"] == "2026-10-09T12:00:00Z" and d["changed"] == d["updated"], "First sync: synced and changed at the same time")
ok(d["provider_updated"] is None, "No provider timestamp in the answers: provider_updated stays null (never invented)")
ok(d["sync"]["ok"] is True and d["sync"]["formats"] == 8 and d["sync"]["of"] == 8, f"Sync record: ok, 8 of 8 formats {d['sync']}")

# same values, only the 30-day trend moved: synced again, values unchanged
for q, t, tep in bm.FORMATS:
    f = src.format(q=q, t=t, tep=tep); rows = json.load(open(f)); rows[3]["trend30Day"] = 99; json.dump(rows, open(f, "w"))
bm.main(src, t0 + timedelta(hours=8)); d = read()
ok(d["updated"] == "2026-10-09T20:00:00Z" and d["changed"] == "2026-10-09T12:00:00Z", f"Unchanged values: synced later, changed stays at the first sync {d['updated']} / {d['changed']}")

# a value moves: changed follows the sync
answers(bump=50)
bm.main(src, t0 + timedelta(hours=16)); d = read()
ok(d["changed"] == d["updated"] == "2026-10-10T04:00:00Z", "Changed values: changed = this sync")

# every call fails: the values and `updated` stay, the attempt is recorded as failed
before = read()
bm.main(os.path.join(tmp, "missing_{q}_{t}_{tep}.json"), t0 + timedelta(hours=24)); d = read()
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

print(f"\n{len(failures)} check(s) failed." if failures else "\nAll market sync checks passed.")
sys.exit(1 if failures else 0)
