#!/bin/sh
# Assemble the CSP connect-src value from backend origin env vars.
#
# Runs before nginx's stock 20-envsubst-on-templates.sh (lexical order in
# /docker-entrypoint.d). It derives ws:// / wss:// origins from the http(s)
# origins automatically, then exports ELLIOT_CSP_CONNECT_SRC + ELLIOT_HSTS so
# envsubst can template them into /etc/nginx/conf.d/default.conf.
#
# Override per deployment:
#   ELLIOT_PLUGIN_ORIGIN   default http://localhost:3000
#   ELLIOT_RUNTIME_ORIGIN  default http://localhost:3001
#   ELLIOT_HSTS            default "" (disabled; set when served over HTTPS)
set -eu

PLUGIN_ORIGIN="${ELLIOT_PLUGIN_ORIGIN:-http://localhost:3000}"
RUNTIME_ORIGIN="${ELLIOT_RUNTIME_ORIGIN:-http://localhost:3001}"

# Map an http(s) origin to its websocket counterpart.
ws_origin() {
    case "$1" in
        https://*) echo "wss://${1#https://}" ;;
        http://*)  echo "ws://${1#http://}" ;;
        *)         echo "$1" ;;
    esac
}

PLUGIN_WS="$(ws_origin "$PLUGIN_ORIGIN")"
RUNTIME_WS="$(ws_origin "$RUNTIME_ORIGIN")"

ELLIOT_CSP_CONNECT_SRC="${PLUGIN_ORIGIN} ${RUNTIME_ORIGIN} ${PLUGIN_WS} ${RUNTIME_WS}"
export ELLIOT_CSP_CONNECT_SRC
export ELLIOT_HSTS="${ELLIOT_HSTS:-}"

echo "[elliot-csp] connect-src: 'self' ${ELLIOT_CSP_CONNECT_SRC}"
