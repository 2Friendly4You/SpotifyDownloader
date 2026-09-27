import os

from flask import Flask

from cleanup_service import start_cleanup_thread

from app.config import MUSIC_DIR, SEARCHES_FILE, SECRET_KEY
from app.extensions import socketio
from app.searches import write_searches_file


def create_app():
    flask_app = Flask(__name__)
    flask_app.config['SECRET_KEY'] = SECRET_KEY
    flask_app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    flask_app.config['SESSION_COOKIE_HTTPONLY'] = True
    socketio.init_app(flask_app)

    # Publish the app before workers or the cleanup thread log through it.
    # create_app is still running, so `from app import app` would fail otherwise.
    import sys
    sys.modules[__name__].app = flask_app

    from app.downloads import expire_download_state
    from app.routes import register

    register(flask_app)

    os.makedirs(MUSIC_DIR, exist_ok=True)
    if os.path.isdir(SEARCHES_FILE):
        flask_app.logger.error(
            "SEARCHES_FILE %s is a directory. Mount a directory and point SEARCHES_FILE at a file inside it.",
            SEARCHES_FILE,
        )
    elif not os.path.isfile(SEARCHES_FILE):
        try:
            write_searches_file({'total': 0})
        except Exception as e:
            flask_app.logger.error(f"Could not create searches.json at startup: {e}")

    start_cleanup_thread(MUSIC_DIR, expire_callback=expire_download_state)
    return flask_app


app = create_app()
