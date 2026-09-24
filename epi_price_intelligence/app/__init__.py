import os

from flask import Flask

from app.config import Config
from app.extensions import db
from app.utils.logging import configure_logging, get_logger


def create_app(config_object: type = Config) -> Flask:
    configure_logging()
    logger = get_logger("epi.startup")

    app = Flask(__name__)
    app.config.from_object(config_object)

    fixtures_dir = app.config.get("FIXTURES_DIR")
    if fixtures_dir and not os.path.isdir(fixtures_dir):
        logger.warning(
            "FIXTURES_DIR does not exist -- fixture-mode searches will return zero "
            "results from every source until this is fixed",
            extra={"ctx": {"fixtures_dir": fixtures_dir}},
        )

    db.init_app(app)

    from app.api.routes import api_bp
    from app.web.routes import web_bp

    app.register_blueprint(web_bp)
    app.register_blueprint(api_bp)

    with app.app_context():
        db.create_all()

    return app
