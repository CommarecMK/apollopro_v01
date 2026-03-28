"""routes/main.py — přihlášení, dashboard, přehled, CRM."""
from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for, abort, current_app
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from ..extensions import db, ANTHROPIC_API_KEY, FREELO_API_KEY, FREELO_EMAIL, FREELO_PROJECT_ID
from ..models import User, Klient, Zapis, Projekt, Nabidka, NabidkaPolozka, TemplateConfig
from ..auth import login_required, admin_required, get_current_user, can
from ..config import TEMPLATE_PROMPTS, TEMPLATE_NAMES, TEMPLATE_SECTIONS, SECTION_TITLES
from ..services.freelo import freelo_get, freelo_post, freelo_patch, freelo_delete, resolve_worker_id, find_project_id_for_tasklist
from ..services.ai_service import slug_from_name
import os, json, re, secrets, string
import anthropic
import requests

from smtplib import SMTP_SSL
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from werkzeug.utils import secure_filename

bp = Blueprint("main", __name__)

# ROUTES — AUTH
# ─────────────────────────────────────────────


@bp.route("/home")
@login_required  
def home():
    """Nový dashboard — status overview rozcestník."""
    now = datetime.utcnow()
    cutoff_60 = now - timedelta(days=60)
    cutoff_30 = now - timedelta(days=30)

    klienti_all = Klient.query.filter_by(is_active=True).all()
    
    stats = {
        "klienti_aktivni": len(klienti_all),
        "projekty_aktivni": Projekt.query.filter_by(is_active=True).count(),
        "zapisy_celkem": Zapis.query.count(),
        "zapisy_30d": Zapis.query.filter(Zapis.created_at >= cutoff_30).count(),
        "bez_aktivity": 0,
        "nabidky_otevrene": Nabidka.query.filter(
            Nabidka.stav.in_(["draft", "odeslana"])
        ).count(),
    }

    pozor_klienti = []
    for k in klienti_all:
        posledni = Zapis.query.filter_by(klient_id=k.id)            .order_by(Zapis.created_at.desc()).first()
        if not posledni or posledni.created_at < cutoff_60:
            dni = (now - posledni.created_at).days if posledni else 999
            if dni > 60:
                pozor_klienti.append({"klient": k, "posledni": posledni, "dni": min(dni, 999)})
    stats["bez_aktivity"] = len(pozor_klienti)
    pozor_klienti = sorted(pozor_klienti, key=lambda x: -x["dni"])[:5]

    aktivita = []
    for z in Zapis.query.order_by(Zapis.created_at.desc()).limit(12).all():
        aktivita.append({
            "typ": z.template or "audit",
            "typ_label": {"audit": "Audit", "operativa": "Operativa", "obchod": "Obchod"}.get(z.template, "Zápis"),
            "title": z.title or (z.projekt.nazev if z.projekt else k.nazev if z.klient else "Zápis"),
            "klient": z.klient.nazev if z.klient else "",
            "projekt": z.projekt.nazev if z.projekt else "",
            "datum": z.created_at,
            "url": url_for("zapisy.detail_zapisu", zapis_id=z.id),
        })
    for n in Nabidka.query.order_by(Nabidka.created_at.desc()).limit(5).all():
        aktivita.append({
            "typ": "nabidka",
            "typ_label": "Nabídka",
            "title": f"{n.cislo} — {n.nazev}",
            "klient": n.klient.nazev if n.klient else "",
            "projekt": n.projekt.nazev if n.projekt else "",
            "datum": n.created_at,
            "url": url_for("nabidky.nabidka_detail", nabidka_id=n.id),
        })
    aktivita.sort(key=lambda x: x["datum"], reverse=True)
    aktivita = aktivita[:15]

    aktivni_projekty = Projekt.query.filter_by(is_active=True)        .order_by(db.case((Projekt.datum_do == None, 1), else_=0), Projekt.datum_do.asc())        .limit(8).all()

    current_user = User.query.get(session["user_id"])

    return render_template("dashboard_new.html",
                           stats=stats, aktivita=aktivita,
                           pozor_klienti=pozor_klienti,
                           aktivni_projekty=aktivni_projekty,
                           now=now,
                           current_user=current_user)

@bp.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("main.prehled"))
    return redirect(url_for("main.login"))

@bp.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()
        if user and user.is_active and check_password_hash(user.password_hash, password):
            session["user_id"]   = user.id
            session["user_name"] = user.name
            session["is_admin"]  = user.is_admin
            session["user_role"] = user.role
            return redirect(url_for("main.dashboard"))
        error = "Nespravny e-mail nebo heslo."
    return render_template("login.html", error=error)

@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("main.login"))

# ─────────────────────────────────────────────
# ROUTES — DASHBOARD
# ─────────────────────────────────────────────

@bp.route("/dashboard")
@login_required
def dashboard():
    zapisy  = Zápisy_query()
    klienti = Klient.query.filter_by(is_active=True).order_by(Klient.nazev).all()
    stats = {
        "celkem":  Zapis.query.count(),
        "freelo":  Zapis.query.filter_by(freelo_sent=True).count(),
        "klienti": Klient.query.filter_by(is_active=True).count(),
        "projekty": Projekt.query.filter_by(is_active=True).count(),
    }
    return render_template("dashboard.html", zapisy=zapisy, klienti=klienti,
                           stats=stats, template_names=TEMPLATE_NAMES)

def Zápisy_query():
    return Zapis.query.order_by(Zapis.created_at.desc()).limit(30).all()

# ─────────────────────────────────────────────
# ROUTES — KLIENTI
# ─────────────────────────────────────────────


# ─── LOGO UPLOAD HELPER ─────────────────────────────────────────────
ALLOWED_LOGO_EXT = {'png', 'jpg', 'jpeg', 'svg', 'webp'}
MAX_LOGO_BYTES   = 2 * 1024 * 1024  # 2 MB

def save_klient_logo(file_obj, klient_id):
    """Uloží logo klienta do static/logos/, vrátí URL nebo None."""
    if not file_obj or not file_obj.filename:
        return None
    ext = file_obj.filename.rsplit('.', 1)[-1].lower()
    if ext not in ALLOWED_LOGO_EXT:
        return None
    file_obj.seek(0, 2)
    size = file_obj.tell()
    file_obj.seek(0)
    if size > MAX_LOGO_BYTES:
        return None
    filename = secure_filename(f"klient_{klient_id}_{secrets.token_hex(6)}.{ext}")
    upload_dir = os.path.join(current_app.root_path, 'static', 'logos')
    os.makedirs(upload_dir, exist_ok=True)
    file_obj.save(os.path.join(upload_dir, filename))
    return f"/static/logos/{filename}"
# ────────────────────────────────────────────────────────────────────


def send_welcome_email(to_email, to_name, password):
    """Odešle uvítací email novému uživateli s přihlašovacími údaji."""
    smtp_host = os.environ.get("SMTP_HOST", "")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_pass = os.environ.get("SMTP_PASS", "")
    smtp_from = os.environ.get("SMTP_FROM", smtp_user)

    if not smtp_host or not smtp_user:
        current_app.logger.warning("SMTP not configured — welcome email not sent")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Přístup do Commarec Zápisy"
        msg["From"]    = f"Commarec Zápisy <{smtp_from}>"
        msg["To"]      = to_email

        app_url = os.environ.get("APP_URL", "https://web-production-76f2.up.railway.app")

        html = f"""
        <div style="font-family:Arial,sans-serif;max-width:500px;margin:0 auto;padding:32px;">
          <img src="{app_url}/static/logo-dark.svg" alt="Commarec" style="height:32px;margin-bottom:24px;">
          <h2 style="color:#173767;font-size:22px;margin-bottom:8px;">Vítejte, {to_name}</h2>
          <p style="color:#4A6080;margin-bottom:24px;">Byl vám vytvořen přístup do aplikace Commarec Zápisy.</p>
          <table style="background:#f7f9fb;border-radius:8px;padding:20px;width:100%;border-collapse:collapse;">
            <tr><td style="padding:8px 12px;color:#4A6080;font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;">Přihlašovací URL</td>
                <td style="padding:8px 12px;"><a href="{app_url}" style="color:#173767;font-weight:700;">{app_url}</a></td></tr>
            <tr><td style="padding:8px 12px;color:#4A6080;font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;">Email</td>
                <td style="padding:8px 12px;font-weight:600;">{to_email}</td></tr>
            <tr><td style="padding:8px 12px;color:#4A6080;font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;">Heslo</td>
                <td style="padding:8px 12px;font-weight:700;font-size:18px;letter-spacing:0.1em;color:#173767;">{password}</td></tr>
          </table>
          <p style="color:#8aa0b8;font-size:12px;margin-top:24px;">Po prvním přihlášení si heslo změňte. Tento email byl vygenerován automaticky.</p>
          <p style="color:#8aa0b8;font-size:12px;margin-top:4px;">Commarec s.r.o. · Varšavská 715/36, Praha 2</p>
        </div>"""

        msg.attach(MIMEText(html, "html", "utf-8"))

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_from, to_email, msg.as_string())

        current_app.logger.info(f"Welcome email sent to {to_email}")
        return True
    except Exception as e:
        current_app.logger.warning(f"Email send failed: {e}")
        return False


@bp.route("/klienti")
@login_required
def klienti_list():
    klienti = Klient.query.order_by(Klient.nazev).all()
    return render_template("klienti.html", klienti=klienti)

@bp.route("/klient/novy", methods=["GET", "POST"])
@login_required
def klient_novy():
    if request.method == "POST":
        nazev = request.form.get("nazev","").strip()
        if not nazev:
            return render_template("klient_form.html", klient=None, error="Název je povinný")
        slug  = slug_from_name(nazev)
        # ensure unique slug
        base, i = slug, 1
        while Klient.query.filter_by(slug=slug).first():
            slug = f"{base}-{i}"; i += 1
        k = Klient(
            nazev=nazev, slug=slug,
            kontakt=request.form.get("kontakt",""),
            email=request.form.get("email",""),
            telefon=request.form.get("telefon",""),
            adresa=request.form.get("adresa",""),
            poznamka=request.form.get("poznamka",""),
        )
        db.session.add(k)
        db.session.flush()  # získáme k.id
        logo_url = save_klient_logo(request.files.get('logo'), k.id)
        if logo_url:
            k.logo_url = logo_url
        db.session.commit()
        return redirect(url_for("klienti.klient_detail", klient_id=k.id))
    return render_template("klient_form.html", klient=None)



# ─────────────────────────────────────────────
# FREELO ÚKOLY — FÁZE 2
# ─────────────────────────────────────────────

@bp.route("/api/freelo/projekt/<int:projekt_id>/ukoly")
@login_required
def freelo_projekt_ukoly(projekt_id):
    """Načte úkoly z Freelo pro daný projekt (přes uložený tasklist_id)."""
    p = Projekt.query.get_or_404(projekt_id)
    if not FREELO_API_KEY or not FREELO_EMAIL:
        return jsonify({"ukoly": [], "error": "Freelo credentials chybí"})
    if not p.freelo_tasklist_id:
        return jsonify({"ukoly": [], "error": "Projekt nemá propojený Freelo tasklist"})
    try:
        resp = freelo_get(f"/tasklist/{p.freelo_tasklist_id}")
        if resp.status_code != 200:
            return jsonify({"ukoly": [], "error": f"Freelo API {resp.status_code}"})
        tasks_raw = resp.json().get("data", [])
        ukoly = []
        for t in tasks_raw:
            if not isinstance(t, dict):
                continue
            assignees = t.get("assigned_users") or []
            ukoly.append({
                "id": t.get("id"),
                "name": t.get("name", ""),
                "is_done": t.get("is_done", False),
                "due_date": t.get("due_date"),
                "assignee": assignees[0].get("fullname", "") if assignees else "",
                "url": f"https://app.freelo.io/task/{t.get('id')}",
                "created_at": t.get("created_at"),
                "finished_at": t.get("finished_at"),
            })
        done = sum(1 for u in ukoly if u["is_done"])
        return jsonify({"ukoly": ukoly, "done": done, "total": len(ukoly)})
    except Exception as e:
        return jsonify({"ukoly": [], "error": str(e)})


@bp.route("/projekt/<int:projekt_id>/nastavit-freelo", methods=["POST"])
@login_required
def projekt_nastavit_freelo(projekt_id):
    """Uloží Freelo project_id a tasklist_id k projektu."""
    p = Projekt.query.get_or_404(projekt_id)
    p.freelo_project_id = request.form.get("freelo_project_id", type=int) or None
    p.freelo_tasklist_id = request.form.get("freelo_tasklist_id", type=int) or None
    db.session.commit()
    return redirect(request.referrer or url_for("klienti.projekt_detail", projekt_id=p.id))


# ─────────────────────────────────────────────
# PROGRESS REPORT — FÁZE 3
# ─────────────────────────────────────────────

@bp.route("/progress-report")
@login_required
def progress_report():
    """Progress report za zvolené období — per klient, per projekt."""
    od_str = request.args.get("od")
    do_str = request.args.get("do")

    # Defaultně: poslední 30 dní
    do_dt = datetime.utcnow()
    od_dt = do_dt - timedelta(days=30)
    if od_str:
        try: od_dt = datetime.strptime(od_str, "%Y-%m-%d")
        except: pass
    if do_str:
        try: do_dt = datetime.strptime(do_str, "%Y-%m-%d")
        except: pass

    klienti = Klient.query.filter_by(is_active=True).order_by(Klient.nazev).all()
    report_data = []

    for k in klienti:
        projekty = Projekt.query.filter_by(klient_id=k.id, is_active=True).all()
        if not projekty:
            continue

        klient_data = {"klient": k, "projekty": []}

        for p in projekty:
            # Zápisy v období
            zapisy_v_obdobi = Zapis.query.filter(
                Zapis.projekt_id == p.id,
                Zapis.created_at >= od_dt,
                Zapis.created_at <= do_dt,
            ).order_by(Zapis.created_at.desc()).all()

            # Všechny zápisy projektu pro kontext
            vsechny_zapisy = Zapis.query.filter_by(projekt_id=p.id)                .order_by(Zapis.created_at.desc()).all()

            # Úkoly ze zápisů (tasks_json)
            ukoly_splnene = []
            ukoly_otevrene = []
            for z in vsechny_zapisy:
                try:
                    tasks = json.loads(z.tasks_json or "[]")
                    for t in tasks:
                        if isinstance(t, dict) and t.get("name"):
                            # Přidej timestamp zápisu
                            t["zapis_datum"] = z.created_at.strftime("%d. %m. %Y")
                            t["zapis_id"] = z.id
                            if t.get("done"):
                                ukoly_splnene.append(t)
                            else:
                                ukoly_otevrene.append(t)
                except: pass

            # Skóre z auditů
            skore_list = []
            for z in vsechny_zapisy:
                if z.template == "audit" and z.output_json:
                    try:
                        import re as _re
                        data = json.loads(z.output_json)
                        ratings = data.get("ratings", "")
                        m = _re.search(r"Celkov[eé][^0-9]*([0-9]+) *%", ratings)
                        if m:
                            skore_list.append({
                                "skore": int(m.group(1)),
                                "datum": z.created_at.strftime("%d. %m. %Y"),
                                "zapis_id": z.id,
                            })
                    except: pass

            # Freelo live hotové úkoly v období
            freelo_splnene = []
            if k.freelo_tasklist_id and FREELO_API_KEY and FREELO_EMAIL:
                try:
                    fr = freelo_get(f"/tasklist/{k.freelo_tasklist_id}")
                    if fr.status_code == 200:
                        raw_fr = fr.json()
                        if isinstance(raw_fr, list):
                            tasks_raw = raw_fr
                        elif isinstance(raw_fr, dict):
                            tasks_raw = raw_fr.get("tasks", raw_fr.get("data", []))
                        else:
                            tasks_raw = []
                        for t in tasks_raw:
                            if not isinstance(t, dict):
                                continue
                            if t.get("state") == "done":
                                finished = t.get("finished_at", "")
                                if finished:
                                    try:
                                        fin_dt = datetime.strptime(finished[:10], "%Y-%m-%d")
                                        if od_dt <= fin_dt <= do_dt + timedelta(days=1):
                                            freelo_splnene.append({
                                                "name": t.get("name", ""),
                                                "finished_at": finished[:10],
                                                "assignee": t.get("worker", {}).get("fullname", "") if t.get("worker") else "",
                                                "url": f"https://app.freelo.io/task/{t.get('id')}",
                                            })
                                    except Exception:
                                        pass
                except Exception:
                    pass

            klient_data["projekty"].append({
                "projekt": p,
                "zapisy_v_obdobi": zapisy_v_obdobi,
                "vsechny_zapisy_count": len(vsechny_zapisy),
                "ukoly_splnene": ukoly_splnene[:10],
                "ukoly_otevrene": ukoly_otevrene[:15],
                "freelo_splnene": freelo_splnene,
                "skore_list": skore_list,
                "posledni_skore": skore_list[0]["skore"] if skore_list else None,
                "prvni_skore": skore_list[-1]["skore"] if len(skore_list) > 1 else None,
            })

        if any(pd["zapisy_v_obdobi"] or pd["skore_list"] for pd in klient_data["projekty"]):
            report_data.append(klient_data)

    return render_template("progress_report.html",
                           report_data=report_data,
                           od=od_dt, do=do_dt,
                           od_str=od_dt.strftime("%Y-%m-%d"),
                           do_str=do_dt.strftime("%Y-%m-%d"),
                           now=datetime.utcnow())

# ─────────────────────────────────────────────
# HLAVNÍ PŘEHLED (nová hlavní stránka)
# ─────────────────────────────────────────────

@bp.route("/prehled")
@login_required
def prehled():
    """Hlavní stránka — přehled všech klientů s filtry, skóre a poslední aktivitou."""
    now = datetime.utcnow()
    filtr = request.args.get("filtr", "vse")
    hledat = request.args.get("q", "").strip()

    klienti_all = Klient.query.filter_by(is_active=True).order_by(Klient.nazev).all()
    cutoff_60 = now - timedelta(days=60)
    cutoff_30 = now - timedelta(days=30)

    prehled_data = []
    for k in klienti_all:
        if hledat and hledat.lower() not in k.nazev.lower() and hledat.lower() not in (k.kontakt or "").lower():
            continue
        zapisy = Zapis.query.filter_by(klient_id=k.id).order_by(Zapis.created_at.desc()).all()
        projekty = Projekt.query.filter_by(klient_id=k.id, is_active=True).all()
        nabidky = Nabidka.query.filter_by(klient_id=k.id).order_by(Nabidka.created_at.desc()).limit(3).all()
        posledni_zapis = zapisy[0] if zapisy else None

        # Filtry
        if filtr == "aktivni" and not projekty:
            continue
        if filtr == "bez_aktivity":
            if posledni_zapis and posledni_zapis.created_at > cutoff_60:
                continue
        if filtr == "tento_mesic":
            if not posledni_zapis or posledni_zapis.created_at < cutoff_30:
                continue

        # Skóre z auditů — vezmi první i poslední pro delta
        skore_list = []
        for z in zapisy:
            if z.template == "audit" and z.output_json and z.output_json != "{}":
                try:
                    import re as _re
                    data = json.loads(z.output_json)
                    ratings = data.get("ratings", "") or data.get("hodnoceni", "")
                    m = _re.search(r"Celkov[eé][^0-9]*([0-9]+)\s*%", ratings)
                    if m:
                        skore_list.append({"skore": int(m.group(1)), "datum": z.created_at})
                except Exception:
                    pass

        posledni_skore = skore_list[0]["skore"] if skore_list else None
        prvni_skore = skore_list[-1]["skore"] if len(skore_list) > 1 else None
        delta = (posledni_skore - prvni_skore) if (posledni_skore is not None and prvni_skore is not None) else None

        # Otevřené úkoly
        ukoly_otevrene = 0
        for z in zapisy[:5]:
            try:
                tasks = json.loads(z.tasks_json or "[]")
                ukoly_otevrene += sum(1 for t in tasks if isinstance(t, dict) and t.get("name") and not t.get("done"))
            except Exception:
                pass

        prehled_data.append({
            "klient": k,
            "zapisy_count": len(zapisy),
            "projekty": projekty,
            "posledni_zapis": posledni_zapis,
            "nabidky": nabidky,
            "skore": posledni_skore,
            "delta": delta,
            "ukoly_otevrene": ukoly_otevrene,
        })

    stats = {
        "klienti": len(prehled_data),
        "zapisy_30d": Zapis.query.filter(Zapis.created_at >= cutoff_30).count(),
        "nabidky_otevrene": Nabidka.query.filter(Nabidka.stav.in_(["draft", "odeslana"])).count(),
        "projekty": Projekt.query.filter_by(is_active=True).count(),
    }

    return render_template("prehled.html",
                           prehled_data=prehled_data, filtr=filtr, hledat=hledat,
                           stats=stats, template_names=TEMPLATE_NAMES, now=now)


# ─────────────────────────────────────────────
# CRM PŘEHLED
# ─────────────────────────────────────────────

@bp.route("/crm")
@login_required
def crm_prehled():
    """Přesměrování na /prehled — CRM je sloučeno s přehledem."""
    from flask import redirect, url_for
    return redirect(url_for("main.prehled"))

