if [ "$(id -un)" = "pwn" ] && [ -n "$SSH_CONNECTION" ] && [ -z "$PWNAGOTCHI_STATUSBAR" ] && [ -t 0 ] && [ -t 1 ]; then
    export PWNAGOTCHI_STATUSBAR=1

    _pwnagotchi_statusbar_size() {
        set -- $(stty size < /dev/tty 2>/dev/null)
        sb_lines=$1
        sb_cols=$2
    }

    _pwnagotchi_statusbar_setup() {
        _pwnagotchi_statusbar_size
        [ "${sb_lines:-0}" -gt 1 ] 2>/dev/null && [ "${sb_cols:-0}" -gt 1 ] 2>/dev/null || return
        printf '\0337\033[r\0338\033D\033M\0337\033[1;%dr\0338' "$((sb_lines - 1))"
    }

    _pwnagotchi_statusbar_draw() {
        _pwnagotchi_statusbar_size
        [ "${sb_lines:-0}" -gt 1 ] 2>/dev/null && [ "${sb_cols:-0}" -gt 1 ] 2>/dev/null || return
        status=$(cat /run/pwnagotchi-status 2>/dev/null)
        mode=$(cat /run/pwnagotchi-mode 2>/dev/null)
        shakes=$(cat /run/pwnagotchi-shakes 2>/dev/null)
        lastpwnd=$(cat /run/pwnagotchi-last-pwnd 2>/dev/null)
        left="$status"
        right="PWND ${shakes} ${lastpwnd}  ${mode}"
        if [ "${#right}" -ge "$sb_cols" ]; then
            line="${right:0:$sb_cols}"
        else
            pad=$((sb_cols - ${#left} - ${#right}))
            if [ "$pad" -lt 0 ]; then
                left="${left:0:$((sb_cols - ${#right}))}"
                pad=0
            fi
            spacer=$(printf '%*s' "$pad" '')
            line="${left}${spacer}${right}"
        fi
        printf '\0337\033[%d;1H\033[?7l\033[0m%-*s\033[?7h\0338' "$sb_lines" "$sb_cols" "$line"
    }

    _pwnagotchi_statusbar_cleanup() {
        kill "$_pwnagotchi_statusbar_pid" 2>/dev/null
        _pwnagotchi_statusbar_size
        [ "${sb_lines:-0}" -gt 1 ] 2>/dev/null || return
        printf '\0337\033[%d;1H\033[K\033[r\0338' "$sb_lines"
    }

    _pwnagotchi_statusbar_setup
    trap '_pwnagotchi_statusbar_setup; _pwnagotchi_statusbar_draw' WINCH

    ( while :; do _pwnagotchi_statusbar_setup 2>/dev/null; _pwnagotchi_statusbar_draw 2>/dev/null; sleep 2; done ) &
    _pwnagotchi_statusbar_pid=$!
    disown

    trap '_pwnagotchi_statusbar_cleanup' EXIT
fi
