"""Rank Circles a member can actually join, then explain why they might care.

This is intentionally a small, transparent rules-based recommender. The data has
no outcomes (joins/retention), so learned weights would suggest false precision.
"""

from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timedelta

# A Circle is not a useful recommendation if nobody is participating anymore.
MAX_IDLE_DAYS = 45
MIN_RECENT_MESSAGES = 5

# An editorial starting shelf for members who have not chosen any interests.
# These are broad career-growth topics, not guesses about someone's identity.
STARTER_TOPICS = {
    "leadership-skills",
    "confidence",
    "sponsorship-mentorship",
    "networking",
    "communication",
}

# Don't infer family status from an incidental tag or someone's job title.
REQUIRES_EXPLICIT_INTEREST = {"working-motherhood"}


def parse_date(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def readable_topic(slug: str, labels: dict[str, str]) -> str:
    return labels.get(slug, slug.replace("-", " ").capitalize()).lower()


def explain(
    *,
    topic: str,
    labels: dict[str, str],
    direct_interest: bool,
    familiar_topic: bool,
    matching_tags: set[str],
    cold_start: bool,
    format: str,
    join_policy: str,
    posts: int,
    chats: int,
) -> str:
    """Short, member-facing reasons, never inferred identities or proximity."""
    subject = readable_topic(topic, labels)
    if direct_interest:
        opening = f"You chose {subject} as an interest."
    elif familiar_topic:
        opening = f"You already belong to a Circle about {subject}."
    elif matching_tags:
        # Tags can be noisy: don't describe a tag match as a direct match.
        related = readable_topic(sorted(matching_tags)[0], labels)
        opening = f"This Circle focuses on {subject} and also lists {related} as a topic."
    elif cold_start:
        opening = f"A starting point for exploring {subject}."
    else:
        opening = f"An option if you'd like to explore {subject}."

    # Eligibility has already checked activity. Say what is actually happening.
    if posts > 0 and chats >= MIN_RECENT_MESSAGES:
        activity = "Members have been posting and chatting recently."
    elif posts > 0:
        activity = "Members have been posting recently."
    else:
        activity = "Members have been chatting recently."

    # The format is useful to members; location is unknown in this dataset.
    format_phrase = {
        "virtual": "meets virtually",
        "hybrid": "offers a hybrid format",
        "in_person": "meets in person",
    }[format]
    join_phrase = "you can join now" if join_policy == "open" else "you can request to join"
    return f"{opening} {activity} It {format_phrase}, and {join_phrase}."


def recommend(conn: sqlite3.Connection, user_id: int, limit: int) -> list[dict]:
    interests = {
        row["topic_slug"]
        for row in conn.execute(
            "SELECT topic_slug FROM user_interests WHERE user_id = ?", (user_id,)
        )
    }
    joined = {
        row["circle_id"]
        for row in conn.execute(
            "SELECT circle_id FROM memberships WHERE user_id = ?", (user_id,)
        )
    }
    familiar_topics = {
        row["topic_slug"]
        for row in conn.execute(
            """SELECT DISTINCT c.topic_slug FROM memberships m
               JOIN circles c ON c.id = m.circle_id
               WHERE m.user_id = ? AND c.topic_slug IS NOT NULL""",
            (user_id,),
        )
    }
    labels = {
        row["slug"]: row["label"] for row in conn.execute("SELECT slug, label FROM topics")
    }
    tags: dict[int, set[str]] = {}
    for row in conn.execute("SELECT circle_id, topic_slug FROM circle_tags"):
        tags.setdefault(row["circle_id"], set()).add(row["topic_slug"])

    # Freeze the clock to the supplied snapshot. Comparing the 2026 fixture to
    # wall-clock time would make the same submission degrade as months pass.
    newest = conn.execute(
        """SELECT MAX(moment) FROM (
               SELECT MAX(created_at) AS moment FROM activity
               UNION ALL SELECT MAX(last_activity_at) FROM circles
           )"""
    ).fetchone()[0]
    snapshot = parse_date(newest)
    recent_cutoff = snapshot - timedelta(days=30)
    engagement: dict[int, int] = {}
    for row in conn.execute(
        "SELECT circle_id, created_at, reaction_count, comment_count, save_count FROM activity"
    ):
        if parse_date(row["created_at"]) >= recent_cutoff:
            cid = row["circle_id"]
            engagement[cid] = engagement.get(cid, 0) + (
                row["reaction_count"] + row["comment_count"] + row["save_count"]
            )

    cold_start = not interests and not joined
    candidates: list[dict] = []

    for circle in conn.execute("SELECT * FROM circles"):
        cid = circle["id"]
        topic = circle["topic_slug"]

        # Eligibility is a gate, not a scoring bonus: a full or inactive Circle
        # should never be recommended just because it matches an interest.
        if cid in joined or circle["access"] != "public" or not topic:
            continue
        if (
            circle["max_members"] is not None
            and circle["member_count"] >= circle["max_members"]
        ):
            continue
        days_idle = max(
            0,
            (snapshot - parse_date(circle["last_activity_at"])).total_seconds() / 86400,
        )
        posts, chats = circle["feed_posts_30d"], circle["chat_messages_30d"]
        if days_idle > MAX_IDLE_DAYS or (posts == 0 and chats < MIN_RECENT_MESSAGES):
            continue
        if (
            topic in REQUIRES_EXPLICIT_INTEREST
            and topic not in (interests | familiar_topics)
        ):
            continue

        direct = topic in interests
        familiar = topic in familiar_topics and not direct
        matching_tags = (tags.get(cid, set()) & interests) - {topic}

        # Strong relevance first; bounded activity signals only refine the order.
        score = 75 if direct else 0
        if familiar:
            score += 18
        score += min(8, 4 * len(matching_tags))
        if cold_start and topic in STARTER_TOPICS:
            score += 14
        score += min(15, 3 * math.log1p(posts) + 1.5 * math.log1p(chats))
        score += max(0, 6 - days_idle / 6)
        score += min(4, math.log1p(engagement.get(cid, 0)))
        score += 3 if circle["join_policy"] == "open" else 0
        if circle["max_members"] is None:
            score += 2
        else:
            score += 2 * (1 - circle["member_count"] / circle["max_members"])
        # Without Circle locations, virtual/hybrid options are generally easier
        # to explore. This is a small nudge, never stronger than an interest.
        score += {"virtual": 4, "hybrid": 3, "in_person": 0}[circle["format"]]
        if cold_start:
            score += {"virtual": 2, "hybrid": 1, "in_person": 0}[circle["format"]]

        candidates.append(
            {
                "circle_id": cid,
                "name": circle["name"],
                "topic": topic,
                "format": circle["format"],
                "join_policy": circle["join_policy"],
                "score": round(score, 2),
                "reason": explain(
                    topic=topic,
                    labels=labels,
                    direct_interest=direct,
                    familiar_topic=familiar,
                    matching_tags=matching_tags,
                    cold_start=cold_start,
                    format=circle["format"],
                    join_policy=circle["join_policy"],
                    posts=posts,
                    chats=chats,
                ),
            }
        )

    candidates.sort(key=lambda c: (-c["score"], c["circle_id"]))

    # Diversity is a product choice: avoid filling the page with similar
    # Circles, including the three seeded negotiation examples.
    chosen: list[dict] = []
    seen_topics: set[str] = set()
    for candidate in candidates:
        if candidate["topic"] in seen_topics:
            continue
        chosen.append(candidate)
        seen_topics.add(candidate["topic"])
        if len(chosen) >= limit:
            break

    for rank, circle in enumerate(chosen, start=1):
        circle["rank"] = rank
    return chosen
