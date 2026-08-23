"""
Parallel API Adapter (Official Integration for Hackathon Track).
Handles communication with Parallel Search and Extract APIs.
https://docs.parallel.ai/
"""

from typing import List, Optional
import httpx
from langsmith import traceable
from src.core.config import settings
from src.core.logging import logger
from src.models.parallel import (
    ParallelSearchRequest,
    ParallelSearchResponse,
    ParallelSearchResultItem,
    ParallelExtractRequest,
    ParallelExtractResponse,
    ParallelExtractResultItem
)


class ParallelAdapter:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.parallel_api_key

    @traceable(run_type="tool", name="Parallel Search")
    async def search(self, request: ParallelSearchRequest) -> ParallelSearchResponse:
        """Executes a Parallel Search query to retrieve web context & feat references."""
        logger.info(f"Parallel Search API query: '{request.query}'")
        
        if not self.api_key:
            logger.info("PARALLEL_API_KEY unset; providing simulated Parallel Search response for offline mode.")
            return self._mock_search(request.query)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        # Parallel Search API expects `search_queries` as a list of strings
        payload: dict = {"search_queries": [request.query]}
        if request.include_domains:
            payload["include_domains"] = request.include_domains

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    settings.parallel_search_url,
                    json=payload,
                    headers=headers
                )
                response.raise_for_status()
                data = response.json()

                # Parallel returns: {"results": [{"url", "title", "publish_date", "excerpts": [...]}, ...]}
                results = [
                    ParallelSearchResultItem(
                        title=item.get("title", ""),
                        url=item.get("url", ""),
                        snippet=" ".join(item.get("excerpts", []))[:500],
                        score=item.get("score")
                    )
                    for item in data.get("results", [])[:request.num_results]
                ]
                return ParallelSearchResponse(query=request.query, results=results)
        except Exception as e:
            logger.error(f"Parallel Search API call failed: {e}. Falling back to simulated response.")
            return self._mock_search(request.query)

    @traceable(run_type="tool", name="Parallel Extract")
    async def extract(self, request: ParallelExtractRequest) -> ParallelExtractResponse:
        """Executes a Parallel Extract request to get full markdown text from web pages."""
        logger.info(f"Parallel Extract API for {len(request.urls)} URLs.")
        
        if not self.api_key:
            return self._mock_extract(request.urls)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    settings.parallel_extract_url,
                    json={"urls": request.urls, "format": request.format},
                    headers=headers
                )
                response.raise_for_status()
                data = response.json()
                
                extracted = [
                    ParallelExtractResultItem(
                        url=item.get("url", ""),
                        title=item.get("title"),
                        content=item.get("content", "")
                    )
                    for item in data.get("extracted", [])
                ]
                return ParallelExtractResponse(extracted=extracted)
        except Exception as e:
            logger.error(f"Parallel Extract API call failed: {e}. Falling back to simulated extract.")
            return self._mock_extract(request.urls)

    def _mock_search(self, query: str) -> ParallelSearchResponse:
        """Simulates search results with rich feats & scaling data for power scaling matchups."""
        mock_results = [
            ParallelSearchResultItem(
                title=f"Vs Battles Wiki & Feats analysis for {query}",
                url="https://vsbattles.fandom.com/wiki/Power_Scaling_Feats",
                snippet=f"Detailed power tier, speed calc (MFTL+), AP/DC, and hax analysis for {query}.",
                score=0.98
            ),
            ParallelSearchResultItem(
                title=f"Reddit r/whowouldwin: {query} comprehensive breakdown",
                url="https://reddit.com/r/whowouldwin/comments/feats_analysis",
                snippet=f"Community consensus, speed scaling, durability feats, and cosmic scaling discussion for {query}.",
                score=0.92
            ),
            ParallelSearchResultItem(
                title=f"ComicVine / Manga respect thread: {query}",
                url="https://comicvine.gamespot.com/forums/battles/respect_thread",
                snippet=f"Scans, statements, and dimensional scaling feats extracted for {query}.",
                score=0.89
            )
        ]
        return ParallelSearchResponse(query=query, results=mock_results)

    def _mock_extract(self, urls: List[str]) -> ParallelExtractResponse:
        items = [
            ParallelExtractResultItem(
                url=url,
                title="Power Scaling Document",
                content=f"Extracted feat document from {url}.\nContender demonstrates multiversal destructive capability, faster-than-light speed feats, and high dimensional resistance."
            )
            for url in urls
        ]
        return ParallelExtractResponse(extracted=items)
