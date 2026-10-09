#!/bin/bash
# Leaves three processes behind; see the project's manifest.
if [ "$LEAK_MODE" = stubborn ]; then
    trap '' INT TERM
fi
sleep 1000 &
child=$!
echo $child >> "$LEAK_PIDS"
setsid sh -c 'echo $$ >> "$LEAK_PIDS"; exec sleep 1000' &
sh -c 'sh -c "echo \$\$ >> \"\$LEAK_PIDS\"; exec sleep 1000" &'
while [ "$(wc -l < "$LEAK_PIDS")" -lt 3 ]; do sleep 0.05; done
touch "$LEAK_PIDS.ready"
case "$LEAK_MODE" in
    exit) exit 0 ;;
    trap) trap 'exit 0' INT; wait $child ;;
    *) wait $child ;;
esac
