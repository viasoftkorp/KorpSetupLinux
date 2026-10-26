# VEN17_W Implementation Plan

**Goal:** disponibilizar Regras de Comissão Web (core, gateway e frontend) pelo setup.
**Spec:** docs/superpowers/specs/2026-10-26-ven17-w-setuplinux-design.md

## Execução
- [x] Criar branch COMI-1-master a partir de master.
- [x] Criar roles/VEN17_W (meta, tasks, vars, composes genérico, 2025.1.0 e 2025.2.0, consul_kv) a partir da VEN27 e da FIS24_W.
- [x] Renderizar composes com Jinja2 StrictUndefined para 2025.1.0/2025.2.0, sufixo vazio/-dev e api_gateway ausente/vazio/preenchido; conferir imagem e container.
- [x] Renderizar e parsear os JSON do Consul; validar YAML de meta, tasks e vars.
- [x] git diff --check.

## Limites
Ansible e Docker não executados localmente: sem syntax-check nativo, docker compose config ou instalação. Sem commit/push.
