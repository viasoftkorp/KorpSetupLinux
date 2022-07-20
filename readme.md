# Korp Setup Linux

Setup destinado para a configuração e manutenção de servidores linux, feito utilizando a ferramenta [Ansible](https://docs.ansible.com/ansible/latest/index.html#).

---

## Adição de serviço

Para adicionar um novo serviço, siga os seguintes passos:

- Localize a pasta do APP do seu projeto na pasta `roles` (ex: infrastructure-web, picking, mobile, etc...).

    Caso não exista nenhum pasta com o APP do seu projeto, siga o tópico 'Adição de APP' para cria-lo.

- De forma geral, 3 passos devem ser feitos:

  1. adicionar serviço no arquivo de compose

      `roles/<APP>/templates/composes/<version>/<APP>-compose.yml.j2`

  2. adicionar serviço na task de configuração

      `roles/<APP>/tasks/main.yml`

  3. adicionar K/V do consul

      `roles/<APP>/templates/consul_kv/<service_name_lowercase>.json.j2`

**A extensão `j2` nos arquivos dentro da para `templates` é ESSENCIAL!**

---

1. Adicionar serviço no compose (`roles/<APP>/templates/composes/<version>/<APP>-compose.yml.j2`) usando o template:

    ``` yml
    <service_name_lowercase>-<version>:
      image: "korp/<service_name_lowercase>:<version>.x"
      container_name: "<service_name>-<version>"
      restart: always
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

2. Adicionar serviço na task de configuração (`roles/<APP>/tasks/main.yml`)

    dentro do arquivo `main.yml`, há um bloco de código conforme o seguinte:

    ``` yml
    - name: adição de serviços de <APP>
      ansible.builtin.include_role:
        name: utils
        tasks_from: services/add_service
      vars:
        service_name: "{{ item }}"
        consul_kv: "{{ lookup('template', 'consul_kv/{{ item | lower }}.json.j2') }}"
      loop:
        - <services>
    ```

    o seu serviço deverá ser adicionado dentro do array `loop`, ficando da seguinte forma:

    ``` yml
    loop:
      - Service.Name.One
      - Service.Name.Two
    ```

3. adicionar K/V do consul

    Para adicionar seu K/V (**todos os serviços devém ter**), criei o arquivo `roles/<APP>/templates/consul_kv/<service_name_lowercase>.json.j2`

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

    template:

    ``` yml
      - "{{ dados_docker_dir_path }}/<service_name_lowercase_without_dot>/:<your_path>/"
    ```

    - `service_name_lowercase_without_dot`: nome do seu serviço, letras minúsculas, com `-` ao invés de `.`

    - `your_path`: caminho interno do seu container

    **note que é possível adicionar mais caminhos após `<service_name_lowercase_without_dot>`**

    Exemplos:

      - ``` yml
        volumes:
          - "{{ self_signed_certs_directory }}/:{{ self_signed_certs_directory }}/"
          - "{{ dados_docker_dir_path }}/viasoft-integration-ecommerce/:/etc/korp/database/"
        ```

      - ``` yml
        volumes:
          - "{{ self_signed_certs_directory }}/:{{ self_signed_certs_directory }}/"
          - "{{ dados_docker_dir_path }}/viasoft-email/data/:/app/data"
          - "{{ dados_docker_dir_path }}/viasoft-email/errors/:/app/errors" 
        ```

---

### Exemplo

Para exemplificar a adição de serviço, usaremos o serviço Korp.Logistica.Picking, na versão 2022.2.0

- service_name: Korp.Logistica.Picking
- version: 2022.2.0
- APP: picking

1. Adicionar serviço no compose:
  
    local do arquivo de compose:

      - template: `roles/<APP>/templates/composes/<version>/<APP>-compose.yml.j2`
      - alterado: `roles/picking/templates/composes/2022.2.0/picking-compose.yml.j2`

    ``` yml
    korp-logistica-picking-2022-2-0: # aqui usamos '-' ao invés de '.'
        image: "korp/korp.logistica.picking:2022.2.0.x" # nome deve se com letras minúsculas
        container_name: "Korp.Logistica.Picking-2022.2.0" # nome deve ser conforme o bitbucket, com letras maiúsculas
        restart: always
        extra_hosts: *default-extra_hosts
        environment:
          - ON_PREMISE_MODE=true
          - URL_CONSUL=http://consul-server:8500
        networks:
          - servicos
        volumes:
          - "{{ self_signed_certs_directory }}/:{{ self_signed_certs_directory }}/"
    ```

2. Adicionar serviço na task de configuração

    local do arquivo:

      - template: `roles/<APP>/tasks/main.yml`
      - alterado: `roles/piking/tasks/main.yml`

    Bloco de configuração de serviço:

    ``` yml
    - name: adição de serviços de picking
      ansible.builtin.include_role:
        name: utils
        tasks_from: services/add_service
      vars:
        service_name: "{{ item }}"
        consul_kv: "{{ lookup('template', 'consul_kv/{{ item | lower }}.json.j2') }}"
      loop:
        - Korp.Logistica.Picking
    ```

3. adicionar K/V do consul

    local do arquivo:

      - template: `roles/<APP>/templates/consul_kv/<service_name_lowercase>.json.j2`
      - alterado: `roles/picking/templates/consul_kv/korp.logistica.picking.json.j2`

    nesse exemplo, vamos assumir que o serviço não tem nenhuma propriedade específica, então seu json ficaria da seguinte forma:

    ``` json
    {
        "Authorization": {
            "Secret": "{{ secret }}"
        }
    }

---

## Adição de APP

O nome do APP deve sem um nome simples e genérico, como: picking, mobile, apontamento

1. criar diretórios

    - `roles/<APP>/`
    - `roles/<APP>/tasks/`
    - `roles/<APP>/templates/`
    - `roles/<APP>/templates/consul_kv/`
    - `roles/<APP>/templates/composes/`
    - `roles/<APP>/templates/composes/<version>/`

2. criação de compose

    Criar aquivo  `roles/<APP>/templates/composes/<version>/<APP>-compose.yml.j2` com o seguinte conteúdo:

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

    Criar arquivo `roles/<APP>/tasks/main.yml` com o seguinte conteúdo:

      - altere todas as variáveis `<APP>`

    ``` yml
    - name: adição de serviços de <APP>
      ansible.builtin.include_role:
        name: utils
        tasks_from: services/add_service
      vars:
        service_name: "{{ item }}"
        consul_kv: "{{ lookup('template', 'consul_kv/{{ item | lower }}.json.j2') }}"
      loop:
        - 

    - name: configuração e transferência de arquivos de compose de <APP>
      ansible.builtin.template:
        dest: "{{ versioned_compose_dir_path }}/{{ item[:-3] | basename }}"
        src: "composes/{{ version_without_build }}/{{ item | basename }}"
        owner: "{{ linux_korp.user }}"
        group: root
        mode: '0644'
      loop:
        "{{ lookup('fileglob', 'templates/composes/{{ version_without_build }}/*', wantlist=True) | select('search','.yml.j2') }}"

    - name: criação e inicialização de <APP>-compose - versionado
      community.docker.docker_compose:
        project_src: "{{ versioned_compose_dir_path }}/"
        env_file: "{{ docker_env_file_path }}"
        files:
          - <APP>-compose.yml
    ```

4. adição de role no playbook

  em `main.yml` adicione as seguintes linhas **ANTES** da linhas contendo `finishing:

  ``` yml
    - role: <APP>
      tags:
        - <APP>
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
