from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from flask import Flask, abort, jsonify, request

from ..context import AppServices


def register_settings_routes(app: Flask, services: AppServices) -> None:
    @app.get("/api/settings/components")
    def component_settings():
        return jsonify(build_component_settings(services))

    @app.post("/api/settings/components")
    def update_component_settings():
        data = request.get_json(silent=True) or {}
        plugins = data.get("plugins", {})
        if not isinstance(plugins, dict):
            abort(400, "plugins must be an object.")

        enabled_plugins = {name for name, enabled in plugins.items() if enabled}
        update_config_components(services, enabled_plugins)
        apply_runtime_component_state(services, enabled_plugins)
        return jsonify(build_component_settings(services))


def build_component_settings(services: AppServices) -> dict[str, Any]:
    return {
        "plugins": services.available_plugins,
        "enabledPlugins": sorted(services.enabled_plugins),
        "pluginAssets": services.plugin_assets,
        "pluginComponents": services.plugin_components,
    }


def update_config_components(services: AppServices, enabled_plugins: set[str]) -> None:
    services.config["plugins"] = [
        serialize_plugin_config(plugin, plugin["name"] in enabled_plugins)
        for plugin in services.available_plugins
    ]
    services.config.pop("core_components", None)
    write_config(services.config_path, services.config)


def serialize_plugin_config(plugin: dict[str, Any], enabled: bool) -> dict[str, Any]:
    item: dict[str, Any] = {"name": plugin["name"], "enabled": enabled}
    if plugin.get("path"):
        item["path"] = plugin["path"]
    if plugin.get("module"):
        item["module"] = plugin["module"]
    return item


def write_config(config_path: Path | None, config: dict[str, Any]) -> None:
    if config_path is None:
        return
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def apply_runtime_component_state(services: AppServices, enabled_plugins: set[str]) -> None:
    services.enabled_plugins.clear()
    services.enabled_plugins.update(enabled_plugins)
    for plugin in services.available_plugins:
        plugin["enabled"] = plugin["name"] in enabled_plugins
    for asset in services.plugin_assets:
        asset["enabled"] = asset["name"] in enabled_plugins
    for component in services.plugin_components:
        component["enabled"] = component.get("plugin") in enabled_plugins
