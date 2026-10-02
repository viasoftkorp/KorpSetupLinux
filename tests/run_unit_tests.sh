#!/bin/bash
# Executa os testes unitários (precisa de python3 com ansible-core instalado, como o host do setup).
set -euo pipefail
cd "$(dirname "$0")/unit"
exec python3 -m unittest discover -v -p 'test_*.py'
