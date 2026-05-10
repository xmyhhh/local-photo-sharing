from __future__ import annotations

from flask import Flask

from ..context import AppServices
from .brackets import register_bracket_routes
from .gallery import register_gallery_routes
from .media import register_media_routes
from .ratings import register_rating_routes


def register_routes(app: Flask, services: AppServices) -> None:
    register_gallery_routes(app, services)
    register_bracket_routes(app, services)
    register_media_routes(app, services)
    register_rating_routes(app, services)
