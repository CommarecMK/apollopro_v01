"""routes/portal.py"""
from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for, abort, current_app
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from ..extensions import db, ANTHROPIC_API_KEY, FREELO_API_KEY, FREELO_EMAIL, FREELO_PROJECT_ID
from ..models import User, Klient, Zapis, Projekt, Nabidka, NabidkaPolozka, TemplateConfig
from ..auth import login_required, admin_required, role_required, get_current_user, can
from ..config import TEMPLATE_PROMPTS, TEMPLATE_NAMES, TEMPLATE_SECTIONS, SECTION_TITLES
from ..services.freelo import freelo_get, freelo_post, freelo_patch, freelo_delete, resolve_worker_id, find_project_id_for_tasklist
import os, json, re, secrets, string
import anthropic
import requests

bp = Blueprint("portal", __name__)

@bp.route("/portal")
def klient_portal():
    """Portál pro klienta — vidí jen své zápisy, nabídky, Freelo úkoly."""
    if "user_id" not in session:
        return redirect(url_for("main.login"))
    u = User.query.get(session["user_id"])
    if not u or u.role != "klient":
        return redirect(url_for("main.prehled"))
    
    if not u.klient_id:
        return render_template("portal.html", klient=None, zapisy=[], nabidky=[], ukoly=[])
    
    k = Klient.query.get(u.klient_id)
    zapisy = Zapis.query.filter_by(klient_id=k.id).order_by(Zapis.created_at.desc()).all()
    nabidky = Nabidka.query.filter_by(klient_id=k.id).order_by(Nabidka.created_at.desc()).all()
    
    # Freelo úkoly
    ukoly = []
    if k.freelo_tasklist_id and FREELO_API_KEY and FREELO_EMAIL:
        try:
            resp = freelo_get(f"/tasklist/{k.freelo_tasklist_id}")
            if resp.status_code == 200:
                raw = resp.json()
                tasks_raw = raw.get("tasks", raw.get("data", []))
                for t in tasks_raw:
                    if not isinstance(t, dict): continue
                    is_done = bool(t.get("date_finished"))
                    ukoly.append({
                        "name": t.get("name", ""),
                        "state": "done" if is_done else "open",
                        "assignee": t.get("worker", {}).get("fullname", "") if t.get("worker") else "",
                        "deadline": (t.get("due_date") or "")[:10],
                    })
        except Exception:
            pass
    
    return render_template("portal.html", klient=k, zapisy=zapisy, nabidky=nabidky, ukoly=ukoly)


# entry point removed (handled by run.py)


# ─────────────────────────────────────────────
# TEST ENDPOINT — ZODPOVĚDNÁ OSOBA (worker_id)
# Otevři: /api/freelo/test-worker/<project_id>/<tasklist_id>
# Příklad: /api/freelo/test-worker/582553/1810216
# ─────────────────────────────────────────────
@bp.route("/api/freelo/test-worker/<int:project_id>/<int:tasklist_id>")
@login_required
def test_freelo_worker(project_id, tasklist_id):
    """
    Kompletní test zodpovědné osoby:
    1. Načte members projektu
    2. Vytvoří testovací úkol BEZ worker_id
    3. Vytvoří testovací úkol S worker_id (první člen)
    4. Upraví úkol přes POST /task/{id} s worker_id
    5. Zobrazí výsledky — uvidíš přesně kde se worker ztrácí
    """
    log = []
