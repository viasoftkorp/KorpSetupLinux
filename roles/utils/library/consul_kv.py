#!/usr/bin/python

from pkg_resources import require
from ansible.module_utils.basic import *

# Este módulo permite a manipulação de KVs do consul.
# Ele realiza as seguintes operações:
#
#   1. Adiciona valores inéditos;
#       
#   2. Sobrescreve valores referentes ao caminho passado explicitamente em 'keys_to_overwrite'; 
#     O caminho é *** relativo ao kv atual ***. Exemplos:
#       current_kv = a: {b: "Valor antigo1", d: "Valor antigo2"}}
#       new_kv     = a: {b: {c: "Valor novo"}}
        # KEYS_TO_OVERWRITE     |    OUTPUT    
#             ["a.b"]           |  a: {b: {c: "Valor novo"}, d: "Valor antigo2"}}
#             ["a"]             |  a: {b: {c: "Valor novo"}} 
#             ["a.b.c"]         |  a: {b: "Valor antigo1", d: "Valor antigo2"}} (sem efeito)
#
#   3. Retorna um novo dicionário resultante da operação.
#
# Função recursiva para substituir valor da chave a ser atualizada;

def replace_key(keys_sequence, dictionary, new_val):
    current_key = keys_sequence[0]
    if len(keys_sequence) == 1:
        dictionary[current_key] = new_val
    else:
        dictionary[current_key] = replace_key(keys_sequence[1:], dictionary[current_key], new_val)
    return dictionary

def access_value(keys_sequence, dictionary):
    if not keys_sequence:
        return dictionary
    current_key = keys_sequence[0]
    if current_key in dictionary:
        return access_value(keys_sequence[1:], dictionary[current_key])
    else:
        return None #Tratado posteriormente para não criar chaves nulas;

def main():

    module = AnsibleModule(
        argument_spec= dict(
            current_kv = dict(type='dict', required=True),
            new_kv = dict(type='dict', required=True),
            keys_to_overwrite = dict(type='list', elements='str', required=True)
        )
    )
 
    # Definição de variáveis consul
    new_kv = module.params['new_kv']
    current_kv = module.params['current_kv']
    keys_to_overwrite = module.params["keys_to_overwrite"]

    temp_kv = new_kv.copy()
    temp_kv.update(current_kv) # armazena novas chaves

    # Removendo chaves antigas se houverem chaves atualizadas
    for key_path in keys_to_overwrite:
        keys_sequence = key_path.split(".")
        new_val = access_value(keys_sequence, new_kv) # garantir existência de valor no novo dict
        if new_val:
            temp_kv = replace_key(keys_sequence, temp_kv, new_val) 
    
    # Retornando resultado
    result = dict(
        changed=False,
        prop=temp_kv,
    )
   
    module.exit_json(**result)
 
if __name__ == "__main__":
    main()
 