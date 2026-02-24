# Toolkit Restructuring Plan

**Status:** In Progress
**Date:** 2026-02-23

`toolkit/cron-helpers/` has 77 files (89 total across toolkit). This plan
reorganizes them into logical subdirectories while keeping `sys.path` imports
and cron job paths working.

---

## Current Layout

```
toolkit/
├── cron-helpers/          77 files — flat dumping ground
├── host-scripts/           4 files — OK as-is
├── README.md + utils etc.  8 files — writing toolkit (unrelated)
```

## Target Layout

```
toolkit/
├── cron-helpers/          shared libs + cron-specific glue only
├── rpg/                   RPG game engine + session management
├── video/                 episode rendering + TTS + Remotion client
├── obs/                   OBS WebSocket + show orchestration
├── twitch/                Twitch API + token refresh + schedule sync
├── trading/               market data, signals, backtesting, news
├── education/             BabyPips, Investopedia, TradingView scrapers
├── jobs/                  job search, triage, term picking
├── episode/               episode parsing, validation, playback
├── host-scripts/          (unchanged)
├── docs/                  schedule .md files, style guides, checklists
```

## Migration Rules

1. Tests move with their source files
2. Shared libs (`*_common.py`, `content_security.py`, `mcp_client.py`, `path_utils.py`) stay in `cron-helpers/`
3. Each new subdir gets an empty `__init__.py`
4. `sys.path.insert` in every moved file updated to include BOTH the new dir AND `cron-helpers` (for shared imports)
5. Cron job commands in `~/.openclaw/cron/jobs.json` updated to new paths
6. Docker mount stays the same (`toolkit/` → `/app/toolkit`) — subdirs are already accessible

---

## Checklist

### Phase 1: RPG files → `toolkit/rpg/`

- [x] Create `toolkit/rpg/` with `__init__.py`
- [x] Move `rpg_game_night.py`
- [x] Move `rpg_game_night_setup.py`
- [x] Move `rpg_session_runner.py`
- [x] Move `rpg_state.py`
- [x] Move `rpg_bot_common.py`
- [x] Move `rpg_bot_test.py`
- [x] Move `rpg_transcript.py`
- [x] Move `rpg_show_flow.py`
- [x] Update `sys.path` in all moved files
- [x] Update subprocess paths in rpg_game_night.py, rpg_bot_common.py, rpg_show_flow.py
- [x] Update config-examples/cron-jobs.json
- [x] Update rpg/shared/GM-GUIDE.md
- [x] Verify zero remaining `cron-helpers/rpg_` references

### Phase 2: Video files → `toolkit/video/`

- [x] Create `toolkit/video/` with `__init__.py`
- [x] Move `render_episode.py`
- [x] Move `render_episode_branding.py`
- [x] Move `render_narrated.py`
- [x] Move `render_video.py`
- [x] Move `remotion_client.py`
- [x] Move `generate_narration.py`
- [x] Move `migrate_renders.py`
- [x] Update render_episode.py sys.path for parse_episode in cron-helpers
- [x] Update play_episode.py subprocess path for render_episode_branding.py
- [x] Update config-examples/cron-jobs.json (5 render paths)
- [x] Verify zero remaining `cron-helpers/render_` references

### Phase 3: OBS files → `toolkit/obs/`

- [x] Create `toolkit/obs/` with `__init__.py`
- [x] Move `obs_client.py`
- [x] Move `obs_health_check.py`
- [x] Move `show_flow.py`
- [x] Update sys.path in show_flow.py for cron-helpers (path_utils)
- [x] Update RPG files with /app/toolkit/obs path
- [x] Update play_episode.py with obs/twitch paths
- [x] Update config-examples (obs_health_check, obs_client, inline sys.path)
- [x] Verify zero remaining cron-helpers/obs_ references

### Phase 4: Twitch files → `toolkit/twitch/`

- [x] Create `toolkit/twitch/` with `__init__.py`
- [x] Move `twitch_client.py`
- [x] Move `twitch_token_refresh.py`
- [x] Move `sync_twitch_schedule.py`
- [x] Update RPG files with /app/toolkit/twitch path
- [x] sync_twitch_schedule.py already has cron-helpers path for parse_episode
- [x] twitch_client.py + twitch_token_refresh.py colocated — imports work
- [x] Verify zero remaining cron-helpers/twitch_ references

### Phase 5: Episode files — DEFERRED

Episode files (`parse_episode.py`, `play_episode.py`, `validate_episode.py`) kept in
`cron-helpers/` as shared libs — too many cross-directory importers.

### Phase 6: Trading files → `toolkit/trading/`

- [x] All 27 trading files moved (19 source + 7 tests + 1 migration)
- [x] Added sys.path for cron-helpers in news_rss, news_hackernews, news_babypips
- [x] Updated config-examples/cron-jobs.json (7 trading job paths)
- [x] Updated play_episode.py with /app/toolkit/trading path

### Phase 7: Education files → `toolkit/education/`

- [x] All 5 education files moved (3 scrapers + common + 1 test)
- [x] Added sys.path for cron-helpers (content_security) in all 3 scrapers
- [x] Updated config-examples/cron-jobs.json (4 education job paths)
- [x] Updated news_babypips.py with /app/toolkit/education path

### Phase 8: Job search files → `toolkit/jobs/`

- [x] All 8 job files moved (5 source + 3 tests)
- [x] Added sys.path for cron-helpers (content_security, mcp_client) in job_search, triage_saved
- [x] Fixed content_security import ordering in job_search.py
- [x] Updated config-examples/cron-jobs.json (5 job search paths)

### Phase 9: Docs → `toolkit/docs/`

- [x] Moved channel-schedule.md, channel-schedule-twitch.md
- [x] Moved writing-style-guide.md, prompt-complexity-checklist.md, feedback-quality-checklist.md
- [ ] README.md left at toolkit root (it's the toolkit README, not a doc)

### Phase 10: SpokeToWork files → `toolkit/jobs/`

- [x] Merged into jobs/ (business outreach is job-adjacent)
- [x] Moved spoketowork_outreach.py, spoketowork_rotation.py, web_board_rotation.py + 2 tests
- [x] Updated config-examples/cron-jobs.json (spoketowork_rotation path)

### Phase 11: Cleanup

- [x] Add `screenshots/` to `.gitignore`
- [x] Remove `__pycache__` from cron-helpers
- [x] Move `map_base_builder.py` to toolkit/rpg/
- [x] Verify remaining `cron-helpers/` files are truly shared (11 files)
- [ ] Update CLAUDE.md project structure section
- [ ] Update MEMORY.md with new paths
- [ ] Update live cron jobs in `~/.openclaw/cron/jobs.json` (Docker)
- [ ] Smoke test: run 2-3 cron jobs in Docker to verify imports work

---

## Remaining in `cron-helpers/` after restructure

```
cron-helpers/
├── content_security.py    Input sanitization (21 patterns)
├── mcp_client.py          MCP-over-SSE client
├── mcp_test.py            MCP test helper
├── test_mcp_client.py     MCP client tests
├── module_loader.py       RPG JSON loader (shared)
├── parse_episode.py       Episode template parser (shared)
├── path_utils.py          Docker↔Windows path conversion
├── play_episode.py        Episode playback orchestrator
├── test_today_date.py     Date tests
├── today_date.py          Timezone-aware date
├── validate_episode.py    Episode validation
├── content_security.py    Input sanitization
├── today_date.py          Timezone-aware date
├── test_today_date.py     Date tests
```

8 files — genuine shared infrastructure.

---

## Risk Notes

- **Docker volume mount unchanged** — `toolkit/` maps to `/app/toolkit`, subdirs accessible as `/app/toolkit/rpg/` etc.
- **Cross-subdir imports** — RPG scripts import from twitch + obs. Will need `sys.path` entries for multiple subdirs.
- **Cron jobs** — ~40 jobs in `jobs.json` need path updates. Do this atomically per phase.
- **No code changes** — Only file moves + path updates. No logic changes.
