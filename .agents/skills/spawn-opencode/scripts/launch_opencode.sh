#!/usr/bin/env bash
set -e

MODEL="${1:-opencode/deepseek-v4.1-flash-free}"
PROMPT="${2:-}"
WORKDIR="$(pwd)"

# Create a temporary runner script to avoid nested quote escaping issues
TMP_SCRIPT=$(mktemp /tmp/opencode_runner.XXXXXX.sh)
cat << 'EOF' > "$TMP_SCRIPT"
#!/usr/bin/env bash
cd "$1"
MODEL="$2"
PROMPT="$3"

echo "Starting OpenCode with model: $MODEL"
echo "Close this window or press Ctrl+C / exit OpenCode when finished."
echo "----------------------------------------------------------------"

if [ -n "$PROMPT" ]; then
  opencode -m "$MODEL" --prompt "$PROMPT"
else
  opencode -m "$MODEL"
fi
EOF
chmod +x "$TMP_SCRIPT"

# Launch in a new interactive terminal window and block until closed
if [[ "$OSTYPE" == "darwin"* ]]; then
  # macOS (Terminal.app) - uses a FIFO pipe to wait until the window closes
  FIFO=$(mktemp -u /tmp/opencode_fifo.XXXXXX)
  mkfifo "$FIFO"
  osascript -e "tell application \"Terminal\"
    activate
    do script \"$TMP_SCRIPT '$WORKDIR' '$MODEL' '$PROMPT'; echo done > '$FIFO'; exit\"
  end tell" >/dev/null
  cat "$FIFO" >/dev/null
  rm -f "$FIFO"

elif [ -n "$TMUX" ]; then
  # Inside tmux - opens a new split pane and waits for it to finish
  tmux split-window -v -c "$WORKDIR" "$TMP_SCRIPT '$WORKDIR' '$MODEL' '$PROMPT'"

elif command -v gnome-terminal >/dev/null 2>&1; then
  # Linux (GNOME Terminal)
  gnome-terminal --wait -- bash -c "$TMP_SCRIPT '$WORKDIR' '$MODEL' '$PROMPT'"

elif command -v x-terminal-emulator >/dev/null 2>&1; then
  # Linux (Generic X11)
  x-terminal-emulator -e bash -c "$TMP_SCRIPT '$WORKDIR' '$MODEL' '$PROMPT'"

elif command -v wt.exe >/dev/null 2>&1; then
  # Windows / WSL (Windows Terminal)
  DONE_FILE=$(mktemp -u /tmp/opencode_done.XXXXXX)
  (wt.exe -w 0 nt bash -c "$TMP_SCRIPT '$WORKDIR' '$MODEL' '$PROMPT'; touch '$DONE_FILE'" 2>/dev/null || wt.exe bash -c "$TMP_SCRIPT '$WORKDIR' '$MODEL' '$PROMPT'; touch '$DONE_FILE'") &
  while [ ! -f "$DONE_FILE" ]; do
    sleep 0.5
  done
  rm -f "$DONE_FILE"

elif command -v powershell.exe >/dev/null 2>&1; then
  # Windows fallback: run via powershell in a new window and wait
  powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell.exe -Wait -ArgumentList '-NoProfile', '-Command', 'Set-Location \"$WORKDIR\"; if (\"$PROMPT\") { opencode -m \"$MODEL\" --prompt \"$PROMPT\" } else { opencode -m \"$MODEL\" }'"

else
  echo "Error: No supported terminal emulator found."
  rm -f "$TMP_SCRIPT"
  exit 1
fi

rm -f "$TMP_SCRIPT"
echo "OpenCode interactive session completed and closed."
