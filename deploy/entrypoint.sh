#!/bin/sh
# Start the town (`town` on a local model server, `play` for any config) or the viewer. A town resumes from $TOWN_DIR when one exists there, so
# a restarted container continues the same run; delete the directory to start a new town.
set -eu
cd /app
case "${1:-play}" in
  town)
    # The living town on a local model server: checks the server, downloads missing models,
    # founds the town in $TOWN_DIR or continues the one that is there. HEARTHSIDE_LLM_URL names
    # the model server (the compose file points it at the Ollama container).
    exec ga town --config "$TOWN_CONFIG" --run-dir "$TOWN_DIR" --host "$HEARTHSIDE_HOST" --port "$HEARTHSIDE_PORT" --speed "$TOWN_SPEED" --no-open --yes ${TOWN_ARGS:-}
    ;;
  play)
    if [ -f "$TOWN_DIR/state.sqlite" ]; then
      echo "resuming the town in $TOWN_DIR"
      exec ga play --resume "$TOWN_DIR" --host "$HEARTHSIDE_HOST" --port "$HEARTHSIDE_PORT" --speed "$TOWN_SPEED" ${TOWN_ARGS:-}
    fi
    echo "starting a new town from $TOWN_CONFIG in $TOWN_DIR"
    exec ga play --config "$TOWN_CONFIG" --run-dir "$TOWN_DIR" --host "$HEARTHSIDE_HOST" --port "$HEARTHSIDE_PORT" --speed "$TOWN_SPEED" --yes ${TOWN_ARGS:-}
    ;;
  watch)
    exec ga play --watch "${2:?run directory}" --host "$HEARTHSIDE_HOST" --port "$HEARTHSIDE_PORT" --speed "$TOWN_SPEED"
    ;;
  serve)
    exec ga serve --run-dir "${2:-$TOWN_DIR}" --host "$HEARTHSIDE_HOST" --port "$HEARTHSIDE_PORT" ${3:+--experiment "$3"}
    ;;
  *)
    exec "$@"
    ;;
esac
