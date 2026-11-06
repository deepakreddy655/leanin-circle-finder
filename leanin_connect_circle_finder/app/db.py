"""SQLite schema and deterministic loading of the provided synthetic snapshot."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS topics (
    id INTEGER PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    label TEXT NOT NULL,
    domain TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    has_photo INTEGER NOT NULL CHECK (has_photo IN (0, 1)),
    bio TEXT,
    job_title TEXT,
    company TEXT,
    industry TEXT,
    location TEXT,
    joined_at TEXT NOT NULL,
    profile_completeness REAL NOT NULL CHECK (profile_completeness BETWEEN 0 AND 1)
);

CREATE TABLE IF NOT EXISTS user_interests (
    user_id INTEGER NOT NULL REFERENCES users(id),
    topic_slug TEXT NOT NULL REFERENCES topics(slug),
    PRIMARY KEY (user_id, topic_slug)
);

CREATE TABLE IF NOT EXISTS circles (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    description TEXT,
    topic_slug TEXT REFERENCES topics(slug),
    cover_image_url TEXT,
    format TEXT NOT NULL CHECK (format IN ('in_person', 'virtual', 'hybrid')),
    access TEXT NOT NULL CHECK (access IN ('public', 'unlisted')),
    join_policy TEXT NOT NULL CHECK (join_policy IN ('open', 'request')),
    max_members INTEGER CHECK (max_members IS NULL OR max_members > 0),
    member_count INTEGER NOT NULL CHECK (member_count >= 0),
    created_at TEXT NOT NULL,
    last_activity_at TEXT NOT NULL,
    feed_posts_30d INTEGER NOT NULL CHECK (feed_posts_30d >= 0),
    chat_messages_30d INTEGER NOT NULL CHECK (chat_messages_30d >= 0)
);

CREATE TABLE IF NOT EXISTS circle_tags (
    circle_id INTEGER NOT NULL REFERENCES circles(id),
    topic_slug TEXT NOT NULL REFERENCES topics(slug),
    PRIMARY KEY (circle_id, topic_slug)
);

CREATE TABLE IF NOT EXISTS memberships (
    user_id INTEGER NOT NULL REFERENCES users(id),
    circle_id INTEGER NOT NULL REFERENCES circles(id),
    role TEXT NOT NULL CHECK (role IN ('member', 'leader')),
    joined_at TEXT NOT NULL,
    PRIMARY KEY (user_id, circle_id)
);

CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY,
    circle_id INTEGER NOT NULL REFERENCES circles(id),
    author_user_id INTEGER NOT NULL REFERENCES users(id),
    body TEXT NOT NULL,
    reaction_count INTEGER NOT NULL CHECK (reaction_count >= 0),
    comment_count INTEGER NOT NULL CHECK (comment_count >= 0),
    save_count INTEGER NOT NULL CHECK (save_count >= 0),
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_circles_topic ON circles(topic_slug);
CREATE INDEX IF NOT EXISTS idx_circles_discovery ON circles(access, last_activity_at);
CREATE INDEX IF NOT EXISTS idx_memberships_circle ON memberships(circle_id);
CREATE INDEX IF NOT EXISTS idx_circle_tags_topic ON circle_tags(topic_slug);
CREATE INDEX IF NOT EXISTS idx_activity_circle ON activity(circle_id);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _load(data_dir: Path, filename: str) -> list[dict]:
    with (data_dir / filename).open(encoding="utf-8") as file:
        return json.load(file)


def initialize(db_path: Path, data_dir: Path) -> None:
    """Create a local DB on first run; never silently overwrite existing data."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect(db_path)) as conn:
        conn.executescript(SCHEMA)
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
            return

        topics = _load(data_dir, "topics.json")
        users = _load(data_dir, "users.json")
        circles = _load(data_dir, "circles.json")
        memberships = _load(data_dir, "memberships.json")
        activity = _load(data_dir, "activity.json")

        # One transaction: a failed seed should never leave partially loaded data.
        with conn:
            conn.executemany(
                "INSERT INTO topics (id, slug, label, domain) VALUES (:id, :slug, :label, :domain)",
                topics,
            )
            conn.executemany(
                """INSERT INTO users (id, first_name, last_name, has_photo, bio,
                   job_title, company, industry, location, joined_at, profile_completeness)
                   VALUES (:id, :first_name, :last_name, :has_photo, :bio, :job_title,
                   :company, :industry, :location, :joined_at, :profile_completeness)""",
                users,
            )
            conn.executemany(
                "INSERT INTO user_interests (user_id, topic_slug) VALUES (?, ?)",
                [(user["id"], slug) for user in users for slug in user["topic_interests"]],
            )
            conn.executemany(
                """INSERT INTO circles (id, name, slug, description, topic_slug,
                   cover_image_url, format, access, join_policy, max_members,
                   member_count, created_at, last_activity_at, feed_posts_30d,
                   chat_messages_30d)
                   VALUES (:id, :name, :slug, :description, :topic, :cover_image_url,
                   :format, :access, :join_policy, :max_members, :member_count,
                   :created_at, :last_activity_at, :feed_posts_30d,
                   :chat_messages_30d)""",
                circles,
            )
            conn.executemany(
                "INSERT INTO circle_tags (circle_id, topic_slug) VALUES (?, ?)",
                [(circle["id"], tag) for circle in circles for tag in set(circle["tags"])],
            )
            conn.executemany(
                """INSERT INTO memberships (user_id, circle_id, role, joined_at)
                   VALUES (:user_id, :circle_id, :role, :joined_at)""",
                memberships,
            )
            conn.executemany(
                """INSERT INTO activity (id, circle_id, author_user_id, body,
                   reaction_count, comment_count, save_count, created_at)
                   VALUES (:id, :circle_id, :author_user_id, :body, :reaction_count,
                   :comment_count, :save_count, :created_at)""",
                activity,
            )
