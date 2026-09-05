"""
Parallel API Request/Response Data Transfer Models.
Reflects Parallel Search, Extract, and Task API schemas.
"""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class ParallelSearchRequest(BaseModel):
    query: str
    num_results: int = Field(default=5, ge=1, le=20)
    include_domains: Optional[List[str]] = None


class ParallelSearchResultItem(BaseModel):
    title: str
    url: str
    snippet: str
    score: Optional[float] = None


class ParallelSearchResponse(BaseModel):
    query: str
    results: List[ParallelSearchResultItem] = Field(default_factory=list)


class ParallelExtractRequest(BaseModel):
    urls: List[str]
    # The API rejects unknown body fields outright (422 extra_forbidden), so only send what
    # it accepts. `objective` focuses extraction on the version we actually care about --
    # without it, a general "Vegeta" page yields whichever era the page emphasises.
    objective: Optional[str] = Field(
        default=None, description="What the extraction should focus on, e.g. the version's feats"
    )


class ParallelExtractResultItem(BaseModel):
    url: str
    title: Optional[str] = None
    content: str


class ParallelExtractResponse(BaseModel):
    extracted: List[ParallelExtractResultItem] = Field(default_factory=list)
