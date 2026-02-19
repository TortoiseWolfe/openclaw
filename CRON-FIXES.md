# Cron Job Fixes — 2026-02-19

Overnight cron jobs are firing but largely ineffective. Tracking fixes here
so work can resume across context windows.

See also: `.claude/plans/shimmying-frolicking-sundae.md` for full investigation.

## Completed

- [x] **Twitch token auth** — `.env` baked into Docker image overrode refreshed
  tokens in `~/.openclaw/.env`. Fixed by adding `.env` to `.dockerignore`.
  Commit: `5b3ed7c52`
- [x] **Ollama context window (4K → 8K)** — Created Modelfile with
  `PARAMETER num_ctx 8192` via `ollama create`. Updated `contextWindow` in
  `~/.openclaw/openclaw.json` from 128000 to 8192, `maxTokens` from 8192 to 4096.
- [x] **ENOENT on contacts.md → Python helper** — Created
  `toolkit/cron-helpers/spoketowork_outreach.py`. Updated cron job message
  in `~/.openclaw/cron/jobs.json` to use the helper instead of LLM file reading.
- [x] **bootstrapMaxChars (5K → 12K)** — Updated `~/.openclaw/openclaw.json`
  from 5000 to 12000. AGENTS.md (10,477 chars) no longer truncated.
- [x] **RPG Game Night timeout (300s → 600s)** — Updated
  `~/.openclaw/cron/jobs.json` from 300 to 600.

## Pending — monitor after next cron cycle

- [ ] **Tool allowlist misses (deferred)**
  - 2x `exec denied: allowlist miss` — model called tools outside allowlist
  - "Unknown entries" warning at startup is cosmetic (MCP loads after validation)
  - May resolve now that context window is fixed (truncated context → hallucinated tool names)
  - Check `/tmp/openclaw/openclaw-*.log` inside container for denied tool names

## Config files reference

| File | Location | What |
|------|----------|------|
| openclaw.json | `~/.openclaw/openclaw.json` | Model config, bootstrapMaxChars |
| cron jobs | `~/.openclaw/cron/jobs.json` | 38 scheduled jobs with timeouts |
| Python helpers | `toolkit/cron-helpers/` (repo, mounted `:ro` at `/app/toolkit/`) | Mechanical work offloaded from LLM |
