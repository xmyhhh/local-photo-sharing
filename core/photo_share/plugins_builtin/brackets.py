from __future__ import annotations

from flask import Flask

from ..context import AppServices
from ..routes.brackets import register_bracket_routes


def register(app: Flask, services: AppServices) -> None:
    register_bracket_routes(app, services)
