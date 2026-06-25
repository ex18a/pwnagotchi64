#!/bin/bash
IFACE="usb0"
SUBNET="10.42.0"
OWN_IP="10.42.0.2"
GW=""

if ping -c 1 -W 1 "${SUBNET}.1" > /dev/null 2>&1; then
    GW="${SUBNET}.1"
else
    for i in $(seq 1 254); do
        ping -c 1 -W 1 "${SUBNET}.${i}" > /dev/null 2>&1 &
    done
    wait
    GW=$(ip neigh show dev "$IFACE" | awk -v me="$OWN_IP" '$1 != me && $NF != "FAILED" {print $1; exit}')
fi

if [ -n "$GW" ]; then
    ip route replace default via "$GW" dev "$IFACE" metric 20
fi
