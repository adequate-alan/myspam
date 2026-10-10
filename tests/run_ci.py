"""Runs the release checks and decides pass/fail (Phase 1 reliability). Used by .github/workflows/site.yml; works the same
locally.

  python3 tests/run_ci.py fast                 static checks + browser smoke test (~30 s)
  python3 tests/run_ci.py full [--shard 1/3]   the full regression suite, or one of N balanced shards
  python3 tests/run_ci.py targeted --suites a,b the named suites only (the targeted release lane, tests/release_tier.py)
           --group shared|exclusive  only that part of the list (CI runs the two groups on two runners at once; an
                           empty group exits 0 with nothing to run)
  options: --jobs N        run up to N suites at once (default 1, as in CI). The timing-sensitive suites listed under
                           "exclusive" in tests/ci_policy.json (the drag suites) always run one at a time with nothing
                           else running, after the others; every other suite is independent (its own server, browser and
                           mock GitHub) and can share the machine. Locally --jobs 3 brings the full tier from ~33 to
                           ~10 minutes on 4 cores.
           --heartbeat S   while suites run, print what is running and for how long every S seconds (default 60, 0 off)
           --timeout M     per-suite timeout in minutes (default from the policy's timeout_minutes, 15)
           --logs DIR      one log per suite (default tests/.ci-logs); --static-args "--base SHA" (passed to static_check)

A suite fails the run when it prints a FAIL line that tests/ci_policy.json doesn't list, or exits non-zero without
printing one (a crash or timeout). One exception (Alan, Oct 15): a crash that is plainly the browser or the local
server and not the site (a Playwright navigation or page-load timeout, a browser that failed to start or closed, a
dropped connection; INFRA below) is retried once, that suite only, inside the same job. A retry that passes is reported
as "passed after a retry (flaky)" and written to flaky.json in the logs directory so repeat offenders get fixed; a
retry that fails again, an assertion FAIL, a whole-suite timeout or any other crash blocks as before. The policy's
suites.infra_retries (default 1) sets the count. Known baseline failures and advisory checks are listed by exact check name and
reported separately; a known failure that starts passing is reported too, so its entry can be removed. Writes a Markdown
summary to $GITHUB_STEP_SUMMARY when it's set. Nothing is ever skipped: every suite of the tier (or shard) runs every time.
"""
import argparse, json, os, re, signal, subprocess, sys, threading, time
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POLICY = json.load(open(os.path.join(ROOT, "tests", "ci_policy.json")))

def shard_of(suites, k, n):   # greedy by expected duration, deterministic
    w = POLICY["suites"]["weights"]; bins = [[0, []] for _ in range(n)]
    for s in sorted(suites, key=lambda s: (-w.get(s, 60), s)):
        b = min(bins, key=lambda b: b[0]); b[0] += w.get(s, 60); b[1].append(s)
    return bins[k - 1][1]

# a crash the browser or the local server caused, not the site: the last lines of the suite's output say so
INFRA = [re.compile(x) for x in (
    r"TimeoutError.*(goto|navigating to|wait_for_(selector|load_state|url|function|timeout)|launch|waiting until|waiting for)",
    r"navigating to \".*waiting until",
    r"Target (page|context|browser) has been closed", r"Browser has been closed", r"browser has disconnected", r"BrowserType\.launch",
    r"Protocol error", r"net::ERR_", r"ECONNRESET|ECONNREFUSED|Connection refused|Connection reset", r"Executable doesn't exist")]
def infra_reason(out):
    tail = "\n".join(out.strip().splitlines()[-60:])
    for rx in INFRA:
        m = rx.search(tail)
        if m: return tail[max(0, m.start() - 40):m.end() + 60].replace("\n", " ").strip()
    return None

def classify(suite, line):
    kf = POLICY["known_failures"].get(suite, {})
    for name in kf:
        if line.startswith(name): return "known", name
    for name in POLICY["advisory"].get(suite, []):
        if line.startswith(name): return "advisory", name
    return "new", None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tier", choices=["fast", "full", "targeted"]); ap.add_argument("--shard", default="1/1")
    ap.add_argument("--suites", default="", help="targeted: comma-separated suites (each must be in the full tier)")
    ap.add_argument("--group", default="all", choices=["all", "shared", "exclusive"], help="targeted: only this part of the list")
    ap.add_argument("--logs", default=os.path.join(ROOT, "tests", ".ci-logs")); ap.add_argument("--static-args", default="")
    ap.add_argument("--jobs", type=int, default=1); ap.add_argument("--heartbeat", type=float, default=60)
    ap.add_argument("--timeout", type=float, default=float(POLICY["suites"].get("timeout_minutes", 15)))
    a = ap.parse_args()
    k, n = map(int, a.shard.split("/"))
    if a.tier == "targeted":
        suites = [x for x in a.suites.split(",") if x]
        unknown = [x for x in suites if x not in POLICY["suites"]["full"]]
        if unknown or not suites:
            print(f"targeted: unknown or no suites {unknown or a.suites!r}"); return 1
    else:
        suites = POLICY["suites"][a.tier]
    if a.tier == "full": suites = shard_of(suites, k, n)
    if a.tier == "targeted" and a.group != "all":
        excl = POLICY["suites"].get("exclusive", [])
        suites = [x for x in suites if (x in excl) == (a.group == "exclusive")]
        if not suites: print(f"targeted ({a.group}): nothing to run in this group"); return 0
    os.makedirs(a.logs, exist_ok=True)
    retries = int(POLICY["suites"].get("infra_retries", 1))
    timeout = a.timeout * 60
    weights = POLICY["suites"]["weights"]
    exclusive = [s for s in suites if s in POLICY["suites"].get("exclusive", [])]
    shared = sorted([s for s in suites if s not in exclusive], key=lambda s: (-weights.get(s, 60), s))   # longest first packs best
    jobs = max(1, a.jobs)
    running, lock, t_start = {}, threading.Lock(), time.time()
    out_lock = threading.Lock()
    def say(*parts):
        with out_lock: print(*parts, flush=True)

    def attempt(s):
        cmd = [sys.executable, os.path.join("tests", s + ".py")] + (a.static_args.split() if s == "static_check" and a.static_args else [])
        # each suite runs in its own process group, so a timeout kills the suite AND its browser / server subprocesses
        proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
        try:
            out, _ = proc.communicate(timeout=timeout); return out, proc.returncode
        except subprocess.TimeoutExpired:
            try: os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            out, _ = proc.communicate(); return out, "timeout"
    def run_suite(s):
        t0 = time.time()
        with lock: running[s] = t0
        say(f"[start] {s}")
        flaky = None
        try:
            out, rc = attempt(s)
            # a browser / server crash (no FAIL line, not a timeout) is retried once, this suite only
            for i in range(retries):
                if rc == 0 or rc == "timeout" or any(l.startswith("FAIL ") for l in out.splitlines()): break
                why = infra_reason(out)
                if not why: break
                open(os.path.join(a.logs, f"{s}.attempt{i + 1}.log"), "w").write(out)
                say(f"    retry {s}: the browser or the local server failed, not a check ({why[:160]})")
                out, rc = attempt(s)
                if rc == 0: flaky = why
        finally:
            with lock: running.pop(s, None)
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
        if rc == "timeout": new.append(f"timed out after {a.timeout:g} min"); crashed = False
        if crashed: new.append("crashed (non-zero exit without a FAIL line): " + (out.strip().splitlines() or ["no output"])[-1][:200])
        # a known failure that didn't show up in a run that completed normally
        fixed = [x for x in POLICY["known_failures"].get(s, {}) if x not in known] if (not crashed and rc != "timeout" and passes) else []
        status = "FAIL" if new else "pass"
        if flaky:
            with lock:
                fp = os.path.join(a.logs, "flaky.json"); led = json.load(open(fp)) if os.path.exists(fp) else []
                led.append({"suite": s, "reason": flaky[:300], "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}); json.dump(led, open(fp, "w"), indent=1)
        lines = [f"[{status}] {s}: {passes} passed, {len(fails)} failed ({len(new)} new, {len(known)} known, {len(adv)} advisory) in {dt:.0f}s"
                 + (f" · passed after a retry (flaky): {flaky[:120]}" if flaky else "")]
        lines += ["    NEW FAILURE: " + x[:300] for x in new]
        lines += ["    known baseline failure: " + x for x in sorted(known)]
        lines += ["    advisory (not blocking): " + x[:200] for x in adv]
        lines += ["    known failure no longer fails, remove it from tests/ci_policy.json: " + x for x in fixed]
        say("\n".join(lines))
        return (s, status, passes, len(fails), dt, new, sorted(known), adv, fixed, flaky)

    stop = threading.Event()
    def heartbeat():
        while not stop.wait(a.heartbeat):
            with lock: snap = sorted(running.items(), key=lambda x: x[1])
            if snap: say("    … running: " + ", ".join(f"{s} ({time.time() - t0:.0f}s)" for s, t0 in snap) + f" · {time.time() - t_start:.0f}s elapsed")
    hb = threading.Thread(target=heartbeat, daemon=True)
    if a.heartbeat > 0: hb.start()

    rows = []
    if shared:
        if jobs > 1: say(f"Running {len(shared)} suites up to {jobs} at a time" + (f", then {len(exclusive)} timing-sensitive suite(s) alone" if exclusive else ""))
        with ThreadPoolExecutor(max_workers=jobs) as ex:
            rows += list(ex.map(run_suite, shared))
    for s in exclusive:   # timing measurements: nothing else may run
        rows.append(run_suite(s))
    stop.set()
    order = {s: i for i, s in enumerate(suites)}
    rows.sort(key=lambda r: order[r[0]])
    blocking = sum(1 for r in rows if r[5])
    wall = time.time() - t_start

    md = [f"### Release checks: {a.tier}" + (f" (shard {k}/{n})" if a.tier == "full" and n > 1 else ""), "",
          "| Suite | Result | Passed | Failed | Time |", "|---|---|---|---|---|"]
    for s, st, p, f, dt, new, known, adv, fixed, flaky in rows:
        md.append(f"| {s} | {'❌ new failure' if st == 'FAIL' else '✅ pass' + (' (known baseline)' if known else '') + (' (advisory)' if adv else '') + (' ⚠ after a retry' if flaky else '')} | {p} | {f} | {dt:.0f}s |")
    for s, st, p, f, dt, new, known, adv, fixed, flaky in rows:
        if flaky: md.append(f"- ⚠ **{s}** passed only after a retry (a flaky suite to fix, not a site failure): {flaky[:200]}")
        for x in new: md.append(f"- **{s}** new failure: {x[:300]}")
        for x in known: md.append(f"- {s} known baseline failure: {x}")
        for x in adv: md.append(f"- {s} advisory: {x[:200]}")
        for x in fixed: md.append(f"- {s}: known failure now passes, remove it from tests/ci_policy.json: {x}")
    md.append(f"\n{len(rows)} suites · {sum(r[4] for r in rows):.0f}s of suite time in {wall:.0f}s" + (f" ({jobs} at a time)" if jobs > 1 else ""))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a").write("\n".join(md) + "\n")
    say(f"\n{len(rows)} suites · {sum(r[4] for r in rows):.0f}s of suite time in {wall:.0f}s wall" + (f" ({jobs} at a time)" if jobs > 1 else ""))
    flaked = [r[0] for r in rows if r[9]]
    say(f"{blocking} suite(s) with new failures." if blocking else "No new failures." + (f" {len(flaked)} suite(s) passed only after a retry (flaky): {', '.join(flaked)}" if flaked else ""))
    return 1 if blocking else 0

if __name__ == "__main__":
    sys.exit(main())
