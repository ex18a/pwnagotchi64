#!/bin/bash
TARGET_HOSTNAME=$1

GREEN=$(printf '\033[0;32m')
NC=$(printf '\033[0m')

cat <<MOTD_EOF > /etc/motd
${GREEN}        (◕‿‿◕) ${TARGET_HOSTNAME}

        Hi! I'm a pwnagotchi, please take good care of me!
        Here are some basic things you need to know to raise me properly!

        If you want to change my configuration, use /etc/pwnagotchi/config.toml

        All the configuration options can be found on /etc/pwnagotchi/default.toml,
        but don't change this file because I will recreate it every time I'm restarted!

        you can set up bluetooth connection, use sudo bt-wizard

        I'm managed by systemd. Here are some basic commands.

        If you want to know what I'm doing, you can check my logs with the command
        tail -f /var/log/pwnagotchi.log

        If you want to know if I'm running, you can use
        systemctl status pwnagotchi

        You can restart me using
        systemctl restart pwnagotchi

        But be aware I will go into MANUAL mode when restarted!
        You can put me back into AUTO mode using
        touch /root/.pwnagotchi-auto && systemctl restart pwnagotchi
        ${NC}
MOTD_EOF
