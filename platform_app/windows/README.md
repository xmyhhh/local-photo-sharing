# Windows Platform App

This folder contains the Windows platform shell for core.

It is responsible for:

- running core behind a system tray icon
- opening the browser UI from the tray menu
- exiting the background service from the tray menu
- packaging the Windows EXE

Core can still run without this folder through the root `app.py` shell entry.
