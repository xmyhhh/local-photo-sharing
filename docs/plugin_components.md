# Plugin Model

Core plugins expose one or more declarative units through `PLUGIN["components"]`.
For now the API field is still named `pluginComponents`, but product UI should call them “插件” unless we are discussing the manifest schema.
The manifest tells core what a plugin can do, how it can be triggered, and what UI surface it owns.
Plugin business UI can still live in plugin JavaScript, while core owns shared placement such as grouped context menus and topbar buttons.

## Manifest Shape

```json
{
  "id": "duplicate_checker.scan_folder",
  "title": "检查重复照片",
  "description": "Human-readable purpose.",
  "capabilities": [],
  "triggers": [],
  "surfaces": []
}
```

`id` should be stable and namespaced by plugin. A manifest item can declare several capabilities, triggers, and surfaces.

## Capabilities

- `folder_batch`: handles one folder or multiple folders. Use `recursive` to say whether descendants are included, and `multi` to say whether multiple folders are accepted.
- `background_service`: runs continuously after startup, such as watching USB insertion or background indexing.
- `file_handler`: handles one file or selected files. Use `extensions` for allowed suffixes.
- `function`: exposes a callable operation without a direct file/folder target.
- `project`: creates and opens component-owned project files, such as bracket merge `.prj` files.

Example:

```json
{
  "type": "file_handler",
  "extensions": [".jpg", ".jpeg", ".heic"],
  "multi": true,
  "operations": ["inspect", "convert"]
}
```

## Triggers

- `startup`: run when core starts.
- `context_menu`: appears in a menu for `folder`, `file`, `file_selection`, or `folder_selection`.
- `topbar_button`: adds a global action button.
- `main_menu`: appears in a global menu.
- `main_tab`: appears as a global tab that navigates to a page.
- `project_open`: opens a component project file.
- `manual`: invoked by another component or core code.

Example:

```json
{
  "type": "context_menu",
  "target": "folder",
  "label": "检查重复照片"
}
```

## Surfaces

- `dialog`: a modal or popover-like flow, such as duplicate photo cleanup.
- `topbar_button`: a visible global button.
- `dedicated_page`: a component-owned page.
- `main_tab`: a global tab that routes to the component page.
- `headless`: no user-facing UI.

Example:

```json
{
  "type": "dedicated_page",
  "route": "/components/brackets/projects/:path"
}
```

## Current Components

- `duplicate_checker.scan_folder`: folder batch component, triggered from folder context menu, displayed as a dialog.
- `brackets.detect_folder`: folder batch and project component, triggered from folder context menu and topbar button, currently displayed as a dialog. Dedicated project page and global tab are declared as planned surfaces.
