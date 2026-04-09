#!/usr/bin/with-contenv bashio

bashio::log.info "Starting Facade add-on..."
exec python3 -u /run.py
