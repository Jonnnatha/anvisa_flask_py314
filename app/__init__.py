from __future__ import annotations

from app.config import settings


def create_app():
    from flask import Flask
    from app.routes.main import main_bp

    app = Flask(__name__)
    app.config["SECRET_KEY"] = "dev"
    app.config["REQUEST_TIMEOUT_SECONDS"] = settings.REQUEST_TIMEOUT_SECONDS
    app.config["VERIFY_SSL"] = settings.VERIFY_SSL
    app.config["ALLOW_INSECURE_SSL_FALLBACK"] = settings.ALLOW_INSECURE_SSL_FALLBACK

    app.register_blueprint(main_bp)
    return app
