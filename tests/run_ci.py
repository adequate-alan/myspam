"""Runs the release checks and decides pass/fail (Phase 1 reliability). Used by .github/workflows/site.yml; works the same
locally.

  python3 tests/run_ci.py fast                 static checks + browser smoke test (~30 s)
  python3 tests/run_ci.py full [--shard 1/3]   the full regression suite, or one of N balanced shards
  options: --logs DIR (one log per suite, default tests/.ci-logs), --static-args "--base SHA" (passed to static_check)

Suites run one at a time (the drag suites measure timing). A suite fails the run when it prints a FAIL line that
tests/ci_policy.json doesn't list, or exits non-zero without printing one (a crash or timeout). Known baseline failures
and advisory timing checks are listed by exact check name and reported separately; a known failure that starts passing
is reported too, so its entry can be removed. Writes a Markdown summary to $GITHUB_STEP_SUMMARY when it's set.
"""
import argparse, json, os, re, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POLICY = json.load(open(os.path.join(ROOT, "tests", "ci_policy.json")))
TIMEOUT = 20 * 60

def shard_of(suites, k, n):   # greedy by expected duration, deterministic
    w = POLICY["suites"]["weights"]; bins = [[0, []] for _ in range(n)]
    for s in sorted(suites, key=lambda s: (-w.get(s, 60), s)):
        b = min(bins, key=lambda b: b[0]); b[0] += w.get(s, 60); b[1].append(s)
    return bins[k - 1][1]

def classify(suite, line):
    kf = POLICY["known_failures"].get(suite, {})
    for name in kf:
        if line.startswith(name): return "known", name
    for name in POLICY["advisory"].get(suite, []):
        if line.startswith(name): return "advisory", name
    return "new", None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tier", choices=["fast", "full"]); ap.add_argument("--shard", default="1/1")
    ap.add_argument("--logs", default=os.path.join(ROOT, "tests", ".ci-logs")); ap.add_argument("--static-args", default="")
    a = ap.parse_args()
    k, n = map(int, a.shard.split("/"))
    suites = POLICY["suites"][a.tier]
    if a.tier == "full": suites = shard_of(suites, k, n)
    os.makedirs(a.logs, exist_ok=True)
    rows, blocking = [], 0
    for s in suites:
        cmd = [sys.executable, os.path.join("tests", s + ".py")] + (a.static_args.split() if s == "static_check" and a.static_args else [])
        t0 = time.time()
        try:
            r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=TIMEOUT)
            out, rc = r.stdout + r.stderr, r.returncode
        except subprocess.TimeoutExpired as e:
            out, rc = (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or ""), "timeout"
        dt = time.time() - t0
        open(os.path.join(a.logs, s + ".log"), "w").write(out)
        fails = [l[5:] for l in out.splitlines() if l.startswith("FAIL ")]
        passes = sum(1 for l in out.splitlines() if l.startswith("PASS "))
        new, known, adv = [], set(), []
        for f in fails:
            kind, name = classify(s, f)
            (new if kind == "new" else adv if kind == "advisory" else []).append(f)
            if kind == "known": known.add(name)
        crashed = rc != 0 and not fails
        if rc == "timeout": new.append(f"timed out after {TIMEOUT // 60} min"); crashed = False
        if crashed: new.append("crashed (non-zero exit without a FAIL line): " + (out.strip().splitlines() or ["no output"])[-1][:200])
        # a known failure that didn't show up in a run that completed normally
        fixed = [x for x in POLICY["known_failures"].get(s, {}) if x not in known] if (not crashed and rc != "timeout" and passes) else []
        status = "FAIL" if new else "pass"
        blocking += bool(new)
        rows.append((s, status, passes, len(fails), dt, new, sorted(known), adv, fixed))
        print(f"[{status}] {s}: {passes} passed, {len(fails)} failed ({len(new)} new, {len(known)} known, {len(adv)} advisory) in {dt:.0f}s", flush=True)
        for x in new: print("    NEW FAILURE: " + x[:300])
        for x in sorted(known): print("    known baseline failure: " + x)
        for x in adv: print("    advisory (timing, not blocking): " + x[:200])
        for x in fixed: print("    known failure no longer fails, remove it from tests/ci_policy.json: " + x)

    md = [f"### Release checks: {a.tier}" + (f" (shard {k}/{n})" if a.tier == "full" and n > 1 else ""), "",
          "| Suite | Result | Passed | Failed | Time |", "|---|---|---|---|---|"]
    for s, st, p, f, dt, new, known, adv, fixed in rows:
        md.append(f"| {s} | {'❌ new failure' if st == 'FAIL' else '✅ pass' + (' (known baseline)' if known else '') + (' (advisory timing)' if adv else '')} | {p} | {f} | {dt:.0f}s |")
    for s, st, p, f, dt, new, known, adv, fixed in rows:
        for x in new: md.append(f"- **{s}** new failure: {x[:300]}")
        for x in known: md.append(f"- {s} known baseline failure: {x}")
        for x in adv: md.append(f"- {s} advisory timing: {x[:200]}")
        for x in fixed: md.append(f"- {s}: known failure now passes, remove it from tests/ci_policy.json: {x}")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a").write("\n".join(md) + "\n")
    print(f"\n{blocking} suite(s) with new failures." if blocking else "\nNo new failures.")
    return 1 if blocking else 0

if __name__ == "__main__":
    sys.exit(main())
