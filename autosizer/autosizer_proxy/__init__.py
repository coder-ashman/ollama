import logging

from flask import Flask

from .request_logging import register_request_logging
from .routes import routes


def create_app() -> Flask:
    app = Flask(__name__)
    register_request_logging(app)
    app.logger.setLevel(logging.INFO)
    app.register_blueprint(routes)
    return app


__all__ = ["create_app"]
