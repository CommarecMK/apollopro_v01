"""routes/klienti.py — správa klientů, projekty."""
from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for, abort, current_app
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from ..extensions import db, ANTHROPIC_API_KEY, FREELO_API_KEY, FREELO_EMAIL, FREELO_PROJECT_ID
from ..models import User, Klient, Zapis, Projekt, Nabidka, NabidkaPolozka, TemplateConfig
from ..auth import login_required, admin_required, get_current_user, can
from ..config import TEMPLATE_PROMPTS, TEMPLATE_NAMES, TEMPLATE_SECTIONS, SECTION_TITLES
from ..services.freelo import freelo_get, freelo_post, freelo_patch, freelo_delete, resolve_worker_id, find_project_id_for_tasklist
import os, json, re, secrets, string
import anthropic
import requests

from werkzeug.utils import secure_filename
from .main import save_klient_logo

bp = Blueprint("klienti", __name__)

@bp.route("/klient/<int:klient_id>")
@login_required
def klient_detail(klient_id):
    k = Klient.query.get_or_404(klient_id)
    projekty = Projekt.query.filter_by(klient_id=klient_id).order_by(Projekt.created_at.desc()).all()
    zapisy   = Zapis.query.filter_by(klient_id=klient_id).order_by(Zapis.created_at.desc()).all()
    nabidky  = Nabidka.query.filter_by(klient_id=klient_id).order_by(Nabidka.created_at.desc()).all()
    konzultanti = User.query.filter_by(is_active=True).all()
    try:
        profil = json.loads(k.profil_json or "{}")
    except Exception:
        profil = {}

    # Skóre history
    import re as _re
    skore_list = []
    for z in zapisy:
        if z.template == "audit" and z.output_json and z.output_json != "{}":
            try:
                data = json.loads(z.output_json)
                ratings = data.get("ratings", "") or data.get("hodnoceni", "")
                m = _re.search(r"Celkov[eé][^0-9]*([0-9]+)\s*%", ratings)
                if m:
                    skore_list.append({"skore": int(m.group(1)), "datum": z.created_at, "zapis_id": z.id})
            except Exception:
                pass

    # Otevřené úkoly napříč zápisy
    ukoly_otevrene = []
    for z in zapisy:
        try:
            tasks = json.loads(z.tasks_json or "[]")
            for t in tasks:
                if isinstance(t, dict) and t.get("name") and not t.get("done"):
                    t["zapis_id"] = z.id
                    t["zapis_title"] = z.title
                    ukoly_otevrene.append(t)
        except Exception:
            pass

    return render_template("klient_detail.html", k=k, projekty=projekty,
                           zapisy=zapisy, nabidky=nabidky, profil=profil,
                           skore_list=skore_list, ukoly_otevrene=ukoly_otevrene,
                           konzultanti=konzultanti, template_names=TEMPLATE_NAMES,
                           now=datetime.utcnow())


@bp.route("/klient/<int:klient_id>/vyvoj")
@login_required
def klient_vyvoj(klient_id):
    k = Klient.query.get_or_404(klient_id)
    projekty = Projekt.query.filter_by(klient_id=klient_id).order_by(Projekt.created_at.desc()).all()
    zapisy   = Zapis.query.filter_by(klient_id=klient_id).order_by(Zapis.created_at.desc()).all()

    # Freelo úkoly — zatím prázdné, napojíme přes Freelo project ID na projektu
    freelo_tasks = {}

    try:
        profil = json.loads(k.profil_json or "{}") if hasattr(k, 'profil_json') else {}
    except Exception:
        profil = {}

    return render_template("klient_vyvoj.html",
                           k=k, projekty=projekty, zapisy=zapisy,
                           freelo_tasks=freelo_tasks,
                           profil=profil,
                           template_names=TEMPLATE_NAMES)

@bp.route("/klient/<int:klient_id>/upravit", methods=["GET", "POST"])
@login_required
def klient_upravit(klient_id):
    k = Klient.query.get_or_404(klient_id)
    if request.method == "POST":
        k.nazev   = request.form.get("nazev", k.nazev).strip()
        k.kontakt = request.form.get("kontakt","")
        k.email   = request.form.get("email","")
        k.telefon = request.form.get("telefon","")
        k.adresa  = request.form.get("adresa","")
        k.poznamka= request.form.get("poznamka","")
        k.is_active = request.form.get("is_active") == "1"
        logo_url = save_klient_logo(request.files.get('logo'), klient_id)
        if logo_url:
            k.logo_url = logo_url
        db.session.commit()
        return redirect(url_for("klienti.klient_detail", klient_id=k.id))
    return render_template("klient_form.html", klient=k)

@bp.route("/api/klient/<int:klient_id>/profil", methods=["POST"])
@login_required
def klient_profil_update(klient_id):
    k = Klient.query.get_or_404(klient_id)
    data = request.json or {}
    try:
        profil = json.loads(k.profil_json or "{}")
    except Exception:
        profil = {}
    for key, val in data.items():
        if val is not None and val != "":
            profil[key] = val
        elif key in profil and (val is None or val == ""):
            del profil[key]
    k.profil_json = json.dumps(profil, ensure_ascii=False)
    db.session.commit()
    return jsonify({"ok": True, "profil": profil})

# ─────────────────────────────────────────────
# ROUTES — PROJEKTY
# ─────────────────────────────────────────────

@bp.route("/api/klient/<int:klient_id>/poznamky", methods=["POST"])
@login_required
def api_klient_poznamky(klient_id):
    """Uloží interní poznámky ke klientovi."""
    k = Klient.query.get_or_404(klient_id)
    data = request.get_json()
    k.poznamka = data.get("poznamka", "")
    try:
        db.session.commit()
        return jsonify({"ok": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@bp.route("/api/klient/<int:klient_id>/upravit", methods=["POST"])
@login_required
def api_klient_upravit(klient_id):
    """Inline editace klienta přes JSON API."""
    k = Klient.query.get_or_404(klient_id)
    data = request.get_json()
    k.nazev   = data.get("nazev", k.nazev).strip()
    k.kontakt = data.get("kontakt", k.kontakt or "").strip()
    k.email   = data.get("email", k.email or "").strip()
    k.telefon = data.get("telefon", k.telefon or "").strip()
    k.adresa  = data.get("adresa", k.adresa or "").strip()
    k.sidlo   = data.get("sidlo", k.sidlo or "").strip()
    k.ic      = data.get("ic", k.ic or "").strip()
    k.dic     = data.get("dic", k.dic or "").strip()
    try:
        db.session.commit()
        return jsonify({"ok": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@bp.route("/api/klient/<int:klient_id>/info", methods=["GET"])
@login_required
def api_klient_info(klient_id):
    """Vrátí základní info o klientovi pro prefill formulářů."""
    k = Klient.query.get_or_404(klient_id)
    return jsonify({
        "id": k.id,
        "nazev": k.nazev or "",
        "kontakt": k.kontakt or "",
        "email": k.email or "",
        "telefon": k.telefon or "",
        "adresa": k.adresa or "",
        "sidlo": k.sidlo or "",
    })


@bp.route("/api/klient/<int:klient_id>/logo", methods=["POST"])
@login_required
def api_klient_logo(klient_id):
    """Upload loga klienta — uloží jako base64 data URL do DB."""
    k = Klient.query.get_or_404(klient_id)
    logo_url = save_klient_logo(request.files.get('logo'), klient_id)
    if not logo_url:
        return jsonify({"error": "Nepodporovaný formát nebo příliš velký soubor (max 2 MB)"}), 400
    try:
        db.session.expire_all()
        k.logo_url = logo_url
        db.session.commit()
        return jsonify({"ok": True, "logo_url": logo_url})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@bp.route("/api/klient/<int:klient_id>/kontakty", methods=["GET"])
@login_required
def api_klient_kontakty(klient_id):
    """Vrátí seznam kontaktních osob klienta."""
    from ..models import KlientKontakt
    k = Klient.query.get_or_404(klient_id)
    return jsonify({"kontakty": [
        {"id": c.id, "jmeno": c.jmeno, "pozice": c.pozice,
         "email": c.email, "telefon": c.telefon, "poznamka": c.poznamka}
        for c in k.kontakty
    ]})


@bp.route("/api/klient/<int:klient_id>/kontakty", methods=["POST"])
@login_required
def api_klient_kontakt_pridat(klient_id):
    """Přidá novou kontaktní osobu ke klientovi."""
    from ..models import KlientKontakt
    Klient.query.get_or_404(klient_id)
    data = request.json or {}
    jmeno = (data.get("jmeno") or "").strip()
    if not jmeno:
        return jsonify({"error": "Jméno je povinné"}), 400
    from ..models import KlientKontakt
    k_kontakt = KlientKontakt(
        klient_id=klient_id,
        jmeno=jmeno,
        pozice=(data.get("pozice") or "").strip(),
        email=(data.get("email") or "").strip(),
        telefon=(data.get("telefon") or "").strip(),
        poznamka=(data.get("poznamka") or "").strip(),
    )
    db.session.add(k_kontakt)
    db.session.commit()
    return jsonify({"ok": True, "id": k_kontakt.id})


@bp.route("/api/klient/kontakt/<int:kontakt_id>", methods=["POST"])
@login_required
def api_klient_kontakt_upravit(kontakt_id):
    """Upraví existující kontaktní osobu."""
    from ..models import KlientKontakt
    c = KlientKontakt.query.get_or_404(kontakt_id)
    data = request.json or {}
    c.jmeno   = (data.get("jmeno") or c.jmeno).strip()
    c.pozice  = (data.get("pozice") or "").strip()
    c.email   = (data.get("email") or "").strip()
    c.telefon = (data.get("telefon") or "").strip()
    c.poznamka= (data.get("poznamka") or "").strip()
    db.session.commit()
    return jsonify({"ok": True})


@bp.route("/api/klient/kontakt/<int:kontakt_id>/smazat", methods=["POST"])
@login_required
def api_klient_kontakt_smazat(kontakt_id):
    """Smaže kontaktní osobu."""
    from ..models import KlientKontakt
    c = KlientKontakt.query.get_or_404(kontakt_id)
    db.session.delete(c)
    db.session.commit()
    return jsonify({"ok": True})


@bp.route("/projekt/novy", methods=["POST"])
@login_required
def projekt_novy():
    data      = request.form
    klient_id = data.get("klient_id")
    nazev     = data.get("nazev","").strip()
    if not nazev or not klient_id:
        return redirect(url_for("klienti.klienti_list"))
    datum_od = None
    datum_do = None
    try:
        if data.get("datum_od"): datum_od = datetime.strptime(data["datum_od"], "%Y-%m-%d").date()
        if data.get("datum_do"): datum_do = datetime.strptime(data["datum_do"], "%Y-%m-%d").date()
    except ValueError:
        pass
    p = Projekt(
        nazev=nazev,
        popis=data.get("popis",""),
        klient_id=int(klient_id),
        user_id=int(data["user_id"]) if data.get("user_id") else None,
        datum_od=datum_od,
        datum_do=datum_do,
    )
    db.session.add(p)
    db.session.commit()
    return redirect(url_for("klienti.klient_detail", klient_id=klient_id))

@bp.route("/projekt/<int:projekt_id>/upravit", methods=["POST"])
@login_required
def projekt_upravit(projekt_id):
    p    = Projekt.query.get_or_404(projekt_id)
    data = request.form
    p.nazev   = data.get("nazev", p.nazev).strip()
    p.popis   = data.get("popis", "")
    p.user_id = int(data["user_id"]) if data.get("user_id") else None
    p.is_active = data.get("is_active") == "1"
    try:
        if data.get("datum_od"): p.datum_od = datetime.strptime(data["datum_od"], "%Y-%m-%d").date()
        if data.get("datum_do"): p.datum_do = datetime.strptime(data["datum_do"], "%Y-%m-%d").date()
    except ValueError:
        pass
    db.session.commit()
    return redirect(url_for("klienti.klient_detail", klient_id=p.klient_id))

@bp.route("/projekt/<int:projekt_id>")
@login_required
def projekt_detail(projekt_id):
    p      = Projekt.query.get_or_404(projekt_id)
    zapisy = Zapis.query.filter_by(projekt_id=projekt_id).order_by(Zapis.created_at.desc()).all()
    konzultanti = User.query.filter_by(is_active=True).all()
    return render_template("projekt_detail.html", p=p, zapisy=zapisy,
                           konzultanti=konzultanti, template_names=TEMPLATE_NAMES)

# ─────────────────────────────────────────────
# ROUTES — ZAPISY
# ─────────────────────────────────────────────


# ── Merk API pro klienty ─────────────────────────────────────

@bp.route("/api/klient/<int:klient_id>/merk/suggest")
@login_required
def merk_suggest(klient_id):
    import requests as req
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])
    key = os.environ.get("MERK_API_KEY", "")
    try:
        resp = req.get("https://api.merk.cz/suggest/",
                       params={"name": q, "country_code": "cz", "limit": 8, "only_active": True},
                       headers={"Authorization": f"Token {key}"}, timeout=5)
        data = resp.json()
        return jsonify(data if isinstance(data, list) else [])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bp.route("/api/klient/<int:klient_id>/merk/ico/<ico>")
@login_required
def merk_ico(klient_id, ico):
    import requests as req
    key = os.environ.get("MERK_API_KEY", "")
    try:
        resp = req.get("https://api.merk.cz/company/",
                       params={"regno": ico, "country_code": "cz"},
                       headers={"Authorization": f"Token {key}"}, timeout=5)
        return jsonify(resp.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bp.route("/api/klient/<int:klient_id>/merk/ulozit", methods=["POST"])
@login_required
def merk_ulozit(klient_id):
    k = Klient.query.get_or_404(klient_id)
    data = request.json or {}
    prepsat = data.get("prepsat_existujici", False)

    def set_if_empty(attr, val):
        if val and (not getattr(k, attr, "") or prepsat):
            setattr(k, attr, val)

    set_if_empty("nazev",   data.get("nazev", ""))
    set_if_empty("ic",      data.get("ic", ""))
    set_if_empty("dic",     data.get("dic", ""))
    set_if_empty("adresa",  data.get("adresa", ""))
    set_if_empty("sidlo",   data.get("sidlo", ""))
    set_if_empty("kontakt", data.get("kontakt_jmeno", ""))
    set_if_empty("email",   data.get("kontakt_email", ""))
    set_if_empty("telefon", data.get("kontakt_tel", ""))
    set_if_empty("logo_url", data.get("logo_url", ""))

    db.session.commit()
    return jsonify({"ok": True})
