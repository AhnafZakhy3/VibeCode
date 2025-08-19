from typing import Optional, List, Dict
from statistics import mean
from fastapi import FastAPI, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import or_
from passlib.context import CryptContext

from .database import SessionLocal, Base, engine
from .models import User, Message, ExchangeSession, Rating

# Initialize DB
Base.metadata.create_all(bind=engine)

app = FastAPI(title="SkillSwap")
app.add_middleware(SessionMiddleware, secret_key="dev-secret-change-me")

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(request: Request, db: Session) -> Optional[User]:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    return db.query(User).filter(User.id == user_id).first()


def require_login(request: Request, db: Session) -> User:
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=302, detail="Redirect", headers={"Location": "/login"})
    return user


def normalize_skills(skills_text: str) -> List[str]:
    return [s.strip().lower() for s in (skills_text or "").split(",") if s.strip()]


@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    return templates.TemplateResponse("index.html", {"request": request, "user": user})


# Auth
@app.get("/register", response_class=HTMLResponse)
def register_form(request: Request):
    return templates.TemplateResponse("auth/register.html", {"request": request, "error": None})


@app.post("/register")
def register(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    location: str = Form(""),
    bio: str = Form(""),
    skills_offered: str = Form(""),
    skills_wanted: str = Form(""),
    db: Session = Depends(get_db),
):
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        return templates.TemplateResponse(
            "auth/register.html",
            {"request": request, "error": "Email already registered."},
            status_code=400,
        )
    user = User(
        name=name,
        email=email.lower(),
        password_hash=pwd_context.hash(password),
        location=location,
        bio=bio,
        skills_offered=skills_offered,
        skills_wanted=skills_wanted,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    request.session["user_id"] = user.id
    return RedirectResponse("/", status_code=302)


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse("auth/login.html", {"request": request, "error": None})


@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == email.lower()).first()
    if not user or not pwd_context.verify(password, user.password_hash):
        return templates.TemplateResponse(
            "auth/login.html",
            {"request": request, "error": "Invalid credentials."},
            status_code=400,
        )
    request.session["user_id"] = user.id
    return RedirectResponse("/", status_code=302)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=302)


# Profile
@app.get("/profile", response_class=HTMLResponse)
def profile_form(request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)
    return templates.TemplateResponse("users/profile.html", {"request": request, "user": user, "message": None})


@app.post("/profile")
def profile_update(
    request: Request,
    name: str = Form(...),
    location: str = Form(""),
    bio: str = Form(""),
    skills_offered: str = Form(""),
    skills_wanted: str = Form(""),
    db: Session = Depends(get_db),
):
    user = require_login(request, db)
    user.name = name
    user.location = location
    user.bio = bio
    user.skills_offered = skills_offered
    user.skills_wanted = skills_wanted
    db.commit()
    db.refresh(user)
    return templates.TemplateResponse("users/profile.html", {"request": request, "user": user, "message": "Profile updated."})


@app.get("/users/{user_id}", response_class=HTMLResponse)
def view_user(user_id: int, request: Request, db: Session = Depends(get_db)):
    viewer = get_current_user(request, db)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    ratings = db.query(Rating).filter(Rating.ratee_id == user.id).all()
    avg_rating: Optional[float] = mean([r.score for r in ratings]) if ratings else None
    return templates.TemplateResponse("users/view.html", {"request": request, "viewer": viewer, "profile": user, "avg_rating": avg_rating, "ratings": ratings})


# Catalog
@app.get("/skills", response_class=HTMLResponse)
def skill_catalog(request: Request, q: Optional[str] = None, db: Session = Depends(get_db)):
    viewer = get_current_user(request, db)
    query = db.query(User)
    if q:
        like = f"%{q.lower()}%"
        query = query.filter(
            or_(
                User.name.ilike(like),
                User.location.ilike(like),
                User.skills_offered.ilike(like),
                User.skills_wanted.ilike(like),
            )
        )
    users = query.limit(100).all()
    return templates.TemplateResponse("skills/browse.html", {"request": request, "user": viewer, "users": users, "q": q or ""})


# Matchmaking
@app.get("/match", response_class=HTMLResponse)
def match(request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)
    user_offered = set(normalize_skills(user.skills_offered))
    user_wanted = set(normalize_skills(user.skills_wanted))

    matches: List[Dict] = []
    candidates = db.query(User).filter(User.id != user.id).all()
    for c in candidates:
        c_offered = set(normalize_skills(c.skills_offered))
        c_wanted = set(normalize_skills(c.skills_wanted))
        offer_match = c_offered.intersection(user_wanted)
        want_match = c_wanted.intersection(user_offered)
        score = len(offer_match) + len(want_match)
        if score > 0:
            matches.append({
                "user": c,
                "offer_match": sorted(list(offer_match)),
                "want_match": sorted(list(want_match)),
                "score": score,
            })
    matches.sort(key=lambda m: m["score"], reverse=True)
    return templates.TemplateResponse("match/matches.html", {"request": request, "user": user, "matches": matches})


# Messaging
@app.get("/messages", response_class=HTMLResponse)
def inbox(request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)
    messages = (
        db.query(Message)
        .filter(or_(Message.sender_id == user.id, Message.receiver_id == user.id))
        .order_by(Message.created_at.desc())
        .limit(100)
        .all()
    )
    return templates.TemplateResponse("messages/inbox.html", {"request": request, "user": user, "messages": messages})


@app.get("/messages/{peer_id}", response_class=HTMLResponse)
def thread(peer_id: int, request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)
    peer = db.query(User).filter(User.id == peer_id).first()
    if not peer:
        raise HTTPException(status_code=404, detail="User not found")
    messages = (
        db.query(Message)
        .filter(
            or_(
                (Message.sender_id == user.id) & (Message.receiver_id == peer.id),
                (Message.sender_id == peer.id) & (Message.receiver_id == user.id),
            )
        )
        .order_by(Message.created_at.asc())
        .all()
    )
    return templates.TemplateResponse("messages/thread.html", {"request": request, "user": user, "peer": peer, "messages": messages, "error": None})


@app.post("/messages/{peer_id}")
def send_message(peer_id: int, request: Request, content: str = Form(...), db: Session = Depends(get_db)):
    user = require_login(request, db)
    peer = db.query(User).filter(User.id == peer_id).first()
    if not peer:
        raise HTTPException(status_code=404, detail="User not found")
    if not content.strip():
        return templates.TemplateResponse(
            "messages/thread.html",
            {"request": request, "user": user, "peer": peer, "messages": [], "error": "Message cannot be empty."},
            status_code=400,
        )
    msg = Message(sender_id=user.id, receiver_id=peer.id, content=content.strip())
    db.add(msg)
    db.commit()
    return RedirectResponse(f"/messages/{peer.id}", status_code=302)


# Sessions
@app.get("/sessions", response_class=HTMLResponse)
def sessions_list(request: Request, db: Session = Depends(get_db)):
    user = require_login(request, db)
    sessions = (
        db.query(ExchangeSession)
        .filter(or_(ExchangeSession.user_a_id == user.id, ExchangeSession.user_b_id == user.id))
        .order_by(ExchangeSession.occurred_at.desc())
        .limit(100)
        .all()
    )
    return templates.TemplateResponse("sessions/list.html", {"request": request, "user": user, "sessions": sessions})


@app.get("/sessions/new", response_class=HTMLResponse)
def new_session_form(request: Request, with_user: Optional[int] = None, skill: str = "", db: Session = Depends(get_db)):
    user = require_login(request, db)
    partner = db.query(User).filter(User.id == with_user).first() if with_user else None
    users = db.query(User).filter(User.id != user.id).all()
    return templates.TemplateResponse("sessions/new.html", {"request": request, "user": user, "partner": partner, "users": users, "skill": skill})


@app.post("/sessions/new")
def create_session(request: Request, partner_id: int = Form(...), skill: str = Form(...), notes: str = Form(""), db: Session = Depends(get_db)):
    user = require_login(request, db)
    partner = db.query(User).filter(User.id == partner_id).first()
    if not partner:
        raise HTTPException(status_code=404, detail="Partner not found")
    session = ExchangeSession(user_a_id=user.id, user_b_id=partner.id, skill=skill.strip() or "Skill Exchange", notes=notes)
    db.add(session)
    db.commit()
    return RedirectResponse("/sessions", status_code=302)


# Ratings
@app.get("/ratings/new", response_class=HTMLResponse)
def rating_form(request: Request, for_user: Optional[int] = None, db: Session = Depends(get_db)):
    user = require_login(request, db)
    target = db.query(User).filter(User.id == for_user).first() if for_user else None
    users = db.query(User).filter(User.id != user.id).all()
    return templates.TemplateResponse("ratings/new.html", {"request": request, "user": user, "target": target, "users": users})


@app.post("/ratings/new")
def create_rating(request: Request, ratee_id: int = Form(...), score: int = Form(...), comment: str = Form(""), db: Session = Depends(get_db)):
    user = require_login(request, db)
    ratee = db.query(User).filter(User.id == ratee_id).first()
    if not ratee:
        raise HTTPException(status_code=404, detail="User not found")
    s = max(1, min(5, int(score)))
    rating = Rating(rater_id=user.id, ratee_id=ratee.id, score=s, comment=comment)
    db.add(rating)
    db.commit()
    return RedirectResponse(f"/users/{ratee.id}", status_code=302)
