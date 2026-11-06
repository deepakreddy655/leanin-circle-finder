# Database schema and indexes

The supplied files are a synthetic snapshot. I use **SQLite** to keep the assessment runnable without Docker or database credentials. The executable DDL and seed loader live in [`app/db.py`](../app/db.py).

| Table | Primary key | Purpose and relationships |
| --- | --- | --- |
| `users` | `id` | Member profile, including stated profile completeness |
| `topics` | `id` | Canonical topic slug, label, and domain (`slug` is unique) |
| `user_interests` | `(user_id, topic_slug)` | Many-to-many link from members to topics |
| `circles` | `id` | Circle topic, description, format, access, capacity, and activity aggregates |
| `circle_tags` | `(circle_id, topic_slug)` | Many-to-many Circle-to-topic tags; duplicate source tags are deduplicated on import |
| `memberships` | `(user_id, circle_id)` | Member or leader role, plus join date |
| `activity` | `id` | Feed posts linked to Circle and author, with engagement counts |

All relationship columns have foreign keys. Check constraints protect nonnegative activity and capacity counts, known format/access/join-policy values, and the 0–1 profile completeness range. `max_members=NULL` means the Circle is uncapped; it does **not** mean full.

**Indexes and rationale**

- `circles(topic_slug)`: look up Circles for a selected interest.
- `circles(access, last_activity_at)`: narrow discovery to public and recently active Circles.
- `memberships(circle_id)`: reverse membership lookups (the composite primary key already supports lookups by user).
- `circle_tags(topic_slug)`: find Circles tagged with an interest.
- `activity(circle_id)`: aggregate engagement by Circle.

The many-to-many primary keys also prevent duplicate memberships and interests. Seeding is transactional and doesn't overwrite an existing database. In a production service, I'd migrate to PostgreSQL, maintain member counts transactionally, index frequently filtered candidate sets, and precompute activity features rather than scanning the full catalog per request.
