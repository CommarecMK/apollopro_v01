"""
services/freelo.py — nízkoúrovňové HTTP helpery pro Freelo API.

Dokumentováno v CLAUDE.md — klíčová pravidla:
- Auth: Basic (FREELO_EMAIL + FREELO_API_KEY)
- Editace úkolu: POST /task/{id} — nikdy PUT/PATCH
- Popis: POST /task/{id}/description — pouze neprázdný content
- Vytvoření: POST /project/{pid}/tasklist/{tlid}/tasks
"""
import requests
from ..extensions import FREELO_EMAIL, FREELO_API_KEY

BASE_URL = "https://api.freelo.io/v1"


def freelo_auth(user=None):
    """Vrátí (email, api_key) — preferuje credentials uživatele před globálními."""
    if user and getattr(user, "freelo_email", None) and getattr(user, "freelo_api_key", None):
        return (user.freelo_email, user.freelo_api_key)
    return (FREELO_EMAIL, FREELO_API_KEY)


def _get_current_user():
    """Vrátí aktuálně přihlášeného uživatele z Flask session."""
    try:
        from flask import session
        from ..models import User
        uid = session.get("user_id")
        if uid:
            return User.query.get(uid)
    except Exception:
        pass
    return None


def freelo_get(path, params=None, user=None):
    if user is None:
        user = _get_current_user()
    return requests.get(
        f"{BASE_URL}{path}",
        auth=freelo_auth(user),
        headers={"Content-Type": "application/json"},
        params=params,
        timeout=15,
    )


def freelo_post(path, payload, user=None):
    if user is None:
        user = _get_current_user()
    return requests.post(
        f"{BASE_URL}{path}",
        auth=freelo_auth(user),
        headers={"Content-Type": "application/json"},
        json=payload,
        timeout=15,
    )


def freelo_patch(path, payload, user=None):
    if user is None:
        user = _get_current_user()
    return requests.patch(
        f"{BASE_URL}{path}",
        auth=freelo_auth(user),
        headers={"Content-Type": "application/json"},
        json=payload,
        timeout=15,
    )


def freelo_delete(path, user=None):
    if user is None:
        user = _get_current_user()
    return requests.delete(
        f"{BASE_URL}{path}",
        auth=freelo_auth(user),
        headers={"Content-Type": "application/json"},
        timeout=15,
    )


def resolve_worker_id(project_id, assignee_name):
    """Přeloží jméno assignee → worker_id. Vrátí None pokud nenalezen."""
    if not assignee_name or not project_id:
        return None
    try:
        r = freelo_get(f"/project/{project_id}/workers")
        if r.status_code == 200:
            for w in r.json().get("data", {}).get("workers", []):
                if w.get("fullname", "").lower() == assignee_name.strip().lower():
                    return w["id"]
    except Exception:
        pass
    return None


def find_project_id_for_tasklist(tasklist_id, default_project_id):
    """Najde project_id pro daný tasklist_id z /projects."""
    try:
        r = freelo_get("/projects")
        if r.status_code == 200:
            for p in r.json():
                for tl in p.get("tasklists", []):
                    if str(tl.get("id")) == str(tasklist_id):
                        return p["id"]
    except Exception:
        pass
    return default_project_id
