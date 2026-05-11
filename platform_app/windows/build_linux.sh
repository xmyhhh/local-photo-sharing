#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
PYTHON_BIN="${VENV_DIR}/bin/python"
PIP_BIN="${VENV_DIR}/bin/pip"

ensure_python() {
  if [[ -x "${PYTHON_BIN}" ]]; then
    return
  fi
  if command -v python3 >/dev/null 2>&1; then
    python3 -m venv "${VENV_DIR}"
  elif command -v python >/dev/null 2>&1; then
    python -m venv "${VENV_DIR}"
  else
    echo "Python is not installed or not in PATH." >&2
    exit 1
  fi
}

ensure_python
"${PYTHON_BIN}" -m ensurepip --upgrade --default-pip >/dev/null
"${PYTHON_BIN}" -m pip install --upgrade pip
"${PIP_BIN}" install -r "${ROOT_DIR}/requirements.txt"
"${PIP_BIN}" install pyinstaller

"${PYTHON_BIN}" -m PyInstaller --noconfirm "${ROOT_DIR}/platform_app/windows/photo_share_tray.spec"

echo "Build completed."
echo "Binary: ${ROOT_DIR}/dist/LocalPhotoSharingTray"
