if [ "$(id -un)" = "pwn" ] && [ -n "$SSH_CONNECTION" ] && [ -z "$TMUX" ] && [ -t 1 ] && command -v tmux >/dev/null 2>&1; then
    printf '\033[?1007l'
    exec tmux new-session -A -s pwnagotchi "cat /run/motd.dynamic /etc/motd 2>/dev/null; exec bash -l"
fi
