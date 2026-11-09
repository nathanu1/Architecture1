#!/bin/sh
# Start the town (default) or the viewer. A town resumes from $TOWN_DIR when one exists there, so
# a restarted container continues the same run; delete the directory to start a new town.
set -eu
cd /app
case "${1:-play}" in
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
