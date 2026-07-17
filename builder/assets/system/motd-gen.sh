#!/bin/bash
TARGET_HOSTNAME=$1

GREEN=$(printf '\033[1;32m')
CYAN=$(printf '\033[1;36m')
DIM=$(printf '\033[2;37m')
NC=$(printf '\033[0m')

cat <<MOTD_EOF > /etc/motd
┏━(${CYAN}pwnagotchi${NC})
┃
┃ ${GREEN}(◕‿‿◕)${NC} ${TARGET_HOSTNAME}
┃
┃ Hi! I'm a pwnagotchi, please take good care of me!
┃ Here are some basic things you need to know to raise me properly!
┃
┃ for an easy guided setup instead of hand-editing the toml, use
┃ sudo pwnagotchi --setup
┃
┃ If you want to change my more advanced configuration options, use
┃ sudo nano /etc/pwnagotchi/config.toml
┃
┃ All the default configuration options can be found in /etc/pwnagotchi/default.toml,
┃ but don't change this file because I will recreate it every time I'm restarted!
┃
┃ you can set up bluetooth connection, use sudo bt-wizard
┃
┃ I'm managed by systemd. Here are some basic commands.
┃
┃ If you want to know what I'm doing, you can check my logs with the command
┃ tail -f /var/log/pwnagotchi.log
┃
┃ watch what im doing in real time with pwnlog
┃
┃ If you want to know if I'm running, you can use
┃ systemctl status pwnagotchi
┃
┃ You can restart me using
┃ systemctl restart pwnagotchi
┃
┃ if you find any bugs or having trouble with anything please raise an issue at
┃ github.com/ex18a/pwnagotchi64
┃
┗━(${DIM}github.com/ex18a/pwnagotchi64${NC})
MOTD_EOF
