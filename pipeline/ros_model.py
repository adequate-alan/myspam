"""Rest-of-season projected points per game (ROS PPG), built on the site's own stats files.

The projection is a *role* projection, not a points average:

1. Role: each player's recent per-game opportunities (pass attempts, carries, targets, red-zone
   targets and carries, goal-line carries, air yards), from data/stats/<season>.json, averaged
   with a recency weight (half-life HALF_LIFE games, so the last 3-5 games count more but don't
   dominate). An injury-shortened game (the file's `short` flags) is scaled up to a full game by
   his snap share / usual snap share and weighted by that fraction, so a half game counts as half
   a game of evidence instead of a bad full game.
2. Opportunity values: what each kind of opportunity was worth at his position, fitted by ridge
   regression on the other seasons' player-games (points ~ opportunities) in the site's scoring.
   role xPPG = his projected opportunities x those values.
3. Efficiency: his own points per expected point over his healthy games, shrunk toward 1 by
   EFF_K pseudo-points and applied at EFF_W strength (efficiency regresses; usage persists).
4. Team environment: implied points for his team in the remaining games vs the games he played,
   from betting lines fitted to team ratings (team_ratings.py), ^ ENV_EL.
5. Schedule: what his remaining opponents allow his position per game vs league average (shrunk
   toward average by sample), ^ SCHED_EL.
6. Small samples: the role is shrunk toward the position's replacement level by PRIOR_GAMES
   games of evidence (sum of game fractions, so a half game is half a game).
A small ACT_W share of his healthy PPG is blended in when the backtest says it helps.

`project(stats, games, cutoff, params)` works for any season and cutoff week, so
ros_backtest.py can score it against what actually happened; project_players.py runs it on
the current season. Weekly points for the site are a different module (the browser's weeklyProjection).
"""
import json, os, math
import numpy as np, pandas as pd
import team_ratings as tr

HERE = os.path.dirname(os.path.abspath(__file__))
POS = ["QB", "RB", "WR", "TE"]
LAST_WEEK = 17
USAGE = ["pass_att", "rush_att", "rec_tgt", "rz_tgt", "rz_rush", "gl_rush", "air_yd"]

# Set from pipeline/ros_backtest.py on 2024-25 (Oct 14; numbers in CLAUDE.md §8). The surface is flat: the backtest's own
# optimum (no recency, no environment, no schedule, efficiency at full strength) scores MAE 3.41; these keep a mild
# recency weight, a half-strength environment term and a quarter-strength schedule term because the live run has posted
# lines for the next weeks that the leak-free backtest can't use, at a cost of about 0.02 PPG of MAE.
PARAMS = dict(HALF_LIFE=20.0, EFF_K=60.0, EFF_W=0.75, ENV_EL=0.5, SCHED_EL=0.25, PRIOR_GAMES=1.0, ACT_W=0.0,
              SHORT_MIN_F=0.15)

def scoring():
    return json.load(open(os.path.join(HERE, "..", "data", "curve_components.json")))["base_scoring"]

def replacement():
    return json.load(open(os.path.join(HERE, "curves.json")))["replacement"]

def load_stats(path):
    return json.load(open(path))

def game_points(r, pos, sc):
    """Fantasy points of one game row (dict by column), site scoring."""
    te = sc.get("bonus_rec_te", 0) if pos == "TE" else 0
    return (sc["pass_yd"] * r["pass_yd"] + sc["pass_td"] * r["pass_td"] + sc["pass_int"] * r["pass_int"]
            + sc["pass_2pt"] * r["pass_2pt"] + sc["rush_yd"] * r["rush_yd"] + sc["rush_td"] * r["rush_td"]
            + sc["rush_2pt"] * r["rush_2pt"] + (sc["rec"] + te) * r["rec"] + sc["rec_yd"] * r["rec_yd"]
            + sc["rec_td"] * r["rec_td"] + sc["rec_2pt"] * r["rec_2pt"] + sc["fum_lost"] * r["fum_lost"])

def frame(stats, sc):
    """One row per player-game: id, name, pos, week, team, opp, usage columns, snap, pts, f (game fraction)."""
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
            rows.append(dict(id=sid, name=p["n"], pos=p["p"], week=r["w"], team=r["tm"], opp=r["opp"],
                             snap=r["snap"] or 0, f=f, pts=game_points(r, p["p"], sc),
                             **{u: (r[u] or 0) for u in USAGE}))
    d = pd.DataFrame(rows)
    return d[d.week <= LAST_WEEK]

def fit_opportunity_values(frames, ridge=5.0):
    """Points per opportunity by position: ridge regression of game points on the usage columns
    over full (non-shortened) player-games with at least one opportunity."""
    d = pd.concat(frames)
    d = d[(d.f >= 1) & (d[USAGE].sum(axis=1) > 0)]
    out = {}
    for pos in POS:
        s = d[d.pos == pos]
        X = s[USAGE].to_numpy(float); y = s.pts.to_numpy(float)
        beta = np.linalg.solve(X.T @ X + ridge * np.eye(len(USAGE)), X.T @ y)
        out[pos] = dict(zip(USAGE, np.clip(beta, 0, None)))   # an opportunity is never worth negative points
    return out

def xpts(d, ov):
    """Expected points per row from its usage and the position's opportunity values."""
    return sum(d[u] * d.pos.map(lambda p, u=u: ov[p][u]) for u in USAGE)

def team_env(games, season, cutoff, use_future_lines, params):
    """Per team: implied points by week (past) and the rest-of-season implied average."""
    g = games[(games.season == season) & (games.game_type == "REG")].copy()
    g["played"] = g.week <= cutoff
    past = g[g.played]
    ratings = tr.fit_ratings(tr.implied_rows(past))
    if not use_future_lines:
        g.loc[~g.played, ["spread_line", "total_line"]] = np.nan
    tg = tr.team_game_totals(g.assign(home_score=np.where(g.played, 1.0, np.nan)), ratings)
    tg["played"] = tg.week <= cutoff
    ros = tr.rest_of_season(tg)
    past_imp = {(r.week, r.team): r.implied for r in tg[tg.played].itertuples()}
    future = {t: list(d.sort_values("week").opp) for t, d in tg[(~tg.played) & (tg.week <= LAST_WEEK)].groupby("team")}
    return past_imp, ros.ros_implied.to_dict(), future

def defense_vs_pos(d, cutoff, shrink_games=4.0):
    """Points allowed per game to each position by each defense through the cutoff, as a factor vs
    league average, shrunk toward 1 by `shrink_games` games."""
    past = d[d.week <= cutoff]
    tot = past.groupby(["opp", "pos", "week"]).pts.sum().reset_index()
    out = {}
    for pos in POS:
        t = tot[tot.pos == pos]
        avg = t.pts.mean()
        for opp, s in t.groupby("opp"):
            n = len(s)
            out[(opp, pos)] = (s.pts.sum() + shrink_games * avg) / ((n + shrink_games) * avg) if avg else 1.0
    return out

def prepare(stats, games, cutoff, ov=None, use_future_lines=False, sc=None, repl=None):
    """Everything a projection needs that doesn't depend on the tunable parameters (so the backtest
    can try many parameter sets on one prepared season/cutoff)."""
    sc = sc or scoring(); repl = repl or replacement()
    d = frame(stats, sc)
    ov = ov or fit_opportunity_values([d])
    past_imp, ros_imp, future = team_env(games, stats["season"], cutoff, use_future_lines, PARAMS)
    dvp = defense_vs_pos(d, cutoff)
    d = d[d.week <= cutoff].copy()
    d["x"] = xpts(d, ov)
    groups = []
    for (sid, name, pos), s in d.groupby(["id", "name", "pos"], sort=False):
        s = s.sort_values("week")
        pi = [past_imp.get((wk, tm)) for wk, tm in zip(s.week, s.team)]
        pi = [v for v in pi if v is not None]
        team = s.team.iloc[-1]
        groups.append(dict(sid=sid, name=name, pos=pos, team=team, week=s.week.to_numpy(float), f=s.f.to_numpy(),
                           x=s.x.to_numpy(), pts=s.pts.to_numpy(), past_imp=np.mean(pi) if pi else None,
                           ros_imp=ros_imp.get(team), sched_f=[dvp.get((o, pos), 1.0) for o in future.get(team, [])]))
    return dict(groups=groups, repl=repl, ov=ov)

def project_from(ctx, params=PARAMS):
    repl = ctx["repl"]; lam = math.log(2) / params["HALF_LIFE"]
    rows = []
    for g in ctx["groups"]:
        pos = g["pos"]; f = g["f"]; x = g["x"]; pts = g["pts"]
        rec = np.exp(-lam * (g["week"].max() - g["week"]))
        w = rec * f
        role_x = float(np.sum(x / f * w) / w.sum())             # opportunities per full game
        g_eff = float(f.sum())
        full = f >= 1
        ppg = pts.mean()
        hppg = pts[full].mean() if full.any() else ppg
        eff = ((pts[full].sum() + params["EFF_K"]) / (x[full].sum() + params["EFF_K"])) if full.any() else 1.0
        eff = min(1.3, max(0.7, eff)) ** params["EFF_W"]
        pg = params["PRIOR_GAMES"]
        base = (g_eff * role_x * eff + pg * repl[pos]) / (g_eff + pg)
        if params["ACT_W"]:
            base = (1 - params["ACT_W"]) * base + params["ACT_W"] * (g_eff * hppg + pg * repl[pos]) / (g_eff + pg)
        env = (g["ros_imp"] / g["past_imp"]) ** params["ENV_EL"] if g["past_imp"] and g["ros_imp"] else 1.0
        sched = (np.mean(g["sched_f"]) ** params["SCHED_EL"]) if g["sched_f"] else 1.0
        proj = base * env * sched
        rows.append(dict(sleeper_id=g["sid"], player=g["name"], pos=pos, team=g["team"], games=len(f), g_eff=round(g_eff, 2),
                         ppg=ppg, healthy_ppg=hppg, role_x=role_x, eff=eff, env=env, sched=sched, proj_ppg=proj,
                         rank_score=(g_eff * proj + 2 * repl[pos]) / (g_eff + 2)))
    out = pd.DataFrame(rows)
    out["proj_rank"] = out.groupby("pos").rank_score.rank(ascending=False, method="first").astype(int)
    return out

def project(stats, games, cutoff, params=PARAMS, ov=None, use_future_lines=False, sc=None, repl=None):
    """ROS projection from the games through `cutoff`: one row per player."""
    return project_from(prepare(stats, games, cutoff, ov, use_future_lines, sc, repl), params)
