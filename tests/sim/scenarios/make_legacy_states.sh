#!/bin/bash
# Executado DENTRO do host isolado (root) sobre um ambiente 2025.1 instalado.
# Cria, a partir de containers reais do compose 202510, os estados legados tratados pelo DEVO-7182:
#   E - recriação parcial:      container canônico ausente e "<12hex>_<nome>" parado
#   F - backup de migração:     "<nome>-legacy-compose-migration" sem o canônico (migração interrompida)
#   A - identidade conflitante: container com o nome canônico, mas rotulado com projeto "composes"
#   C - legado sem sufixo:      "<nome sem -2025.1.0>" ao lado do canônico, mesma imagem
# Uso: make_legacy_states.sh  (imprime os nomes usados)
set -euo pipefail
# Proteção: só roda dentro do host isolado de testes (nunca em um servidor real).
if [ ! -e /sim/sim-entry ] || [[ "$(hostname)" != sim* ]]; then
  echo "Recusado: este script só pode ser executado dentro do host isolado de testes (hostname 'sim*' com /sim/sim-entry)." >&2
  exit 1
fi
VER=2025.1.0
PROJECT=202510
mapfile -t CANDIDATES < <(docker ps --filter "label=com.docker.compose.project=$PROJECT" --format '{{.Names}}' \
  | grep -E -- "-$VER\$" | sort | head -4)
[ "${#CANDIDATES[@]}" -eq 4 ] || { echo "precisa de 4 containers do projeto $PROJECT"; exit 1; }
label() { docker inspect -f "{{ index .Config.Labels \"$2\" }}" "$1"; }

# E: parcial
E=${CANDIDATES[0]}
docker stop "$E" >/dev/null
docker rename "$E" "0123456789ab_$E"
echo "E partial: 0123456789ab_$E"

# F: backup de migração interrompida
F=${CANDIDATES[1]}
docker stop "$F" >/dev/null
docker rename "$F" "$F-legacy-compose-migration"
echo "F backup: $F-legacy-compose-migration"

# A: identidade conflitante (mesma imagem e serviço, projeto antigo "composes")
A=${CANDIDATES[2]}
A_IMAGE=$(docker inspect -f '{{.Config.Image}}' "$A")
A_SERVICE=$(label "$A" com.docker.compose.service)
docker rm -f "$A" >/dev/null
docker run -d --restart unless-stopped --name "$A" --network servicos \
  --label com.docker.compose.project=composes --label com.docker.compose.service="$A_SERVICE" \
  --label com.docker.compose.oneoff=False "$A_IMAGE" >/dev/null
echo "A identity conflict: $A (project=composes service=$A_SERVICE)"

# C: container legado sem sufixo de versão
C=${CANDIDATES[3]}
C_LEGACY=${C%-$VER}
C_IMAGE=$(docker inspect -f '{{.Config.Image}}' "$C")
C_SERVICE=$(label "$C" com.docker.compose.service)
docker run -d --restart unless-stopped --name "$C_LEGACY" --network servicos \
  --label com.docker.compose.project=composes --label com.docker.compose.service="$C_SERVICE" \
  --label com.docker.compose.oneoff=False "$C_IMAGE" >/dev/null
echo "C legacy: $C_LEGACY (next to $C)"
