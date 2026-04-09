from flask import Flask

from .routes import web


def create_app() -> Flask:
    app = Flask(__name__, template_folder='templates', static_folder='static')
    app.register_blueprint(web)
    return app
