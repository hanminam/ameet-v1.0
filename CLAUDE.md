# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**AMEET v1.0** is an AI-powered collective intelligence discussion platform built with FastAPI and Python. The system orchestrates multi-agent debates where specialized AI agents (powered by LangChain, Google Gemini, OpenAI, and Anthropic) engage in structured discussions, analyze topics, and generate comprehensive reports.

## Essential Commands

### Development
```bash
# Install dependencies (using pip-compile workflow)
pip install -r requirements.txt

# Run locally (development server with auto-reload)
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Note: Must run from src directory
cd src
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Docker
```bash
# Build Docker image
docker build -t ameet-v1 .

# Run container (maps to port 8080 in production)
docker run -p 8080:8080 ameet-v1
```

### Deployment
- Google Cloud Run via Cloud Build
- Configuration in `cloudbuild.yaml`
- Deployment triggered on repository pushes

## Architecture Overview

### Core Discussion Flow (3-Stage Pipeline)

The system follows a sophisticated orchestration pattern:

1. **Stage 1: Orchestration** (`src/app/services/orchestrator.py`)
   - **Topic Analysis**: AI analyzes discussion topic using "Topic Analyst" agent
   - **Evidence Gathering**: Parallel web search and file processing
   - **Team Selection**: "Jury Selector" AI dynamically selects 4-6 expert agents from a pool, can create new agents on-demand if needed
   - Result: `DebateTeam` with judge + jury agents, stored in `DiscussionLog.participants`

2. **Stage 2: Discussion Rounds** (`src/app/services/discussion_flow.py`)
   - **Parallel Agent Execution**: All jury agents generate responses simultaneously using `asyncio.gather()`
   - **Tool Usage**: Agents autonomously decide whether to use web search via LangChain's AgentExecutor
   - **Central Search**: Before each round (except first), "Search Coordinator" generates a unified search query
   - **Analysis Pipeline**: After each round, three analyses run in parallel:
     - Stance Analysis: Tracks opinion changes (유지/강화/수정/약화)
     - Flow Analysis: "Interaction Analyst" identifies agent interactions (agreement/disagreement)
     - Round Summary: "Round Analyst" selects critical utterances
   - **Vote Generation**: "Vote Caster" creates dynamic vote options for user to guide next round

3. **Stage 3: Report Generation** (`src/app/services/report_generator.py`)
   - **Outline Generation**: "Report Outline Generator" creates structure from full transcript
   - **Chart Pipeline** (currently disabled): Intelligent chart generation for financial/economic topics
   - **HTML Generation**: "Infographic Report Agent" produces styled HTML report
   - **Transcript Append**: Full participant statements added as Section V
   - Result: Stored in `DiscussionLog.report_html` and `pdf_url`

### Database Architecture

**MongoDB (Beanie ODM)**:
- `DiscussionLog` (collection: discussions): Full discussion state, transcript, status
- `AgentSettings` (collection: agents): Dynamic agent configurations with versioning
- `User` (collection: users): User accounts with role-based access
- `SystemSettings` (collection: system_settings): Key-value configuration store

**Redis**:
- User vote history: `vote_history:{discussion_id}` (TTL: 24 hours)
- Environment-aware: Uses `LOCAL_REDIS_HOST` locally, `CLOUD_REDIS_HOST` in Cloud Run

### Agent System

**Special Agents** (type: "special", fixed roles):
- `재판관` (Judge): Moderates and guides discussion
- `비판적 관점` (Critical Perspective): Forced inclusion, challenges consensus
- `Topic Analyst`: Initial topic analysis
- `Jury Selector`: Team composition
- `Search Coordinator`: Generates search queries
- `Stance Analyst`: Tracks opinion evolution
- `Round Analyst`: Identifies critical moments
- `Interaction Analyst`: Maps agent relationships
- `Vote Caster`: Creates vote options

**Expert Agents** (type: "expert", dynamic):
- Loaded from MongoDB (`agent_type: "expert", status: "active"`)
- Can be created dynamically by Jury Selector during orchestration
- Default prompt template stored in `system_settings.default_agent_prompt`
- Each has icon, model, temperature, and custom prompt

### Key Design Patterns

**Concurrent Execution**:
- Agent responses: `asyncio.gather()` on all jury members simultaneously
- Analysis tasks: Stance/Flow/Summary analyses run in parallel
- Evidence gathering: Web search and file processing in parallel

**Status State Machine** (DiscussionLog.status):
```
orchestrating → ready → turn_inprogress → waiting_for_vote
     ↓                        ↑__________________|
     ↓ (user ends)
report_generating → completed
```

**Model Flexibility**:
- `get_llm_client()` in discussion_flow.py routes to correct provider (Gemini/OpenAI/Claude)
- Admin can override models per agent via `model_overrides` parameter

**LangSmith Integration**:
- All LLM calls include tags: `discussion_id:{id}`, `agent_name:{name}`, `turn:{number}`
- Enabled via `LANGCHAIN_TRACING_V2` environment variable

## File Structure

```
src/app/
├── main.py                   # FastAPI app, routes, middleware
├── db.py                     # DB initialization (Redis, MongoDB via Beanie)
├── core/
│   ├── config.py            # Settings with environment-aware computed fields
│   ├── security.py          # JWT authentication
│   └── settings/            # Agent configuration JSONs
├── api/v1/                  # REST endpoints
│   ├── discussions.py       # User discussion API
│   ├── login.py             # Authentication
│   └── admin/               # Admin-only endpoints
├── services/
│   ├── orchestrator.py      # Stage 1: Team assembly
│   ├── discussion_flow.py   # Stage 2: Discussion execution
│   ├── report_generator.py  # Stage 3: Report creation
│   ├── summarizer.py        # Web content summarization
│   └── utility_agents.py    # SNR & Verifier agents
├── models/
│   └── discussion.py        # Beanie Document models
├── schemas/                 # Pydantic schemas for validation
└── tools/
    └── search.py            # Tavily web search, yfinance, FRED API
```

## Important Conventions

**Working Directory**: All imports and file paths assume `src/` as the working directory. Always `cd src` before running uvicorn or Python scripts.

**Environment Variables**:
- Development: Uses `.env` file (not committed)
- Cloud Run: Environment variables override `.env` values
- Critical: `INSTANCE_CONNECTION_NAME` determines environment (presence = Cloud Run)

**Agent Modifications**:
- Changes to `AgentSettings` require updating MongoDB directly or via admin API
- New agents auto-created by Jury Selector use icon selection logic in `orchestrator.py:_get_icon_for_agent()`

**LLM Response Handling**:
- Always handle both string and list response formats (Anthropic vs OpenAI/Gemini)
- See `discussion_flow.py:_run_single_agent_turn()` lines 293-307 for pattern

**Background Tasks**:
- Discussion rounds: `execute_turn()` runs async, updates DB status
- Report generation: `generate_report_background()` runs async
- Status checks via `/api/v1/discussions/{id}/status` endpoint
