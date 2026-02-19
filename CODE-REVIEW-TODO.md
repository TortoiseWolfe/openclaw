# Code Review TODO — 2026-02-19

Full codebase review findings. Check off as completed.

## CRITICAL — Fix Immediately

- [x] **1. `.env` permissions** — `chmod 600 .env` (world-readable with live secrets)
- [x] **2. Content security ordering** — `detect_suspicious()` before `write_summary()` in `investopedia_education.py` and `tradingview_education.py`; block write on detection
- [x] **3. Empty candle overwrite guard** — `market_data_pull.py` `save_candles()` refuses to overwrite non-empty file with empty candle list
- [ ] **4. PII in git history** — Phone + email in CLAUDE.md:210-211 committed to git. Must rewrite history with `git filter-repo` or BFG, then install gitleaks pre-commit hook
- [ ] **5. Fix cron job configs** — RPG model IDs, news timeouts, model-scout stale prompt, RPG tool name

## HIGH — Security

- [ ] **6. Scraped content not sanitized** — Raw content persisted without `sanitize_field()` or `wrap_external()` boundary in `investopedia_education.py:255`, `tradingview_education.py:210`
- [ ] **7. `content_security.py` gaps** — Missing ChatML/LLaMA delimiters (`<|im_start|>`, `[INST]`), "act as"/"pretend to be", `<tool_call>` injection, jailbreak templates
- [ ] **8. `job_search.py` non-atomic write** — `update_term_performance()` uses `open(TERM_PERF, "w")` instead of `atomic_text_write()`
- [ ] **9. Install gitleaks** — Add as pre-commit hook to prevent future secret/PII commits

## MEDIUM — Security

- [ ] **10. MCP client auth on redirects** — `mcp_client.py:198-214` sends bearer token to redirect destinations without origin check
- [ ] **11. XXE guard incomplete** — `news_rss.py:33-35` byte-substring check bypassed by encoding tricks
- [ ] **12. `trading-data/private/` in Docker image** — Not in `.dockerignore`, gets baked into image via `COPY . .`
- [ ] **13. `TRANSCRIPTS_REPO` + `BUSINESS_DEV_REPO` mounted rw** — Could be `:ro` in `docker-compose.yml`

## MEDIUM — Data Integrity

- [ ] **14. `forex_education.py` no lock file** — Concurrent runs corrupt curriculum; `triage_saved_jobs.py` has a lock file pattern to follow
- [ ] **15. `atomic_json_write` leaves `.tmp`** — `trading_common.py:225-231` doesn't clean up temp file if `json.dump` raises; use `tempfile.mkstemp` with try/except like `rpg_state.py`
- [ ] **16. `trade-lessons.json` unbounded growth** — `market_post_mortem.py:416-451` `trade_details` list grows forever
- [ ] **17. `job_search.py` tracker append not atomic** — Crash leaves partial markdown rows, corrupts dedup

## MEDIUM — Config Errors (actively breaking things)

- [ ] **18. `market-news-sentiment` timeout** — Currently 300s, needs 600s in `jobs.json`
- [ ] **19. `market-news-supplementary` hanging** — Already at 600s timeout, script needs per-request timeout in Python
- [ ] **20. RPG cron model ID mismatch** — `ollama/llama3.1:8b` should be `ollama/llama3.1:8b-ctx16k` in `jobs.json:1207,1238`
- [ ] **21. RPG tool name wrong** — `twitch_manage_channel` should be `twitch_update_channel` in `jobs.json:1204`
- [ ] **22. Remotion `VALID_COMPOSITIONS` missing** — `HighlightTitle` and `SH-HighlightTitle` not in `remotion/server.js:36-47`
- [ ] **23. `model-scout` stale prompt** — References `qwen3:14b-ctx8k` and wrong GPU spec in `jobs.json:713`

## MEDIUM — Code Quality

- [ ] **24. `fetch_page()` triplicated** — Extract to shared module from `forex_education.py`, `investopedia_education.py`, `tradingview_education.py`
- [ ] **25. `slugify()` triplicated** — Same three files
- [ ] **26. `ContentExtractor` duplicated** — `forex_education.py` vs `tradingview_education.py` with diverged config
- [ ] **27. `location_gate()` copy-pasted and diverged** — `job_search.py:130-160` vs `triage_saved_jobs.py:103-117` have different city lists

## MEDIUM — Documentation

- [ ] **28. openclaw `AGENTS.md` stale** — Not symlinked to CLAUDE.md, 2-day divergence with wrong GPU/models
- [ ] **29. `docs/setup-plan.md` missing** — Referenced in CLAUDE.md:17 but doesn't exist
- [ ] **30. CLAUDE.md background bloat** — ~5K chars (52% of file) of resume data in every session; extract to separate file
- [ ] **31. `skills/forex-trading/SKILL.md` stale paths** — References `~/repos/trading-data/Forex/...` (actual: `~/repos/openclaw/trading-data/`)
- [ ] **32. clawd-twitch workspace layout incomplete** — CLAUDE.md:53-56 lists 3 items, actual has 13+ files
- [ ] **33. CLAUDE.md "13 cron jobs"** — Actually 38 (34 enabled)
- [ ] **34. CLAUDE.md `timer.ts:114-136`** — Line reference 330+ off; actual lines 471, 545, 649
- [ ] **35. CLAUDE.md Anthropic model ID** — `claude-sonnet-4-20250514` should be `claude-sonnet-4-5`

## LOW

- [ ] **36. `ollama` service missing `no-new-privileges:true`** — `docker-compose.yml`
- [ ] **37. Dockerfile `curl | bash` for Bun** — Supply chain risk; use verified-hash install
- [ ] **38. Dockerfile `pip --break-system-packages`** — Use venv instead
- [ ] **39. `remotion/.dockerignore` minimal** — Missing `.env*`, only 3 entries
- [ ] **40. AV fetchers dead code** — `FETCHERS` dict in `market_data_pull.py:199-203` never called (`uses_yahoo=True` always)
- [ ] **41. `market_news_supplementary.py:137`** — Missing `encoding="utf-8"` on file open
- [ ] **42. `--limit abc` unhandled** — Both education scrapers need try/except ValueError
- [ ] **43. ScriptHammer feature count inconsistency** — CLAUDE.md "45+" vs "46" in three places
- [ ] **44. No `robots.txt` compliance** — All education scrapers; ethical/legal concern
- [ ] **45. `retry_fetch` no HTTP 429/5xx retry** — `trading_common.py:170-192`
- [ ] **46. `news_hackernews.py` no response size cap** — `_fetch_json()` reads unlimited bytes
- [ ] **47. `atomic_text_write` missing encoding** — `trading_common.py:237-240`
- [ ] **48. AV sentiment articles from 2022-2023** — API returns old articles by relevance, not recency
