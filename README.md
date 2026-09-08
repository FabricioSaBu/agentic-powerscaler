# 🎬 Agentic PowerScaler — Autonomous Cinematic Battle Engine

> **Devpost Hackathon Entry**: *Agentic Cinema: The Blockbuster Hackathon*
> **Partner Track**: **Parallel** (Search & Extract API Integration)
> **Built on**: **Google Cloud Agent Development Kit (ADK)**, **Vertex AI** (Gemini), **Cloud SQL**, **Cloud Run**
> **Live**: **https://powerscaler-680593447318.us-central1.run.app**

---

## 🌟 Overview

**Agentic PowerScaler** resolves hypothetical character matchups — *"Goku (Ultra Instinct) vs. Superman (Prime One Million)"* — through a six-agent pipeline: it researches real feats via **Parallel's Search & Extract APIs**, extracts them into structured, source-attributed stats, pauses for a **human to review and correct** what it found, evaluates the matchup with **Gemini on Vertex AI**, and writes a multi-shot **cinematic screenplay** for the outcome — including counterfactual scripts for the loser winning, or a draw.

It's not a one-shot prompt. Character identity, versions/eras, equipment, feats, and verdicts are all persisted in a relational schema, so a character researched once is reused (not re-scraped) in every later matchup, and every stat the app states traces back to a specific source URL a human can check.

---

## 🏗️ Architecture

Orchestration runs on **Google ADK** (`google-adk`): each agent below is a real ADK `BaseAgent` node, driven by an ADK `Runner`/`Session`, not a hand-rolled call chain.

```
Resolver ──▶ Scout ──▶ Profiler ──▶ [ Human Review Gate ] ──▶ Analyst ──▶ Director
 (preview)   (search)  (extract)     ▲                │        (verdict)  (screenplay)
                                      └── Researcher ◀─┘ (rejected contenders only)
```

| Agent | Role |
|---|---|
| **Resolver** | Turns free-text roster input ("naruto" + "gauntlet") into concrete, choosable character versions and equipment — before the expensive research runs, at zero LLM cost for anything already known |
| **Scout** | Runs Parallel Search + Extract for every roster member, scoped to the confirmed version/era |
| **Profiler** | Extracts structured, catalog-grounded traits and feats from Scout's raw research, citing sources |
| **Human Review Gate** | Pauses the pipeline so a person can approve or reject each contender's profile, with a note on what's wrong — persisted to the database, not an in-memory checkpoint, so it survives a restart |
| **Researcher** | The retry path: an ADK `LlmAgent` with a search tool that composes its own query from the reviewer's rejection note, instead of replaying Scout's template |
| **Analyst** | Weighs speed, attack potency, durability, and hax resistances to declare a winner, diff tier, and win-probability split |
| **Director** | Turns the verdict into a shot-by-shot cinematic screenplay — camera angles, VFX notes, dialogue — for the canonical outcome or any counterfactual |

A rejected contender loops back through Researcher → Profiler → Review up to 3 rounds before the pipeline proceeds with best-available data.

### Tech stack

| Layer | Choice |
|---|---|
| Agent orchestration | **Google ADK** (`google-adk`) — `Runner`, `Session`, custom `BaseAgent` nodes, `LlmAgent` + `FunctionTool` for the retry path |
| LLM | **Gemini on Vertex AI** (`gemini-3.5-flash-lite`), explicit per-agent thinking-level and token-limit config; falls back to an AI Studio key (or a fully offline simulated mode) when no GCP project is configured |
| Research | **Parallel Search & Extract API** — real web research, not a mock; offline mode returns *no* fabricated documents rather than inventing feats |
| Web framework | FastAPI, both a JSON API and a server-rendered HTMX web UI sharing the same service layer |
| Database | **Cloud SQL (PostgreSQL)** in production, SQLite for zero-config local/offline dev — the same schema and migration path work on both |
| Deployment | **Cloud Run**, `min-instances: 1`, connected to Cloud SQL via its native Unix-socket integration |

### Project layout

```
src/
├── main.py                    # FastAPI entry point
├── core/                      # Config, logging, exceptions, live progress reporting
├── models/                    # Pydantic domain models (matchup, preview, parallel, extraction)
├── adapters/                  # parallel_adapter.py — the Parallel API client
├── agents/                    # The six agents above, plus adk_common.py (the ADK adapter)
│   ├── resolver_agent.py
│   ├── scout_agent.py
│   ├── profiler_agent.py
│   ├── researcher_agent.py
│   ├── analyst_agent.py
│   ├── director_agent.py
│   └── adk_common.py          # Wraps a plain agent as a genuine ADK BaseAgent node
├── services/
│   ├── gemini_service.py      # Vertex AI / AI Studio client, retry, structured output
│   └── powerscaler_service.py # Pipeline orchestration: builds and runs the ADK agent tree
├── db/                        # SQLAlchemy async models, repository, lightweight migrations, seed data
├── api/v1/                    # JSON API: preview, evaluate, scenario scripts
└── web/                       # HTMX UI: roster form → preview/versions → review gate → result
tests/
```

---

## 🚀 Key Features

1. **Human-in-the-loop research review** — before the verdict runs, a person sees exactly what was found for each contender (with sources) and can reject anything that looks wrong, with a note the Researcher agent uses to fix it.
2. **Version-aware character resolution** — "Naruto" isn't one stat block; the app asks which era, tracks whether that version's power is finished or still developing, and scopes research to just that version.
3. **Counterfactual scenario scripts** — beyond the canonical verdict, generate (and cache) a screenplay for the loser winning, or a draw, without re-running the analysis.
4. **Persistent character catalog** — a character profiled once is reused across every future matchup instead of being re-researched from scratch.
5. **Team battles** — 1v1 or up to 3-a-side, with per-member handicaps and equipment.
6. **Both a REST API and a full web UI** — `/docs` for the API, `/` for the interactive HTMX front end, sharing one pipeline.
7. **Runs fully offline** — with no API keys configured at all, the whole pipeline still executes end-to-end on simulated responses, useful for demos, tests, and CI.

---

## 🛠️ Quickstart Guide

### 1. Install dependencies
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment variables
```bash
cp .env.example .env
```
- **For Google Cloud (Vertex AI) — the primary path**: set `GOOGLE_CLOUD_PROJECT` and `GOOGLE_CLOUD_LOCATION` (use `global` for current-generation Gemini 3.x models — a regional location 404s even though the model exists), and authenticate via `gcloud auth application-default login` or a service account.
- **For local dev without GCP**: set `GEMINI_API_KEY` (AI Studio) instead — no project needed.
- **Neither set**: the app runs fully offline on simulated responses.
- `PARALLEL_API_KEY`: your [Parallel](https://platform.parallel.ai/) key — omit it to run on simulated search results instead.
- `DATABASE_URL`: defaults to local SQLite; point it at a `postgresql+asyncpg://...` URL to use Cloud SQL/Postgres instead (see `src/db/base.py` — its migration helper is dialect-aware).

### 3. Run the server
```bash
python3 -m uvicorn src.main:app --reload --port 8000
```
Open [http://localhost:8000](http://localhost:8000) for the web UI, or [http://localhost:8000/docs](http://localhost:8000/docs) for the API.

---

## ☁️ Deployment (Cloud Run)

```bash
gcloud run deploy powerscaler \
  --source=. \
  --region=us-central1 \
  --allow-unauthenticated \
  --port=8000 \
  --min-instances=1 \
  --add-cloudsql-instances=PROJECT:REGION:INSTANCE \
  --env-vars-file=cloudrun-env.yaml
```
`cloudrun-env.yaml` sets `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION=global`, `GEMINI_MODEL`, `PARALLEL_API_KEY`, and a `DATABASE_URL` pointing at the Cloud SQL instance over its Unix socket: `postgresql+asyncpg://user:pass@/dbname?host=/cloudsql/PROJECT:REGION:INSTANCE`.

---

## 🧪 Run Tests

```bash
pytest -v
```
Runs fully offline with zero configuration (no API keys needed), or end-to-end against real Vertex AI / Parallel / Postgres if configured.

---

## 📜 License
This project is licensed under the [MIT License](LICENSE).
