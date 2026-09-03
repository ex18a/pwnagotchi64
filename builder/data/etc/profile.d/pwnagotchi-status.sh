if [ "$(id -un)" = "pwn" ] && [ -n "$SSH_CONNECTION" ] && [ -z "$TMUX" ] && [ -t 1 ] && command -v tmux >/dev/null 2>&1; then
    exec tmux new-session -A -s pwnagotchi
fi
