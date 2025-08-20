## SkillSwap (MVP)

A peer-to-peer platform where users exchange skills via knowledge barter instead of money.

### Quickstart

1) Create a virtual environment (optional but recommended)

```bash
python -m venv .venv
.venv\Scripts\activate
```

2) Install dependencies

```bash
pip install -r requirements.txt
```

3) Run the app

```bash
uvicorn app.main:app --reload
```

Then open `http://127.0.0.1:8000` in your browser.

### Features (MVP)
- Registration and Login (session-based)
- User Profiles (name, location, offered skills, wanted skills)
- Skill Catalog (browse/search)
- Basic Matchmaking (complementary skills)
- Messaging (user-to-user)
- Session Tracking (log completed exchanges)
- Feedback & Ratings

### Tech
- FastAPI, Jinja2 templates
- SQLite via SQLAlchemy
- Session cookies using Starlette middleware

### Notes
- This MVP stores skills as comma-separated values to keep the schema simple.
- You can reset the database by deleting `skillswap.db` (created on first run).
