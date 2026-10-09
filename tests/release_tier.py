"""Risk tier of a change (Alan, Oct 14): decides how much CI a push needs before it may deploy.

  python3 tests/release_tier.py --base <sha> [--head <sha>] [--force-full] [--json]

Reads `git diff base..head` and classifies every changed line of index.html by the part of the page it sits in (the
rankings block, CSS, markup, the settings script, or the JavaScript function it belongs to) and every other file by its
path. The highest tier wins:

  data    only data: JSON under data/ and the RANKINGS_CSV block. Not a code change: the existing fast path decides
          (the fast checks when this exact code already passed the full suite, the full suite before deploy otherwise).
  Tier 0  docs (*.md, .gitignore), the BUILD_ID line, JavaScript comment lines. Fast checks block the deploy.
  Tier 1  CSS only (outside the drag elements). Fast checks + ui_check block the deploy.
  Tier 2  rendering code of ONE isolated UI system (the risk map below), CSS on the drag elements, or a test file.
          Fast checks + ui_check + that system's suites block the deploy.
  Tier 3  the value model, editor, publishing, history, league layer, trade logic, scoring and projections, market,
          the settings script (VALUE_MODEL, tradeModel, FORMAT_ADJUST …), page markup, pipeline scripts, any function
          the risk map doesn't list, and changes to two or more UI systems at once. The full suite blocks the deploy.
  Tier 4  shared helpers used across the site, CI and test infrastructure (the workflow, run_ci, the policy, the fast
          checks, shared test helpers), any other file, or more than two systems. The full suite blocks the deploy.

Tiers 0–2 deploy after their targeted checks; the full suite then runs anyway, never blocking that deploy, and only its
success marks the code verified. Anything ambiguous goes up a tier: a function not in the risk map is Tier 3; markup is
Tier 3 (an id or class can be read anywhere); two UI systems are Tier 3. `--force-full` (the workflow's full_ci input,
the `full-ci` pull request label) or a `CI: full` line in any commit message of the range makes it Tier 4.

The risk map is plain data (RISK below). Adding a function there is a deliberate decision about its blast radius; a new
function nobody mapped gets the full suite until someone does.
"""
import argparse, json, os, re, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# system -> (tier, suites, top-level names in index.html's main script). Tier 2 systems name the suites that cover them.
RISK = {
 "shared":        (4, [], "esc fmt $ parseCSV loadPlayers rebuild showTab teamMeta teamLogo teamStyle teamAccent face nameLink compactName tierLabel tierNameOf isTagTier posLabel dv adjOf leagueView valueLeague syncedLeague toast setTheme tabs currentTab players byId editor LG FMT".split()),
 "value-model":   (3, [], "keepRankOrder keepRankOrderBySource autoValues keepOverallOrder valueKey positionCurve localLevel stateValues applyTiers maxValue valueCheck VCHECK formulaPreview modelValue rawValue".split()),
 "editor":        (3, [], "writeOrder makeManual overallOrder moveOverall valueAfter sendOut movePlayer valueFit setValue applyValue recalcLevel recalcPlayer recalcAuto editSession storeSession resetEditSession deriveTiers tierNameAfter valueEdited ownEdit pruneTouched pruneRevalued tiersInOrder tierAction shiftTiers materializeTierNames tierNums tierConflict tierMoveNotice splitNotice zeroNotice valueNotice packSession freshSession unpackSession changedRows".split()),
 "publishing":    (3, [], "gh ghError redact repoEntry repoBlobText repoSnapshot repoRead commitLanded repoCommit repoWrite repoReadMany repoWriteMany extractRankings replaceRankings validateRankings verifyToken readLocal readBase baseFor applyEdits diffEdits pubState readTouch writeTouch inferTouch touch anchorValue reprice persistEdits saveLocal discardLocal mergeInto conflictError readAt historyUpdate checkPublication readPublish writePublish inFlightEdits adoptPublished settlePending publishLive storedToken storeToken clearToken forgetToken openSignin publishInjOverrides".split()),
 "history":       (3, [], "rankingSnapshot normalizeHistory lastOf rankMoved historyChanged kindOf addEntry addSnapshot recordPublish historySummary historyMessage readPending writePending historyWithPending valueEdits recordSave historyText valueAt snapEventAt needSnaps loadSnapMonth histNorm histNow".split()),
 "league-layer":  (3, [], "curvesFor replLevels modelParts modelTable scarcityIndex leagueDepth leagueRecalc leagueTeams adjustValues adjMapFor formatSteps formatCheck smoothTiers stickyOrder playerFactors fmtLeague fmtClean fmtFromUrl fmtToUrl setFormat useLeagueSettings trimLeague syncLeague refreshLeague espnToLeague espnScoring parseYahooSettings matchPlayer".split()),
 "trade-logic":   (3, [], "tradeModel runModel tcAdjusted rosterContext teamImpact utilScore acceptance acceptFor valueFloor tcMarketModel rationale leagueBalance rostersBeforeTrade histReport evalTrade analyzeTrade findTrades findThree plausibleForThem mlAssess mlTypes findTargets findSells enrichTarget bestLineup evaluateTeams roomWeights playoffOdds tfShapes tfCombos".split()),
 "scoring-proj":  (3, [], "gamePoints calculateFantasyPoints scoringNow enteredGame weeklyProjection contextProjection propsProjection weekOutlook projRatios seasonRanks prodData prodMetric prodRanks totals seasonLog shortMap defenseVsPos sleeperPoints".split()),
 "market":        (3, [], "loadMarket marketNow mkSources mkWeigh mkAll mkOf flockParse flockNow".split()),
 "rankings-ui":   (2, ["league_hub_check", "production_check", "xss_check", "drag_check", "drag_repeat_check", "value_state_check"],
                   "renderRankings renderProd renderMkt renderMkBar renderRail valueCell valueCellEdit nflTag nflMark ownPill ownerTag tierTag boardMove boardMoves sinceText rankMove patchRows syncRkControls updateEditorBar renderReview reviewWarnings reviewMarket renderValueCheck renderMarketAudit openReview closeReview".split()),
 "drag-ui":       (2, ["drag_check", "drag_repeat_check", "drag_scroll_check", "tier_boundary_check"],
                   "dragFloat dropNum dragStart dragZone applySlot dragMove dragLoop dragScroll showDrop endDrag commitDrop clearMarks DRAG_STATE drag".split()),
 "drawer-ui":     (2, ["drawer_check", "injury_check", "production_check", "xss_check"],
                   "openPlayer closePlayer renderPlayer ppSection ppOverview thisWeekCard ppSchedule ppPractice ppDepth ppGameLog ppStats ppPerformance ppHistory ppTradeValue ppCompare weeklySeries weeksChart barChart lineChart usageGrid prodRankLine statsStamp markCurrent mkDrawer".split()),
 "league-ui":     (2, ["league_hub_check", "xss_check", "trade_history_check"],
                   "renderLeague powerHtml teamExpand standingsHtml matchupsHtml rostersHtml rostersInner scheduleHtml txHtml txRail moveRow openBids tradeCard tradeHistoryHtml snapText agedText renderMyTeam renderFA strengthCards".split()),
 "finder-ui":     (2, ["trade_target_check", "market_edge_check", "league_hub_check", "xss_check"],
                   "renderFinder renderDiscover renderFinderPick tfResults targetCard mlCard shortWhy fullWhy fitBadge".split()),
 "calc-ui":       (2, ["roster_fit_check", "format_check", "trade_target_check", "xss_check"],
                   "renderTrade renderTrade3 renderImpact rationaleHtml renderBreakdown formatBreakdown renderBeforeAfter renderHist renderTradeContext renderTcMarket".split()),
}
FN = {n: k for k, (_, _, ns) in RISK.items() for n in ns}
UI_CHECK = "ui_check"
DRAG_CSS = re.compile(r"\.drag-|drag-shield|\.ed-move|\.ed-arrows|\.handle\b|\.drop-")
# CI and test infrastructure: a change here changes the gate itself, so it always gets the full suite
INFRA = {"tests/run_ci.py", "tests/ci_policy.json", "tests/static_check.py", "tests/smoke_check.py", "tests/ci_pipeline_check.py",
         "tests/release_fingerprint.py", "tests/release_tier.py", "tests/requirements-ci.txt", "tests/gh_mock.py",
         "tests/fixture_board.py", "tests/league_hub_check.py", "tests/ui_check.py"}   # league_hub_check's header is exec'd by other suites
NAMES = {0: "Tier 0 · trivial", 1: "Tier 1 · visual", 2: "Tier 2 · isolated UI", 3: "Tier 3 · data, model or logic", 4: "Tier 4 · broad, core or CI"}

def git(*a):
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, check=True).stdout.decode("utf-8", "replace")

def regions(text):
    """Per line (1-based): the region (rankings / css / markup / settings-js / js) and, in a script, the enclosing
    top-level declaration (the main script declares everything at two spaces of indent)."""
    lines = text.split("\n"); reg = ["markup"] * (len(lines) + 2); fn = [None] * (len(lines) + 2)
    for m in re.finditer(r"<(style|script)\b[^>]*>([\s\S]*?)</\1>", text):
        a = text.count("\n", 0, m.start()) + 1; b = text.count("\n", 0, m.end()) + 1
        kind = "css" if m.group(1) == "style" else ("settings-js" if re.search(r"^const VALUE_MODEL = \{", m.group(2), re.M) else "js")
        for i in range(a, b + 1): reg[i] = kind
    m = re.search(r"const RANKINGS_CSV = `\n[\s\S]*?\n`;", text)
    if m:
        a = text.count("\n", 0, m.start()) + 1; b = text.count("\n", 0, m.end()) + 1
        for i in range(a + 1, b): reg[i] = "rankings"   # the data lines only, not the declaration around them
    decl = re.compile(r"^  (?:async\s+)?(?:function\s*\*?\s*([A-Za-z_$][\w$]*)|(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=)")
    cur = None
    for i, l in enumerate(lines, 1):
        if reg[i] != "js": cur = None; continue
        mm = decl.match(l)
        if mm: cur = mm.group(1) or mm.group(2)
        elif l.startswith("  ") and not l.startswith("   ") and l.strip().startswith(("})", "}", "];", ")")):
            pass   # the closing line of the current declaration still belongs to it
        fn[i] = cur
    return lines, reg, fn

def classify(base, head="HEAD", force=False):
    out = {"base": base, "head": head, "tier": None, "systems": [], "suites": [], "reasons": [], "files": []}
    try:
        git("cat-file", "-e", base + "^{commit}")
    except subprocess.CalledProcessError:
        out.update(tier=4, reasons=[f"T4 no usable comparison commit ({base[:12] or 'none'}): full suite"]); return out
    files = [f for f in git("diff", "--name-only", base, head).split("\n") if f]
    out["files"] = files
    tier, suites, reasons, systems = None, set(), [], set()
    def bump(t, why, s=()):
        nonlocal tier
        tier = t if tier is None else max(tier, t)
        reasons.append(f"T{t} {why}"); suites.update(s)
    msgs = git("log", "--format=%B%x00", f"{base}..{head}")
    if force: bump(4, "full CI requested (workflow input or full-ci label)")
    if re.search(r"^CI:\s*full\s*$", msgs, re.M | re.I): bump(4, "a commit in the range asks for full CI (CI: full)")
    data_only = True
    for f in files:
        if f.startswith("data/") and f.endswith(".json"): reasons.append(f"data {f}"); continue
        data_only = False
        if f.endswith(".md") or f == ".gitignore": bump(0, f"{f} (docs)"); continue
        if f.startswith(".github/") or f in INFRA or f.startswith("tests/fixtures/"): bump(4, f"{f} (CI / test infrastructure)"); continue
        if re.fullmatch(r"tests/[a-z_]+_check\.py", f): bump(2, f"{f} (test only: its own suite runs)", [f[6:-3], UI_CHECK]); continue
        if f.startswith("tests/"): bump(4, f"{f} (other test file)"); continue
        if f.startswith("pipeline/"): bump(3, f"{f} (pipeline script)"); continue
        if f != "index.html": bump(3, f"{f} (other site file)"); continue
        try:
            old = git("show", f"{base}:index.html")
        except subprocess.CalledProcessError:
            bump(4, "index.html is new"); continue
        new = git("show", f"{head}:index.html")
        Lo, ro, fo = regions(old); Ln, rn, fnn = regions(new)
        hunks = git("diff", "-U0", "--no-color", base, head, "--", "index.html")
        keys = set()
        for h in re.finditer(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", hunks, re.M):
            os_, oc, ns_, nc = int(h[1]), int(h[2] or 1), int(h[3]), int(h[4] or 1)
            for side, start, count, L, R, F in (("o", os_, oc, Lo, ro, fo), ("n", ns_, nc, Ln, rn, fnn)):
                for i in range(start, start + count):
                    r, name, line = R[i], F[i], L[i - 1]; s = line.strip()
                    if r == "rankings": keys.add(("rankings",))
                    elif r == "css": keys.add(("css", "drag" if DRAG_CSS.search(line) else ""))
                    elif r == "markup": keys.add(("markup",))
                    elif r == "settings-js": keys.add(("settings-js",))
                    elif re.match(r'^const BUILD_ID = "[^"`$\\]*";$', s): keys.add(("build-id",))
                    elif s == "" or (s.startswith("//") and "`" not in s): keys.add(("js-comment",))
                    else: keys.add(("js", name))
        if keys != {("rankings",)}: pass
        for key in sorted(keys, key=str):
            k = key[0]
            if k == "rankings": reasons.append("data RANKINGS_CSV block"); continue
            data_only = False
            if k == "build-id": bump(0, "BUILD_ID")
            elif k == "js-comment": bump(0, "JavaScript comment or blank lines")
            elif k == "css" and key[1] == "drag": bump(2, "CSS on the drag elements (drag-ui)", RISK["drag-ui"][1] + [UI_CHECK]); systems.add("drag-ui")
            elif k == "css": bump(1, "CSS", [UI_CHECK])
            elif k == "markup": bump(3, "page markup (ids and classes are read across the site)")
            elif k == "settings-js": bump(3, "the settings script (VALUE_MODEL, tradeModel, FORMAT_ADJUST …)")
            else:
                sysname = FN.get(key[1])
                if sysname is None: bump(3, f"JS {key[1] or 'outside any declaration'} (not in the risk map)")
                else:
                    t, st, _ = RISK[sysname]; systems.add(sysname)
                    bump(t, f"JS {key[1]} ({sysname})", st + ([UI_CHECK] if t == 2 else []))
    ui = sorted(s for s in systems if RISK[s][0] == 2)
    if len(systems) > 2: bump(4, f"more than two systems changed ({', '.join(sorted(systems))})")
    elif len(ui) > 1: bump(3, f"more than one UI system changed ({', '.join(ui)}): not isolated")
    if tier is None: tier = "data" if data_only and files else 0
    out.update(tier=tier, systems=sorted(systems), reasons=reasons,
               suites=sorted(suites) if tier in (1, 2) else [])
    return out

def decide(c):
    """The release mode for a classification: data (existing fingerprint path), fast (targeted checks gate, trailing
    full suite), or full (the full suite gates)."""
    t = c["tier"]
    return "data" if t == "data" else "fast" if t <= 2 else "full"

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=""); ap.add_argument("--head", default="HEAD")
    ap.add_argument("--force-full", action="store_true"); ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    c = classify(a.base, a.head, a.force_full); c["mode"] = decide(c)
    if a.json: print(json.dumps(c)); sys.exit(0)
    print(f"{NAMES.get(c['tier'], 'Data only')} → {c['mode']}")
    for r in c["reasons"]: print("  ", r)
    if c["suites"]: print("   targeted suites:", ", ".join(c["suites"]))
