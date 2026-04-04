"""routes/admin.py — CRM admin: šablony zápisů, klienti, Freelo diagnostika."""
from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for
from ..extensions import db
from ..models import Klient, Zapis, TemplateConfig
from ..auth import admin_required
from ..config import TEMPLATE_PROMPTS, TEMPLATE_NAMES, TEMPLATE_SECTIONS

bp = Blueprint("admin_bp", __name__)


@bp.route("/admin")
@admin_required
def admin():
    klienti = Klient.query.order_by(Klient.nazev).all()
    flash = session.pop("admin_flash", None)
    tmpl_configs = {}
    for key in TEMPLATE_PROMPTS:
        cfg = TemplateConfig.query.filter_by(template_key=key).first()
        tmpl_configs[key] = cfg
    return render_template("admin.html", klienti=klienti, admin_flash=flash,
                           template_names=TEMPLATE_NAMES, tmpl_configs=tmpl_configs,
                           tmpl_sections=TEMPLATE_SECTIONS, tmpl_default_prompts=TEMPLATE_PROMPTS)


@bp.route("/admin/templates", methods=["GET"])
@admin_required
def admin_templates():
    configs = {}
    for key in TEMPLATE_PROMPTS:
        cfg = TemplateConfig.query.filter_by(template_key=key).first()
        configs[key] = cfg
    return render_template("admin_templates.html",
        configs=configs, template_names=TEMPLATE_NAMES,
        default_prompts=TEMPLATE_PROMPTS, template_sections=TEMPLATE_SECTIONS)


@bp.route("/admin/templates/<template_key>", methods=["POST"])
@admin_required
def admin_template_save(template_key):
    if template_key not in TEMPLATE_PROMPTS:
        return redirect(url_for("admin_bp.admin"))
    prompt = request.form.get("system_prompt", "").strip()
    cfg = TemplateConfig.query.filter_by(template_key=template_key).first()
    if not cfg:
        cfg = TemplateConfig(
            template_key=template_key,
            name=TEMPLATE_NAMES.get(template_key, template_key)
        )
        db.session.add(cfg)
    cfg.system_prompt = prompt
    db.session.commit()
    session["admin_flash"] = f"Šablona '{TEMPLATE_NAMES.get(template_key, template_key)}' uložena."
    return redirect(url_for("admin_bp.admin"))


@bp.route("/admin/templates/<template_key>/reset", methods=["POST"])
@admin_required
def admin_template_reset(template_key):
    cfg = TemplateConfig.query.filter_by(template_key=template_key).first()
    if cfg:
        cfg.system_prompt = ""
        db.session.commit()
    return jsonify({"ok": True, "msg": "Resetováno na výchozí"})
