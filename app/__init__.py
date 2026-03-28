"""
app/__init__.py — Flask application factory.
"""
import os
import json as _json
from flask import Flask
from .extensions import db


def create_app():
    app = Flask(__name__, template_folder="../templates", static_folder="../static")

    app.secret_key = os.environ.get("SECRET_KEY", "change-this-in-production")

    database_url = os.environ.get("DATABASE_URL", "sqlite:///zapisy.db")
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    app.config["SQLALCHEMY_DATABASE_URI"]        = database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["JSON_AS_ASCII"]                  = False
    app.config["SQLALCHEMY_ENGINE_OPTIONS"]      = {"pool_pre_ping": True}

    app.jinja_env.filters["fromjson"] = lambda s: _json.loads(s) if s else {}
    app.jinja_env.filters["regex_replace"] = (
        lambda s, pattern, repl: __import__("re").sub(pattern, repl, s) if s else ""
    )

    db.init_app(app)

    from .routes.main    import bp as main_bp
    from .routes.klienti import bp as klienti_bp
    from .routes.nabidky import bp as nabidky_bp
    from .routes.zapisy  import bp as zapisy_bp
    from .routes.freelo  import bp as freelo_bp
    from .routes.admin   import bp as admin_bp
    from .routes.report  import bp as report_bp
    from .routes.portal  import bp as portal_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(klienti_bp)
    app.register_blueprint(nabidky_bp)
    app.register_blueprint(zapisy_bp)
    app.register_blueprint(freelo_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(report_bp)
    app.register_blueprint(portal_bp)

    from flask import render_template

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("403.html"), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template("404.html"), 404

    @app.errorhandler(500)
    def server_error(e):
        return render_template("500.html"), 500

    # Vytvoří tabulky pokud neexistují — bezpečné, nemaže data
    with app.app_context():
        db.create_all()
        _ensure_admin()

    return app


def _ensure_admin():
    """Vytvoří default admina pokud neexistuje. Nemaže nic."""
    from .models import User
    from werkzeug.security import generate_password_hash
    try:
        if not User.query.filter_by(email="admin@commarec.cz").first():
            db.session.add(User(
                email="admin@commarec.cz",
                name="Admin",
                role="superadmin",
                password_hash=generate_password_hash(
                    os.environ.get("ADMIN_PASSWORD", "admin123")
                ),
                is_admin=True
            ))
            db.session.commit()
            print("Vytvořen admin: admin@commarec.cz")

        if os.environ.get("ENABLE_SEED", "").lower() == "true":
            from .seed import seed_test_data
            seed_test_data()
    except Exception as e:
        print(f"Init: {e}")
        try:
            db.session.rollback()
        except:
            pass
