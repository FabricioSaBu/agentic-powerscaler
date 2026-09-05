"""
Main FastAPI Application & Entrypoint for Agentic PowerScaler.
Run with: uvicorn src.main:app --reload
"""

import sys
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from src.core.config import settings
from src.core.logging import logger
from src.api.router import api_router
from src.web.router import router as web_router
from src.db.base import init_db

app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    description=(
        "Agentic PowerScaler: Autonomous Battle Evaluator & Cinematic Screenplay Engine "
        "powered by Google Gemini and Parallel API (Devpost Hackathon Entry)."
    ),
    docs_url="/docs",
    redoc_url="/redoc"
)

# Enable CORS for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "web" / "static")), name="static")
app.include_router(api_router)
app.include_router(web_router)


@app.on_event("startup")
async def startup_event():
    logger.info(f"Starting {settings.app_name} v{settings.version} [{settings.environment}]")
    logger.info(f"Parallel Track Enabled: {settings.partner_track}")
    await init_db()
    logger.info(f"Database ready at {settings.database_url}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host=settings.host, port=settings.port, reload=settings.debug)
