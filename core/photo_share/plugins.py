from __future__ import annotations

import importlib
import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any

from .runtime import get_app_base_dir

if TYPE_CHECKING:
    from flask import Flask
    from .context import AppServices


@dataclass(frozen=True)
class PluginSpec:
    name: str
    module: str | None = None
    path: Path | None = None
    enabled: bool = True


class PluginLoadError(RuntimeError):
    pass


def parse_plugin_specs(config: dict[str, Any]) -> list[PluginSpec]:
    value = config.get("plugins")
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("Config field plugins must be an array.")

    specs: list[PluginSpec] = []
    for index, item in enumerate(value):
        if isinstance(item, str):
            specs.append(PluginSpec(name=item.strip(), module=item.strip()))
            continue
        if not isinstance(item, dict):
            raise ValueError(f"Config field plugins[{index}] must be a string or object.")
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Config field plugins[{index}].name must be a non-empty string.")
        enabled = bool(item.get("enabled", True))
        module = item.get("module")
        path = item.get("path")
        if module is not None and (not isinstance(module, str) or not module.strip()):
            raise ValueError(f"Config field plugins[{index}].module must be a non-empty string.")
        if path is not None and (not isinstance(path, str) or not path.strip()):
            raise ValueError(f"Config field plugins[{index}].path must be a non-empty string.")
        if module is None and path is None:
            specs.append(PluginSpec(name=name.strip(), module=name.strip(), enabled=enabled))
            continue
        specs.append(
            PluginSpec(
                name=name.strip(),
                module=module.strip() if isinstance(module, str) else None,
                path=resolve_plugin_path(path) if isinstance(path, str) else None,
                enabled=enabled,
            )
        )
    return specs


def discover_plugin_specs(config: dict[str, Any]) -> list[PluginSpec]:
    configured = parse_plugin_specs(config)
    specs: dict[str, PluginSpec] = {spec.name: spec for spec in configured}
    plugins_dir = get_app_base_dir() / "plugins"
    if plugins_dir.is_dir():
        for plugin_file in sorted(plugins_dir.glob("*/plugin.py")):
            name = plugin_file.parent.name
            if name not in specs:
                specs[name] = PluginSpec(name=name, path=plugin_file, enabled=False)
    return list(specs.values())


def register_plugins(app: "Flask", services: "AppServices", specs: list[PluginSpec]) -> None:
    for spec in specs:
        module = _load_plugin_module(spec)
        services.available_plugins.append(_plugin_summary(spec, module))
        register = getattr(module, "register", None)
        if not callable(register):
            raise PluginLoadError(f"Plugin {spec.name} does not expose register(app, services).")
        register(app, services)
        _register_plugin_assets(app, services, spec, module)
        _register_plugin_components(services, spec, module)
        if spec.enabled:
            services.enabled_plugins.add(spec.name)

def _load_plugin_module(spec: PluginSpec) -> ModuleType:
    if spec.module:
        return importlib.import_module(spec.module)
    if spec.path is None:
        raise PluginLoadError(f"Plugin {spec.name} must define module or path.")
    plugin_file = spec.path
    if plugin_file.is_dir():
        plugin_file = plugin_file / "plugin.py"
    if not plugin_file.exists():
        raise PluginLoadError(f"Plugin {spec.name} was not found: {plugin_file}")
    module_name = f"_photo_share_plugin_{spec.name.replace('-', '_')}"
    module_spec = importlib.util.spec_from_file_location(module_name, plugin_file)
    if module_spec is None or module_spec.loader is None:
        raise PluginLoadError(f"Plugin {spec.name} cannot be loaded: {plugin_file}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_name] = module
    module_spec.loader.exec_module(module)
    return module


def resolve_plugin_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = get_app_base_dir() / path
    return path.resolve()


def _register_plugin_assets(app: "Flask", services: "AppServices", spec: PluginSpec, module: ModuleType) -> None:
    from flask import send_from_directory

    manifest = getattr(module, "PLUGIN", None)
    if not isinstance(manifest, dict):
        return
    static_dir_value = manifest.get("static_dir")
    if not isinstance(static_dir_value, str) or not static_dir_value.strip():
        return
    module_file = Path(getattr(module, "__file__", "")).resolve()
    static_dir = (module_file.parent / static_dir_value).resolve()
    if not static_dir.is_dir():
        raise PluginLoadError(f"Plugin {spec.name} static_dir was not found: {static_dir}")

    endpoint = f"plugin_static_{spec.name.replace('-', '_')}"
    url_prefix = f"/plugin-assets/{spec.name}"

    def plugin_static(filename: str, root: Path = static_dir):
        return send_from_directory(root, filename)

    app.add_url_rule(f"{url_prefix}/<path:filename>", endpoint, plugin_static)
    services.plugin_assets.append({
        "name": spec.name,
        "enabled": spec.enabled,
        "scripts": [_plugin_asset_url(url_prefix, static_dir, item) for item in manifest.get("scripts", []) if isinstance(item, str)],
        "styles": [_plugin_asset_url(url_prefix, static_dir, item) for item in manifest.get("styles", []) if isinstance(item, str)],
    })


def _plugin_asset_url(url_prefix: str, static_dir: Path, filename: str) -> str:
    asset = (static_dir / filename).resolve()
    version = int(asset.stat().st_mtime) if asset.is_file() else 0
    return f"{url_prefix}/{filename}?v={version}"


def _register_plugin_components(services: "AppServices", spec: PluginSpec, module: ModuleType) -> None:
    manifest = getattr(module, "PLUGIN", None)
    if not isinstance(manifest, dict):
        return
    components = manifest.get("components")
    if components is None:
        return
    if not isinstance(components, list):
        raise PluginLoadError(f"Plugin {spec.name} components must be an array.")
    for index, component in enumerate(components):
        if not isinstance(component, dict):
            raise PluginLoadError(f"Plugin {spec.name} components[{index}] must be an object.")
        component_id = component.get("id")
        if not isinstance(component_id, str) or not component_id.strip():
            raise PluginLoadError(f"Plugin {spec.name} components[{index}].id must be a non-empty string.")
        services.plugin_components.append({
            **component,
            "id": component_id.strip(),
            "plugin": spec.name,
            "pluginTitle": _plugin_summary(spec, module)["title"],
            "enabled": spec.enabled,
        })


def _plugin_summary(spec: PluginSpec, module: ModuleType) -> dict[str, Any]:
    manifest = getattr(module, "PLUGIN", None)
    title = spec.name
    description = ""
    if isinstance(manifest, dict):
        title = manifest.get("title") if isinstance(manifest.get("title"), str) else title
        description = manifest.get("description") if isinstance(manifest.get("description"), str) else ""
    return {
        "name": spec.name,
        "title": title,
        "description": description,
        "enabled": spec.enabled,
        "path": str(spec.path) if spec.path else None,
        "module": spec.module,
    }
