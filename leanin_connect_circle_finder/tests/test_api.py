"""Integration tests against the original deterministic synthetic dataset."""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LEANIN_DB_PATH", str(tmp_path / "test.db"))
    with TestClient(app) as test_client:
        yield test_client


def results(client, user_id, limit=10):
    response = client.get(f"/recommendations/{user_id}?limit={limit}")
    assert response.status_code == 200
    return response.json()["recommendations"]


def test_health_and_validation(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/recommendations/9999").status_code == 404
    assert client.get("/recommendations/7?limit=0").status_code == 422
    assert client.get("/recommendations/7?limit=21").status_code == 422


def test_seeded_dataset_loaded(client):
    conn = sqlite3.connect(app.state.db_path)
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 100
    assert conn.execute("SELECT COUNT(*) FROM circles").fetchone()[0] == 40
    assert conn.execute("SELECT COUNT(*) FROM memberships").fetchone()[0] == 441
    assert conn.execute("SELECT COUNT(*) FROM activity").fetchone()[0] == 386
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()


def test_cold_start_has_relevant_accessible_diverse_results(client):
    recs = results(client, 42)
    assert len(recs) == 10
    assert len({r["topic"] for r in recs}) == len(recs)
    assert any(r["format"] in {"virtual", "hybrid"} for r in recs[:5])
    assert all("Matches your interest" not in r["reason"] for r in recs)


def test_obvious_interest_matches(client):
    recs = results(client, 7)
    top = {r["circle_id"] for r in recs[:5]}
    assert {5, 6}.issubset(top)
    assert any("leadership skills" in r["reason"].lower() for r in recs)
    assert any("public speaking" in r["reason"].lower() for r in recs)


def test_negotiation_duplicates_are_diversified(client):
    recs = results(client, 15, limit=20)
    ids = {r["circle_id"] for r in recs}
    assert len(ids & {10, 11, 12}) == 1
    assert len({r["topic"] for r in recs}) == len(recs)


def test_full_inactive_and_alternative(client):
    recs = results(client, 23)
    ids = [r["circle_id"] for r in recs]
    assert 20 not in ids  # full
    assert 21 not in ids  # inactive
    assert 22 in ids  # active alternative


def test_every_user_eligible_and_explainable(client):
    conn = sqlite3.connect(app.state.db_path)
    for user_id in range(1, 101):
        recs = results(client, user_id)
        assert recs, f"No recommendations for user {user_id}"
        assert [r["rank"] for r in recs] == list(range(1, len(recs) + 1))
        assert all(r["reason"] and r["score"] >= 0 for r in recs)
        assert all(r["score"] >= recs[i + 1]["score"] for i, r in enumerate(recs[:-1]))
        for rec in recs:
            circle_id = rec["circle_id"]
            row = conn.execute(
                """SELECT access, member_count, max_members, last_activity_at,
                   feed_posts_30d, chat_messages_30d FROM circles WHERE id = ?""",
                (circle_id,),
            ).fetchone()
            assert row[0] == "public"
            assert row[2] is None or row[1] < row[2]
            assert not (row[4] == 0 and row[5] < 5)
            assert conn.execute(
                "SELECT COUNT(*) FROM memberships WHERE user_id=? AND circle_id=?",
                (user_id, circle_id),
            ).fetchone()[0] == 0
    conn.close()


def test_deterministic_across_requests(client):
    assert results(client, 15) == results(client, 15)


def test_request_to_join_wording(client):
    recs = results(client, 23)
    level_up = next(r for r in recs if r["circle_id"] == 22)
    assert level_up["join_policy"] == "request"
    assert "request to join" in level_up["reason"].lower()


def test_no_parenting_assumptions_from_incidental_tags(client):
    # User 23 has a promotion interest, but has not said she is a parent.
    # A Circle about motherhood should not be inferred from a promotion tag.
    ids = {r["circle_id"] for r in results(client, 23)}
    assert 19 not in ids
