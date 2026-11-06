"""HTTP API for member-facing Circle recommendations."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager, closing
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel

from app.db import connect, initialize
from app.recommend import recommend

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Recommendation(BaseModel):
    rank: int
    circle_id: int
    name: str
    topic: str | None
    format: str
    join_policy: str
    score: float
    reason: str


class RecommendationResponse(BaseModel):
    user_id: int
    count: int
    recommendations: list[Recommendation]


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_path = Path(os.environ.get("LEANIN_DB_PATH", PROJECT_ROOT / ".local" / "leanin.db"))
    data_dir = Path(os.environ.get("LEANIN_DATA_DIR", PROJECT_ROOT / "data"))
    initialize(db_path, data_dir)
    app.state.db_path = db_path
    yield


app = FastAPI(
    title="Circle Finder — Lean In Connect",
    version="1.0.0",
    description="Find active, joinable Circles with reasons members can understand.",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/recommendations/{user_id}", response_model=RecommendationResponse)
def get_recommendations(
    request: Request,
    user_id: int,
    limit: int = Query(default=5, ge=1, le=20),
) -> RecommendationResponse:
    with closing(connect(request.app.state.db_path)) as conn:
        exists = conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail=f"User {user_id} not found")
        recommendations = recommend(conn, user_id, limit)
    return RecommendationResponse(
        user_id=user_id, count=len(recommendations), recommendations=recommendations
    )
