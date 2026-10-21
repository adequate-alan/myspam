"""Rest-of-season projected points per game (ROS PPG) and the next-4-weeks outlook, built on the site's stats files.

The projection is a stat line, not a points average (Alan, Oct 14): projected opportunity × projected efficiency
+ TD expectation, per game, then scored with the league's own scoring. Five signals:

1. Current-season role: his per-game opportunities (pass attempts, carries, targets, red-zone carries and targets),
   averaged with a recency weight (half-life HALF_LIFE games), an injury-shortened game scaled up to a full game by
   snap share ÷ usual snap share and weighted by that fraction (a half game is half a game of evidence).
2. Historical prior: his previous season's per-game opportunities, blended with this season by games of evidence. Since
   Oct 13 (prior_weights) the weight is estimated per position and stat from two complete seasons instead of one
   K_PRIOR for everything: last season regressed toward what such a role becomes a year later (a + b x last season,
   x lvl on a new team), worth K = sigma2 / tau2 games (per-game noise over season-to-season change; K / move on a
   new team). A player with no previous season is shrunk toward the position's regular-starter average (K_NOPRIOR).
   Efficiency keeps its own, slower prior (signal 3: last season's attempts at PRIOR_EFF_W, never faded by games).
3. Efficiency: yards, catches, TDs and interceptions per opportunity, his own counts (this season + PRIOR_EFF_W × last
   season) shrunk toward the position's league rate by K_EFF pseudo-opportunities, applied at EFF_W strength; TD rates
   are split red zone / outside the red zone so red-zone work counts directly.
4. Betting market, team level: implied points for his team in the remaining games vs the games he played
   (team_ratings.py: posted spreads and totals where they exist, fitted ratings elsewhere) ^ ENV_EL. Player props
   (data/props/<season>.json, not produced yet: it needs a keyed odds feed) are not used until that file exists.
5. Remaining schedule: what his remaining opponents allow his position per game vs average, shrunk by sample, ^ SCHED_EL.

Next 4 = the same role and efficiency over his next four games (NEXT_N), without the market or matchup factor (Oct 21
audit: both added error), and with a faster-updating line after a snap-share jump (ROLE_JUMP). Next game = the line
with that game's market and matchup factors (ENV1_EL / SCHED1_EL); it is the site's weekly projection since Oct 21.
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
# ratings-fitted environment term costs 0.05 PPG of MAE in the leak-free backtest.
QB_START_SNAP = 0.5   # a quarterback game under half the snaps that wasn't cut short by injury is a relief appearance
PARAMS = dict(HALF_LIFE=20.0, K_PRIOR=None, K_PRIOR_FALLBACK=2.0, K_NOPRIOR=1.0, MIN_PRIOR_G=4, PRIOR_EFF_W=0.5, K_EFF=30.0, EFF_W=0.75,
              ENV_EL=0.0, SCHED_EL=0.25, ENV4_EL=0.0, SCHED4_EL=0.0, ENV1_EL=0.5, SCHED1_EL=0.25, PRIOR_GAMES=0.0, SHORT_MIN_F=0.15,
              ROLE_JUMP=0.15, ROLE_HALF_LIFE=3.0, ROLE_K_SCALE=0.5)
# Per horizon (Oct 21 projection audit, reports/projection-audit-2026-10-21/ in the project files; Alan's approval): the next
# game keeps the market at 0.5 and the matchup at 0.25 (ENV1_EL / SCHED1_EL, the values the Oct 14 model used for it); Next 4
# has neither (ENV4_EL / SCHED4_EL 0): both added error to Next 4 on 2024-25 and on held-out 2023 and 2026.
# LEGACY_N4 reproduces the Next 4 before Oct 21 (eval_projections.py keeps it as a comparison baseline).
LEGACY_N4 = dict(ENV4_EL=0.5, SCHED4_EL=0.25, ROLE_JUMP=None)
# The market environment (implied team totals) and the matchup (defense vs position) are separate factors everywhere
# (env / sched, env4 / sched4, env1 / sched1), never one blended "environment": eval_projections.py scores each on its own.

# Prior weights for opportunity (Oct 13, Kenneth Walker audit): how many games of evidence last season's per-game
# opportunities are worth, per position and stat, estimated from the data instead of one global K_PRIOR. Empirical Bayes:
# a player's true per-game opportunity this season = last season's + a season-to-season change with variance tau2; his
# per-game counts scatter around it with variance sigma2. The best estimate weighs last season like K = sigma2 / tau2 games.
# Both come from the two latest complete seasons (players with MIN_G+ full games in both); a player who changed teams
# has a larger tau2 (a structural break the data can see), pooled across positions as one factor (MOVE).
KW_MIN_G = 6
KW_BOUNDS = (0.25, 8.0)   # last season is worth at most 8 games: the larger estimates (QB pass attempts ~40) rest on
                          # ~30 quarterbacks and made projections worse when fitted on half the players and scored on the other
KW_PARENT = {"rz_rush": "rush_att", "rz_tgt": "rec_tgt"}   # red-zone work follows the role; its own counts are too sparse
KW_MAIN = {"QB": ["pass_att", "rush_att"], "RB": ["rush_att", "rec_tgt"], "WR": ["rec_tgt"], "TE": ["rec_tgt"]}
# positions that keep the weighting from before Oct 13 (last season at face value, K_PRIOR_FALLBACK games, no team-change
# factor). Alan, Oct 13: TEs stay on it for now. With an unbiased TE workload the backtest showed TE PPG under-projected
# (-1.3): an efficiency bias the old workload over-projection had been hiding, to be investigated on its own before
# TE workload weighting changes (reports/ros-prior-weighting/te-efficiency-followup.md in the project files).
KW_OLD_POS = frozenset({"TE"})

def prior_weights(prev, cur):
    """Empirical-Bayes prior for each position and opportunity stat, from two complete seasons' frames (frame()):
    this season's per-game opportunity ~ a + b x last season's (b < 1: roles regress toward the position, and a player
    who changed teams keeps `lvl` of that on average), with what that misses having variance tau2; his per-game counts
    scatter around his true rate with variance sigma2, so last season is worth K = sigma2 / tau2 games of evidence
    (tau2 x `move` for a player on a new team, so K / move).
    -> {"a", "b", "K": {pos: {stat: ...}}, "move", "lvl", "n"}"""
    def summ(d):
        d = d[d.f >= 1]; g = d.groupby("id")
        return g[OPPS].mean(), g[OPPS].var(ddof=1), g.size(), g.team.agg(lambda s: s.iloc[-1]), g.pos.first()
    a0, v0, n0, t0, _ = summ(prev); a1, v1, n1, t1, p1 = summ(cur)
    ids = [i for i in a0.index.intersection(a1.index) if n0[i] >= KW_MIN_G and n1[i] >= KW_MIN_G]
    moved = {i: t0[i] != t1[i] for i in ids}
    A, B, K, tau, res = {}, {}, {}, {}, {}
    for pos in POS:
        P = [i for i in ids if p1[i] == pos]; S = [i for i in P if not moved[i]]
        A[pos], B[pos], K[pos] = {}, {}, {}
        for o in OPPS:
            x, y = a0.loc[S, o].to_numpy(float), a1.loc[S, o].to_numpy(float)
            if len(S) >= 8 and x.var() > 1e-6:
                b = float(np.clip(np.cov(x, y, bias=True)[0, 1] / x.var(), 0.0, 1.0)); a = float(y.mean() - b * x.mean())
            else:
                a, b = 0.0, 1.0
            A[pos][o], B[pos][o] = a, b
            r = (a1.loc[P, o] - (a + b * a0.loc[P, o]))
            # sampling noise of this season's mean, plus last season's carried through b
            noise = v1.loc[P, o] / n1[P] + b * b * v0.loc[P, o] / n0[P]
            s2 = float(pd.concat([v0.loc[P, o], v1.loc[P, o]]).mean()) if P else 0.0
            tau[(pos, o)] = max(float((r[S] ** 2 - noise[S]).mean()) if S else 0.0, 1e-9)
            K[pos][o] = float(np.clip(s2 / tau[(pos, o)], *KW_BOUNDS)) if s2 > 0 else KW_BOUNDS[1]
            res[(pos, o)] = (r, noise, [i for i in P if moved[i]])
    for pos in POS:
        for o, par in KW_PARENT.items(): K[pos][o] = K[pos][par]
    # a new team: the level he keeps (actual / predicted, main stats pooled) and how much more his role can move (tau2)
    num = den = yy = pp = 0.0
    for pos in POS:
        for o in KW_MAIN[pos]:
            r, noise, M = res[(pos, o)]
            if not M: continue
            pred = A[pos][o] + B[pos][o] * a0.loc[M, o]
            yy += float(a1.loc[M, o].sum()); pp += float(pred.sum())
            num += float((r[M] ** 2 - noise[M]).sum()); den += tau[(pos, o)] * len(M)
    lvl = float(np.clip(yy / pp, 0.7, 1.0)) if pp > 0 else 1.0
    move = float(np.clip(num / den, 1.0, 6.0)) if den > 0 else 1.0
    return dict(a=A, b=B, K=K, move=move, lvl=lvl, n=dict(players=len(ids), moved=int(sum(moved.values()))))

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
            # role fraction (Oct 12): a quarterback's relief or garbage-time appearance (under half the snaps, not already
            # an injury-shortened game) is that share of a game of evidence for his per-start volume, not a full start
            # with a starter's workload missing; other positions share the field, so their snaps are their role
            rf = f
            if p["p"] == "QB" and f >= 1 and (r["snap"] or 0) < QB_START_SNAP and r["snap"] is not None:
                rf = min(1.0, max(PARAMS["SHORT_MIN_F"], r["snap"]))
            row = dict(id=sid, name=p["n"], pos=p["p"], week=r["w"], team=r["tm"], opp=r["opp"], snap=r["snap"] or 0, f=f, rf=rf,
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
        rates["reg_snap"] = float(reg.snap.mean()) if len(reg) else 1.0
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

def confidence(g_full, prior_g, opp_cv, last_short, status, props=False, prior_info=1.0):
    """Projection confidence 0-1 (Alan, Oct 15): healthy games this season, the strength of the prior, how stable his
    role has been (coefficient of variation of his per-game opportunities), injury uncertainty (an injury-shortened game
    in his last two, or a game-status designation), and whether props agree (reserved until a props feed exists).
    `prior_info` (Oct 13) scales the prior's credit by how informative it is: 1 / move for a player on a new team.
    Informs the card's label only; it never touches AM rank."""
    sample = min(1.0, g_full / 6.0)
    prior = min(1.0, prior_g / 12.0) * prior_info   # a previous season on another team says less (prior_weights: tau2 x move)
    stable = max(0.0, 1.0 - opp_cv / 0.6) if opp_cv is not None else 0.5
    health = 1.0
    if last_short: health -= 0.4
    if status in ("Out", "IR", "Doubtful"): health -= 0.6
    elif status == "Questionable": health -= 0.3
    health = max(0.0, health)
    c = 0.35 * sample + 0.2 * prior + 0.25 * stable + 0.2 * health
    return round(min(1.0, c + (0.1 if props else 0.0)), 3)

def prepare(stats, games, cutoff, prior_stats=None, rates=None, use_future_lines=False, sc=None, repl=None, kw=None):
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
            prior[sid] = dict(g=len(s), opps={o: s[o].mean() for o in OPPS}, team=s.sort_values("week").team.iloc[-1],
                              counts={name: (s[num].sum(), s[den].sum()) for name, num, den in RATES})
    groups = []
    for (sid, name, pos), s in d.groupby(["id", "name", "pos"], sort=False):
        s = s.sort_values("week")
        pi = [past_imp.get((wk, tm)) for wk, tm in zip(s.week, s.team)]; pi = [v for v in pi if v is not None]
        team = s.team.iloc[-1]
        fut = future.get(team, [])
        groups.append(dict(sid=sid, name=name, pos=pos, team=team, week=s.week.to_numpy(float), f=s.f.to_numpy(), rf=s.rf.to_numpy(),
                           snap=(s.snap / s.f).clip(upper=1.0).to_numpy(),
                           pts=s.pts.to_numpy(), opps={o: s[o].to_numpy(float) for o in OPPS},
                           counts={name: (s.loc[s.f >= 1, num].sum(), s.loc[s.f >= 1, den].sum()) for name, num, den in RATES},
                           past_imp=np.mean(pi) if pi else None, prior=prior.get(sid), status=status.get(sid),
                           wk1=(int(fut[0][0]) if fut else None), fut_imp=[v for _, _, v in fut], fut_w=ros_weights(fut), fut_sched=[dvp.get((o, pos), 1.0) for _, o, _ in fut]))
    return dict(groups=groups, repl=repl, rates=rates, sc=sc, kw=kw)

def snap_jump(g):
    """Role-change signal (Oct 21 audit): his snap share over his last two games minus his earlier games' average this
    season (full-game equivalents); 0 with fewer than three games."""
    s = g["snap"]
    return float(np.mean(s[-2:]) - np.mean(s[:-2])) if len(s) >= 3 else 0.0

def project_from(ctx, params=PARAMS):
    repl, rates, sc = ctx["repl"], ctx["rates"], ctx["sc"]
    rows = []
    for g in ctx["groups"]:
        pos = g["pos"]; f = g["f"]; rf = g["rf"]; lg = rates[pos]
        g_eff = float(rf.sum()); full = f >= 1
        ppg = g["pts"].mean(); hppg = g["pts"][full].mean() if full.any() else ppg
        pr = g["prior"]
        # fitted weights (prior_weights) unless K_PRIOR forces one weight, none were fitted, or his position keeps the old
        # weighting (KW_OLD_POS); `moved` = a team change that made last season count less (always False on the old path)
        use_kw = params.get("K_PRIOR") is None and bool(ctx.get("kw")) and pos not in params.get("KW_OLD_POS", KW_OLD_POS)
        moved = bool(use_kw and pr and pr.get("team") and pr["team"] != g["team"])

        def role_line(half_life, k_scale):
            """The projected per-game stat line from his role (recency half-life, prior weight x k_scale) and efficiency."""
            rec = np.exp(-math.log(2) / half_life * (g["week"].max() - g["week"])); w = rec * rf
            # 1-2. role: current per-full-game opportunities blended with the prior by games of evidence
            cur = {o: float(np.sum(g["opps"][o] / rf * w) / w.sum()) for o in OPPS}
            if pr and pr["g"] >= params["MIN_PRIOR_G"]:
                base = pr["opps"]
                if use_kw and params.get("PRIOR_REGRESS", True):
                    kw = ctx["kw"]   # last season regressed toward what such a role becomes a year later (prior_weights)
                    base = {o: (kw["a"][pos][o] + kw["b"][pos][o] * base[o]) * (kw["lvl"] if moved else 1.0) for o in OPPS}
                if not use_kw:   # one weight for every stat (the model before Oct 13)
                    kp = {o: params["K_PRIOR"] if params.get("K_PRIOR") is not None else params["K_PRIOR_FALLBACK"] for o in OPPS}
                else:   # per position and stat, and lighter for a player on a new team (prior_weights)
                    kw = ctx["kw"]; kp = {o: kw["K"][pos][o] / (kw["move"] if moved else 1.0) for o in OPPS}
                kp = {o: v * k_scale for o, v in kp.items()}
            else:
                # no usable previous season: shrink toward the position's regulars, scaled by his own share of the snaps for
                # RB / WR / TE (Oct 12: a backup on 4% of the snaps was pulled halfway to a starter's workload); a quarterback's
                # per-start volume is a starter's by definition, so his target stays the regulars' (the role layer, roles.py,
                # decides whether he starts)
                sn = float(np.sum(g["snap"] * rec) / rec.sum())
                role = 1.0 if pos == "QB" or sn <= 0 else min(1.0, sn / lg.get("reg_snap", 1.0))   # no snap data: no scaling
                kp, base = {o: params["K_NOPRIOR"] for o in OPPS}, {o: lg["opps"][o] * role for o in OPPS}
            opp = {o: (g_eff * cur[o] + kp[o] * base[o]) / (g_eff + kp[o]) for o in OPPS}
            # transparency: the share of his projected main opportunity (KW_MAIN) that comes from this season's games
            mo = [o for o in KW_MAIN[pos] if opp[o] > 0]
            cur_share = (sum(g_eff * cur[o] / (g_eff + kp[o]) for o in mo) / sum(opp[o] for o in mo)) if mo else 1.0
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
            pts = game_points(line, pos, sc)
            if params["PRIOR_GAMES"]:
                pg = params["PRIOR_GAMES"]; pts = (g_eff * pts + pg * repl[pos]) / (g_eff + pg)
            return line, pts, cur_share

        line, base_pts, cur_share = role_line(params["HALF_LIFE"], 1.0)
        # Next 4 role change (Oct 21 audit, Alan's approval): a snap-share jump of ROLE_JUMP or more over his last two games
        # is a role the model was slow to accept (under-projected 1-3 PPG in 2023-26), so his Next 4 line updates faster:
        # recency half-life ROLE_HALF_LIFE and last season's weight x ROLE_K_SCALE. ROS and the next game are unchanged.
        role_change = pos != "QB" and params.get("ROLE_JUMP") is not None and snap_jump(g) >= params["ROLE_JUMP"]
        line4, base4 = (role_line(params["ROLE_HALF_LIFE"], params["ROLE_K_SCALE"])[:2] if role_change else (line, base_pts))
        # 4-5. environment and schedule, per horizon: rest of season (ENV_EL / SCHED_EL), the next NEXT_N games
        # (ENV4_EL / SCHED4_EL) and the next game (ENV1_EL / SCHED1_EL); market and matchup always separate factors
        def ctx_factors(n, e_el, s_el):
            imp, wts, sch = g["fut_imp"][:n], g["fut_w"][:n], g["fut_sched"][:n]
            env = (np.average(imp, weights=wts) / g["past_imp"]) ** e_el if imp and g["past_imp"] else 1.0
            sched = (np.average(sch, weights=wts) ** s_el) if sch else 1.0
            return env, sched
        env, sched = ctx_factors(None, params["ENV_EL"], params["SCHED_EL"]); env4, sched4 = ctx_factors(NEXT_N, params["ENV4_EL"], params["SCHED4_EL"])
        env1, sched1 = ctx_factors(1, params["ENV1_EL"], params["SCHED1_EL"])
        env4_raw, sched4_raw = ctx_factors(NEXT_N, 1.0, 1.0)   # unweighted factors, stored with each forecast so the
        # Next 4 before Oct 21 (LEGACY_N4: env4_raw^0.5 x sched4_raw^0.25 on the ROS line) stays scoreable as a baseline
        proj = base_pts * env * sched
        # confidence: healthy games, prior, role stability (CV of per-game opportunity volume over full games), injury signals
        vol = sum(g["opps"][o] for o in ("pass_att", "rush_att", "rec_tgt"))[full]
        cv = (vol.std() / vol.mean()) if len(vol) >= 2 and vol.mean() > 0 else None
        last_short = bool(len(f) and (f[-2:] < 1).any())
        kwi = ctx.get("kw")
        conf = confidence(int(full.sum()), pr["g"] if pr else 0, cv, last_short, g["status"],
                          prior_info=(1.0 / kwi["move"]) if moved else 1.0)
        rows.append(dict(sleeper_id=g["sid"], player=g["name"], pos=pos, team=g["team"], games=len(f), g_eff=round(g_eff, 2),
                         ppg=ppg, healthy_ppg=hppg, prior_g=(pr["g"] if pr else 0), base_ppg=base_pts, env=env, sched=sched,
                         env4=env4, sched4=sched4, env1=env1, sched1=sched1, proj_ppg=proj, n4_ppg=base4 * env4 * sched4,
                         n1_ppg=base_pts * env1 * sched1, n1_week=g.get("wk1"), env4_raw=env4_raw, sched4_raw=sched4_raw, conf=conf, cur_share=cur_share, moved=moved, role_change=role_change,
                         rank_score=(g_eff * proj + 2 * repl[pos]) / (g_eff + 2), line={k: round(v, 3) for k, v in line.items()},
                         line4=({k: round(v, 3) for k, v in line4.items()} if role_change else None)))
    out = pd.DataFrame(rows)
    out["proj_rank"] = out.groupby("pos").rank_score.rank(ascending=False, method="first").astype(int)
    return out

def project(stats, games, cutoff, prior_stats=None, params=PARAMS, rates=None, use_future_lines=False, sc=None, kw=None):
    return project_from(prepare(stats, games, cutoff, prior_stats, rates, use_future_lines, sc, kw=kw), params)
