"""routes/zapisy.py"""
from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for, abort, current_app
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from ..extensions import db, ANTHROPIC_API_KEY, FREELO_API_KEY, FREELO_EMAIL, FREELO_PROJECT_ID
from ..models import User, Klient, Zapis, Projekt, Nabidka, NabidkaPolozka, TemplateConfig
from ..auth import login_required, admin_required, role_required, get_current_user, can
from ..config import TEMPLATE_PROMPTS, TEMPLATE_NAMES, TEMPLATE_SECTIONS, SECTION_TITLES
from ..services.freelo import freelo_get, freelo_post, freelo_patch, freelo_delete, resolve_worker_id, find_project_id_for_tasklist
from ..services.ai_service import (build_system_prompt, assemble_output_text,
    condensed_transcript, extract_klient_profil, get_template_prompt)
import os, json, re, secrets, string
import anthropic
import requests

import json as _json
bp = Blueprint("zapisy", __name__)

@bp.route("/novy")
@login_required
def novy_zapis():
    klienti     = Klient.query.filter_by(is_active=True).order_by(Klient.nazev).all()
    konzultanti = User.query.filter_by(is_active=True).all()
    return render_template("novy.html", klienti=klienti,
                           konzultanti=konzultanti, template_names=TEMPLATE_NAMES)


@bp.route("/novy/projekty/<int:klient_id>")
@login_required
def get_projekty_for_klient(klient_id):
    projekty = Projekt.query.filter_by(klient_id=klient_id, is_active=True).all()
    return jsonify([{"id": p.id, "nazev": p.nazev} for p in projekty])


@bp.route("/api/generovat", methods=["POST"])
@login_required
def generovat():
    data        = request.json
    template    = data.get("template", "audit")
    input_text  = data.get("text", "").strip()
    client_info = data.get("client_info", {})
    blocks      = set(client_info.get("blocks", [
        "uvod","zjisteni","hodnoceni","procesy","rizika","kroky","prinosy","poznamky","dalsi_krok"
    ]))
    notes_raw       = data.get("notes", [])   # [{title, text}, ...]
    interni_prompt  = data.get("interni_prompt", "").strip()
    klient_id       = data.get("klient_id")
    projekt_id      = data.get("projekt_id")
    freelo_context  = data.get("freelo_context", [])  # [{id, name, state, description, comments, assignee, deadline}]

    if not input_text:
        return jsonify({"error": "Prazdny text"}), 400

    ai = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Load client profile for context
    klient_profil = None
    if klient_id:
        k = Klient.query.get(klient_id)
        if k:
            try:
                klient_profil = json.loads(k.profil_json or "{}")
            except Exception:
                pass

    # Zkondenzuj dlouhe prepisy — aby vystup AI nepresahl limit tokenu
    # Limit: 6000 znaku ~ 1700 tokenu vstupu, vystup pak snadno vejde do 8000 tokenu
    transcript = input_text
    if len(input_text) > 50000:  # Zkracuj jen opravdu dlouhé přepisy (>50k znaků = cca 2h+)
        try:
            current_app.logger.info(f"Condensing transcript: {len(input_text)} chars")
            transcript = condensed_transcript(ai, input_text)
            current_app.logger.info(f"Condensed to: {len(transcript)} chars")
        except Exception as e:
            current_app.logger.warning(f"Condensation failed, using original: {e}")

    # Combine notes with transcript
    notes_text = ""
    if notes_raw:
        notes_parts = []
        for n in notes_raw:
            if n.get("text","").strip():
                title = n.get("title","Poznamka")
                notes_parts.append(f"[{title}]\n{n['text'].strip()}")
        if notes_parts:
            notes_text = "\n\n".join(notes_parts)

    client_context = f"""
Klient: {client_info.get('client_name', '')}
Kontaktni osoba klienta: {client_info.get('client_contact', '')}
Za Commarec: {client_info.get('commarec_rep', '')}
Datum schuzky: {client_info.get('meeting_date', '')}
Misto: {client_info.get('meeting_place', '')}
Typ schuzky: {TEMPLATE_NAMES.get(template, template)}
"""

    user_message = f"""INFORMACE O SCHUZCE:
{client_context}
"""
    if notes_text:
        user_message += f"\nPOZNAMKY Z TERENU (auditora):\n{notes_text}\n"

    # Přidej Freelo kontext pokud byl vybrán
    if freelo_context:
        freelo_lines = []
        done_tasks = [t for t in freelo_context if t.get("state") == "done"]
        open_tasks = [t for t in freelo_context if t.get("state") == "open"]

        if done_tasks:
            freelo_lines.append(f"DOKONČENÉ ÚKOLY OD POSLEDNÍHO ZÁPISU ({len(done_tasks)}):")
            for t in done_tasks:
                line = f"  ✓ {t['name']}"
                if t.get("assignee"): line += f" [{t['assignee']}]"
                if t.get("date_finished"): line += f" (dokončeno {t['date_finished'][:10]})"
                freelo_lines.append(line)
                if t.get("description"):
                    freelo_lines.append(f"    Popis: {t['description'][:200]}")
                for c in (t.get("comments") or [])[:3]:
                    freelo_lines.append(f"    Komentář ({c.get('author','?')}): {c.get('content','')[:150]}")

        if open_tasks:
            freelo_lines.append(f"\nAKTIVNÍ ÚKOLY ({len(open_tasks)}):")
            for t in open_tasks:
                line = f"  → {t['name']}"
                if t.get("assignee"): line += f" [{t['assignee']}]"
                if t.get("deadline"): line += f" (termín {t['deadline'][:10]})"
                freelo_lines.append(line)
                if t.get("description"):
                    freelo_lines.append(f"    Popis: {t['description'][:200]}")
                for c in (t.get("comments") or [])[:2]:
                    freelo_lines.append(f"    Komentář ({c.get('author','?')}): {c.get('content','')[:150]}")

        if freelo_lines:
            user_message += f"\n\nFREELO ÚKOLY — STAV A ZMĚNY:\n" + "\n".join(freelo_lines) + "\n"
            user_message += "\nTyto Freelo úkoly zahrň DO SEKCE ===FREELO_STATUS=== jako přehlednou HTML tabulku.\n"
            user_message += "Do ostatních sekcí (SUGGESTED_ACTIONS apod.) Freelo úkoly NEDÁVEJ — tam piš pouze nové kroky vycházející z obsahu schůzky.\n"

    user_message += f"\nPREPIS / POZNAMKY ZE SCHUZKY:\n{transcript}"

    system = build_system_prompt(interni_prompt, klient_profil, template)

    try:
        message = ai.messages.create(
            model="claude-sonnet-4-5", max_tokens=8000,
            system=system,
            messages=[{"role": "user", "content": user_message}]
        )
        raw = message.content[0].text.strip()
        current_app.logger.info(f"AI response: {len(raw)} chars, stop={message.stop_reason}")
    except Exception as e:
        return jsonify({"error": f"Chyba API: {str(e)}"}), 500

    # Parse section markers ===SEKCE===
    SECTION_KEYS = [
        # Standardní sekce (všechny typy)
        "participants_commarec", "participants_company", "introduction", "meeting_goal",
        "findings", "ratings", "processes_description", "dangers", "suggested_actions",
        "expected_benefits", "additional_notes", "summary", "tasks",
        # Freelo status — samostatná sekce pro stav úkolů
        "freelo_status",
        # Operativa
        "current_state",
        # Obchod
        "client_situation", "client_needs", "opportunities", "risks",
        "commercial_model", "next_steps", "expected_impact", "client_signals",
    ]

    def parse_sections(text):
        """Parsuje sekce z AI odpovědi. Zvládá různé formáty markerů.
        Také opravuje časté chyby: JSON pole místo HTML, raw text bez markerů.
        """
        result = {}
        current_key = None
        current_lines = []

        # Normalizuj alternativní markery na standard ===KEY===
        import re as _re
        # Zvládne: ## PARTICIPANTS_COMMAREC, # PARTICIPANTS_COMMAREC:, **PARTICIPANTS_COMMAREC**
        alt_marker = _re.compile(
            r'^(?:#+\s*|[*]{2})?([A-Z_]{3,30})(?:[:\s*]*)?$'
        )

        for line in text.split("\n"):
            stripped = line.strip()

            # Hlavní formát: ===KEY===
            if stripped.startswith("===") and stripped.endswith("==="):
                if current_key:
                    result[current_key] = "\n".join(current_lines).strip()
                inner = stripped.strip("=").strip()
                if inner.upper().startswith("SEKCE:"):
                    inner = inner[6:].strip()
                marker = inner.lower().replace(" ", "_").replace("-", "_")
                if marker in SECTION_KEYS:
                    current_key = marker
                    current_lines = []
                else:
                    current_key = None
                    current_lines = []

            # Fallback: alternativní markery (## PARTICIPANTS_COMMAREC)
            elif not current_key or not current_lines:
                m = alt_marker.match(stripped)
                if m:
                    candidate = m.group(1).lower()
                    if candidate in SECTION_KEYS:
                        if current_key:
                            result[current_key] = "\n".join(current_lines).strip()
                        current_key = candidate
                        current_lines = []
                        continue
                if current_key:
                    current_lines.append(line)
            else:
                current_lines.append(line)

        if current_key:
            result[current_key] = "\n".join(current_lines).strip()

        # Oprav hodnoty: JSON array ["x","y"] → <p>x, y</p>
        for k, v in result.items():
            if v and v.strip().startswith('[') and v.strip().endswith(']'):
                try:
                    import json as _json
                    items = _json.loads(v.strip())
                    if isinstance(items, list):
                        result[k] = "<p>" + ", ".join(str(i) for i in items) + "</p>"
                except Exception:
                    pass

        return result

    def parse_tasks(tasks_text):
        """Parsuje UKOL/POPIS/TERMIN bloky ze sekce TASKS."""
        tasks = []
        if not tasks_text:
            return tasks
        current = {}
        for line in tasks_text.split("\n"):
            line = line.strip()
            if line.startswith("UKOL:"):
                if current.get("name"):
                    tasks.append(current)
                current = {"name": line[5:].strip()[:200], "desc": "", "deadline": "dle dohody"}
            elif line.startswith("POPIS:") and current:
                current["desc"] = line[6:].strip()
            elif line.startswith("TERMIN:") and current:
                current["deadline"] = line[7:].strip()
            elif line == "---" and current.get("name"):
                tasks.append(current)
                current = {}
        if current.get("name"):
            tasks.append(current)
        return tasks[:8]

    summary_json = parse_sections(raw)
    current_app.logger.info(f"Parsed sections: {list(summary_json.keys())}")

    # Pokud parser nic nenasel — AI ignorovalo format, zkus znovu s pripomentim
    if not summary_json:
        current_app.logger.warning(f"No sections found, retrying. Raw start: {raw[:200]}")
        retry_msg = user_message + """

DULEZITE: Tvuj vystup MUSI zacinat presne takto (bez jakehokoliv uvodni textu):
===PARTICIPANTS_COMMAREC===
...obsah...
===PARTICIPANTS_COMPANY===
...obsah...
atd.

Pouzij PRESNE tyto markery, jinak aplikace zapis nezobrazi."""
        try:
            retry = ai.messages.create(
                model="claude-sonnet-4-5", max_tokens=8000,
                system=system,
                messages=[{"role": "user", "content": retry_msg}]
            )
            raw = retry.content[0].text.strip()
            summary_json = parse_sections(raw)
            current_app.logger.info(f"Retry parsed sections: {list(summary_json.keys())}")
        except Exception as e:
            current_app.logger.error(f"Retry failed: {e}")

    if not summary_json:
        current_app.logger.error(f"Both attempts failed. Raw: {raw[:400]}")
        return jsonify({"error": f"AI nevrátilo ocekávany format ani po opakování. Začátek odpovědi: {raw[:150]}"}), 500

    tasks = parse_tasks(summary_json.pop("tasks", ""))

    output_text = assemble_output_text(client_info, summary_json, blocks)

    # Build title
    client_name  = client_info.get("client_name","").strip()
    meeting_date = client_info.get("meeting_date","").strip()
    title = f"{client_name} - {meeting_date}" if client_name else f"Zapis {meeting_date}"

    # Auto-update client profile v pozadí (neblokuje odpověď)
    if klient_id:
        import threading
        def update_profil_bg(app_ctx, kid, text):
            with app_ctx:
                try:
                    k = Klient.query.get(kid)
                    if k:
                        ai_bg = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
                        existing = json.loads(k.profil_json or "{}")
                        new_profil = extract_klient_profil(ai_bg, text[:10000], existing)
                        k.profil_json = json.dumps(new_profil, ensure_ascii=False)
                        db.session.commit()
                except Exception as e:
                    current_app.logger.warning(f"BG profile extraction failed: {e}")
        t = threading.Thread(target=update_profil_bg, args=(current_app._get_current_object().app_context(), int(klient_id), input_text), daemon=True)
        t.start()

    zapis = Zapis(
        title=title, template=template,
        input_text=input_text,
        output_json=json.dumps(summary_json, ensure_ascii=False),
        output_text=output_text,
        tasks_json=json.dumps(tasks, ensure_ascii=False),
        notes_json=json.dumps(notes_raw, ensure_ascii=False),
        interni_prompt=interni_prompt,
        user_id=session["user_id"],
        klient_id=int(klient_id) if klient_id else None,
        projekt_id=int(projekt_id) if projekt_id else None,
    )
    db.session.add(zapis)
    db.session.commit()

    return jsonify({"zapis_id": zapis.id, "text": output_text,
                    "tasks": tasks, "title": title, "summary": summary_json})

# ─────────────────────────────────────────────
# API — EDIT SECTION
# ─────────────────────────────────────────────

@bp.route("/api/zapis/<int:zapis_id>/sekce", methods=["POST"])
@login_required
def ulozit_sekci(zapis_id):
    zapis = Zapis.query.get_or_404(zapis_id)
    data  = request.json or {}
    key   = data.get("key","")
    html  = data.get("html","")
    if key not in SECTION_TITLES:
        return jsonify({"error": "Neznama sekce"}), 400
    try:
        summary = json.loads(zapis.output_json or "{}")
    except Exception:
        summary = {}
    summary[key] = html
    zapis.output_json = json.dumps(summary, ensure_ascii=False)
    db.session.commit()
    return jsonify({"ok": True})

@bp.route("/api/zapis/<int:zapis_id>/ai-sekce", methods=["POST"])
@login_required
def ai_upravit_sekci(zapis_id):
    zapis = Zapis.query.get_or_404(zapis_id)
    data  = request.json or {}
    key          = data.get("key","")
    user_prompt  = data.get("prompt","").strip()
    current_html = data.get("html","")
    if not user_prompt:
        return jsonify({"error": "Chybi instrukce"}), 400
    section_title = SECTION_TITLES.get(key, key)
    system = f"""Uprav tuto sekci zapisu ze schuzky podle instrukce uzivatele.
Sekce: {section_title}
Zachovej styl, strukturu a HTML formatting pokud instrukce nerika jinak.
Vrat POUZE upravene HTML bez komentaru, vysvetleni nebo markdown znacek."""
    try:
        ai = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = ai.messages.create(
            model="claude-sonnet-4-5", max_tokens=2000,
            system=system,
            messages=[{"role": "user", "content": f"ORIGINAL HTML:\n{current_html}\n\nINSTRUKCE:\n{user_prompt}"}]
        )
        new_html = msg.content[0].text.strip()
        new_html = re.sub(r'^```[\w]*\n?', '', new_html)
        new_html = re.sub(r'\n?```$', '', new_html).strip()
        return jsonify({"ok": True, "html": new_html})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bp.route("/api/zapis/<int:zapis_id>/notes", methods=["POST"])
@login_required
def ulozit_notes(zapis_id):
    zapis = Zapis.query.get_or_404(zapis_id)
    notes = request.json or []
    zapis.notes_json = json.dumps(notes, ensure_ascii=False)
    db.session.commit()
    return jsonify({"ok": True})

# ─────────────────────────────────────────────
# FREELO HELPERS
# ─────────────────────────────────────────────

def sanitize_summary(summary):
    """Oprav časté problémy v AI výstupu uloženém v DB."""
    if not isinstance(summary, dict):
        return {}
    cleaned = {}
    for key, val in summary.items():
        if not val:
            cleaned[key] = val
            continue
        val = str(val).strip()
        # JSON array ["x","y"] → <p>x, y</p>
        if val.startswith('[') and val.endswith(']'):
            try:
                items = json.loads(val)
                if isinstance(items, list):
                    val = "<p>" + ", ".join(str(i).strip('"') for i in items) + "</p>"
            except Exception:
                pass
        # Markdown bold **text** → <strong>text</strong>
        import re
        val = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', val)
        # Markdown bullet • nebo - na začátku řádku → <li>
        if '\n' in val and not val.strip().startswith('<'):
            lines = val.split('\n')
            html_lines = []
            in_ul = False
            for line in lines:
                line = line.strip()
                if not line:
                    if in_ul:
                        html_lines.append('</ul>')
                        in_ul = False
                    continue
                if line.startswith(('• ', '- ', '* ')):
                    if not in_ul:
                        html_lines.append('<ul>')
                        in_ul = True
                    html_lines.append(f'<li>{line[2:]}</li>')
                else:
                    if in_ul:
                        html_lines.append('</ul>')
                        in_ul = False
                    html_lines.append(f'<p>{line}</p>')
            if in_ul:
                html_lines.append('</ul>')
            val = '\n'.join(html_lines)
        cleaned[key] = val
    return cleaned


@bp.route("/zapis/<int:zapis_id>")
@bp.route("/zapis/<int:zapis_id>")
@login_required
def detail_zapisu(zapis_id):
    zapis = Zapis.query.get_or_404(zapis_id)
    tasks = json.loads(zapis.tasks_json or "[]")
    notes = json.loads(zapis.notes_json or "[]")
    try:
        summary = json.loads(zapis.output_json or "{}")
    except Exception:
        summary = {}
    # Sanitizuj hodnoty — oprav JSON arrays (["x","y"]) → HTML text
    summary = sanitize_summary(summary)

    # Tasklist klienta — pokud je nastaven, zápis ho použije automaticky (bez dropdownu)
    klient_tasklist_id = None
    klient_tasklist_name = None
    klient_project_name = None
    if zapis.klient and zapis.klient.freelo_tasklist_id:
        klient_tasklist_id = zapis.klient.freelo_tasklist_id
        # Pokus se načíst název tasklist z Freelo
        try:
            r = freelo_get(f"/tasklist/{klient_tasklist_id}")
            if r.status_code == 200:
                d = r.json()
                klient_tasklist_name = d.get("name", str(klient_tasklist_id))
        except Exception:
            klient_tasklist_name = str(klient_tasklist_id)

    return render_template("detail.html", zapis=zapis, tasks=tasks, notes=notes,
                           summary=summary, section_titles=SECTION_TITLES,
                           template_names=TEMPLATE_NAMES,
                           klient_tasklist_id=klient_tasklist_id,
                           klient_tasklist_name=klient_tasklist_name,
                           klient_project_name=klient_project_name)

@bp.route("/zapis/verejny/<token>")
def zapis_verejny(token):
    zapis = Zapis.query.filter_by(public_token=token, is_public=True).first_or_404()
    try:
        summary = json.loads(zapis.output_json or "{}")
    except Exception:
        summary = {}
    summary = sanitize_summary(summary)
    return render_template("verejny.html", zapis=zapis, summary=summary,
                           section_titles=SECTION_TITLES, template_names=TEMPLATE_NAMES)

@bp.route("/api/zapis/<int:zapis_id>/publikovat", methods=["POST"])
@login_required
def zapis_publikovat(zapis_id):
    zapis = Zapis.query.get_or_404(zapis_id)
    data  = request.json or {}
    publish = data.get("publish", True)
    if publish and not zapis.public_token:
        zapis.public_token = secrets.token_urlsafe(20)
    zapis.is_public = bool(publish)
    db.session.commit()
    url = url_for("zapisy.zapis_verejny", token=zapis.public_token, _external=True) if zapis.is_public else None
    return jsonify({"ok": True, "is_public": zapis.is_public, "url": url, "token": zapis.public_token})

