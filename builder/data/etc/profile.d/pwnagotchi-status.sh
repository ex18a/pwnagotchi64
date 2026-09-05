if [ "$(id -un)" = "pwn" ] && [ -n "$SSH_CONNECTION" ] && [ -z "$PWNAGOTCHI_STATUSBAR" ] && [ -t 0 ] && [ -t 1 ]; then
    export PWNAGOTCHI_STATUSBAR=1

    _pwnagotchi_statusbar_setup() {
        lines=$(tput lines)
        printf '\0337\033[r\0338\033D\033M\0337\033[1;%dr\0338' "$((lines - 1))"
    }

    _pwnagotchi_statusbar_draw() {
        lines=$(tput lines)
        cols=$(tput cols)
        status=$(cat /run/pwnagotchi-status 2>/dev/null)
        mode=$(cat /run/pwnagotchi-mode 2>/dev/null)
        shakes=$(cat /run/pwnagotchi-shakes 2>/dev/null)
        lastpwnd=$(cat /run/pwnagotchi-last-pwnd 2>/dev/null)
        line="${status}  PWND ${shakes} ${lastpwnd}  ${mode}"
        printf '\0337\033[%d;1H\033[?7l\033[0m%-*.*s\033[?7h\0338' "$lines" "$cols" "$cols" "$line"
    }

    _pwnagotchi_statusbar_cleanup() {
        kill "$_pwnagotchi_statusbar_pid" 2>/dev/null
        lines=$(tput lines)
        printf '\0337\033[%d;1H\033[K\033[r\0338' "$lines"
    }

    _pwnagotchi_statusbar_setup
    trap '_pwnagotchi_statusbar_setup; _pwnagotchi_statusbar_draw' WINCH

    ( while :; do _pwnagotchi_statusbar_draw 2>/dev/null; sleep 2; done ) &
    _pwnagotchi_statusbar_pid=$!
    disown

    trap '_pwnagotchi_statusbar_cleanup' EXIT
fi
