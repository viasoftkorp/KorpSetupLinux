# Korp Setup Linux

Setup destinado para a configuração e manutenção de servidores linux, feito utilizando a ferramenta [Ansible](https://docs.ansible.com/ansible/latest/index.html#).

---

## Adição de serviço

Para adicionar um novo serviço, siga os seguintes passos:

- Localize a pasta do AppId do seu projeto na pasta `roles` (ex: infrastructure-web, picking, mobile, etc...).

    Caso não exista nenhum pasta com o AppId do seu projeto, siga o tópico 'Adição de AppId' para cria-lo.

- De forma geral, 3 passos devem ser feitos:

  1. adicionar serviço no arquivo de compose

      `roles/<AppId>/templates/composes/<version>/<AppId>-compose.yml.j2`

  2. adicionar serviço no arquivo de variáveis

      `roles/<AppId>/vars/main.yml`

  3. adicionar K/V do consul

      `roles/<AppId>/templates/consul_kv/<service_name_lowercase>.json.j2`

**A extensão `j2` nos arquivos dentro da para `templates` é ESSENCIAL!**

---

1. Adicionar serviço no compose (`roles/<AppId>/templates/composes/<version>/<AppId>-compose.yml.j2`) usando o template:

    ``` yml
    <service_name_lowercase>-<version>:
      image: "korp/<service_name_lowercase>:<version>.x"
      container_name: "<service_name>-<version>"
      restart: on-failure:10
      extra_hosts: *default-extra_hosts
      environment:
        - ON_PREMISE_MODE=true
        - URL_CONSUL=http://consul-server:8500
      networks:
        - servicos
      volumes:
        - "{{ self_signed_certs_directory }}/:{{ self_signed_certs_directory }}/"
    ```

    **Caso seu serviço tenha `volumes` adicionais, siga o passo *4***

2. adicionar serviço no arquivo de variáveis (`roles/<AppId>/vars/main.yml`)

    dentro do arquivo `main.yml`, adicione o seu serviço dentro do dicionário `services`:

    ``` yml
    - <service_name>:
        # OPCIONAL, caso não haja a necessidade de criar DataBase, remover bloco 'db'
        db: 
          name: <db_name> # OPCIONAL, caso vazio 'name' será o nome do serviço com '_' ao invés de '.'
          type: mssql/postgres  # OBRIGATÓRIO
        # OPCIONAL, caso bloco não exista, irá gerar cliente oauth
        oauth_client:
          skip: false
        # OPCIONAL, lista contendo o caminho absoluto para os diretórios dos volumes.
        volumes_directories:
        - "{{ dados_docker_dir_path }}/<path>" # sempre utilize esse template
    ```

    por exemplo, caso seu serviço tenha banco de dados em postgres, cliente oauth, e não tenha volumes, sua configuração ficaria da seguinte forma:

    ``` yml
    - <service_name>:
        db: 
          name: <db_name>
          type: postgres
    ```


    para serviços que não possuem nenhuma propriedade, a configuração ficaria:

    ``` yml
    - <service_name>:
    ```

    **OBSERVAÇÃO:**

    note que após o `service_name`, sempre deve haver dois pontos `:`


3. adicionar K/V do consul

    Para adicionar seu K/V (**todos os serviços devém ter**), criei o arquivo `roles/<AppId>/templates/consul_kv/<service_name_lowercase>.json.j2`

    - `<service_name_lowercase>` é o nome do seu serviço, com todas as letras minúsculas.

    Todo K/V deve conter as seguintes propriedades:

    ``` json
    {
        "Authorization": {
            "Secret": "{{ secret }}"
        }
    }
    ```

    Caso seu serviço não tenha nenhuma propriedade específica, basta criar o arquivo `.json.j2` com o json a cima.

4. esse passo só é usado caso seu serviço tenha `volumes` adicionais

    template de compose:

    ``` yml
      - "{{ dados_docker_dir_path }}/<AppId>/<your_path>:<container_path>/"
    ```

    - `your_path`: caminho do volume

    Exemplos:

      - ``` yml
        volumes:
          - "{{ self_signed_certs_directory }}/:{{ self_signed_certs_directory }}/"
          - "{{ dados_docker_dir_path }}/MOB02/data/:/app/data"
          - "{{ dados_docker_dir_path }}/financeiro/errors/:/app/errors" 
        ```

    Após adicionar o volume no compose, é necessário adiciona-lo nas variáveis do serviço.

    Para isso, abra `roles/<AppId>/vars/main.yml`, nas propriedades do seu serviço adicione o diretório na lista `volumes_directories`:

    ``` yml
    - <service_name>:
        volumes_directories:
        - "{{ dados_docker_dir_path }}/<AppId>/<your_path>"
    ```

---

### Exemplo

Para exemplificar a adição de serviço, usaremos o serviço Korp.Logistica.Picking, na versão 2022.2.0

- service_name: Korp.Logistica.Picking
- version: 2022.2.0
- AppId: picking
- Tem DataBase: `false`

1. Adicionar serviço no compose:
  
    local do arquivo de compose:

      - template: `roles/<AppId>/templates/composes/<version>/<AppId>-compose.yml.j2`
      - alterado: `roles/picking/templates/composes/2022.2.0/picking-compose.yml.j2`

    ``` yml
    korp-logistica-picking-2022-2-0: # aqui usamos '-' ao invés de '.'
        image: "korp/korp.logistica.picking:2022.2.0.x" # nome deve se com letras minúsculas
        container_name: "Korp.Logistica.Picking-2022.2.0" # nome deve ser conforme o bitbucket, com letras maiúsculas
        restart: on-failure:10
        extra_hosts: *default-extra_hosts
        environment:
          - ON_PREMISE_MODE=true
          - URL_CONSUL=http://consul-server:8500
        networks:
          - servicos
        volumes:
          - "{{ self_signed_certs_directory }}/:{{ self_signed_certs_directory }}/"
    ```

2. Adicionar variáveis do serviço

    local do arquivo:

      - template: `roles/<AppId>/vars/main.yml`
      - alterado: `roles/piking/vars/main.yml`

    Bloco de configuração de serviço:

    ``` yml
    services:
      - Korp.Logistica.Picking:
    ```

3. adicionar K/V do consul

    local do arquivo:

      - template: `roles/<AppId>/templates/consul_kv/<service_name_lowercase>.json.j2`
      - alterado: `roles/picking/templates/consul_kv/korp.logistica.picking.json.j2`

    nesse exemplo, vamos assumir que o serviço não tem nenhuma propriedade específica, então seu json ficaria da seguinte forma:

    ``` json
    {
        "Authorization": {
            "Secret": "{{ secret }}"
        }
    }

---

## Adição de AppId/Domínio

O nome do Domínio deve sem um nome simples e genérico, como: picking, mobile, apontamento
O nome do AppId deve ser pego do portal.korp, na aba de gerenciamento de aplicativos.

Chamaremos AppId/Domínio de `ID`

1. criar diretórios

    - `roles/<ID>/`
    - `roles/<ID>/tasks/`
    - `roles/<ID>/vars/`
    - `roles/<ID>/templates/`
    - `roles/<ID>/templates/consul_kv/`
    - `roles/<ID>/templates/composes/`
    - `roles/<ID>/templates/composes/<version>/`

2. criação de compose

    Criar aquivo  `roles/<ID>/templates/composes/<version>/<ID>-compose.yml.j2` com o seguinte conteúdo:

    ```yml
    version: "3.8"

    x-extra_hosts:
      &default-extra_hosts
      - "db_mssql: $DB_MSSQL"
      - "app_server: $APP_SERVER"
      - "korp-api: $API_GATEWAY"
      - "korp: $PORTAL_GATEWAY"
      - "korp-cdn: $CDN_GATEWAY"

    networks:
      servicos:
        external:
          name: servicos

    services:
    ```

3. criação de tasks

    Criar arquivo `roles/<ID>/tasks/main.yml` com o seguinte conteúdo:

      - altere todas as variáveis `<ID>`

    ``` yml
    - name: adição de serviços de <ID>
      ansible.builtin.include_role:
        name: utils
        tasks_from: services/add_service
      vars:
        service_name: "{{ item.key }}"
        id: <ID>
      with_dict: "{{ (lookup('file', 'vars/main.yml') | from_yaml)['services'] }}"
      loop_control:
        extended: true
    ```

4. criação de arquivo de variáveis

    Criar arquivo `roles/<ID>/vars/main.yml` com o seguinte conteúdo:

    ``` yml
    services:
    ```

5. adição de role no playbook

    em `main.yml` adicione as seguintes linhas **ANTES** da linhas contendo `finishing:

    ``` yml
    - name: <ID>
      ansible.builtin.import_role:
        name: <ID>
      tags:
        - <ID>
    ```

---

## Execução de PlayBook

Para executar um PlayBook utilize:

``` bash
ansible-playbook <PlayBook_Name.yml>
```

Parâmetros opcionais que podem ser utilizados são:

- `-l <hosts>` = IP, dns, ou grupo (arquivo 'inventory')
- `--tags <tags>` =  tags que estão associadas a cada role 'principal'

## Execução de testes de PlayBook

Para a realização de linting, utilize a ferramenta [Ansible Lint](https://ansible-lint.readthedocs.io/en/latest/).

``` bash
ansible-lint <PlayBook_Name.yml>
```
