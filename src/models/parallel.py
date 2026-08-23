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
    format: str = Field(default="markdown", description="markdown or text")


class ParallelExtractResultItem(BaseModel):
    url: str
    title: Optional[str] = None
    content: str


class ParallelExtractResponse(BaseModel):
    extracted: List[ParallelExtractResultItem] = Field(default_factory=list)
