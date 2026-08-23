# 🎬 Agentic PowerScaler - Autonomous Cinematic Battle Engine

> **Devpost Hackathon Entry**: *Agentic Cinema: The Blockbuster Hackathon*  
> **Partner Track**: **Parallel** (Search & Extract API Integration)  
> **LLM Engine**: **Google Gemini API** (`google-genai`)

---

## 🌟 Overview

**Agentic PowerScaler** is an autonomous multi-agent system designed for power scaling enthusiasts and pop-culture debaters. It resolves hypothetical character matchups (e.g., *"Goku (Ultra Instinct) vs. Superman (Prime One Million)"*) by executing deep web research via **Parallel's Search & Extract APIs**, retrieving verified feats, speed tiers, and cosmological scaling stats, evaluating the matchup via **Google Gemini**, and producing an epic **cinematic screenplay & storyboard**.

---

## 🏗️ Layered Modular Architecture

The project follows a clean, non-monolithic layered architecture:

```
PS-Fan-Project/
├── README.md                  # Project overview & submission guide
├── LICENSE                    # Open Source MIT License (Devpost requirement)
├── pyproject.toml             # Project metadata & pytest configuration
├── requirements.txt           # Exact pinned dependencies (pip freeze)
├── .env.example               # Environment variables template
├── .gitignore                 # Version control ignores
├── src/
│   ├── main.py                # FastAPI application entry point
│   ├── core/                  # App configuration, logging & exceptions
│   │   ├── config.py
│   │   ├── logging.py
│   │   └── exceptions.py
│   ├── models/                # Pydantic domain models
│   │   ├── matchup.py         # Matchup, Verdict, Feats & Shot models
│   │   └── parallel.py        # Parallel API schemas
│   ├── adapters/              # External partner API adapters
│   │   ├── parallel_adapter.py# Official Parallel Search & Extract API client
│   │   └── mcp_adapter.py     # Model Context Protocol bridge
│   ├── services/              # AI & Orchestration services
│   │   ├── gemini_service.py  # Google Gemini SDK integration
│   │   └── powerscaler_service.py # Multi-agent workflow orchestrator
│   ├── agents/                # Autonomous Agent Crew
│   │   ├── base.py            # Base Agent abstraction
│   │   ├── scout_agent.py     # Parallel Data Scout (Feats retrieval)
│   │   ├── analyst_agent.py   # PowerScaling Analyst (Tiering & Verdict)
│   │   └── director_agent.py  # Cinematic Battle Director (Screenplay generation)
│   └── api/                   # REST API routes
│       ├── router.py          # API Router aggregator
│       └── v1/
│           ├── health.py      # Health check endpoint
│           └── powerscaler.py # Matchup evaluation endpoint
└── tests/                     # Automated pytest test suite
    ├── test_health.py
    └── test_powerscaler.py
```

---

## 🚀 Key Features

1. **Parallel API Web Scout Agent**: Queries Parallel's `Search` and `Extract` APIs to fetch live feats, wiki lore, speed tiers, and cosmic scale data.
2. **Dimensional Tiering Analyst**: Evaluates speed, attack potency (AP), durability, and hax resistances using Google Gemini.
3. **Cinematic Battle Screenplay Engine**: Turns the analytical verdict into a multi-shot cinematic screenplay with camera angles, visual effects (VFX), and dialogue.
4. **REST API & Interactive Docs**: Built with FastAPI, OpenAPI swagger interface (`/docs`), and full unit test coverage.

---

## 🛠️ Quickstart Guide

### 1. Activate Environment
```bash
source .venv/bin/activate
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env` and set your API keys:
```bash
cp .env.example .env
```
Key configuration:
- `GEMINI_API_KEY`: Your Google Gemini API Key.
- `PARALLEL_API_KEY`: Your Parallel API Key (https://platform.parallel.ai/).

### 3. Run the Server
```bash
python3 -m uvicorn src.main:app --reload --port 8000
```
Open [http://localhost:8000/docs](http://localhost:8000/docs) in your browser to interact with the API endpoints!

---

## 🧪 Run Tests

To verify full pipeline execution:
```bash
.venv/bin/pytest -v
```

---

## 📜 License
This project is licensed under the [MIT License](LICENSE).
