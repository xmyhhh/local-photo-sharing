#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
VENV_DIR="${ROOT_DIR}/.venv"
PYTHON_BIN="${VENV_DIR}/bin/python"
PIP_BIN="${VENV_DIR}/bin/pip"
APP_FILE="${ROOT_DIR}/app.py"
DEFAULT_CONFIG="${ROOT_DIR}/config.json"
DEPLOY_DIR="${ROOT_DIR}/.deploy"
PID_FILE="${DEPLOY_DIR}/photo-share.pid"
LOG_FILE="${DEPLOY_DIR}/photo-share.log"

usage() {
  cat <<EOF
Usage: ./core/deploy/deploy.sh <command> [--config <path>]

Commands:
  install     Create .venv and install requirements
  init        Create default config.json if it does not exist
  start       Start core in foreground
  start-bg    Start core in background
  stop        Stop background core
  restart     Restart background core
  status      Show background core status
  logs        Follow background core logs

Options:
  --config <path>  Config file path. Default: ${DEFAULT_CONFIG}
EOF
}

command="${1:-}"
if [[ -n "${command}" ]]; then
  shift
fi

CONFIG_FILE="${DEFAULT_CONFIG}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --config)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for --config" >&2
        exit 2
      fi
      CONFIG_FILE="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 2
      ;;
  esac
done

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

install_app() {
  ensure_python
  "${PYTHON_BIN}" -m ensurepip --upgrade --default-pip >/dev/null
  "${PYTHON_BIN}" -m pip install --upgrade pip
  "${PIP_BIN}" install -r "${ROOT_DIR}/requirements.txt"
}

init_config() {
  ensure_python
  if [[ -f "${CONFIG_FILE}" ]]; then
    echo "Config already exists: ${CONFIG_FILE}"
    return
  fi
  set +e
  "${PYTHON_BIN}" "${APP_FILE}" --config "${CONFIG_FILE}"
  status=$?
  set -e
  if [[ ${status} -ne 0 ]]; then
    exit "${status}"
  fi
}

is_running() {
  [[ -f "${PID_FILE}" ]] || return 1
  local pid
  pid="$(cat "${PID_FILE}")"
  [[ -n "${pid}" ]] || return 1
  kill -0 "${pid}" >/dev/null 2>&1
}

start_foreground() {
  ensure_python
  exec "${PYTHON_BIN}" "${APP_FILE}" --config "${CONFIG_FILE}"
}

start_background() {
  ensure_python
  mkdir -p "${DEPLOY_DIR}"
  if is_running; then
    echo "Already running with PID $(cat "${PID_FILE}")"
    return
  fi
  nohup "${PYTHON_BIN}" "${APP_FILE}" --config "${CONFIG_FILE}" >>"${LOG_FILE}" 2>&1 &
  echo "$!" >"${PID_FILE}"
  echo "Started with PID $(cat "${PID_FILE}")"
  echo "Logs: ${LOG_FILE}"
}

stop_background() {
  if ! [[ -f "${PID_FILE}" ]]; then
    echo "Not running: PID file not found."
    return
  fi
  local pid
  pid="$(cat "${PID_FILE}")"
  if [[ -z "${pid}" ]]; then
    rm -f "${PID_FILE}"
    echo "Not running: empty PID file removed."
    return
  fi
  if kill -0 "${pid}" >/dev/null 2>&1; then
    kill "${pid}"
    for _ in {1..20}; do
      if ! kill -0 "${pid}" >/dev/null 2>&1; then
        break
      fi
      sleep 0.2
    done
    if kill -0 "${pid}" >/dev/null 2>&1; then
      kill -9 "${pid}"
    fi
    echo "Stopped PID ${pid}"
  else
    echo "Process ${pid} is not running."
  fi
  rm -f "${PID_FILE}"
}

show_status() {
  if is_running; then
    echo "Running with PID $(cat "${PID_FILE}")"
  else
    echo "Not running"
  fi
}

case "${command}" in
  install)
    install_app
    ;;
  init)
    init_config
    ;;
  start)
    start_foreground
    ;;
  start-bg)
    start_background
    ;;
  stop)
    stop_background
    ;;
  restart)
    stop_background
    start_background
    ;;
  status)
    show_status
    ;;
  logs)
    mkdir -p "${DEPLOY_DIR}"
    touch "${LOG_FILE}"
    tail -f "${LOG_FILE}"
    ;;
  -h|--help|"")
    usage
    ;;
  *)
    echo "Unknown command: ${command}" >&2
    usage
    exit 2
    ;;
esac
