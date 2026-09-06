"""
Web (HTML) frontend for Agentic PowerScaler.
Server-rendered via Jinja2 + HTMX -- reuses the same PowerScalerService singleton and DB
session as the JSON API, it just returns HTML instead of JSON.

The roster form is dynamic (1-3 members per side, each with N handicaps and N items), so the
client serializes it into a single `roster_json` field instead of brittle repeated flat
fields; the preview's per-member selects come back as `version_{side}_{i}` /
`item_{side}_{i}_{j}` and are read from the raw form multidict.
"""

import json
from pathlib import Path
from typing import List, Tuple

import markdown
from fastapi import APIRouter, Request, Form, Depends
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from pydantic import ValidationError

from src.db.base import get_session
from src.models.matchup import MAX_TEAM_SIZE, ContenderSpec, PowerScalerMatchupRequest
from src.models.preview import MatchupResolution
from src.core.exceptions import PowerScalerException
from src.api.v1.powerscaler import powerscaler_service

router = APIRouter(tags=["Web"])
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
_STYLESHEET = Path(__file__).parent / "static" / "style.css"


def _parse_roster(roster_json: str) -> Tuple[List[ContenderSpec], List[ContenderSpec]]:
    """Parses the client-serialized roster. Raises ValueError when either side is empty --
    the roster is the source of the contender names, so there is no fallback without it."""
    try:
        data = json.loads(roster_json or "{}")
    except json.JSONDecodeError:
        raise ValueError("Malformed roster payload.")

    def clean(raw_team) -> List[ContenderSpec]:
        team = []
        for raw in (raw_team or [])[:MAX_TEAM_SIZE]:
            try:
                spec = ContenderSpec.model_validate(raw)
            except ValidationError:
                continue
            if not spec.name.strip():
                continue
            spec.name = spec.name.strip()
            spec.handicaps = [h.strip() for h in spec.handicaps if h.strip()]
            spec.item_queries = [q.strip() for q in spec.item_queries if q.strip()]
            spec.version_hint = (spec.version_hint or "").strip() or None
            team.append(spec)
        return team

    team_a, team_b = clean(data.get("team_a")), clean(data.get("team_b"))
    if not team_a or not team_b:
        raise ValueError("Both sides need at least one contender.")
    return team_a, team_b


def _form_int(form, key: str, default: int = 0) -> int:
    try:
        return int(form.get(key, default))
    except (TypeError, ValueError):
        return default


def _confirmed_rosters(
    roster_json: str, resolution_json: str, form
) -> Tuple[List[ContenderSpec], List[ContenderSpec]]:
    """Maps the preview form's selected version/item indices back onto the roster the user
    confirmed. A missing or malformed resolution degrades gracefully: the raw roster runs
    with legacy string identities instead of failing the request."""
    team_a, team_b = _parse_roster(roster_json)
    if not resolution_json:
        return team_a, team_b
    try:
        resolution = MatchupResolution.model_validate_json(resolution_json)
    except ValidationError:
        return team_a, team_b

    for side, team, resolved in (("a", team_a, resolution.team_a), ("b", team_b, resolution.team_b)):
        for i, spec in enumerate(team):
            if i >= len(resolved):
                continue
            member = resolved[i]

            version_index = _form_int(form, f"version_{side}_{i}")
            if 0 <= version_index < len(member.options):
                spec.version = member.options[version_index]
                spec.canonical = member.canonical_name or None
                spec.franchise = member.franchise or None

            # Keep chosen_items aligned with item_queries (Scout uses the query at the same
            # index as the alias to learn), dropping queries that resolved to nothing.
            confirmed_queries, chosen = [], []
            for j, query in enumerate(spec.item_queries):
                if j >= len(member.items):
                    continue
                candidates = member.items[j].candidates
                item_index = _form_int(form, f"item_{side}_{i}_{j}")
                if 0 <= item_index < len(candidates):
                    confirmed_queries.append(member.items[j].query or query)
                    chosen.append(candidates[item_index])
            spec.item_queries = confirmed_queries
            spec.chosen_items = chosen

    return team_a, team_b


def _render_run(request: Request, report, pending, thread_id: str):
    """A run either paused for review or produced a verdict -- render whichever."""
    if pending is not None:
        return templates.TemplateResponse(request, "_review.html", {
            "request": request,
            "review": pending,
            "thread_id": thread_id,
            "last_round": pending.get("round", 0) + 1 >= pending.get("max_rounds", 3),
            "error": None,
        })
    return templates.TemplateResponse(request, "_result.html", {
        "request": request,
        "report": report,
        "verdict": report.verdict,
        "verdict_html": markdown.markdown(report.verdict.summary_verdict),
        "is_team_battle": len(report.verdict.team_a_stats) > 1 or len(report.verdict.team_b_stats) > 1,
        "error": None,
    })


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    # Cache-bust the stylesheet by its mtime: the URL changes whenever the file is edited, so
    # browsers can't serve a stale copy (StaticFiles sends no cache-control, and the plain
    # /static/style.css URL otherwise looks unchanged forever).
    return templates.TemplateResponse(
        request, "index.html", {"static_version": int(_STYLESHEET.stat().st_mtime)}
    )


@router.post("/preview", response_class=HTMLResponse)
async def preview(
    request: Request,
    roster_json: str = Form(""),
    battle_environment: str = Form(""),
    include_cinematic_script: bool = Form(False),
    session: AsyncSession = Depends(get_session),
):
    """Step 1: resolve which character versions (and items) to use for every roster member,
    for the user to confirm or change before the expensive research pipeline runs."""
    try:
        team_a, team_b = _parse_roster(roster_json)
        resolution = await powerscaler_service.resolve_versions(team_a, team_b, session)
        context = {
            "request": request,
            "resolution": resolution,
            # Round-tripped through the form so step 2 doesn't re-resolve (and re-pay for) it.
            "resolution_json": resolution.model_dump_json(),
            "roster_json": json.dumps({
                "team_a": [m.model_dump(include={"name", "handicaps", "item_queries", "version_hint"}) for m in team_a],
                "team_b": [m.model_dump(include={"name", "handicaps", "item_queries", "version_hint"}) for m in team_b],
            }),
            "team_a_specs": team_a,
            "team_b_specs": team_b,
            "battle_environment": battle_environment,
            "include_cinematic_script": include_cinematic_script,
            "error": None,
        }
    except (PowerScalerException, ValueError) as e:
        context = {"request": request, "error": getattr(e, "message", None) or str(e)}
    except Exception as e:
        context = {"request": request, "error": str(e)}

    return templates.TemplateResponse(request, "_preview.html", context)


@router.post("/script", response_class=HTMLResponse)
async def script(
    request: Request,
    report_id: str = Form(...),
    scenario: str = Form(...),
    session: AsyncSession = Depends(get_session),
):
    """On-demand screenplay for one outcome of a finished matchup, triggered by clicking a
    segment of the probability bar. Served from storage when that scenario already exists."""
    try:
        scenes, from_cache, label = await powerscaler_service.generate_scenario_script(
            report_id, scenario, session
        )
        context = {
            "request": request,
            "scenes": scenes,
            "from_cache": from_cache,
            "scenario_label": label,
            "error": None,
        }
    except PowerScalerException as e:
        context = {"request": request, "error": e.message}
    except Exception as e:
        context = {"request": request, "error": str(e)}

    return templates.TemplateResponse(request, "_script.html", context)


@router.post("/evaluate", response_class=HTMLResponse)
async def evaluate(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Step 2: run the pipeline against the versions (and items) the user confirmed in step 1.
    Reads the raw form because the select names are dynamic (version_{side}_{i}, ...)."""
    try:
        form = await request.form()
        team_a, team_b = _confirmed_rosters(
            form.get("roster_json", ""), form.get("resolution_json", ""), form
        )
        report, pending, thread_id = await powerscaler_service.run_matchup_pipeline(
            PowerScalerMatchupRequest(
                team_a=team_a,
                team_b=team_b,
                battle_environment=form.get("battle_environment") or None,
                include_cinematic_script=form.get("include_cinematic_script") == "true",
            ),
            session,
            human_review=True,
        )
        return _render_run(request, report, pending, thread_id)
    except (PowerScalerException, ValueError) as e:
        context = {"request": request, "error": getattr(e, "message", None) or str(e)}
    except Exception as e:
        context = {"request": request, "error": str(e)}

    return templates.TemplateResponse(request, "_result.html", context)


@router.post("/resume", response_class=HTMLResponse)
async def resume(request: Request, session: AsyncSession = Depends(get_session)):
    """Continues a run paused at the review gate, carrying the reviewer's per-contender
    approvals. Reads the raw form because the field names are indexed per contender."""
    try:
        form = await request.form()
        thread_id = form.get("thread_id", "")
        decision = {}
        for side in ("a", "b"):
            entries = []
            index = 0
            while f"present_{side}_{index}" in form:
                entries.append({
                    "approved": form.get(f"approved_{side}_{index}") == "on",
                    "hint": form.get(f"hint_{side}_{index}", ""),
                })
                index += 1
            decision[side] = entries

        report, pending, thread_id = await powerscaler_service.resume_review(
            thread_id, decision, session
        )
        return _render_run(request, report, pending, thread_id)
    except (PowerScalerException, ValueError) as e:
        context = {"request": request, "error": getattr(e, "message", None) or str(e)}
    except Exception as e:
        context = {"request": request, "error": str(e)}

    return templates.TemplateResponse(request, "_result.html", context)
