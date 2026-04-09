from flask import Flask

from app.routes.main import main_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "dev"

    app.register_blueprint(main_bp)
    return app
