# -*- coding: utf-8 -*-
"""Filtros do KV Global (roles/infrastructure/tasks/main.yml)."""


def _origens(cors):
    return [o.strip() for o in (cors or "").split(",") if o.strip()]


def korp_global_cors(kv_atual, frontend_url):
    """CORS do KV Global depois de uma possível troca de domínio.

    Troca a origem do frontend antigo (FrontendUrl atual) pela nova, coloca a nova em primeiro se ela não estiver
    na lista e mantém as origens cadastradas à mão. O Viasoft.Core separa o CORS por vírgula e compara cada
    origem exatamente, sem os espaços. Sem mudança, devolve o valor atual como está.
    """
    kv_atual = kv_atual or {}
    atual = kv_atual.get("CORS") or ""
    origens = _origens(atual)
    if "*" in origens:
        return atual
    antigo = (kv_atual.get("FrontendUrl") or "").strip()
    novas = []
    for origem in origens:
        origem = frontend_url if antigo and origem == antigo else origem
        if origem not in novas:
            novas.append(origem)
    if frontend_url not in novas:
        novas.insert(0, frontend_url)
    return atual if novas == origens else ",".join(novas)


class FilterModule(object):
    def filters(self):
        return {"korp_global_cors": korp_global_cors}
