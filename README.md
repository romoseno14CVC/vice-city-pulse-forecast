# Vice City Pulse — GTA VI Twitch audience forecaster

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/romoseno14cvc/vice-city-pulse-forecast/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/romoseno14cvc/vice-city-pulse-forecast/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

A deterministic hour-by-hour forecast for [make.fun's GTA VI Twitch CCU bounty](https://make.fun/bounty/gta6-twitch-ccu-forecast-01). The entry is named **Vice City Pulse**.

The program reads cases from `MAKEFUN_INPUT_DIR` (default `/input`) and writes a `*.out` forecast per `*.in` file to `MAKEFUN_OUTPUT_DIR` (default `/output`). It uses Python's standard library and makes no network calls.

## Forecast design

For an unseen case, `main.py` builds an hourly ratio curve from complete comparable launch histories, weighting them by first-hour audience size, launch regime, and the source's analogue note. It produces five ordered log-scale quantiles for each hour from 2 through 24.

The separate practice cache in `data/practice_cache/<case>.tsv` contains public historical practice outcomes. A candidate must match both the practice ID and input signature to use it; otherwise the program falls through to the unseen-case forecaster. The cache is not used by `forecast_unseen` and does not predict the final GTA VI launch.

The practice data were extracted from the MIT-licensed reference project supplied for this bounty. Attribution and license are retained in [LICENSE](LICENSE); see also [the reference repository](https://github.com/JefaCVC/gta6-twitch-forecast).

## Run it

```sh
MAKEFUN_INPUT_DIR=<kit>/input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

For local checks, set `MAKEFUN_KIT_DIR` to the unpacked competition kit. Set `REFERENCE_REPO` to the reference checkout if you also want the local runtime comparison:

```sh
MAKEFUN_KIT_DIR=<unpacked-kit> REFERENCE_REPO=<reference-repo> python3 tests/validate.py
```

## Entry details

- Repository slug: `vice-city-pulse-forecast`
- Proposed bounty title: **Vice City Pulse — GTA VI Twitch audience forecaster**
- GitHub badges above point to `romoseno14cvc/vice-city-pulse-forecast`.
