from app.routes.admin import admin_bp
from app.routes.search import search_bp
from app.routes.status import status_bp


def register(app):
    app.register_blueprint(search_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(status_bp)
