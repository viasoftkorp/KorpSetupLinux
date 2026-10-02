#!/bin/bash
# Executa o mesmo cenário com duas refs a partir do mesmo snapshot e compara o estado final.
# Uso: scenarios/run_pair.sh NOME SNAPSHOT VERSAO REF_ORIGINAL REF_OTIMIZADA [args do setup.sh...]
#   ex.: scenarios/run_pair.sh s4 upd25 2025.1.0 release/2025.1.0.x release/2025.1.0.x-performance-test custom_tags=update
# SIM_ALLOW="--allow REGEX ..." repassa exceções documentadas ao compare (ver README).
set -u
H=$(cd "$(dirname "$0")/.." && pwd); cd "$H"
NAME=$1; SNAP=$2; VER=$3; ORIG=$4; OPT=$5; shift 5
W=$H/.work
for side in orig opt; do
  REF=$ORIG; [ $side = opt ] && REF=$OPT
  ./simctl.sh restore sim1 "$SNAP" >/dev/null
  [ $side = orig ] && ./simctl.sh dump sim1 "$W/dumps/$NAME-initial.json" >/dev/null
  ./simctl.sh version "$VER" >/dev/null
  SIM_REF=$REF ./simctl.sh setup sim1 "$NAME-$side.log" branch_name="$REF" token=simtoken skip_salt_test=true \
    should_update_rabbitmq=true "$@" > "$W/runs/$NAME-$side.out" 2>&1
  echo "$side ($REF): $(grep -A1 'PLAY RECAP' "$W/runs/$NAME-$side.log" | tail -1 | tr -s ' ' | cut -c1-160) | $(tail -1 "$W/runs/$NAME-$side.log")"
  grep -E 'fatal: \[' "$W/runs/$NAME-$side.log" | head -1 | cut -c1-300
  python3 count_actions.py "$W/runs/$NAME-$side.log" | tail -1
  ./simctl.sh dump sim1 "$W/dumps/$NAME-$side.json" >/dev/null
done
python3 compare_dumps.py "$W/dumps/$NAME-initial.json" "$W/dumps/$NAME-orig.json" "$W/dumps/$NAME-opt.json" ${SIM_ALLOW:-} | tail -8
