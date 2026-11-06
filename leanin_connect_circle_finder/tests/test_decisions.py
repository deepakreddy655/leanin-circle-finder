"""Tests for product decisions, not just whether the endpoint returns HTTP 200."""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LEANIN_DB_PATH", str(tmp_path / "test.db"))
    with TestClient(app) as test_client:
        yield test_client


def recs(client, user_id, limit=10):
    response = client.get(f"/recommendations/{user_id}?limit={limit}")
    assert response.status_code == 200
    return response.json()["recommendations"]


def test_direct_interests_beat_general_popularity(client):
    # Make an unrelated Circle extraordinarily busy. A user's own interests
    # should still outrank its popularity.
    with sqlite3.connect(app.state.db_path) as conn:
        conn.execute(
            "UPDATE circles SET feed_posts_30d=100000, chat_messages_30d=100000 WHERE id=31"
        )
    top_two = {r["circle_id"] for r in recs(client, 7)[:2]}
    assert top_two == {5, 6}


def test_capacity_is_a_hard_filter(client):
    with sqlite3.connect(app.state.db_path) as conn:
        conn.execute("UPDATE circles SET member_count=max_members WHERE id=5")
    assert 5 not in {r["circle_id"] for r in recs(client, 7)}


def test_inactivity_is_a_hard_filter(client):
    with sqlite3.connect(app.state.db_path) as conn:
        conn.execute(
            """UPDATE circles SET last_activity_at='2026-01-01T00:00:00.000Z',
               feed_posts_30d=0, chat_messages_30d=0 WHERE id=22"""
        )
    assert 22 not in {r["circle_id"] for r in recs(client, 23)}


def test_secondary_tags_are_not_misrepresented_as_main_focus(client):
    # Team Leads Circle is about managing a team; public speaking is a tag.
    item = next(r for r in recs(client, 7) if r["circle_id"] == 31)
    assert "focuses on managing a team" in item["reason"].lower()
    assert "also lists public speaking" in item["reason"].lower()
    assert "you chose public speaking" not in item["reason"].lower()


def test_cold_start_is_not_treated_as_a_deficient_profile(client):
    top_five = recs(client, 42, 5)
    assert len(top_five) == 5
    assert {r["topic"] for r in top_five} == {
        "leadership-skills", "confidence", "sponsorship-mentorship",
        "networking", "communication",
    }
    assert all("you chose" not in r["reason"].lower() for r in top_five)
    assert all(len(r["reason"]) <= 200 for r in top_five)


def test_never_infer_geography_or_sensitive_identity(client):
    for user_id in (7, 23, 42):
        results = recs(client, user_id, 20)
        assert not ({18, 27, 28, 30} & {r["circle_id"] for r in results})
        assert all("near you" not in r["reason"].lower() for r in results)
        assert all("local" not in r["reason"].lower() for r in results)


def test_returns_empty_list_if_no_eligible_circles(client):
    with sqlite3.connect(app.state.db_path) as conn:
        conn.execute("UPDATE circles SET access='unlisted'")
    response = client.get("/recommendations/42")
    assert response.status_code == 200
    assert response.json() == {"user_id": 42, "count": 0, "recommendations": []}


def test_all_users_have_nonduplicative_recommendations(client):
    for user_id in range(1, 101):
        items = recs(client, user_id, 20)
        assert items
        assert len({r["circle_id"] for r in items}) == len(items)
        assert len({r["topic"] for r in items}) == len(items)
        assert all(r["reason"].strip() and len(r["reason"]) <= 200 for r in items)
        assert not ({20, 21, 32} & {r["circle_id"] for r in items})
