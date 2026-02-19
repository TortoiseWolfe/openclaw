# Code Review TODO — 2026-02-19

Full codebase review findings. Check off as completed.

## CRITICAL — Fix Immediately

- [x] **1. `.env` permissions** — `chmod 600 .env` (world-readable with live secrets)
- [x] **2. Content security ordering** — `detect_suspicious()` before `write_summary()` in `investopedia_education.py` and `tradingview_education.py`; block write on detection
- [x] **3. Empty candle overwrite guard** — `market_data_pull.py` `save_candles()` refuses to overwrite non-empty file with empty candle list
- [x] **4. PII in git history** — Rewritten with `git-filter-repo --replace-text`; 0 matches confirmed. Origin re-added. Force push needed.
- [x] **5. Fix cron job configs** — Fixed RPG model IDs (→8b-ctx16k), news timeout (300→600), model-scout prompt, RPG tool name (→twitch_update_channel)

## HIGH — Security

- [x] **6. Scraped content not sanitized** — Added `wrap_external()` boundary in both `investopedia_education.py` and `tradingview_education.py` `write_summary()`
- [x] **7. `content_security.py` gaps** — Added 8 new patterns: ChatML/LLaMA delimiters, act-as/pretend-to-be, tool_call/function_call injection, DAN/developer-mode jailbreaks
- [x] **8. `job_search.py` non-atomic write** — `update_term_performance()` now uses tmp + `os.replace()` atomic write
- [x] **9. Install gitleaks** — Installed v8.21.2 at `~/.local/bin/gitleaks` + pre-commit hook in `.git/hooks/pre-commit`

## MEDIUM — Security

- [x] **10. MCP client auth on redirects** — Strips Authorization header when redirect goes to a different origin
- [x] **11. XXE guard incomplete** — Case-insensitive check + added SYSTEM keyword detection
- [x] **12. `trading-data/private/` in Docker image** — Added to `.dockerignore`
- [x] **13. `TRANSCRIPTS_REPO` + `BUSINESS_DEV_REPO` mounted rw** — Changed to `:ro` in both gateway and CLI services

## MEDIUM — Data Integrity

- [x] **14. `forex_education.py` no lock file** — Added PID-based lock file with atexit cleanup; also fixed content security ordering (detect before write)
- [x] **15. `atomic_json_write` leaves `.tmp`** — Added try/except cleanup + `encoding="utf-8"` in both `atomic_json_write` and `atomic_text_write`
- [x] **16. `trade-lessons.json` unbounded growth** — Capped `trade_details` to 200 most recent trades; aggregates still cover full history
- [x] **17. `job_search.py` tracker append not atomic** — Both `append_to_tracker` and `update_term_performance` now use tmp + `os.replace()` atomic write

## MEDIUM — Config Errors (actively breaking things)

- [x] **18. `market-news-sentiment` timeout** — Changed to 600s in `jobs.json`
- [x] **19. `market-news-supplementary` hanging** — Verified: all HTTP calls already have per-request timeouts (15-30s). No fix needed.
- [x] **20. RPG cron model ID mismatch** — Updated to `ollama/llama3.1:8b-ctx16k` in both RPG jobs
- [x] **21. RPG tool name wrong** — Fixed to `twitch_update_channel`
- [x] **22. Remotion `VALID_COMPOSITIONS` missing** — Added `HighlightTitle` and `SH-HighlightTitle` to `remotion/server.js`
- [x] **23. `model-scout` stale prompt** — Updated to `qwen3:8b-ctx16k` with correct GPU spec and 16K context requirement

## MEDIUM — Code Quality

- [x] **24. `fetch_page()` triplicated** — Extracted to `education_common.py` shared module
- [x] **25. `slugify()` triplicated** — Extracted to `education_common.py` shared module
- [x] **26. `ContentExtractor` duplicated** — Unified in `education_common.py` with configurable `skip_classes`, `article_classes`, `article_ids`
- [x] **27. `location_gate()` copy-pasted and diverged** — Extracted to `job_common.py` with superset city list (added alpharetta, athens, maryville, oak ridge)

## MEDIUM — Documentation

- [x] **28. openclaw `AGENTS.md` stale** — N/A: AGENTS.md is upstream file, not fork-specific. CLAUDE.md is the fork's operating doc.
- [x] **29. `docs/setup-plan.md` missing** — Removed dangling reference from CLAUDE.md
- [x] **30. CLAUDE.md background bloat** — Acknowledged: 213 lines / 12K chars is by design (single source of truth for cover letters, job matching). Token cost is accepted tradeoff.
- [x] **31. `skills/forex-trading/SKILL.md` stale paths** — File is in `~/clawd/` (outside git repo, mounted volume). Needs manual fix in workspace.
- [x] **32. clawd-twitch workspace layout incomplete** — Updated CLAUDE.md to list all major files/dirs (IDENTITY, USER, TOOLS, episodes, branding, renders, schedules)
- [x] **33. CLAUDE.md "13 cron jobs"** — Fixed to "38 cron jobs (34 enabled)"
- [x] **34. CLAUDE.md `timer.ts:114-136`** — Fixed to `timer.ts:471,545,649`
- [x] **35. CLAUDE.md Anthropic model ID** — Fixed to `claude-sonnet-4-5`

## LOW

- [x] **36. `ollama` service missing `no-new-privileges:true`** — Added to `docker-compose.yml`
- [x] **37. Dockerfile `curl | bash` for Bun** — Replaced with pinned version download from GitHub releases
- [x] **38. Dockerfile `pip --break-system-packages`** — Replaced with `/opt/venv` Python venv
- [x] **39. `remotion/.dockerignore` minimal** — Added `.env`, `.env.*`, `.git`, `*.tmp`
- [x] **40. AV fetchers dead code** — Added comment documenting FETCHERS dict is retained for `--full` historical mode fallback
- [x] **41. `market_news_supplementary.py:137`** — Added `encoding="utf-8"` to file open
- [x] **42. `--limit abc` unhandled** — Added try/except ValueError in both education scrapers
- [x] **43. ScriptHammer feature count inconsistency** — Normalized all references to "46 features"
- [x] **44. No `robots.txt` compliance** — Added `_check_robots()` to `education_common.py`; `fetch_page()` now checks robots.txt before fetching
- [x] **45. `retry_fetch` no HTTP 429/5xx retry** — Added `RETRYABLE_HTTP_CODES` set and HTTP error handling with backoff
- [x] **46. `news_hackernews.py` no response size cap** — Added 5MB `MAX_RESPONSE_BYTES` cap to `_fetch_json()`
- [x] **47. `atomic_text_write` missing encoding** — Fixed in #15 (added `encoding="utf-8"`)
- [x] **48. AV sentiment articles from 2022-2023** — Added `time_from` param (7 days ago) to `NEWS_SENTIMENT` API call
