"""Backtest for ros_model.py: project from weeks 2, 3, 4, 6, 8 and 10 of 2024 and 2025 and score against what each
player actually averaged in his healthy games over the rest of the fantasy season (weeks cutoff+1..17), against
simple baselines. League rates are fitted on the *other* season, team ratings only on games through the cutoff and
no future betting lines are used, so nothing from after the cutoff leaks in. 2025 cases have a previous season
(2024) as the prior; 2024 cases have none (the stats files start in 2024), which shows what the prior is worth.

    python3 ros_backtest.py <games.csv> [--grid]

Players scored: at least 1 game of evidence before the cutoff and 4 healthy games after it, among the fantasy-relevant
pool (top 32 QB / 50 RB / 70 WR / 24 TE by pre-cutoff healthy PPG, or by prior-season PPG at week 2-3).
Metrics: mean absolute error (PPG) and the mean within-position Spearman rank correlation.
"""
import sys, json
import numpy as np, pandas as pd
import ros_model as m

SEASONS = [2024, 2025]
CUTOFFS = [2, 3, 4, 6, 8, 10]
POOL = {"QB": 32, "RB": 50, "WR": 70, "TE": 24}

def targets(d, cutoff):
    fut = d[(d.week > cutoff) & (d.week <= m.LAST_WEEK) & (d.f >= 1)]
    t = fut.groupby("id").agg(target=("pts", "mean"), n_after=("pts", "size"))
    n4 = fut[fut.week <= cutoff + m.NEXT_N].groupby("id").agg(target4=("pts", "mean"), n4=("pts", "size"))
    return t[t.n_after >= 4].join(n4)

def baselines(d, cutoff):
    past = d[d.week <= cutoff].sort_values("week"); g = past.groupby("id")
    return pd.DataFrame({"season_ppg": g.pts.mean(), "healthy_ppg": past[past.f >= 1].groupby("id").pts.mean(),
                         "last3_ppg": g.apply(lambda s: s.pts.tail(3).mean(), include_groups=False)})

def spearman(a, b):
    return pd.Series(a).rank().corr(pd.Series(b).rank())

def score(pred, ev):
    j = ev.join(pred.rename("pred"), how="inner").dropna(subset=["pred"])
    mae = (j.pred - j.target).abs().mean()
    rho = np.mean([spearman(s.pred, s.target) for _, s in j.groupby("pos") if len(s) > 5])
    return mae, rho, len(j)

def build_cases(games_path):
    games = pd.read_csv(games_path); sc = m.scoring()
    stats = {y: m.load_stats(f"../data/stats/{y}.json") for y in SEASONS}
    frames = {y: m.frame(stats[y], sc) for y in SEASONS}
    rates = {y: m.league_rates([frames[o] for o in SEASONS if o != y]) for y in SEASONS}
    cases = []
    for y in SEASONS:
        prior = stats.get(y - 1)
        for c in CUTOFFS:
            d = frames[y]
            ctx = m.prepare(stats[y], games, c, prior_stats=prior, rates=rates[y], use_future_lines=False, sc=sc)
            ev = targets(d, c).join(baselines(d, c)).join(d.groupby("id").pos.first())
            ev = ev[ev.index.isin(set(g["sid"] for g in ctx["groups"]))]
            pool_by = ev.healthy_ppg.fillna(ev.season_ppg)
            if prior and c <= 3:   # at week 2-3 the pool is the previous season's regulars plus this season's early leaders
                pp = frames[y - 1].groupby("id").pts.mean()
                pool_by = pd.concat([pool_by, pp.reindex(ev.index)], axis=1).max(axis=1)
            ev["pool_rank"] = pool_by.groupby(ev.pos).rank(ascending=False)
            ev = ev[ev.pool_rank <= ev.pos.map(POOL)]
            cases.append((y, c, ctx, ev))
    return cases

def evaluate(cases, params, seasons=None, cutoffs=None, horizon="ros"):
    """horizon "ros": proj_ppg vs the rest-of-season healthy PPG; "n4": n4_ppg vs the healthy PPG of the next 4 weeks (3+ games)."""
    maes, rhos, ns = [], [], []
    for y, c, ctx, ev in cases:
        if (seasons and y not in seasons) or (cutoffs and c not in cutoffs): continue
        if horizon == "n4": ev = ev[ev.n4 >= 3].assign(target=lambda e: e.target4)
        out = m.project_from(ctx, params).set_index("sleeper_id")[("n4_ppg" if horizon == "n4" else "proj_ppg")]
        mae, rho, n = score(out, ev); maes.append(mae); rhos.append(rho); ns.append(n)
    return np.mean(maes), np.mean(rhos), sum(ns)

def run(games_path, grid=False):
    cases = build_cases(games_path)
    print("baselines (mean over season/cutoff cases):")
    for b in ("season_ppg", "healthy_ppg", "last3_ppg"):
        r = [score(ev[b], ev) for _, _, _, ev in cases]
        print(f"  {b:12s} MAE {np.nanmean([x[0] for x in r]):.3f}  rho {np.nanmean([x[1] for x in r]):.3f}  n {sum(x[2] for x in r)}")
    mae, rho, n = evaluate(cases, m.PARAMS)
    print(f"ros_model (PARAMS) MAE {mae:.3f}  rho {rho:.3f}  n {n}")
    for y in SEASONS:
        for c in CUTOFFS:
            mae, rho, n = evaluate(cases, m.PARAMS, [y], [c]); hb = [score(ev.healthy_ppg, ev) for yy, cc, _, ev in cases if yy == y and cc == c][0]
            print(f"  {y} week {c:2d}: n {n:3d}  model MAE {mae:.2f} rho {rho:.3f}   healthy PPG MAE {hb[0]:.2f} rho {hb[1]:.3f}")
    if grid:
        space = dict(K_PRIOR=[1, 2, 4, 8, 16], K_NOPRIOR=[0.5, 1, 2], PRIOR_EFF_W=[0, 0.5, 1.0], K_EFF=[30, 60, 120, 240],
                     EFF_W=[0.5, 0.75, 1.0], HALF_LIFE=[5, 10, 20, 100], ENV_EL=[0, 0.5, 1.0], SCHED_EL=[0, 0.25, 0.5], PRIOR_GAMES=[0, 0.5, 1])
        best = dict(m.PARAMS); best_mae = evaluate(cases, best)[0]
        for _ in range(2):
            for k, vals in space.items():
                for v in vals:
                    p = dict(best); p[k] = v
                    mae, rho, _ = evaluate(cases, p)
                    print(f"  {k}={v:<5} MAE {mae:.3f} rho {rho:.3f}")
                    if mae < best_mae - 1e-4: best_mae, best = mae, p
            print("best so far", {k: best[k] for k in space}, round(best_mae, 3))
        mae, rho, _ = evaluate(cases, best)
        print("BEST", json.dumps({k: best[k] for k in space}), f"MAE {mae:.3f} rho {rho:.3f}")
    # the next-4 outlook: its own environment / schedule strength against the healthy PPG of the next four weeks
    print("next 4 (n4_ppg vs the next 4 weeks' healthy PPG):")
    for e in (0, 0.5, 1.0):
        for sc_ in (0, 0.25, 0.5, 1.0):
            p = dict(m.PARAMS); p["ENV4_EL"] = e; p["SCHED4_EL"] = sc_
            mae, rho, n = evaluate(cases, p, horizon="n4")
            print(f"  ENV4_EL={e} SCHED4_EL={sc_}: MAE {mae:.3f} rho {rho:.3f} n {n}")
    hb = [score(ev[ev.n4 >= 3].assign(target=lambda e: e.target4).healthy_ppg, ev[ev.n4 >= 3].assign(target=lambda e: e.target4)) for _, _, _, ev in cases]
    print(f"  healthy PPG baseline: MAE {np.nanmean([x[0] for x in hb]):.3f} rho {np.nanmean([x[1] for x in hb]):.3f}")

if __name__ == "__main__":
    run(sys.argv[1], grid="--grid" in sys.argv)
