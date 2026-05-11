from __future__ import annotations

from flask import Flask

from ..context import AppServices
from .auth import register_auth_routes
from .gallery import register_gallery_routes
from .files import register_file_routes
from .media import register_media_routes
from .ratings import register_rating_routes
from .settings import register_settings_routes
from .tasks import register_task_routes
from .uploads import register_upload_routes


def register_routes(app: Flask, services: AppServices) -> None:
    register_auth_routes(app, services)
    register_gallery_routes(app, services)
    register_file_routes(app, services)
    register_media_routes(app, services)
    register_rating_routes(app, services)
    register_upload_routes(app, services)
    register_settings_routes(app, services)
    register_task_routes(app, services)
