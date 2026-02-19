# Repository Guidelines

Personal OpenClaw fork (formerly MoltBot). Runs entirely in Docker on WSL2.
Upstream: [openclaw/openclaw](https://github.com/openclaw/openclaw)

## Project Structure

- Source: `src/` (CLI in `src/cli`, commands in `src/commands`, infra in `src/infra`)
- Extensions: `extensions/*` (channel plugins like `extensions/twitch`)
- Tests: colocated `*.test.ts`
- Built output: `dist/` (compiled JS, runs inside Docker)
- Config templates: `config-examples/` (openclaw.json, mcporter.json, cron-jobs.json)
- Agent tooling: `toolkit/` (mounted read-only into Docker at `/app/toolkit`)
- Trading data: `trading-data/` (watchlist, candles, education)
- Video pipeline: `remotion/` (episode rendering with Steampunk design system)
- RPG system: `rpg/` (adventures, campaigns, maps)
- Docs: `docs/` (upstream reference docs)

## Docker Workflow

Everything runs in Docker. No `node_modules` on the host.

```bash
# Build image
docker build -t openclaw:local .

# Start all services (ollama, mcp-gateway, openclaw-gateway, remotion-renderer)
docker compose up -d

# Rebuild and restart after code changes
docker build -t openclaw:local . && docker compose up -d --force-recreate openclaw-gateway

# Pick up .env changes (docker compose restart does NOT re-read .env)
docker compose up -d --force-recreate openclaw-gateway

# Interactive CLI
docker compose run --rm openclaw-cli

# Check logs
docker compose logs openclaw-gateway --tail 50
```

## Workspace Layout

```
~/clawd/                          # Main agent workspace → /home/node/clawd
  skills/job-search/SKILL.md      # Job search skill (353 lines)
  skills/spoketowork/SKILL.md     # Business automation skill
  skills/forex-trading/SKILL.md   # Forex education & paper trading skill (298 lines)
  USER.md                         # Agent profile
  SOUL.md                         # Agent persona

~/clawd-twitch/                   # Twitch agent workspace → /home/node/clawd-twitch
  SOUL.md                         # Twitch host persona
  AGENTS.md                       # Operating instructions
  IDENTITY.md, USER.md, TOOLS.md  # Agent identity + tool config
  HEARTBEAT.md                    # Health check
  episodes.json                   # Episode metadata
  episodes/                       # Episode scripts
  branding/                       # Channel assets
  highlights/                     # Stream highlight logs
  renders/                        # Remotion video output
  schedule.md, channel-schedule*.md  # Stream schedules

~/.openclaw/                      # Config directory → /home/node/.openclaw
  openclaw.json                   # Main config (agents, models, channels, tools)
  config/mcporter.json            # MCP gateway connection
  cron/jobs.json                  # 38 scheduled cron jobs
  agents/                         # Agent session data
```

## Dependent Repos (mounted into Docker)

| Host path | Container path | What |
|-----------|---------------|------|
| `${OPENCLAW_CONFIG_DIR}` | `/home/node/.openclaw` | Config |
| `${OPENCLAW_WORKSPACE_DIR}` | `/home/node/clawd` | Main workspace + skills |
| `${TWITCH_WORKSPACE_DIR}` | `/home/node/clawd-twitch` | Twitch workspace |
| `${BUSINESS_DEV_REPO}` | `/home/node/repos/SpokeToWork---Business-Development` | SpokeToWork data |
| `${TRANSCRIPTS_REPO}` | `/home/node/repos/TranScripts` | Job search data, resume, references |
| `${TRADING_DATA_DIR}` | `/home/node/repos/Trading` | Trading data (forex, stocks, crypto) |
| `${DOCKER_MCP_CONFIG}` | `/root/.docker/mcp` (mcp-gateway) | Docker MCP Toolkit config |

All paths are env vars in `.env` (gitignored). See `.env.example` for the template.

## Job Search (Active)

**Start here:** `~/repos/TranScripts/Career/JobSearch/README.md`

Contains session continuation notes, remaining applications, leads to triage,
screening question answers, and file locations. All job data lives in
`~/repos/TranScripts/Career/JobSearch/private/` (gitignored — local only).

## Reference Files in TranScripts

Security and Docker best-practices reference materials:
- `~/repos/TranScripts/Claude_Edited/MoltBot/` -- setup/security expert guidance
- `~/repos/TranScripts/Docker/Docker_Edited/` -- Docker best practices notes

Trading data (in-repo at `trading-data/`, mounted via `${TRADING_DATA_DIR}`):
- `trading-data/education/` -- BabyPips progress, video notes, article summaries
- `trading-data/config/` -- multi-asset watchlist config
- `trading-data/data/` -- multi-asset candles (forex, stocks, crypto)
- `trading-data/private/` -- unified paper trading state and journal

## MCP Gateway

139 tools across 9 servers (LinkedIn, Gmail, Playwright, GitHub, YouTube, etc.)
exposed as a single SSE endpoint via Docker MCP Toolkit.

Connection: openclaw-gateway → `http://mcp-gateway:8808/sse` (Docker DNS)
Auth: `MCP_GATEWAY_AUTH_TOKEN` in `.env`

## Local Models (Ollama)

- **Primary**: `ollama/qwen3:8b-ctx16k` — Qwen3 8B with 16K context, fits in 8GB GPU (RTX 3060 Ti)
- **Fallback 1**: `ollama/llama3-groq-tool-use:8b-ctx16k` — tool-calling specialist (89% BFCL), 16K context
- **Fallback 2**: `ollama/llama3.1:8b-ctx16k` — general reasoning fallback, 16K context
- **Note**: RTX 3060 Ti has 8GB VRAM (not 12GB). 14B models don't fit — they spill to CPU RAM and timeout. All production models are 8B with 16K context (~7GB VRAM).
- Model scout cron job runs monthly (1st Saturday) to research upgrades
- Cognitive load split: local model handles mechanical tool work (file reads, API calls,
  data writes); judgment/analysis gets queued for user + Claude Code sessions

## Tool Scoping

Ollama models get a restricted tool set via `tools.byProvider` on each agent
in openclaw.json (NOT on `agents.defaults` — the defaults type doesn't support `tools`).
This cuts tools from 139+ MCP to 22 total, reducing system prompt from ~48K to ~22K chars.
Interactive Claude Code sessions are unaffected (byProvider only applies to ollama).

Verified: system prompt report shows 22 tools, 22,328 chars total prompt.

Allowed for Ollama: native file ops (read/edit/write/exec/process), web search/fetch,
LinkedIn (search_jobs, get_job_details, get_company_profile, get_person_profile,
get_recommended_jobs), Gmail (findMessage, listMessages), Maps (maps_search_places,
maps_directions), Playwright basics (browser_navigate, browser_snapshot, browser_click,
browser_fill_form), YouTube (get_transcript, get_video_info).

Denied for Ollama: GitHub (40 tools), Postman (39 tools), Git (12 tools), Cloudflare (2),
automation (cron/gateway), session management, all administrative tools.

Known issues: Previous qwen3:14b (9.3GB) exceeded RTX 3060 Ti 8GB VRAM — spilled to CPU
and timed out. Switched to qwen3:8b-ctx16k (~7.2GB VRAM) which fits with headroom.
OpenClaw requires minimum 16K context window (CONTEXT_WINDOW_HARD_MIN_TOKENS in
src/agents/context-window-guard.ts).

## Build and Test Commands

- Install deps: `pnpm install` (only needed if developing locally outside Docker)
- Type-check/build: `pnpm build` (tsc)
- Lint: `pnpm lint` (oxlint)
- Format: `pnpm format` (oxfmt)
- Tests: `pnpm test` (vitest)
- Runtime: Node 22+

## Coding Style

- Language: TypeScript (ESM). Prefer strict typing; avoid `any`.
- Formatting via Oxlint and Oxfmt.
- Keep files under ~500 LOC when feasible.
- Brief comments for tricky logic only.

## Security

- `.env` is gitignored. Never commit real API keys, tokens, or personal paths.
- `docker-compose.yml` uses `${VAR}` substitution for all personal paths.
- All ports bind to `127.0.0.1` only (no public exposure).
- MCP gateway uses a bearer token for auth (no default fallback — requires explicit token).
- Container runs as non-root `node` user (uid 1000).
- `init: true` ensures proper signal handling (Tini as PID 1).
- Personal data (resume, contacts) lives in TranScripts (private repo).

### Accepted Risks

- **Docker socket mount**: mcp-gateway mounts `/var/run/docker.sock` for Docker MCP Toolkit.
  This grants full daemon access but is required for the MCP gateway to function.
  Mitigated by loopback-only port binding and bearer token auth.
- **Prompt injection**: Inherent to all LLM-based agents. Every input channel (Twitch chat,
  email content, web pages) is a potential attack vector. Mitigated by sandbox mode,
  least-privilege tool access, and not exposing the bot to untrusted group chats.
- **Volume mounts**: Host directories (config, workspaces, repos) are mounted into containers.
  If a container is compromised, those directories are accessible. Use read-only mounts
  where possible (toolkit is already `:ro`).
- **Claude Max setup-token**: Anthropic cracked down on third-party tools using
  setup-tokens for autonomous loops (Jan 2026). Accounts have been banned.
  Local Ollama models are the primary strategy for cron jobs. Cloud models
  (API key or setup-token) are optional for interactive Claude Code sessions.

### Deferred Hardening

- **Ollama SPOF (C2)**: All 38 cron jobs (34 enabled) fail if Ollama is down. The model fallback
  infrastructure (`src/agents/model-fallback.ts:226-282`) supports mixed providers.
  To enable Anthropic as final fallback: set `ANTHROPIC_API_KEY` in `.env`, then add
  `"anthropic/claude-sonnet-4-5"` to the `model.fallbacks` array in
  `~/.openclaw/openclaw.json`. No code changes needed — just config + env var.
- **Env var exposure (S3)**: Tokens are visible via `docker inspect` and
  `/proc/<pid>/environ`. Inherent to Docker Compose; fix requires Swarm secrets or
  external vault. Acceptable for single-user local setup.
- **Cron failure alerting (C4)**: Already implemented. `src/cron/service/timer.ts:471,545,649`
  posts job errors to the main agent session via `enqueueSystemEvent()`.

## Multi-Agent Safety

- Do not create/apply/drop `git stash` entries unless explicitly requested.
- Do not switch branches unless explicitly requested.
- Do not create/remove `git worktree` checkouts unless explicitly requested.
- When committing, scope to your changes only.
- When you see unrecognized files, keep going; focus on your changes.

## Jonathan's Background — Comprehensive Reference

Use this section for cover letters, resume updates, job matching, and interview prep.
This is the single source of truth for Jonathan's skills and experience.

### Identity

- **Name:** Jonathan Pohlner (use "TurtleWolfe" casually, "Jonathan Pohlner" on applications)
- **Location:** Cleveland, TN 37312
- **Contact:** See ~/clawd/USER.md (not committed to git)
- **GitHub:** github.com/TortoiseWolfe (current), github.com/TurtleWolfe (older repos)
- **Portfolio:** TurtleWolfe.com
- **LinkedIn:** linkedin.com/in/pohlner
- **Twitch:** twitch.tv/turtlewolfe

### Employment History

**Trinam Drafting and Design** | Software Developer | Mar 2022 – Sep 2024 | Remote
- Built C# plugins for Revit drafting software (Autodesk BIM platform)
- Built WPF-based UI for embedding a chatbot into the Revit environment
- Explored MAUI and Blazor as alternative UI frameworks for the Revit integration
- Managed virtual Windows machines for their drafting team
- Used AWS for infrastructure alongside personal project AWS usage
- Small, high-trust team where he owned projects end to end
- **IMPORTANT:** This was C#/.NET plugin development + IT infrastructure.
  NOT full-stack web development, NOT database work at Trinam.

**TechJoy Software** | Software Engineering Intern | Jan – Mar 2022 | Remote
- Built responsive UI components in React and TypeScript for client web applications
- Integrated RESTful APIs following agile methodology

**Mercor** | Reviewer (Contract) | Jan 2026 – Present | Remote
- Runs evaluations on LLM models (strict NDA — do not describe specific work)
- Promoted to Reviewer after first shift
- Demonstrates recognized expertise in AI/LLM evaluation at a professional level

**TechJoy Software** | Peer Mentor | Nov 2024 – Present | Remote
- Effectively leads the AI development class — instructor says he's beyond her
  and consistently finds creative ways to push AI tooling further
- Teaches other interns how to use AI coding tools effectively
- Offloads logic to Python helper scripts to decrease token usage and improve
  reliable outcomes from LLM-assisted workflows — practical prompt engineering
- Code review, debugging support, weekly community learning sessions
- **Instructor endorsement** (direct quote): "Also how did you figure out that you
  can serve static Next on Github and use supabase db queries? ... You're always
  miles ahead of me and when I think ive figured it out my mind is blown again"
- LinkedIn endorsement from instructor requested (pending)

**Collective Minds Incorporated** | Lead Developer | Jan 2021 – Present | Remote
- Lead development of React and React Native applications
- Architected RESTful APIs using Node.js and Express
- Mentored junior developers and established coding standards

**ScriptHammer** | Full Stack Web Developer | Aug 2011 – Present | Cleveland, TN
- Designed and developed 20+ custom web applications for small business clients
- Built 1000+ React components across multiple projects
- Current iteration: Next.js 15 / React 19 / Supabase SaaS platform with 46 features
- AI-first development: 27-terminal orchestration with council governance, 12 slash commands, SpecKit workflow
- Game components specified: DiceRoller, CharacterSheet, InitiativeTracker, MapGrid, ChatPanel
- Manages full project lifecycle from requirements gathering to deployment

**Creative Touch** | Lead Graphic Designer | Oct 1995 – Dec 2018 | Cleveland, TN
- Led design team of 3, producing visual layouts for 100+ church directories annually

**Pohlner Landscaping** | Owner Operator | Mar 1997 – Mar 2020 | Cleveland, TN
- Family business (took over after father passed away)
- Built the company website — first software development project

**High Country Adventures** | Photographer | Mar 2012 – Oct 2016 | Ocoee, TN
- Photographed rafting groups on Ocoee River rapids, same-day photo processing and sales

### Technical Skills (Complete)

**Frontend:** React, React Native, TypeScript, JavaScript (ES6+), HTML5, CSS3, Next.js,
Tailwind CSS, Bootstrap, jQuery, Storybook, Responsive Design, Accessibility (WCAG),
Figma, Adobe Suite, UI/UX Design

**Backend:** Node.js, Express, C#/.NET, PHP, Python, RESTful APIs, GraphQL

**.NET Frameworks:** WPF, Blazor, MAUI (explored for Revit chatbot integration)

**Databases:** PostgreSQL (extensive — see below), MongoDB, MySQL, Firebase, Supabase

**DevOps/Infra:** Docker, Docker Compose, AWS, Git, GitHub Actions, CI/CD, Linux,
Windows Server administration, VM management

**Testing:** Jest, Vitest, Playwright, Cypress, React Testing Library, Storybook

**AI/ML Tools:** Claude Code (primary dev environment), GitHub Copilot, LLM integration,
MCP tool orchestration, prompt engineering

**Design:** 20+ years — Adobe Photoshop, GIMP, Figma, Typography, Wireframing,
Information Architecture, 3D/AR work with C# and Unity

### Key Skill Details

**Node.js — 10+ years.** Started making games with Node.js over a decade ago, before
the ecosystem was mature. Has kept shipping with it since. This is NOT limited to
professional experience at Trinam — it predates that by years.

**PostgreSQL — Extensive.** Years of schema design from game development — prototyping
different versions of games, reworking data models across iterations. Current usage is
through Supabase (which is PostgreSQL): RLS policies, migrations, triggers, audit logging,
TypeScript type generation, GDPR/SOC 2 compliance patterns. Do NOT describe as "basic"
or "partial." Do NOT attribute to Trinam — PostgreSQL experience is from game dev and
personal projects.

**AWS — Real experience.** Used at both Trinam AND personal projects (including
Drupal_on_AWS, personal infrastructure). Do NOT describe as "basic" or "limited."

**React — Daily production use.** SpokeToWork, ScriptHammer, OpenClaw. 1000+ components
across projects. React Native for mobile (Expo).

**Python — 6 years.** Started ~2020. Used for scripting, automation, LLM helper scripts
(token reduction), Joy of Coding Academy coursework. Currently pursuing CompTIA Data+.

**Linux — 9+ years.** Server administration, Docker/WSL2, web hosting, CI/CD pipelines.

**C#/.NET — Professional.** 2.5 years at Trinam building Revit plugins. WPF for desktop UI,
explored Blazor and MAUI. Also Unity/C# for 3D/AR work on TurtleWolfe.com portfolio.

**AI Code Generation — 2 years.** Claude Code (primary dev environment), GitHub Copilot.
Built OpenClaw fork orchestrating 139 MCP tools. Daily AI-assisted development since 2024.

**Rust — 0.** Hello world only. Do not claim experience.
**Scala — 0.** No experience.
**Ruby — 0.** No experience.

### Major Projects

**OpenClaw / MoltBot** (2025–present) — Docker-based AI agent pipeline
- Fork of openclaw/openclaw with custom services (Ollama, MCP gateway, Remotion)
- Node.js/TypeScript, orchestrates 139 MCP tools through a gateway
- Scheduled cron jobs, multi-agent sessions, Twitch integration
- External API integrations: LinkedIn, Gmail, YouTube, Google Maps, GitHub
- Ollama local models for autonomous operation
- This is the most technically impressive current project for AI-focused roles.

**ScriptHammer** (2011–present) — SaaS platform / app factory
- Next.js 15, React 19, TypeScript, Supabase (PostgreSQL), Tailwind CSS
- 46 features across 8 categories (foundation, auth, core, enhancements,
  integrations, polish, testing, payments)
- 27-terminal AI orchestration: 7 council (CTO, ProductOwner, Architect,
  UXDesigner, Toolsmith, Security, DevOps) + 19 contributors + 1 operator
- Formal governance: RFC process (draft→proposed→review→voting→decided),
  9 decision records, memo routing (mixture-of-experts gating), broadcasting
- 68 audit files produced in 2 days (wireframe validation, security reviews)
- Operator handoff primers for multi-day session continuity
- 12 SpecKit slash commands for specification-driven development
- Game components: DiceRoller, CardDeck, CharacterSheet, InitiativeTracker, MapGrid
- PostgreSQL via Supabase with RLS, migrations, triggers, audit logging
- Docker Compose dev environment with Storybook, Vitest, Playwright

**SpokeToWork** (2025–present) — Workforce mobility platform
- Next.js 15, React 19, TypeScript, Supabase
- PWA with offline support, bike route planning
- Connecting workers without car access to employment within cycling distance
- Social impact / mission-driven — good talking point for nonprofit roles

**ChatRPG** (GitHub: TortoiseWolfe/ChatRPG) — RPG gamemaster + social network
- Open source game project — demonstrates Node.js + game dev history
- Where PostgreSQL schema design experience comes from

**StarWarRPG** (GitHub: TortoiseWolfe/StarWarRPG) — Star Wars West End Games RPG
- Character templates and game system implementation

**Punk Stack** — Design system with 12 cyberpunk/solarpunk/steampunk themes
- Next.js 15, DaisyUI 5, React 19, TypeScript, Tailwind CSS 4
- Docker Compose, Vitest, Storybook, Chromatic visual regression

**Other GitHub repos:** ThreeJsSeanBradley (Three.js + TypeScript), ExpoDevOps
(Expo + Docker + ChatGPT), WinSer22 (Windows Server admin), Docker-on-Ubuntu,
Drupal_on_AWS, Revit (BIM productivity), rn_Turtorial_Outline (React Native tutorials),
DevCamper API (Node.js + Express + MongoDB + JWT auth)

### Education & Certifications

- CAD Certificate — Cleveland State Community College (1996, GPA 3.8)
- High School Diploma — Bradley Central High School (1993)
- FreeCodeCamp Front End Libraries Certification (2021)
- Node.js API Masterclass (Udemy, 2020)
- Indeed: Software Developer Skills (Proficient), Problem Solving (Expert)
- CompTIA Data Analytics — currently enrolled, targeting March 2026 completion
- No CS degree — DO NOT volunteer this in cover letters

### Cover Letter Rules

- **Never lead with weaknesses.** No "I'll be direct/upfront/straightforward: [thing I can't do]."
  If a skill transfers, just say it transfers. If it's irrelevant, don't mention it.
- **Never volunteer gaps.** Don't say "I don't have X experience" unless directly asked.
  Focus on what IS there, not what isn't.
- **Trinam accuracy matters.** Always describe as C# Revit plugins (WPF/Blazor) +
  VM infrastructure. Never say "full-stack web apps" or "front-end and back-end systems."
- **Don't undersell.** "Basic AWS" is wrong. "Partial PostgreSQL" is wrong. These are
  real skills from real projects.
- **Don't position as junior** when he has 10+ years of development experience.
  Entry-level listings are foot-in-the-door opportunities, not reflections of skill level.
- **ScriptHammer is the AI differentiator.** For AI roles, lead with ScriptHammer's
  27-terminal orchestration with council governance. This demonstrates AI at scale.
- **OpenClaw is workflow customization.** Not a product — it's how Jonathan works.
  A personal Docker pipeline with 139 MCP tools and autonomous cron jobs.
  Mention to show he customizes AI tooling to his own workflows.
- **ScriptHammer shows scale.** 46 features across 8 categories, 27 AI terminals with formal
  governance (RFC process, council voting, audit trails), 680+ tests.
  One operator managing an entire AI-assisted development pipeline.
- **Instructor endorsement is available.** TechJoy instructor quote ("You're always
  miles ahead of me") can be referenced in cover letters where teaching, mentoring,
  or AI leadership is relevant.
- **Design background is an asset.** 20+ years of graphic design means he thinks
  about UX, typography, layout, and visual hierarchy before writing code.
  Use this for design-adjacent roles (LifeMD, Crossing Hurdles, True Social).
- **Answer questions, don't jump to edits.** If user asks "what do you think," answer
  the question first. Don't silently rewrite content without discussing.

## Commit Guidelines

- Concise, action-oriented messages (e.g., `chore: update config templates`).
- Group related changes; avoid bundling unrelated refactors.
- Never commit `.env` or files containing real secrets.
