#!/usr/bin/python

from ansible.module_utils.basic import *

# Este módulo permite a manipulação de KVs do consul.
# Ele realiza as seguintes operações:
#
#   - Adiciona valores inéditos;
#       
#   - Sobrescreve valores referentes ao caminho passado ***explicitamente*** em 'keys_to_overwrite'; 
#     O caminho é relativo ao kv atual. Exemplos:
#       current_kv = a: {b: "Valor antigo"}}
#       new_kv     = a: {b: {c: "Valor novo"}}
#       - keys_to_overwrite = [a.b]   -> SOBRESCREVE 
#       - keys_to_overwrite = [a]     -> NÃO SOBRESCREVE
#       - keys_to_overwrite = [a.b.c] -> NÃO SOBRESCREVE
#       - keys_to_overwrite = [b.c]   -> NÃO SOBRESCREVE
#       - keys_to_overwrite = [c]     -> NÃO SOBRESCREVE
#
#   - Retorna um novo dicionário resultante da operação.
#
 
# Função recursiva para acessar valor da chave a ser atualizada;
def access_key(keys_sequence, dictionary):
    if not keys_sequence:
        return dictionary
    current_key = keys_sequence[0]
    if current_key in dictionary:
        return access_key(keys_sequence[1:], dictionary[current_key])
    else:
        return None #Tratado posteriormente para não criar chaves nulas;
 
# Criação de um dict com o caminho até a chave atualizada
def build_dict_with_new_value(new_value, keys_sequence):
    new_dict = {}
    new_dict_ref = new_dict 
    for key in keys_sequence[:-1]: 
        new_dict_ref[key] = {}
        new_dict_ref = new_dict_ref[key] # avança um nível para dentro do dict;
    new_dict_ref[keys_sequence[-1]] = new_value 
    return new_dict
 
# Função recursiva para reconstruir o dicionário com o novo valor, e mantendo valores das outras chaves;
def merge_dicts(current_dict, new_dict, keys_sequence):
    for key, value in new_dict.items():
        if key in current_dict and isinstance(current_dict[key], dict) and isinstance(value, dict):
            merge_dicts(current_dict[key], value, keys_sequence) # Acessa próximo nível;
        else:
            if key == keys_sequence[-1]: # Altera apenas a chave explícitamente definida em keys_to_overwrite
                current_dict[key] = value 
    return current_dict
           
   
def main():
    module = AnsibleModule(
        argument_spec= dict(
            current_kv = dict(type='dict', required=True),
            new_kv = dict(type='dict', required=True),
            keys_to_overwrite = dict(type='list', elements='str', required=True)
        )
    )
 
    # Definição de variáveis
    new_kv = module.params['new_kv']
    current_kv = module.params['current_kv']
    keys_to_overwrite = module.params["keys_to_overwrite"]
    
    # Obtenção de novos KV
    temp_kv = new_kv.copy()
    temp_kv.update(current_kv)

    # Fazendo sobrescrita de chaves
    merged_kv = temp_kv.copy()
    for key in keys_to_overwrite:
        keys_sequence = key.split(".")
        new_value = access_key(keys_sequence, new_kv)
        if new_value:
            dict_with_new_value = build_dict_with_new_value(new_value, keys_sequence)
            merged_kv = merge_dicts(merged_kv, dict_with_new_value, keys_sequence)
    print(merged_kv)
 
    # Retornando resultado
    result = dict(
        changed=False,
        prop=merged_kv,
    )
   
    module.exit_json(**result)
 
if __name__ == "__main__":
    main()
 