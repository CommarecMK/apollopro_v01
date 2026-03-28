"""routes/nabidky.py"""
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

bp = Blueprint("nabidky", __name__)

@bp.route("/nabidka/nova", methods=["GET", "POST"])
@login_required
def nabidka_nova():
    klienti = Klient.query.filter_by(is_active=True).order_by(Klient.nazev).all()
    klient_id = request.args.get("klient_id", type=int)
    projekt_id = request.args.get("projekt_id", type=int)

    if request.method == "POST":
        klient_id = request.form.get("klient_id", type=int)
        # Generuj číslo nabídky
        rok = datetime.utcnow().year
        pocet = Nabidka.query.filter(
            db.func.extract("year", Nabidka.created_at) == rok
        ).count()
        cislo = f"NAB-{rok}-{(pocet+1):03d}"

        n = Nabidka(
            cislo=cislo,
            klient_id=klient_id,
            projekt_id=request.form.get("projekt_id", type=int) or None,
            user_id=session["user_id"],
            nazev=request.form.get("nazev", "").strip(),
            poznamka=request.form.get("poznamka", "").strip(),
            stav="draft",
            mena=request.form.get("mena", "CZK"),
        )
        if request.form.get("platnost_do"):
            from datetime import date as date_type
            n.platnost_do = datetime.strptime(request.form["platnost_do"], "%Y-%m-%d").date()
        db.session.add(n)
        db.session.flush()

        # Položky
        nazvy = request.form.getlist("pol_nazev")
        popisy = request.form.getlist("pol_popis")
        mnozstvi = request.form.getlist("pol_mnozstvi")
        jednotky = request.form.getlist("pol_jednotka")
        ceny = request.form.getlist("pol_cena")
        slevy = request.form.getlist("pol_sleva")

        for i, nazev in enumerate(nazvy):
            if not nazev.strip():
                continue
            p = NabidkaPolozka(
                nabidka_id=n.id,
                poradi=i,
                nazev=nazev.strip(),
                popis=popisy[i] if i < len(popisy) else "",
                mnozstvi=float(mnozstvi[i]) if i < len(mnozstvi) and mnozstvi[i] else 1,
                jednotka=jednotky[i] if i < len(jednotky) else "ks",
                cena_ks=float(ceny[i]) if i < len(ceny) and ceny[i] else 0,
                sleva_pct=float(slevy[i]) if i < len(slevy) and slevy[i] else 0,
                dph_pct=float(request.form.getlist("pol_dph")[i]) if i < len(request.form.getlist("pol_dph")) and request.form.getlist("pol_dph")[i] else 0,
            )
            db.session.add(p)

        db.session.commit()
        return redirect(url_for("nabidky.nabidka_detail", nabidka_id=n.id))

    k = Klient.query.get(klient_id) if klient_id else None
    projekty = Projekt.query.filter_by(klient_id=klient_id).all() if klient_id else []
    return render_template("nabidka_nova.html", klienti=klienti, klient=k,
                           projekty=projekty, klient_id=klient_id, projekt_id=projekt_id)


@bp.route("/nabidka/<int:nabidka_id>")
@login_required
def nabidka_detail(nabidka_id):
    n = Nabidka.query.get_or_404(nabidka_id)
    return render_template("nabidka_detail.html", n=n)


@bp.route("/nabidka/<int:nabidka_id>/polozka/pridat", methods=["POST"])
@login_required
def nabidka_polozka_pridat(nabidka_id):
    n = Nabidka.query.get_or_404(nabidka_id)
    p = NabidkaPolozka(
        nabidka_id=n.id,
        poradi=len(n.polozky),
        nazev=request.form.get("nazev", "Nová položka"),
        mnozstvi=1, cena_ks=0, jednotka="ks",
    )
    db.session.add(p)
    db.session.commit()
    return redirect(url_for("nabidky.nabidka_detail", nabidka_id=n.id))


@bp.route("/nabidka/<int:nabidka_id>/polozka/<int:pol_id>/smazat", methods=["POST"])
@login_required
def nabidka_polozka_smazat(nabidka_id, pol_id):
    p = NabidkaPolozka.query.get_or_404(pol_id)
    db.session.delete(p)
    db.session.commit()
    return ("", 204)


@bp.route("/nabidka/<int:nabidka_id>/ulozit", methods=["POST"])
@login_required
def nabidka_ulozit(nabidka_id):
    """Uloží všechny položky z AJAX POST (JSON)."""
    n = Nabidka.query.get_or_404(nabidka_id)
    data = request.get_json()
    if not data:
        return jsonify(ok=False), 400

    # Update hlavičky
    if "nazev" in data: n.nazev = data["nazev"]
    if "poznamka" in data: n.poznamka = data["poznamka"]
    if "stav" in data: n.stav = data["stav"]

    # Update položek
    for pol_data in data.get("polozky", []):
        pol_id = pol_data.get("id")
        if pol_id:
            p = NabidkaPolozka.query.get(pol_id)
            if p and p.nabidka_id == n.id:
                p.nazev = pol_data.get("nazev", p.nazev)
                p.popis = pol_data.get("popis", p.popis)
                p.mnozstvi = float(pol_data.get("mnozstvi", p.mnozstvi))
                p.jednotka = pol_data.get("jednotka", p.jednotka)
                p.cena_ks = float(pol_data.get("cena_ks", p.cena_ks))
                p.sleva_pct = float(pol_data.get("sleva_pct", p.sleva_pct or 0))
                p.dph_pct = float(pol_data.get("dph_pct", p.dph_pct or 0))
        else:
            # Nová položka
            p = NabidkaPolozka(
                nabidka_id=n.id,
                poradi=pol_data.get("poradi", 99),
                nazev=pol_data.get("nazev", ""),
                popis=pol_data.get("popis", ""),
                mnozstvi=float(pol_data.get("mnozstvi", 1)),
                jednotka=pol_data.get("jednotka", "ks"),
                cena_ks=float(pol_data.get("cena_ks", 0)),
                sleva_pct=float(pol_data.get("sleva_pct", 0)),
                dph_pct=float(pol_data.get("dph_pct", 0)),
            )
            db.session.add(p)

    db.session.commit()
    return jsonify(ok=True, celkem=float(n.celkova_cena), dph=float(n.celkova_dph), celkem_s_dph=float(n.celkova_cena_s_dph), cislo=n.cislo)


@bp.route("/nabidka/<int:nabidka_id>/stav", methods=["POST"])
@login_required
def nabidka_stav(nabidka_id):
    n = Nabidka.query.get_or_404(nabidka_id)
    n.stav = request.form.get("stav", n.stav)
    db.session.commit()
    return redirect(url_for("nabidky.nabidka_detail", nabidka_id=n.id))
