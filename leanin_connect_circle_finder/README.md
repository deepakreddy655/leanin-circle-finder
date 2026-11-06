# Circle Finder

**A small recommendation API for Lean In Connect.**

A Circle can match someone's interests perfectly and still be a poor recommendation if it's full, inactive, or already on their list. I built this around a simple rule: **find Circles people can actually join, then explain why each one is worth considering.**

This is a take-home exercise using Lean In's provided **synthetic** data. No AI API, external service, or paid account is needed to run it.

## Run it locally

Requires **Python 3.10+**.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
uvicorn app.main:app --reload
```

On first startup, the app imports the five original JSON files into `.local/leanin.db`. It reuses that database on subsequent runs. To reset it, stop the server and delete `.local/leanin.db`.

Open **http://127.0.0.1:8000/docs** to try the endpoint interactively.

### API

`GET /recommendations/{user_id}?limit=5`

- `user_id`: a seeded member ID (1–100)
- `limit`: number of results, 1–20; default 5
- Response: Circle IDs, names, topics, formats, join policies, ranking scores, and short member-facing reasons
- Unknown member: `404`; invalid limit: `422`; no eligible Circles: an empty list

Try the four cases called out in the dataset:

```bash
curl -s 'http://127.0.0.1:8000/recommendations/42?limit=5' | python3 -m json.tool
curl -s 'http://127.0.0.1:8000/recommendations/7?limit=5' | python3 -m json.tool
curl -s 'http://127.0.0.1:8000/recommendations/15?limit=5' | python3 -m json.tool
curl -s 'http://127.0.0.1:8000/recommendations/23?limit=5' | python3 -m json.tool
```

Example of a recommendation for user 23 (fields shortened):

```json
{
  "circle_id": 22,
  "name": "Level Up Collective",
  "topic": "getting-promoted",
  "join_policy": "request",
  "reason": "You chose getting promoted as an interest. Members have been posting and chatting recently. It offers a hybrid format, and you can request to join."
}
```

`GET /health` returns `{"status":"ok"}`.

## How I approached the recommendations

**1. Eligibility before ranking.** Never recommend a Circle that is already joined, unlisted, at capacity, or inactive. Request-to-join Circles are allowed, but their explanation says approval is required.

**2. Member goals before popularity.** An exact match to a selected interest gets the strongest weight. Topics from existing memberships are a secondary clue. Tags are weaker still, because the supplied tags can be noisy. Community activity helps choose among reasonable matches; it doesn't override the member's interests.

**3. A useful cold start.** When a member has no interests or memberships, offer a varied starting shelf around leadership, confidence, mentorship, networking, and communication. Prefer virtual/hybrid options slightly because the data doesn't give Circle locations. Don't invent a member's interests or background.

**4. Room to explore.** Show at most one Circle per primary topic in a response. This keeps the three near-identical negotiation Circles from taking over the page.

**5. Reasons that can be defended.** The reason describes a direct interest, familiar topic, secondary tag, or exploration option accurately. It also mentions activity, meeting format, and whether joining requires approval. No claims about geographic proximity or people being "like you."

The scoring constants are **heuristics, not trained probabilities**. The snapshot is from September 2026, so activity freshness is measured relative to the newest timestamp in the dataset, not today's date.

## Check the behavior

```bash
python -m pytest -q
```

The 18 tests cover all 100 members, the four planted scenarios, HTTP validation, foreign-key integrity, and what happens when a good match becomes full or inactive. They also check that high popularity can't overwhelm a stated interest, and that explanations don't treat weak tags as exact matches.

## Files

```text
app/main.py                FastAPI route and response models
app/recommend.py           Eligibility, ranking, diversity, explanations
app/db.py                  SQLite schema, indexes, JSON importer
data/*.json                Original synthetic dataset (unchanged)
tests/                     API and product-behavior tests
docs/TECHNICAL_DESIGN.md   One-page design and tradeoffs
docs/SCHEMA.md             Tables, relationships, and indexes
```

Read [the one-page design](docs/TECHNICAL_DESIGN.md) and [the schema notes](docs/SCHEMA.md) for the reasoning behind the implementation.
