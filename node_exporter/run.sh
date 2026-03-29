#!/usr/bin/with-contenv bashio

export HA_BASE_URL="http://supervisor/core"
export SUPERVISOR_TOKEN="${SUPERVISOR_TOKEN}"

bashio::log.info "Starting Home Assistant Node Exporter..."
exec python3 -m app.main
