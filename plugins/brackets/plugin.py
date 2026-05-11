from __future__ import annotations

from flask import Flask

from core.photo_share.context import AppServices
from core.photo_share.routes.brackets import register_bracket_routes


def register(app: Flask, services: AppServices) -> None:
    register_bracket_routes(app, services)
