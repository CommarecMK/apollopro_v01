"""
auth.py — dekorátory pro autentizaci, systém rolí a oprávnění.
"""
from functools import wraps
from flask import session, redirect, url_for, abort
from .extensions import db


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("main.login"))
        # Klient má vlastní portál
        if session.get("user_role") == "klient":
            return redirect(url_for("portal.klient_portal"))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    """Pouze superadmin."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("main.login"))
        from .models import User
        user = User.query.get(session["user_id"])
        if not user or user.role != "superadmin":
            return abort(403)
        return f(*args, **kwargs)
    return decorated


def role_required(*roles):
    """Povolí přístup jen uživatelům s jednou z uvedených rolí."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("main.login"))
            from .models import User
            user = User.query.get(session["user_id"])
            if not user or user.role not in roles:
                return abort(403)
            return f(*args, **kwargs)
        return decorated
    return decorator


def get_current_user():
    """Vrátí aktuálně přihlášeného uživatele nebo None."""
    uid = session.get("user_id")
    if not uid:
        return None
    from .models import User
    return User.query.get(uid)


# ─────────────────────────────────────────────
# OPRÁVNĚNÍ — co smí která role
# ─────────────────────────────────────────────
ROLE_PERMISSIONS = {
    "admin": {
        "edit_zapis_any", "delete_zapis", "manage_klient", "freelo_setup",
        "nabidky", "nabidky_any", "send_freelo", "view_all",
        "create_zapis", "edit_zapis_own",
    },
    "konzultant": {
        "create_zapis", "edit_zapis_own", "send_freelo", "view_all",
    },
    "obchodnik": {
        "nabidky", "nabidky_any", "view_all",
    },
    "junior": {
        "create_zapis", "edit_zapis_own", "view_assigned",
    },
    "klient": {
        "portal_only",
    },
}


def can(action, obj=None):
    """Kontrola zda má aktuální uživatel dané oprávnění."""
    u = get_current_user()
    if not u:
        return False
    if u.role == "superadmin":
        return True
    perms = ROLE_PERMISSIONS.get(u.role, set())
    if action in perms:
        if action == "edit_zapis_own" and obj and hasattr(obj, "user_id"):
            return obj.user_id == u.id
        return True
    if action == "edit_zapis":
        if "edit_zapis_any" in perms:
            return True
        if "edit_zapis_own" in perms:
            if obj and hasattr(obj, "user_id"):
                return obj.user_id == u.id
            return True
    return False
