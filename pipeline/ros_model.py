"""Rest-of-season projected points per game (ROS PPG) and the next-4-weeks outlook, built on the site's stats files.

The projection is a stat line, not a points average (Alan, Oct 14): projected opportunity × projected efficiency
+ TD expectation, per game, then scored with the league's own scoring. Five signals:

1. Current-season role: his per-game opportunities (pass attempts, carries, targets, red-zone carries and targets),
   averaged with a recency weight (half-life HALF_LIFE games), an injury-shortened game scaled up to a full game by
   snap share ÷ usual snap share and weighted by that fraction (a half game is half a game of evidence).
2. Historical prior: his previous season's per-game opportunities and his pooled efficiency, blended with this season
   by games of evidence (prior weight K_PRIOR games: it dominates early and fades as the season develops); a player
   with no previous season is shrunk toward the position's regular-starter average instead (K_NOPRIOR games).
3. Efficiency: yards, catches, TDs and interceptions per opportunity, his own counts (this season + PRIOR_EFF_W × last
   season) shrunk toward the position's league rate by K_EFF pseudo-opportunities, applied at EFF_W strength; TD rates
   are split red zone / outside the red zone so red-zone work counts directly.
4. Betting market, team level: implied points for his team in the remaining games vs the games he played
   (team_ratings.py: posted spreads and totals where they exist, fitted ratings elsewhere) ^ ENV_EL. Player props
   (data/props/<season>.json, not produced yet: it needs a keyed odds feed) are not used until that file exists.
5. Remaining schedule: what his remaining opponents allow his position per game vs average, shrunk by sample, ^ SCHED_EL.

Next 4 = the same role and efficiency with the environment and schedule of only his next four games (NEXT_N).
`project(stats, games, cutoff, prior_stats, params)` works for any season and cutoff week, so ros_backtest.py can
score it against what actually happened; project_players.py runs it on the current season.
"""
import json, os, math
import numpy as np, pandas as pd
import team_ratings as tr

HERE = os.path.dirname(os.path.abspath(__file__))
POS = ["QB", "RB", "WR", "TE"]
LAST_WEEK = 17
NEXT_N = 4
OPPS = ["pass_att", "rush_att", "rec_tgt", "rz_rush", "rz_tgt"]
STATS = ["pass_att", "pass_cmp", "pass_sack", "pass_yd", "pass_td", "pass_int", "rush_att", "rush_yd", "rush_td", "rec_tgt", "rec", "rec_yd", "rec_td",
         "fum_lost", "rz_rush", "rz_tgt"]
# efficiency rates: (name, numerator, denominator); TD rates split by red zone
RATES = [("cmp", "pass_cmp", "pass_att"), ("sack", "pass_sack", "pass_att"), ("pyd", "pass_yd", "pass_att"), ("ptd", "pass_td", "pass_att"), ("pint", "pass_int", "pass_att"),
         ("ryd", "rush_yd", "rush_att"), ("rtd_rz", "rush_td_rz", "rz_rush"), ("rtd_out", "rush_td_out", "rush_out"),
         ("catch", "rec", "rec_tgt"), ("recyd", "rec_yd", "rec_tgt"), ("rectd_rz", "rec_td_rz", "rz_tgt"), ("rectd_out", "rec_td_out", "tgt_out"),
         ("fum", "fum_lost", "touch")]

# Set by pipeline/ros_backtest.py (Oct 14; numbers in CLAUDE.md §8). ENV_EL is 0 for the rest-of-season number: the
# ratings-fitted environment term costs 0.05 PPG of MAE in the leak-free backtest. The next-4 outlook keeps environment
# and schedule at ENV4_EL / SCHED4_EL: posted lines exist for the coming weeks and that horizon is what they're for.
PARAMS = dict(HALF_LIFE=20.0, K_PRIOR=2.0, K_NOPRIOR=1.0, MIN_PRIOR_G=4, PRIOR_EFF_W=0.5, K_EFF=30.0, EFF_W=0.75,
              ENV_EL=0.0, SCHED_EL=0.25, ENV4_EL=0.5, SCHED4_EL=0.25, PRIOR_GAMES=0.0, SHORT_MIN_F=0.15)
# The market environment (implied team totals) and the matchup (defense vs position) are separate factors everywhere
# (env / sched, env4 / sched4, env1 / sched1), never one blended "environment": eval_projections.py scores each on its own.

def scoring():
    return json.load(open(os.path.join(HERE, "..", "data", "curve_components.json")))["base_scoring"]

def replacement():
    return json.load(open(os.path.join(HERE, "curves.json")))["replacement"]

def load_stats(path):
    return json.load(open(path))

def game_points(r, pos, sc):
    """Fantasy points of one stat line (dict by column; missing columns count 0), site scoring."""
    g = lambda k: r.get(k, 0) or 0
    te = sc.get("bonus_rec_te", 0) if pos == "TE" else 0
    return (sc["pass_yd"] * g("pass_yd") + sc["pass_td"] * g("pass_td") + sc["pass_int"] * g("pass_int") + sc["pass_2pt"] * g("pass_2pt")
            + sc["rush_yd"] * g("rush_yd") + sc["rush_td"] * g("rush_td") + sc["rush_2pt"] * g("rush_2pt")
            + (sc["rec"] + te) * g("rec") + sc["rec_yd"] * g("rec_yd") + sc["rec_td"] * g("rec_td") + sc["rec_2pt"] * g("rec_2pt")
            + sc["fum_lost"] * g("fum_lost"))

def frame(stats, sc):
    """One row per player-game: id, name, pos, week, team, opp, the stat columns, snap, pts, f (game fraction)
    and the red-zone TD split (a red-zone carry/target that scored counts as a red-zone TD, capped by the TDs)."""
    cols = stats["cols"]; short = stats.get("short", {})
    rows = []
    for sid, p in stats["players"].items():
        if p["p"] not in POS: continue
        sh = {g[0]: g for g in short.get(sid, [])}
        for g in p["g"]:
            r = dict(zip(cols, g))
            f = 1.0
            if r["w"] in sh:
                s = sh[r["w"]]
                f = (s[1] / s[2]) if s[2] else 0.5
                f = min(1.0, max(PARAMS["SHORT_MIN_F"], f))
            row = dict(id=sid, name=p["n"], pos=p["p"], week=r["w"], team=r["tm"], opp=r["opp"], snap=r["snap"] or 0, f=f,
                       pts=game_points(r, p["p"], sc), **{k: (r.get(k) or 0) for k in STATS})
            # TDs scored from the red zone can't be told apart in the data; attribute TDs to red-zone opportunities first
            row["rush_td_rz"] = min(row["rush_td"], row["rz_rush"]); row["rush_td_out"] = row["rush_td"] - row["rush_td_rz"]
            row["rush_out"] = row["rush_att"] - row["rz_rush"]
            row["rec_td_rz"] = min(row["rec_td"], row["rz_tgt"]); row["rec_td_out"] = row["rec_td"] - row["rec_td_rz"]
            row["tgt_out"] = row["rec_tgt"] - row["rz_tgt"]
            row["touch"] = row["rush_att"] + row["rec"]
            rows.append(row)
    d = pd.DataFrame(rows)
    return d[d.week <= LAST_WEEK]

def league_rates(frames):
    """Position league rates for every efficiency rate (full games only) and the regular-starter opportunity averages."""
    d = pd.concat(frames); d = d[d.f >= 1]
    out = {}
    for pos in POS:
        s = d[d.pos == pos]
        rates = {name: (s[num].sum() / s[den].sum() if s[den].sum() > 0 else 0.0) for name, num, den in RATES}
        reg = s[s.snap >= 0.5]   # regulars: the shrink target for players without a previous season
        rates["opps"] = {o: (reg[o].sum() / len(reg) if len(reg) else 0.0) for o in OPPS}
        out[pos] = rates
    return out

def team_env(games, season, cutoff, use_future_lines):
    g = games[(games.season == season) & (games.game_type == "REG")].copy()
    g["played"] = g.week <= cutoff
    ratings = tr.fit_ratings(tr.implied_rows(g[g.played]))
    if not use_future_lines:
        g.loc[~g.played, ["spread_line", "total_line"]] = np.nan
    tg = tr.team_game_totals(g.assign(home_score=np.where(g.played, 1.0, np.nan)), ratings)
    tg["played"] = tg.week <= cutoff
    past_imp = {(r.week, r.team): r.implied for r in tg[tg.played].itertuples()}
    fut = tg[(~tg.played) & (tg.week <= LAST_WEEK)].sort_values("week")
    future = {t: [(r.week, r.opp, r.implied) for r in d.itertuples()] for t, d in fut.groupby("team")}
    return past_imp, future

def defense_vs_pos(d, cutoff, shrink_games=4.0):
    past = d[d.week <= cutoff]
    tot = past.groupby(["opp", "pos", "week"]).pts.sum().reset_index()
    out = {}
    for pos in POS:
        t = tot[tot.pos == pos]; avg = t.pts.mean()
        for opp, s in t.groupby("opp"):
            out[(opp, pos)] = (s.pts.sum() + shrink_games * avg) / ((len(s) + shrink_games) * avg) if avg else 1.0
    return out

def ros_weights(future):
    """Playoff weeks count 1.5x in rest-of-season averages, as team_ratings does."""
    return [tr.PLAYOFF_WEIGHT if w in tr.PLAYOFF_WEEKS else 1.0 for w, _, _ in future]

def injury_status(stats):
    """Sleeper ID -> game status from the latest injury report in the stats file (Out / Doubtful / Questionable), if any."""
    inj = stats.get("injuries"); out = {}
    if not inj or "cols" not in inj: return out
    ci = {c: i for i, c in enumerate(inj["cols"])}
    for rows in (inj.get("teams") or {}).values():
        for r in rows:
            sid, st = r[ci["sid"]], r[ci["status"]]
            if sid and st: out[str(sid)] = st
    return out

def confidence(g_full, prior_g, opp_cv, last_short, status, props=False):
    """Projection confidence 0-1 (Alan, Oct 15): healthy games this season, the strength of the prior, how stable his
    role has been (coefficient of variation of his per-game opportunities), injury uncertainty (an injury-shortened game
    in his last two, or a game-status designation), and whether props agree (reserved until a props feed exists).
    Informs the card's label only; it never touches AM rank."""
    sample = min(1.0, g_full / 6.0)
    prior = min(1.0, prior_g / 12.0)
    stable = max(0.0, 1.0 - opp_cv / 0.6) if opp_cv is not None else 0.5
    health = 1.0
    if last_short: health -= 0.4
    if status in ("Out", "IR", "Doubtful"): health -= 0.6
    elif status == "Questionable": health -= 0.3
    health = max(0.0, health)
    c = 0.35 * sample + 0.2 * prior + 0.25 * stable + 0.2 * health
    return round(min(1.0, c + (0.1 if props else 0.0)), 3)

def prepare(stats, games, cutoff, prior_stats=None, rates=None, use_future_lines=False, sc=None, repl=None):
    """Everything a projection needs that doesn't depend on the tunable parameters."""
    sc = sc or scoring(); repl = repl or replacement()
    status = injury_status(stats) if cutoff >= stats.get("through_week", cutoff) else {}
    d = frame(stats, sc)
    pr = frame(prior_stats, sc) if prior_stats else None
    rates = rates or league_rates([d] + ([pr] if pr is not None else []))
    past_imp, future = team_env(games, stats["season"], cutoff, use_future_lines)
    dvp = defense_vs_pos(d, cutoff)
    d = d[d.week <= cutoff].copy()
    prior = {}
    if pr is not None:
        for sid, s in pr[pr.f >= 1].groupby("id"):
            prior[sid] = dict(g=len(s), opps={o: s[o].mean() for o in OPPS},
                              counts={name: (s[num].sum(), s[den].sum()) for name, num, den in RATES})
    groups = []
    for (sid, name, pos), s in d.groupby(["id", "name", "pos"], sort=False):
        s = s.sort_values("week")
        pi = [past_imp.get((wk, tm)) for wk, tm in zip(s.week, s.team)]; pi = [v for v in pi if v is not None]
        team = s.team.iloc[-1]
        fut = future.get(team, [])
        groups.append(dict(sid=sid, name=name, pos=pos, team=team, week=s.week.to_numpy(float), f=s.f.to_numpy(),
                           pts=s.pts.to_numpy(), opps={o: s[o].to_numpy(float) for o in OPPS},
                           counts={name: (s.loc[s.f >= 1, num].sum(), s.loc[s.f >= 1, den].sum()) for name, num, den in RATES},
                           past_imp=np.mean(pi) if pi else None, prior=prior.get(sid), status=status.get(sid),
                           fut_imp=[v for _, _, v in fut], fut_w=ros_weights(fut), fut_sched=[dvp.get((o, pos), 1.0) for _, o, _ in fut]))
    return dict(groups=groups, repl=repl, rates=rates, sc=sc)

def project_from(ctx, params=PARAMS):
    repl, rates, sc = ctx["repl"], ctx["rates"], ctx["sc"]
    lam = math.log(2) / params["HALF_LIFE"]
    rows = []
    for g in ctx["groups"]:
        pos = g["pos"]; f = g["f"]; lg = rates[pos]
        rec = np.exp(-lam * (g["week"].max() - g["week"])); w = rec * f
        g_eff = float(f.sum()); full = f >= 1
        ppg = g["pts"].mean(); hppg = g["pts"][full].mean() if full.any() else ppg
        # 1-2. role: current per-full-game opportunities blended with the prior by games of evidence
        cur = {o: float(np.sum(g["opps"][o] / f * w) / w.sum()) for o in OPPS}
        pr = g["prior"]
        if pr and pr["g"] >= params["MIN_PRIOR_G"]:
            kp, base = params["K_PRIOR"], pr["opps"]
        else:
            kp, base = params["K_NOPRIOR"], lg["opps"]
        opp = {o: (g_eff * cur[o] + kp * base[o]) / (g_eff + kp) for o in OPPS}
        opp["rz_rush"] = min(opp["rz_rush"], opp["rush_att"]); opp["rz_tgt"] = min(opp["rz_tgt"], opp["rec_tgt"])
        # 3. efficiency: own counts (this season + prior season at PRIOR_EFF_W) shrunk to the league rate, applied at EFF_W
        rate = {}
        for name, _, _ in RATES:
            num, den = g["counts"][name]
            if pr: num += params["PRIOR_EFF_W"] * pr["counts"][name][0]; den += params["PRIOR_EFF_W"] * pr["counts"][name][1]
            r_lg = lg[name]
            r = (num + params["K_EFF"] * r_lg) / (den + params["K_EFF"]) if den + params["K_EFF"] > 0 else r_lg
            rate[name] = r_lg * (r / r_lg) ** params["EFF_W"] if r_lg > 0 else 0.0
        rate["fum"] = lg["fum"]
        line = dict(pass_att=opp["pass_att"], pass_cmp=opp["pass_att"] * rate["cmp"], pass_sack=opp["pass_att"] * rate["sack"], pass_yd=opp["pass_att"] * rate["pyd"], pass_td=opp["pass_att"] * rate["ptd"],
                    pass_int=opp["pass_att"] * rate["pint"], rush_att=opp["rush_att"], rush_yd=opp["rush_att"] * rate["ryd"],
                    rush_td=opp["rz_rush"] * rate["rtd_rz"] + (opp["rush_att"] - opp["rz_rush"]) * rate["rtd_out"],
                    rec_tgt=opp["rec_tgt"], rec=opp["rec_tgt"] * rate["catch"], rec_yd=opp["rec_tgt"] * rate["recyd"],
                    rec_td=opp["rz_tgt"] * rate["rectd_rz"] + (opp["rec_tgt"] - opp["rz_tgt"]) * rate["rectd_out"])
        line["fum_lost"] = (line["rush_att"] + line["rec"]) * rate["fum"]
        base_pts = game_points(line, pos, sc)
        if params["PRIOR_GAMES"]:
            pg = params["PRIOR_GAMES"]; base_pts = (g_eff * base_pts + pg * repl[pos]) / (g_eff + pg)
        # 4-5. environment and schedule, rest of season and the next NEXT_N games
        def ctx_factors(n, e_el, s_el):
            imp, wts, sch = g["fut_imp"][:n], g["fut_w"][:n], g["fut_sched"][:n]
            env = (np.average(imp, weights=wts) / g["past_imp"]) ** e_el if imp and g["past_imp"] else 1.0
            sched = (np.average(sch, weights=wts) ** s_el) if sch else 1.0
            return env, sched
        env, sched = ctx_factors(None, params["ENV_EL"], params["SCHED_EL"]); env4, sched4 = ctx_factors(NEXT_N, params["ENV4_EL"], params["SCHED4_EL"])
        env1, sched1 = ctx_factors(1, params["ENV4_EL"], params["SCHED4_EL"])
        proj = base_pts * env * sched
        # confidence: healthy games, prior, role stability (CV of per-game opportunity volume over full games), injury signals
        vol = sum(g["opps"][o] for o in ("pass_att", "rush_att", "rec_tgt"))[full]
        cv = (vol.std() / vol.mean()) if len(vol) >= 2 and vol.mean() > 0 else None
        last_short = bool(len(f) and (f[-2:] < 1).any())
        conf = confidence(int(full.sum()), pr["g"] if pr else 0, cv, last_short, g["status"])
        rows.append(dict(sleeper_id=g["sid"], player=g["name"], pos=pos, team=g["team"], games=len(f), g_eff=round(g_eff, 2),
                         ppg=ppg, healthy_ppg=hppg, prior_g=(pr["g"] if pr else 0), base_ppg=base_pts, env=env, sched=sched,
                         env4=env4, sched4=sched4, env1=env1, sched1=sched1, proj_ppg=proj, n4_ppg=base_pts * env4 * sched4,
                         n1_ppg=base_pts * env1 * sched1, conf=conf,
                         rank_score=(g_eff * proj + 2 * repl[pos]) / (g_eff + 2), line={k: round(v, 3) for k, v in line.items()}))
    out = pd.DataFrame(rows)
    out["proj_rank"] = out.groupby("pos").rank_score.rank(ascending=False, method="first").astype(int)
    return out

def project(stats, games, cutoff, prior_stats=None, params=PARAMS, rates=None, use_future_lines=False, sc=None):
    return project_from(prepare(stats, games, cutoff, prior_stats, rates, use_future_lines, sc), params)
