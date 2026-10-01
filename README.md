# SPMetrics Fantasy Rankings

Fantasy football rankings and a trade calculator for a 12-team, full-PPR, TE-premium, superflex redraft league. Rankings by Steven ([@SPMetrics](https://github.com/stevenp36)) and Alan; player values come from a model that blends those rankings with this season's usage and betting-market team outlooks.

**Live site:** https://stevenp36.github.io/spmetrics-fantasy/

## How player values work

1. **Positional rank → points per game.** Each rank (WR1, WR2, …) maps to the average points per game that finish produced in 2023–2025 under this league's scoring (pass yd 0.04, pass TD 4, INT −2, rush/rec yd 0.1, TD 6, reception 1, TE reception +0.5, fumble lost −2). Source: [nflverse](https://github.com/nflverse/nflverse-data).
2. **Projection as a second opinion.** This season's targets, carries and pass attempts (converted to expected points), blended with actual points and scaled by each team's rest-of-season scoring outlook from betting lines. The projection re-orders the ranked players at each position; its weight grows with games played.
3. **Value over replacement.** Points above the last starter at the position (full credit) plus points between waiver level and the last starter (25% credit), with replacement and waiver levels set by the league's lineup (1QB 2RB 3WR 1TE 1FLEX 1SF, 6 bench).
4. **Rank order and tiers.** Values never break the positional ranking; players in a tier are pulled together and each tier drop costs value. Scaled so the top player is 10,000.

## Repository

| Path | What it does |
|---|---|
| `index.html` | The whole site: rankings data (`RANKINGS_CSV`), tier names, value model settings, and the page itself |
| `pipeline/build_curves.py` | Builds the points-by-finish curves and replacement/waiver levels → `curves.json` (rerun only if league settings change) |
| `pipeline/team_ratings.py` | Fits team offense/defense ratings from posted spreads and totals; projects every remaining game |
| `pipeline/project_players.py` | Rest-of-season projections from usage, actual points and team environment → `projections.csv` |
| `pipeline/merge_projections.py` | Writes projection columns into `index.html` for every ranked player |
| `pipeline/stamp_date.py` | Sets the "Updated" date on the site |
| `.github/workflows/site.yml` | Deploys on every push; every Tuesday it also refreshes projections, commits, and redeploys |

## Updating

- **Rankings:** edit `RANKINGS_CSV` in `index.html` (columns `player, pos, team, pos_rank, tier`) and push. The site redeploys in about a minute.
- **Projections:** automatic every Tuesday. To run it now: Actions → *Build and deploy site* → *Run workflow*.
- **End of season:** after week 17, disable the workflow's schedule (or the whole workflow) under Actions.
