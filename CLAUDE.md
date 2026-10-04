# CLAUDE.md: SPAM project handoff

Read this file first. It's the context an AI assistant (or a new developer) needs to keep building SPAM without undoing decisions that were already made. `README.md` has the feature-by-feature reference; this file has the **why**, the **rules**, and the **workflow**.

Owners: **Steven** (GitHub `stevenp36`) and **Alan** (GitHub `adequate-alan`), both collaborators on the repo, which belongs to the shared **`spamfantasy`** GitHub account (a personal account both can sign in to; only it can change repo settings, Pages, collaborators or transfers). Both edit the rankings; both may work on the code from their own Claude accounts. Keep this file current: when you make a product decision, add it here in the same commit.

**Git workflow (agreed Oct 3, 2026):** Steven (`stevenp36`) and Alan (`adequate-alan`) **both push straight to `main`**; there's no branch/PR step. Every push to `main` redeploys the live site, so: `git pull --rebase` right before you start and again right before you push, keep commits small and focused, test locally first, and never force-push. If a rebase conflicts in `index.html`, resolve it by keeping both people's changes; never resolve a `RANKINGS_CSV` conflict by taking one side wholesale (that can drop the other person's published ranking edits). Commit as yourself (git `user.name`/`user.email` set to your own GitHub account) so the history shows who changed what. **For Alan**, every session sets this automatically before committing: `git config user.name adequate-alan` and `git config user.email 54249725+adequate-alan@users.noreply.github.com` (GitHub noreply address; "Keep my email addresses private" is on, so use this, not a personal email). The `alan-dev` branch was only an access test and can be deleted.

---

## 1. What SPAM is

- **SPAM** is the product: fantasy football rankings, values and trade tools. Brand mark is the one-word wordmark **`SPAM.`** (the period is part of the logo: burgundy word + warm accent dot in light mode, cream word in dark mode). The old name was SPMetrics. Never bring that name back in the UI, metadata or copy.
- Live site: **https://spamfantasy.github.io/** (rankings at `#rankings`). Repo: **`spamfantasy/spamfantasy.github.io`** (Oct 4, 2026: transferred from `stevenp36/spam` to the `spamfantasy` account and renamed so Pages serves it at the root; before that it was `spmetrics-fantasy`). GitHub redirects the old git URL, but **Pages URLs don't redirect**: `stevenp36.github.io/spam/` no longer serves the site. Never create a new `stevenp36/spam` repo (it would break GitHub's git redirect); a redirect page for the old URL would go in a `stevenp36/stevenp36.github.io` repo at `spam/index.html`. Browser-saved data (`spm_*`: leagues, edits, tokens, theme) is per web address, so everyone starts fresh on the new URL.
- Base format: **12-team, Full PPR, Superflex, TE premium (+0.5), redraft.** That's what the SPAM Board means.
- The **SPAM Board** (Steven & Alan's manual rankings, tiers and published values) is the **core source of truth**. Everything else (league-adjusted values, trade verdicts, power rankings, Trade Finder) is *derived* from it.

## 2. Product rules that must not be undone

1. **The base SPAM Board is never overwritten by derived calculations.** League-adjusted values, custom formats, Sleeper data, stats refreshes and projections are separate layers computed in the browser. They must never write back into `RANKINGS_CSV` or change rank/tier/value for anyone.
2. **Manual rankings are locked.** Players with `source=manual` keep the order, tiers and values Steven/Alan set. Automatic processes (projections, Auto players, the weekly job) must never reorder them or push them down.
3. **Auto players sit underneath.** `source=auto` players (70 added Oct 2, 2026) are ranked below every manual player (overall #184+), valued with a gentle tail that never exceeds anyone ranked above them. Moving, re-tiering or re-valuing an Auto player in the editor and saving makes him Manual. Players who only shift because someone else moved stay Auto.
4. **Values follow the overall rank (decided by Alan, Oct 3, 2026).** On the SPAM Board no player is ever valued above someone ranked ahead of him. `keepOverallOrder` enforces it over the whole board (Auto tail included) by adjusting values, never ranks. **No two players share a value** (Alan, Oct 4; 94 players were tied, e.g. six at 2,263 and nine at 1,021 around Croskey-Merritt's published value): each model value is at least `VALUE_MODEL.minRankStep` (0.25%) below the one ranked ahead, found as the closest fit to the tier values (pool-adjacent-violators on log(value + 200) − i·log(1 − step), so a tied run spreads both ways instead of sinking); values under 400 at the bottom step by whole points; only players at 0 can tie. Published values are fixed anchors: the model values between two of them stay strictly between them, with a smaller step if the stretch is too crowded. (This replaced the 2% `overallMaxShift` cap and then a pooled 0.5% step that still left ties.)
5. **Tiers first, then rank order, then format.** Tiers decide where the value gaps are; rank order inside a tier sets small gaps; format (league size, scoring, lineup) adjusts how much each tier is worth. No artificial cliffs just because a player crosses QB12→QB13 or WR36→WR37.
6. **"Custom" means unpublished.** A typed value shows the CUSTOM label, striped bar and an Auto/Reset button only until it's published. Once published it's that player's official SPAM value and looks like every other player. It stays fixed (it doesn't follow the model) until someone edits it again.
7. **Save → Publish workflow.** Before saving = unsaved edit. Save changes = saved (in the browser, and published automatically if the browser has a GitHub token). Publish to live site = committed to `index.html` on GitHub and becomes the master rankings. Tier changes follow the same workflow.
8. **League-specific screens always show league-adjusted values and position ranks** (Trade Finder, My Team, League, Free Agents, the calculator in league mode, player pages opened from those). The SPAM Board / League-adjusted toggle only affects the Rankings board. Never show the base positional rank (e.g. superflex QB3) inside a 1QB league's trade recommendation.
9. **Historical honesty in Trade History.** A trade is "Historical SPAM values" only if every player had a SPAM value on or before the trade date. Trades before SPAM existed are labeled **Pre-SPAM trade** and judged as a retrospective with today's values. Never present today's values as what a player was worth back then.
10. **Stats never change rankings.** Stats refreshes update game logs and fantasy points only.
11. **Design consistency.** Use the theme tokens; no default browser controls (selects, checkboxes, dialogs). No Patreon button or styling. Labels are sentence-case in copy, uppercase with letter spacing for small labels.
12. **The website is the master source of truth for rankings** (from Alan). Don't sync the Excel file unless Alan or Steven asks.
13. **Keep the layers separate** (from Alan). Don't overwrite manual rankings or published values, don't let stats or projection updates change rankings, and keep league calculations derived from the base board.
14. **Stay in scope** (from Alan). Don't change unrelated parts of the site when doing a specific feature. Preserve the SPAM branding and design system.
15. **Don't rename the `spm_` localStorage keys** (from Alan). Renaming them would wipe visitors' saved leagues, edits and tokens.
16. **League data is private to each visitor** (from Alan, Oct 4). The League hub is a template that works for any Sleeper league: everything in it (username, selected league, rosters, standings, matchups, transactions, waiver activity) is fetched in the visitor's browser and kept there (`spm_sleeper` in localStorage; matchups only in memory). Never commit anyone's league data, never hard-code a league, team or manager, and never make a personal league a public dataset. Tests use synthetic leagues only. Public/shared: base SPAM rankings, player identity, stats, ranking history, design, trade-value and league-adjustment logic.

## 3. How to run it

It's a static site: **one HTML file** plus JSON data. No build step, no framework, no npm.

```bash
git clone https://github.com/spamfantasy/spamfantasy.github.io.git && cd spamfantasy.github.io
python3 -m http.server 8000          # then open http://localhost:8000/
```

Opening `index.html` straight from disk works for most things, but `fetch()` of `data/*.json` needs a local server.

Pipeline scripts (Python 3.12, pandas, numpy): `cd pipeline && pip install pandas numpy`. They download public nflverse / DynastyProcess data.

### Testing (how changes were verified so far)
There's no committed test suite. Changes were verified with throwaway **Playwright** (Python) scripts:
- Serve the repo locally, open the page with `chromium.launch()`, and read the rankings table from the DOM (`#rank-body tr.player`, `.pl-name`, `.pos-col .pos`, `.val .num` / `.val .num-btn`).
- **Mock Sleeper** by routing `https://api.sleeper.app/**` to fake JSON (users, leagues, rosters, transactions) and connect through the UI (`#sl-connect` → Sleeper → username → pick league).
- **Mock GitHub** by routing `https://api.github.com/**` to test the Save/Publish flow without touching the real repo.
- Key regression checks:
  - Manual players' ranks and values are identical before and after a model change, compared across several `?fmt=` formats.
  - A league in the base format gives exactly the base values: all 253 match.
  - No `pageerror` events.
  - Light and dark screenshots look right.
- `?fmt=` URL form: `t10_qb1_rec0.5_tep0` (keys: `t` teams, `qb` 1/sf/2, `sx` superflex spots, `rec`, `tep`, `ptd`, `pyd`, `int`, `fl` fumble, `fd`, `rb`, `wr`, `te`, `fx` flex, `bn` bench).

Committed so far: **`tests/league_hub_check.py`** (a synthetic 12-team and 10-team Sleeper league, mocked API with a rotating season schedule: every League tab incl. Rosters (picker, header, columns, slots, week switch, schedule → matchup), filters, bidder counts, waiver availability, a past week's finals, league switching, persistence, base board unchanged) and **`tests/format_check.py`** (`CHROMIUM=/path python3 tests/format_check.py`): runs `SPM.formatCheck()` in the page (Kittle rises with TE premium none → + → ++, Josh Allen 1QB vs Superflex, WR36 vs WR starters, RB30 vs league size and FLEX, WR1 vs points per catch, base format = base values exactly), then checks with a mock league that the Trade Calculator uses league-adjusted values in both "No league" and league mode, shows the Format adjustment table, follows Custom format changes, and that the base SPAM Board never changes. Run it after any change to the value model or the calculator. More checks belong in `tests/`.

## 4. Where things are

```
index.html                     the whole site (HTML + CSS + JS, ~8k lines) AND the rankings data
data/rank_history.json         ranking history: {note, version: 2, players: {sleeper_id: [[ts, rank, posRank, tier, value, src]]}}; the browser writes src M, the scheduler S; existing P entries come from older code
data/stats/<season>.json       weekly game stats + team schedules for player pages (2026, 2025, 2024); schedule rows also carry kickoff (ET), team spread, game total, roof, stadium (see `schedule_cols`); `defense` = per-team run/pass EPA, success, explosive rate allowed (play-by-play); `injuries` = latest week's injury report per team (cols include `wed`/`thu`/`fri` practice status)
data/sleeper_players.json      Sleeper ID → [name, pos, team, gsis_id, birthdate]
data/platform_ids.json         ESPN/Yahoo ID → Sleeper ID (for ESPN/Yahoo imports)
data/curve_components.json     points-by-rank curve inputs used to re-score other formats
pipeline/                      Python data jobs (see §8)
.github/workflows/site.yml     the only workflow: deploy on push + scheduled data refreshes
favicon.svg, manifest.webmanifest
README.md                      detailed feature reference
CLAUDE.md                      this file
```

Inside `index.html` (search for these names):
- **Settings at the top** (plain JS constants, meant to be tuned):
  - `SITE`: name, repo, format text.
  - `RANKINGS_CSV`: the data.
  - `VALUE_MODEL`: curves, tiers, `tagTierFrom: 90`, `autoDecay`.
  - Trade model constants, `TEAM_FIT`, `DEPTH_ADJUST`.
  - `TIER_NAMES`: preset tier names.
  - `STATS_SEASONS`.
  - `FORMAT_ADJUST`: margin, maxPosMove, `tierKeep: 0.40`, `floor`.
  - `TRADE_VERDICTS`.
- **Value pipeline:**
  - `loadPlayers` → `modelValue` → `keepRankOrderBySource` → `applyTiers` → `autoValues` (the tail) → `keepOverallOrder` (whole board: values never increase down the overall rank).
  - League layer: `leagueRecalc` → `adjustValues(valueLeague())` → `smoothTiers` → `stickyOrder` → `LG.adj` / `LG.adjPos` / `LG.adjRank`.
  - Display helpers: `dv(p)` = value in the current context, `posLabel(p)` = position rank in the current context, `leagueView()` decides which. `adjOf(p)` = league-adjusted value whenever a format is set, on any tab (the calculator's `tv`).
  - Format debugging: `adjMapFor(league)` (adjusted values for any league object without touching `LG`), `formatSteps(p)` (base → scoring → TE premium → lineup & league size), `SPM.formatCheck()` (self-test, see §3).
- **Editor:**
  - `editor`, `draft`, `writeOrder`, `moveOverall`, `movePlayer`, `setValue`, `makeManual`.
  - Tier editing: `tierAction`, `shiftTiers`, `materializeTierNames`, `TIER_EMPTY`.
  - Saving and publishing: `saveLocal`, `publishLive`, `mergeInto`.
  - Data columns: `EDIT_COLS`.
- **History:** `recordSave`, `saveHistory`, `addSnapshot`, `normalizeHistory`, `window.SPM` (used by `pipeline/snapshot_history.py`).
- **Sleeper/ESPN/Yahoo:** `SL_KEY`, `slGet`, `leagueTeams`, `espnToLeague`, `parseYahooSettings`, `activeData()`, `syncedLeague()`.
- **Custom format:** `FMT`, `FMT_DEFAULT`, `FMT_FIELDS`, `fmtLeague`, `FMT_SRC` (synced vs custom), `configText`.
- **Tabs:**
  - My Team: `renderMyTeam`.
  - League hub: `renderLeague` (`LEAGUE_SUBS`, `LT`), `powerHtml`, `teamExpand`, `standingsHtml`, `matchupsHtml` (`loadMatchups`, `nflGameState`, `etMs`), `rostersHtml` (`ensureRosters`, `rosterWeek`, `scheduleHtml`, `faabLeft`), `txHtml` (`loadTrades` loads every transaction type, `moveCard`, `tradeCard`, `evalTrade`, `valueAt`).
  - Trade Finder: `renderFinder`, `findTrades`, `findThree`.
  - Waiver Wire: `renderFA` (`faFit`, `waiverUntil`, `recentFormData`).
  - Calculator: `renderTrade`, `tradeModel`, `runModel`, `rosterContext`.
  - Player modal: `openPlayer`, `renderPlayer`, `ppSection`, `statsStamp`.
- **UI components:**
  - Dropdowns: `SpamSelect` (end of file), which turns every `<select>` into a themed dropdown.
  - Themed checkboxes and radios: global CSS.
  - Theme: `setTheme`, `spm_theme`.
  - Update prompt: `BUILD_ID` and `checkForUpdate`.

## 5. How the rankings data flows

1. **`RANKINGS_CSV`** (inside `index.html`) is the master data. Columns:
   `player,pos,team,rank,pos_rank,tier,value,proj_ppg,games,proj_score,sleeper_id,source`
   (`tier_name` is not in the current header; the editor's `colOf()` adds it as a 13th column the first time a tier is renamed.)
   - `rank` = overall rank (source of truth for order); `pos_rank` derived from it.
   - `tier` = positional tier number; **90+ are tag tiers** (e.g. 90 = "Hurt"), not part of the ladder.
   - `value` = blank → model value; a number → published official value (fixed).
   - `source` = `manual` / `auto`. `tier_name` = editable tier name (falls back to `TIER_NAMES`).
   - `proj_ppg/games/proj_score` = written weekly by the pipeline (projection blend). `sleeper_id` written by the pipeline.
2. On load, `loadPlayers` builds player objects and values (base SPAM values, scaled so #1 = 10,000).
3. Editor edits change a `draft` copy of the CSV and call `rebuild()`. Save stores the changed fields per player in `localStorage` (`spm_local_edits`); Publish merges only the edited fields onto the latest `index.html` from GitHub and commits it (so the weekly projection refresh is never clobbered).
4. The **league layer** is computed after every rebuild from the base values: never stored.
5. Snapshot as of Oct 3, 2026: 253 players (183 Manual #1–183, 70 Auto #184–253), 4 published values (Bijan Robinson, Kenneth Walker III, Jacorey Croskey-Merritt, Jaxon Smith-Njigba), A.J. Brown in tag tier 90.

## 6. Publishing (rankings) and deploying (code)

**Rankings edits** (no code): in the site's editor (currently open to every visitor, temporarily), make changes → **Save changes**. If that browser has a GitHub token, Save publishes immediately; otherwise click **Publish to live site** once and paste a token:
- **Steven and Alan** (collaborators on a repo owned by the `spamfantasy` personal account): fine-grained tokens can't reach repos owned by another personal account, so each uses a **classic** token with the **`repo`** scope (`public_repo` is enough for publishing; `repo` is needed to start the stats workflow). Old fine-grained tokens for `stevenp36/spam` stopped working with the transfer.
- Signed in as **`spamfantasy`** (the owner), a *fine-grained* token for this repo with **Contents: Read and write** (+ **Actions: Read and write** for Refresh stats) also works.
- Tokens live only in that browser's `localStorage` (`spm_editor_token`). **Never put a token in the code or the repo.**

**Code changes**: commit to `main` and push. The `push` trigger in `site.yml` deploys the repo root to GitHub Pages in ~1 minute. **Bump `BUILD_ID`** (top of the main script) in every code change so open browsers get the "new version" prompt. Rankings publishes from the editor don't need it.

Both owners push straight to `main` (see the workflow note at the top). Before pushing a code change, `git pull --rebase` first: the editor and the scheduled jobs commit to `main` too (`Rankings edit by @…`, `Ranking history: N changes`, `Player stats refresh`, `Weekly projections and stats refresh`).

## 7. How to change rankings safely

- Prefer the website editor. If editing `RANKINGS_CSV` by hand:
  - Keep the columns.
  - Keep ranks unique and contiguous.
  - Put every Auto player after every Manual player.
  - Quote any field containing a comma.
  - Leave `proj_*` and `sleeper_id` alone (pipeline-owned).
- After resolving any `RANKINGS_CSV` merge or rebase conflict, check that ranks still run 1–N with no duplicates or gaps and that every Auto player is below every Manual player. Verify by parsing the CSV, not by eye.
- After a model change, verify manual players' values are unchanged (or changed only as intended) in the base format and a few `?fmt=` formats.
- Don't put the draft rankings of one person into the board without saying so: the board is Steven & Alan's combined ranking.
- Ranking History records committed changes (Save/Publish), one entry per changed player, plus scheduled snapshots. Same-day separate publishes are separate entries; unchanged players get no duplicate. Tier changes are included.

## 8. Scheduled jobs and data updates (`.github/workflows/site.yml`)

| Trigger | What runs | Writes |
|---|---|---|
| push to `main` | deploy only | Pages |
| **Tue 14:00 UTC** (weekly) | `project_players.py` → `merge_projections.py` → `build_sleeper_ids.py` → `build_stats.py 2026` → `stamp_date.py` → `snapshot_history.py` (headless browser) | `index.html` (proj columns, sleeper IDs, date), `data/sleeper_players.json`, `data/platform_ids.json`, `data/stats/2026.json`, `data/rank_history.json` |
| **Fri 08:30 & 15:00, Sun 08:30 & 15:00, Mon 08:30 & 15:00, Tue 08:30, Thu 15:00 UTC**, plus **Wed/Thu/Fri 22:00 UTC** for injury/practice reports | **stats only**: `build_stats.py 2026` (stats, schedule lines, defense efficiency, injury report) | `data/stats/2026.json` |
| manual "Run workflow" (`stats_only` true/false) or editor **Refresh stats** button | stats-only or the full weekly job | as above |

- Stats come from nflverse's weekly player stats, which usually appear the night of the games and sometimes the next morning. That's why each game day has a retry.
- The stats file includes `updated` (UTC timestamp) and `through_week`; player pages show "Stats updated … · through Week N".
- The weekly projection refresh changes `proj_*` columns, which feed the model's projection blend for *model-valued* players (not published fixed values). Rank order and tiers are never changed by it.
- Season rollover: add the new season to `STATS_SEASONS` and the workflow's `build_stats.py <year>` and git-add lines.

## 9. Sleeper and league data are separate from SPAM data

- Connected leagues (Sleeper username → leagues; ESPN direct or paste; Yahoo/other paste) are stored in the **visitor's browser** (`spm_sleeper`). Nothing about a visitor's league is committed to the repo.
- Every import becomes a Sleeper-shaped object `{league, users, rosters}`, so all features work the same way.
- Ownership: `LG.ownerOf` maps players to fantasy teams for owner tags, the "Show" filter, Free Agents, rosters.
- Trade History reads Sleeper `transactions` for each week (Sleeper only).
- **League-adjusted values** come from the selected league's settings (Synced league) or the user's **Custom format** (`FMT`, saved per browser, also in `?fmt=`). League size + lineup set replacement levels; scoring re-scores the points-by-rank curves; tiers are re-priced as blocks; `tierKeep` limits tier-to-tier drops in shallow formats; a small `floor` (25, easing down by position rank) stops a format from pushing values to ~0, but never lifts a player above his base value (so a base-format league equals the base board exactly; a player at 0 on the board shows 0 everywhere); a per-player scoring-profile nudge (max ±10%) applies; within a position, order moves only when a value beats the player above by >3% (max 2 spots), and a value is capped just below the player ahead at his position (published values too); **across positions the overall league-adjusted order follows value** (`mergeByValue`: the position queues merged by adjusted value, ties to the earlier board slot), and the Auto tail is capped below the lowest manual player, so **no lower value is ever ranked ahead of a higher one** (Alan, Oct 4: Tyler Warren 3,281 sat ahead of DeVonta Smith 3,367 in a custom 12-team 1QB format because the old 3% margin also applied across positions; `tests/format_check.py` now checks four formats for inversions). In the base format nothing moves. **None of this touches the SPAM Board.**
- League depth (`DEPTH_ADJUST`): shallow leagues (e.g. 10 teams × 7 starters) weight bench depth less.
- **Custom format over a connected league must always be visible** (Alan, Oct 4). A Custom format replaces the league's own settings for every value (`valueLeague()`), so: the league chip shows "Custom · <format>" in gold, and a notice bar on every tab says which format the values use instead of the league's, with **Use <league>'s settings** (`useLeagueSettings`). Connecting or switching to a different league goes back to that league's own settings; a refresh of the same league keeps the custom format. (The Oct 4 "Superflex QBs collapsed" report was a saved 1QB custom format silently overriding a Superflex league; the Superflex math was correct and unchanged.)
- Superflex/2QB are applied through replacement levels: `replLevels` fills each SUPER_FLEX slot with the position whose next starter scores most (QBs in practice), so a 12-team Superflex league starts ~24 QBs and QB replacement drops accordingly; there is no separate league-size penalty before it. `SPM.formatCheck()` guards it (Allen, Jackson, Purdy and QB20 must be ≥1.4× their 1QB values in 12- and 10-team leagues; QB20 ≥3×; QB12 2QB ≥1.4× 1QB) and reports when a custom format overrides the selected league.

## 10. Features and the decisions behind them

- **Format labels** come only from `formatLabel()` / `formatParts()` (no hard-coded format text). TE premium is shown as shorthand (Alan's call): one "+" per 0.5 per catch ("TE Premium +" = +0.5, "++" = +1.0, "+++" = +1.5, "++++" = +2.0), nothing at all without TE premium; values that aren't a multiple of 0.5 keep the number. `tepLabel()` does this; calculations always use the real number.
- **Player identity layout (every screen that lists players):** line 1 is the player name (strongest) with the NFL team as a small muted abbreviation right beside it (`nflTag`, `.pl-team`). Line 2 is the fantasy owner as smaller secondary text (`ownPill` / `ownerTag`, `.own-tag`): "Owned by X" muted, **My team** in warm gold (`--mine-accent`), **Free agent** in muted green. Never put the owner on the NFL team's line. A player with no NFL team shows no team (not "FA"), so "Free agent" always means the fantasy league. Screens where the owner is already obvious (My Team, a team's roster board, a Trade History side, Free Agents) show no owner line.
- **Rankings tab:**
  - All / QB / RB / WR / TE.
  - Board view toggle: SPAM Board vs League-adjusted.
  - Column guide (RK / RANK, PLAYER, POS, VALUE): compact and muted, and sticky under the masthead while scrolling (desktop; `--mast-h` is set from JS).
  - Dense rows (~53px). Tier bands: a soft full-width band with the tier name as the focus (normal case, not oversized). A small muted note "N players · high–low" is derived only from the players currently in that tier; never show a formula-style value range as the headline.
  - Typography: big headings (page titles, card titles, verdicts, player name in the modal) and the main tabs use normal case; uppercase with letter spacing is kept for small labels (column guides, tags, badges).
  - Owner "Show" filter when a league is connected.
  - **"Last updated" date** (header and the rail; Alan: it should show the day of every published ranking change) = `lastUpdated()`: the newer of the weekly job's stamp (`SITE.updated`, written Tuesdays by `stamp_date.py`) and the latest Ranking History entry, so a publish shows its date right away on every screen (Oct 4: phones showed the stale Tuesday stamp while the desktop rail showed the publish date).
- **Editor** (top bar, temporary: open to everyone):
  - Drag or arrows to reorder.
  - Click a value to type it.
  - In position tabs, hover a tier header to rename it, add a tier above or below, or delete it (asks whether players move to the tier above or below; never drops players).
  - Drag players onto tier headers or empty tiers.
  - Empty tiers last only until you save.
  - **Sign out** sits at the right of the editor bar whenever this browser has a saved GitHub token (next to `@login`); it removes the token from the browser. Unpublished edits stay saved.
- **Player modal:**
  - Tabs (title case, Alan's call): Overview, Game Log, Schedule, Stats, Fantasy Performance, Ranking History, Trade Value, Practice Report (last: useful but secondary), Compare.
  - Desktop layout (≥1100px modal): two-column top (identity, numbers, actions | full This week card) and two-column Overview (season, production, chart | This week context: start/sit, next weeks, practice notes, ranking moves). Narrower screens put the This week card at the top of the Overview instead.
  - Header: a compact matchup strip right of the name (week, opponent, kickoff, verdict, spread/total, status); hidden on phones.
  - Game log: every week of the season: result (W/L score), points, weekly position finish (`weeklyFinish`, current scoring), bye week, and upcoming games greyed with kickoff.
  - Schedule: every remaining week with a Matchup verdict and the opponent's ranks vs his position (points allowed, EPA, success, explosive; 1 = softest), a key line above the table and hover explanations on each column.
  - **NFL team identity** comes only from `NFL_TEAMS` (top of the main script: full name, nickname, primary/secondary color, ESPN logo code; from nflverse teams_colors_logos) through `teamMeta`, `teamLogo`, `teamStyle` / `teamAccent`. Team colors are small accents only (header strip, photo ring, matchup-card strip, practice-report section edge, schedule-row edge); `teamAccent` picks a readable shade per theme (`--tc-d` / `--tc-l`, `.tm` chooses). Never hard-code team colors or logos elsewhere.
  - **Weekly projections: one shared module** (Alan, Oct 4). `PROJ_PROVIDERS` (priority list; today only SPAM's pipeline projection `proj_ppg`) → `weeklyProjection(entry, scoring)` (a provider's raw stats are scored exactly with `gamePoints`; SPAM's points-in-site-scoring are rescored with the player's own league/site ratio, `projRatios`) → season-PPG fallback flagged `fallback` (only when no provider has him and our stats do; our stats cover QB/RB/WR/TE only, so K/DEF/IDP can't be projected yet) → **`contextProjection`** calibrates it for the week: Vegas (`gameContext`: team implied total vs its average over the remaining games, ^0.75, ±15%; nflverse lines, keyless), matchup (what the opponent allows the position vs league average, shrunk by sample, ±10%), and **player props** when `data/props/<season>.json` exists (`propsProjection`: prop lines → expected stats, anytime-TD probability → expected TDs via −ln(1−p) split rush/rec by his history, the rest of his line from his recent per-game averages, scored with the league's settings; blended with the calibrated SPAM number at 15% + 15% per market, max 60%; no props = no change, never zero) → `weekOutlook(entry, week, {pts})` adds game status (final / live approx / upcoming / bye / Out / missing). Waiver Wire (`weekProj`), Matchups (`starterProj`) and the player modal's This week tile all use it; never re-implement projection scoring elsewhere. Never invent a projection: missing stays missing. Weekly projections never touch rankings, values, tiers or history. `SPM.projectionCheck()` (in `tests/format_check.py`) checks TE premium, Standard/Half/Full PPR (WR and RB), 4 vs 6 pt passing TDs, first-down and 100-yard bonuses, that 1QB/Superflex/2QB don't change a QB's own projection, and that an unprojectable K gets null. To add an external provider, put it first in `PROJ_PROVIDERS` returning `{ stats }` keyed like Sleeper scoring keys. Each projection carries `inputs` (shown in tooltips: SPAM projection, Vegas team total, matchup, props), never the weights.
- **Player props file contract** (not produced yet; needs a keyed odds API, see §11): `data/props/<season>.json` = `{ updated, week, books: ["…"], players: { <sleeper_id>: { rec, rec_yd, rush_yd, rush_att, pass_yd, pass_td, pass_att, pass_cmp, atd } } }`: consensus (median across books) of each O/U line, and `atd` = the no-vig consensus implied probability of an anytime TD (0–1). Only the current week's file is used (`week` must match). A scheduled pipeline job would write it with the key in a repository secret, never in the page.
- **NFL game status comes only from `nflGameState(team, week)`** (Alan, Oct 4): no game in that week's schedule = Bye; scored = Final (with the result); past kickoff = Live (Final 4½ h after kickoff if the score isn't in yet); otherwise Upcoming. Waiver Wire, Matchups, the player modal's This week card and Schedule tab, and projections all use it. Never infer Bye from "no game left this week" (`nextGame` is only for "next unplayed opponent", e.g. practice notes). Once a player's game is final, show his actual points (`weekPoints`) instead of a projection: Waiver Wire's "Wk N" column shows "9.7 Final", "DNP" when the stats include that week but he has no line, or "— Final · pts pending" until they do. The modal's This week card shows the played game as Final with his points; the Schedule tab keeps this week's game as Final.
  - **Status colors** are one system site-wide (`--st-*` tokens, `stBlock` / `stBadge`): FP green, LP amber, DNP red, Out deep red, Questionable amber, Doubtful orange-red, IR muted red.
  - Practice report: sections per team (logo, full name, team-color edge, "Opponent" label), grouped by position, columns Player (with game-status badge) · Wed · Thu · Fri · Injury. Days fill from the Wed/Thu/Fri evening runs (`build_stats.py` records the latest status under the run's ET weekday and carries earlier days; this week before those runs existed only has Friday). By default only what matters for him (`RELEVANT`: e.g. RB = his own status, own RB/QB/OL, opponent DL/LB; WR = own QB/WR/TE, opponent DBs), worst status first; both full team reports behind "View full team reports". Group headers are muted so statuses stand out. Full reports show his team's and the next opponent's latest practice report grouped by position (game status, practice FP/LP/DNP, injury). nflverse keeps only the latest practice status per week, not Wed/Thu/Fri separately.
  - Overview order: identity → rank / value / PPG (header) → **This week** card → Start/sit line (league only) → season grid → season line → weekly chart.
  - This week: opponent, home/away, kickoff, stadium + roof, spread, game total, implied team total (from nflverse `games.csv` via `build_stats.py`), the opponent's rank vs the position and fantasy points allowed per game (computed in the browser from the weekly logs, current scoring: `defenseVsPos`). Matchup verdict Favorable / Neutral / Tough = thirds of a blend of the four Schedule metrics: points allowed per game 40%, EPA 25%, success 20%, explosive 15% (from play-by-play: runs for RBs, dropbacks for QB/WR/TE); it only tints a thin edge and its label. The card also shows the opponent's EPA / success / explosive ranks, his practice status (or "Not on practice report"), a Next line (the 3 weeks after this one with verdict dots) and Practice notes (the relevant players listed Out / Doubtful / Questionable / DNP / LP). Bye weeks show "Week N · Bye". No player props (no keyless source) and no forecast weather yet (nflverse fills temp/wind only after games).
  - Start/sit (league): his slot in his fantasy team's best lineup, "Every-week starter / Flex starter / Bench depth", next player up at the position, and Sleeper's own lineup status.
  - Photos come from `sleepercdn.com`, with an initials fallback.
  - Shows both the league position rank and the SPAM Board rank when they differ.
  - "Stats updated" line.
- **My Team:** the connected user's roster with slots, league ranks and values. The roster table is the centerpiece; no new cards (Alan, Oct 4).
  - Header: team avatar, name, one summary line "Power Rank #N · Record W-L · Team Score X", then manager · league; "Position breakdown" opens the team in League.
  - Strength cards lead with the league rank (green top third, red bottom third); the strength score is small at top right; the player / vs-average note is small and muted.
  - Roster sections (Starters / Bench / Injured reserve / Taxi) are tinted full-width bands with a player count; a **Recent form** column (`recentForm`, also on Free Agents): his last three team weeks, oldest to newest with a small muted "Wk N" under each score (BYE / OUT instead of zeros, still with their week), "Avg" of the games played, and ▲ Hot / → Steady / ▼ Cooling vs his season PPG (last season's while this season has ≤3 games; ±15% and ±2 pts; no trend without a baseline); when Sleeper has no lineup set, starters are SPAM's best lineup (labelled).
  - Slim outline-only right rail (260px): position-rank badges (best/worst highlighted) with a needs/strengths line, Hot lately (last 3 games), and "Trade with" as one themed dropdown.
- **League tab (League hub, Alan, Oct 4):** one hub for the selected Sleeper league. Sub-tabs: **Power Rankings** (default) / **Standings** / **Matchups** / **Rosters** / **Transactions** / **Waiver Wire**. The title carries the league name as an eyebrow. Switching leagues (header menu, calculator) re-syncs and redraws every tab with no reload; the selected league persists in `spm_sleeper`. Old `#fa` links and the old "trades" sub-tab open Waiver Wire / Transactions (`LSUB_ALIAS`). Matchups and Transactions need a Sleeper league (ESPN/pasted leagues get a note); Rosters works for any league but its week picker and season schedule need Sleeper.
  - Compact player names (Power Rankings top players, matchup top players/scorers) come only from `compactName()`: the last name with its suffix ("Walker III", "Harrison Jr.", "Mahomes II") or "St." ("St. Brown"). Everywhere else shows the full name.
  - Power Rankings: compact rows; the whole row expands inline into a roster board (QB/RB/WR/TE columns with starter/BN tags, position ranks vs the league). IR and taxi players are never hidden: they're listed in full at the bottom in a muted, dashed "Injured reserve · Taxi squad" section (photo, name, NFL team, position rank, overall rank, value, a muted IR / TAXI badge), marked "not counted in team strength"; they're never starters, bench or part of the position strength (the lineup only uses the healthy roster); Trade with / Find trades never toggle the row; one team open at a time unless "Keep teams open to compare" (custom checkbox). Gold accent on your own team. Team score bar scaled to the top team.
  - Standings: rank, team, manager, record, PF, PA, streak, SPAM Power Rank, and the difference (▲ roster ahead / ▼ record ahead). No "luck" scores.
  - Matchups (redesigned Oct 4, BDGE-style hierarchy in SPAM's design; desktop polish Oct 4: one centered column `.mx-wrap`, max 1200px, so the page doesn't read as a tablet layout; hierarchy score (2.45rem) → Live proj (bold, 1rem) → team name → PR/record → players left; bigger bar percentages; Show lineups in the accent color with a hover and chevron; **only one matchup open at a time**; your matchup gets a warm-gold edge, border and faint gold tint (`--mine-accent`); the small source line sits right beside the week controls): each matchup is one horizontal card. Each side: avatar, SPAM PR badge, team name, manager · record; the current score is the biggest number, with "Proj" (not started) or "Live proj" under it; final cards show the score with Win / Final instead (no projections). Center: Upcoming / Live / Final pill and "vs". Under the scores a **Projected matchup** bar (each team's share of the two projected totals, burgundy vs gold; never called win probability), then "N played · N active · N remaining" per side, then **Show lineups** (the only toggle) which opens both starting lineups side by side: slot, photo, name, NFL team, position, opponent logo + vs/@, game status (Final / Live / kickoff / Bye / Out), points (final; "12.4 LIVE" + "Proj 18.7"; or "Proj 16.2"), and each side's top scorer. Your matchup has a gold edge. No top-players text on collapsed cards. Header: week picker, Refresh scores, and a muted "Scores: Sleeper · Projections: SPAM · Updated …" line. **Projections** come from the shared weekly projection module (below), summed over each starting lineup: final = actual points; live = points so far + projection for the share of the game left, estimated from time since kickoff. The projected final score is labeled **"Live proj"** everywhere in Matchups (cards, lineup headers, player rows) before and during games (Alan, Oct 4: one label, no "Proj" / "Approx." variants); its tooltip explains it's the expected final score before kickoff and an estimate from time since kickoff during games, not a real-time game model; not started = projection; bye, empty or ruled Out before kickoff = 0. A starter with no projection and no season PPG makes the total **partial**: a "*", a "Partial projection · one or more starters could not be projected" note, and **no bar** (the bar only shows when both lineups are fully projected; share = each team's projected total ÷ the two combined, one decimal). Lineup rows: "Proj 16.2" before kickoff (+ "season PPG" when that fallback is used), "12.4 LIVE / Approx. proj 18.7", "21.6 Final" (no projection once final). Scores from Sleeper `/matchups/{week}` (memory only, refresh button, 2-minute cache); NFL game status from our schedule (kickoff ET → `etMs`).
  - Rosters (Alan, Oct 4; layout inspired by a BDGE screenshot, built in SPAM's design): a compact team dashboard for any team in the league (`rostersHtml`, `rosterWeek`, `scheduleHtml`; state `LT.rTeam` / `LT.rWeek` / `LT.rOpen`, reset to your team when the league changes). Top: a horizontal team picker (avatars, yours first then by SPAM power rank), then the team header (avatar, name, manager, SPAM PR, record, PF, PA, FAAB left via `faabLeft`, shared with the Transactions rail) and a ‹ Week N › picker. Main table, weekly usefulness first: **Slot · Player · Wk N · Szn rk · SPAM rk · GP · FPTS · PPG** in sections Starters (with the starters' total: points, "Live proj" or "Proj") / Bench (by position, then value) / Injured reserve / Taxi squad. Slot badges use the position tokens (FLEX, W/R, W/T and SF blend the positions they take; bench/IR/taxi muted). The player cell has photo, name, NFL logo + abbreviation, a Q/D badge from this week's report, and under it opponent logo, vs/@ and kickoff or status. Wk N comes from the shared `weekOutlook`: "21.6 Final", "12.4 Live" + "Live proj 18.7", "16.2 Proj", BYE, OUT, DNP, — when unprojectable. Szn rk/FPTS/PPG = `seasonRanks` (league scoring); SPAM rk = league-adjusted overall rank with the position rank under it. Clicking a row expands SPAM value, league rank, SPAM Board rank when different, matchup verdict, recent form and a Player page link (value is never a main column). **Which lineup:** past weeks show the lineup Sleeper recorded for that week (`/matchups/{week}`, with its points); the current week shows Sleeper's current lineup; future weeks the current lineup; no lineup set → SPAM's best lineup (labelled, as on My Team). IR and taxi are always the current roster's (labelled "Current" on past weeks). Right rail (≥1240px, sticky; stacked below on smaller screens): **Season schedule** for every regular-season week (`regularWeeks`: through `playoff_week_start` − 1): W/L/T badge, score, opponent avatar, name, today's record and SPAM PR; the current week marked Now, the viewed week highlighted; a row opens that matchup in Matchups, expanded. All weeks' matchups load once per league into the same in-memory `LT.mx` cache as Matchups. Nothing here changes ownership, rankings or values.
  - Transactions: every completed trade, waiver claim, free-agent add/drop and commissioner move, newest first; filters **All / Trades / Waiver Wire** (one combined filter for waiver and FAAB claims, free-agent adds, drops and commissioner moves; Alan, Oct 4: one filter, titled Waiver Wire, not separate Waiver Wire and Adds / Drops filters), plus Week and Team. Each move card still names its kind (`txKind`): WAIVER CLAIM, FREE AGENT, DROP (a move with no add) or COMMISSIONER. The feed is **grouped by week**, newest first (Alan, Oct 4): only the latest week shows at first ("Load older transactions · Week N" adds one week at a time, `LT.txShow`; the Week filter shows that week). Each week header has a summary from real data ("1 claim · 2 adds/drops · 1 trade · $12 FAAB spent", team filter respected). Waiver claims, adds and drops are **dense rows** (`moveRow`) inside one bordered list per run: type badge (+ bidders) · team · "+ added player · $FAAB · − dropped player" (only what exists; $0 FAAB muted, a bid ≥10% of the budget in gold) · day and time. Trades break the list as larger cards with a gold edge and a TRADE badge (`tx-trade-card`). Max 960px on desktop, full width on tablet/phone. The bidder count sits beside WAIVER CLAIM, only when Sleeper's failed claims show 2+ teams claimed the same player in the same run (never invented); clicking it opens the **FAAB bids** panel (`openBids`): every team's bid, highest first, the winner first in a tie (Sleeper already resolved it) and highlighted green, the others muted as Outbid / Lost tie-break / Not awarded, with Sleeper's note when it gives one. Sleeper doesn't log the waiver priority it used for a tie, so the panel says so instead of showing one. Closes on X, Escape or a click outside. Beside the feed (≥1320px, sticky while scrolling and scrollable on its own; below the feed on smaller screens) a **League Activity rail** (`txRail`, 330px); on wide screens the filters, feed and rail form one block (`.tx-wrap`, max 1326px) centered in the page so the empty space is shared evenly instead of piling up on the right: FAAB remaining for every team, highest first, your team highlighted (Sleeper's `waiver_budget_used`, saved as `faabUsed`; older saved data falls back to winning bids and traded FAAB in the log; FAAB leagues only) · Most active (the Week filter's week, else the latest week with moves: the busiest teams) · Top waiver claims (largest paid claims that week, with their bidders link). The feed never stretches to fill the space. Stored transactions carry `txV` (`TX_VERSION`); bump it when their shape changes so saved logs reload. Trades reuse the trade-history analysis (historical / Pre-SPAM / current-value labels, verdict, difference, 3-team per-team verdicts, Analyze trade → calculator).
  - Waiver Wire (replaced Free Agents; redesigned Oct 4 as a weekly scouting table, max 1180px on desktop, centered in the page like Transactions): **no SPAM value column or value bar**. Columns: RK (league-adjusted overall rank) · Player (photo, name, NFL team, "Free agent" / "On waivers · clears <day>", and Sleeper's **trending adds** "▲ 4.2k adds · 24h" when he's in Sleeper's top 300) · Pos (league position rank) · **Wk N** (`weekProj`: projection before/during his game, his actual points once it's final, Bye / Out / DNP; the header stays "Wk N", not "Proj", because the column mixes projections and finals, and each cell says PROJ / FINAL / LIVE underneath) · Recent form (muted week labels and average line on this page) · Matchup (opponent logo, vs/@, kickoff, Good/Neutral/Tough) · Szn rk (muted plain text: secondary to the SPAM position rank) / FPTS / PPG (this season in the league's scoring, `seasonRanks`) · Fit (`faFit`: Starts at FLEX / TE upgrade / Would be WR4 / Bench depth). The whole row opens the player page (click, Enter or Space). Width stays at 1180px (Alan: a focused waiver board, not a spreadsheet). Default order = SPAM rank; sorts: weekly projection, recent form, season PPG, matchup, position rank, trending adds. **Trending adds** come from Sleeper's documented, keyless `/players/nfl/trending/add?lookback_hours=24` (all of Sleeper, not this league; memory only, 10-minute cache, `TREND`); it stands in for roster %, which Sleeper's public API doesn't have. "My team fit" checkbox nudges the rank (starters ×0.85, bench depth ×1.1) and never re-sorts by fit alone. **Projection source:** SPAM's own weekly-pipeline projection (`proj_ppg`, rest-of-season PPG in the site's scoring) rescored per player with his league/site scoring ratio over his recent games (`projRatios`, position average as fallback); Bye / Out (this week's report) / — when missing, never a fake 0; not matchup-adjusted. Sleeper's public API has no projections and no roster %, so there's no Roster % column (trending adds instead) and no FAAB suggestions.
- **Trade Calculator:**
  - 2-team, plus optional 3-team.
  - League mode with roster context (lineup impact, team-specific value, position rooms).
  - Verdict tiers in `TRADE_VERDICTS`.
  - Consolidation bonus and roster-spot cost are small and capped.
  - One compact setup bar: League · Team 1 vs Team 2 (· Team 3) · + Add third team · "League context: <league>" indicator.
  - Each card's head (league mode with a team picked): team avatar, team name + "gets", one short line "Manager: X · Needs QB · Strong RB, TE", and the total it receives.
  - Cards keep "gets" semantics. In a 2-team league trade, each card's main button is "+ Add from <partner>'s roster" (the players it receives come from the other team); "Or search any player (hypothetical)" is secondary. 3-team mode keeps each team's own roster with send-to buttons.
  - Rows read: name on line 1; line 2 = position badge · NFL team · owner (just the partner's team name when he comes from the trade partner, else "Owned by X" / My team / Free agent; 3-team shows the "from" menu instead). Value right-aligned.
  - Verdict card is compact: verdict, adjusted difference, one-line reason, then Balance / Swap / Clear on one row; Why?, Roster impact (lineup changes) and Value breakdown stay collapsed.
  - Universal mode (No league) drops team names, avatars and ownership and goes back to You / They. **Values still follow the active format** (Alan, Oct 4: fixes a bug where "No league" with a league connected silently used base values): the connected league's settings, or your Custom format / League settings; base SPAM values only when no format is set at all. The context bar says whose settings the values use.
  - Value breakdown ends with a **Format adjustment** table for every player in the trade: Base SPAM Value → Scoring → TE premium (from → to) → Lineup & league size → League-adjusted Value. Each step is measured from the one before (the same `adjustValues` run on in-between formats), so they add up exactly; columns with nothing to show are hidden. Note that a step can move non-TEs too (e.g. TE premium changes flex replacement levels).
- **Trade Finder:**
  - League-wide discovery for one player, or a **2-player package from one roster**.
  - 1-for-1 or packages; 3-team cycles only for single players.
  - Cards read: partner → short verdict ("FAIR + GOOD FIT") → muted numbers → give/get → optional one-line roster insight → View full analysis (Alan, Oct 4). The insight (`shortWhy`) says *why* the deal makes sense, never *what* it is: a received player who'd mostly sit on the bench, a weak room fixed for both teams, fair on value but better for one lineup (with the reason), depth turned into a stronger room, or a room improved without opening a hole. When there's nothing non-obvious, the line is omitted. Detailed explanations stay inside the full analysis.
  - Built for scanning (Alan, Oct 4): partner (bigger avatar and name) → verdict (largest text) → players → fit; the raw/fit numbers line is small and muted. Good fit for both = thin green left edge; a bad fit for either side = dimmed card with the verdict in muted red (full opacity on hover/focus) so it's easy to skip. Actions are quiet text links ("Full analysis", "Open in calculator →"). Cards sit slightly lifted off the page. The first 10 ideas show, then "Show 10 more" (`TF_PAGE`; resets when the player or filters change). The selected player block above the list is its own card with a gold edge.
  - Generated trade text never makes a team name the subject of a verb ("the gooners swaps"); use possessives (`possOf`: "your", "Team's", "the gooners'").
  - Always uses league-adjusted values.
- **Main nav:** Rankings · My Team · League · Trade Finder · Trade Calculator. The Waiver Wire table lives in `#fa-wrap` inside the League panel (shown when `LT.sub === "waivers"`); its rows have no owner line (they're all available), just the availability line.
- **Themes:**
  - Light: cream `#F7F2EB`, burgundy `#5A1F32`, coral `#D96B5B`, peach `#F0B18A`, ink `#2E2A28`.
  - Dark: near-black `#1A1314`, burgundy surfaces, cream `#F3EDE4`, gold `#F4B979`.
  - All colors come from tokens at the top of the CSS.
  - Archivo typography.
  - Custom dropdowns, checkboxes and radios; no native controls.

## 11. Known limitations and unfinished work

- **Editor security:** editing is open to every visitor (Steven's temporary choice); only people with a GitHub token can publish. Real authentication is still to do.
- **Tests:** only `tests/format_check.py` so far (see §3).
- **IR / taxi spots** aren't format options; they don't change values.
- **Draft picks** are listed in trades but not valued.
- **Transactions and Matchups:** only for Sleeper leagues; ESPN/Yahoo imports have no transaction or matchup feed.
- **Not in the League hub yet (no reliable keyless source):** win probabilities, roster percentages, FAAB bid suggestions, K/DEF/IDP projections.
- **Player props / odds sources (researched Oct 4, nothing integrated):** every legitimate props feed needs an API key (The Odds API: NFL props incl. anytime TD, yards, receptions, attempts; free tier with a small credit budget where props cost markets × regions per game; paid plans above. Also SportsGameOdds, TheRundown, SharpAPI, OddsPapi with free tiers; OddsJam, Unabated, SportsDataIO paid). A key can't live in this static site, so props would come from a scheduled pipeline job with a repository secret, which SPAM doesn't have yet (§12). Decide the provider, check its terms for public display, and add the secret before building that job. Game lines (total, spread, implied totals) already come keyless from nflverse.
- **External projection sources (researched Oct 4, nothing integrated):** no free, documented source permits public website use. Sleeper's `api.sleeper.com/projections/nfl/{season}/{week}` has raw stats for every position incl. K/DEF/IDP keyed by Sleeper ID (ideal technically) but is undocumented (not in docs.sleeper.com, a different host from the documented `api.sleeper.app`), the data is reportedly RotoWire's licensed projections, it changed in Sept 2026, and Sleeper's API is free for non-commercial use only: only with Sleeper's written OK. FantasyPros API: documented, key required, free tier is non-production only, production needs a paid plan, public display/redistribution needs a commercial agreement. Fantasy Nerds: ~$200–400/yr, raw stat projections QB/RB/WR/TE/K + IDP (no weekly DEF), key. SportsDataIO: paid (~$99–149/mo self-serve), raw stats all positions, commercial licensing. MySportsFeeds: free for non-commercial personal use; projections are an add-on. Open source (nflverse/ffverse): no weekly projections (ffopportunity is expected points; ffanalytics scrapes sites). Recommended path: keep SPAM's model; have `project_players.py` output per-game raw stat projections (it already models targets/carries/attempts) so SPAM scores exactly per league; ask Sleeper or FantasyPros for permission before using theirs.
- **Deep tiers in shallow formats:** a 10-team 1QB board values QB13+ at a few hundred by design (tiers keep ≥40% of the value above).
- **Excel master workbook:** Steven & Alan's original Excel file (`StevenAlanRankings`, per-position Steven/Alan/Combined sheets) is **not synced** with the site. The website is now the source of truth. An Oct 2 copy with the 70 Auto players and a "SPAM Board" sheet was produced but isn't in the repo.
- **Old URLs:** `stevenp36.github.io/spmetrics-fantasy/` and (since the Oct 4 transfer) `stevenp36.github.io/spam/` are dead. A redirect page for either could live in a `stevenp36/stevenp36.github.io` user-site repo (`spam/index.html`, `spmetrics-fantasy/index.html`) if wanted; never recreate `stevenp36/spam`.
- **Custom domain:** not set up. Every path is relative; only `canonical`/`og:url` would change.
- **Player data:** some player-name matches use aliases (`pipeline/merge_projections.py` `ALIASES`, `pipeline/build_sleeper_ids.py` `ID_ALIASES`). Add an alias when a new player's projection or Sleeper ID comes up empty.
- **Known issues, not yet fixed (found in an Oct 3 code review):**
  - The README is stale: it says stats refresh weekly only (game-day runs exist), and its token section only mentions fine-grained tokens.
  - The scheduled workflow runs `git push` without pulling first. If someone publishes during the Tuesday job, the job's push is rejected and that run's deploy fails.
  - `mergeInto` merges rank columns per row. If Steven and Alan publish overlapping rank moves from stale pages, the board could end up with duplicate ranks. The 409 retry only catches a changed file.
  - The weekly projection refresh changes values for all model-valued players (all but the 4 with published values). Ranks and tiers stay fixed. This is by design.
  - The `trade-boost-preview` and `alan-dev` branches are already merged or were only tests. Either can be deleted.

## 12. Secrets, services, accounts

- **No API keys or repository secrets.** The workflow uses GitHub's built-in `GITHUB_TOKEN` (`contents: write`, `pages: write`, `id-token: write`).
- External services, all public and keyless:
  - Sleeper API (`api.sleeper.app`), called from the visitor's browser.
  - Sleeper CDN for photos.
  - ESPN's logo CDN (`a.espncdn.com/i/teamlogos/nfl/500/…`) for NFL team logos.
  - ESPN fantasy API for public leagues.
  - nflverse data releases and DynastyProcess player IDs (pipeline).
  - Google Fonts.
- Pages source: **GitHub Actions** (`Build and deploy site` workflow). Custom domain: none.

## 13. Working agreement for AI assistants

- Make the change, test it locally (Playwright if it touches behavior), bump `BUILD_ID`, `git pull --rebase`, commit with a clear message, push.
- Never rewrite or reorder `RANKINGS_CSV` as a side effect. Never commit tokens. Never remove Ranking History entries.
- Ask before anything irreversible (deleting data, renaming the repo, rewriting history).
- When you change a behavior described here, update this file in the same commit.
