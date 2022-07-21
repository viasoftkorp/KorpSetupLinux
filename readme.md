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

  2. adicionar serviço na task de configuração

      `roles/<AppId>/tasks/main.yml`

  3. adicionar K/V do consul

      `roles/<AppId>/templates/consul_kv/<service_name_lowercase>.json.j2`

**A extensão `j2` nos arquivos dentro da para `templates` é ESSENCIAL!**

---

1. Adicionar serviço no compose (`roles/<AppId>/templates/composes/<version>/<AppId>-compose.yml.j2`) usando o template:

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

2. Adicionar serviço na task de configuração (`roles/<AppId>/tasks/main.yml`)

    dentro do arquivo `main.yml`, há um bloco de código conforme o seguinte:

    ``` yml
    - name: adição de serviços de <AppId>
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
          - "{{ dados_docker_dir_path }}/viasoft-email/data/:/AppId/data"
          - "{{ dados_docker_dir_path }}/viasoft-email/errors/:/AppId/errors" 
        ```

    Após adicionar o volume no compose, é necessário adiciona-lo na task de criação de diretório.

    Para isso, abra `roles/<AppId>/tasks/main.yml`, após o bloco

    ``` yml
    - name: adição de serviços de <AppId>
    ```

    adicione o seguinte bloco:

    ``` yml
    - name: garantia da existência dos diretórios de volumes de <AppId>
      ansible.builtin.include_role:
        name: utils
        tasks_from: services/ensure_volume_folder
      vars:
        volume_path: "{{ item }}"
      loop:
        - "{{ dados_docker_dir_path }}/<service_name_lowercase_without_dot>/"
    ```

    **OBS: esse bloco pode já existir, nesse caso, basta adicionar o seu volume ao array `loop`**

    Exemplos:

      - ``` yml
        - name: garantia da existência dos diretórios de volumes de <AppId>
          ansible.builtin.include_role:
            name: utils
            tasks_from: services/ensure_volume_folder
          vars:
            volume_path: "{{ item }}"
          loop:
            - "{{ dados_docker_dir_path }}/viasoft-integration-ecommerce/"
            - "{{ dados_docker_dir_path }}/viasoft-email/data/"
            - "{{ dados_docker_dir_path }}/viasoft-email/errors/"
        ```

---

### Exemplo

Para exemplificar a adição de serviço, usaremos o serviço Korp.Logistica.Picking, na versão 2022.2.0

- service_name: Korp.Logistica.Picking
- version: 2022.2.0
- AppId: picking

1. Adicionar serviço no compose:
  
    local do arquivo de compose:

      - template: `roles/<AppId>/templates/composes/<version>/<AppId>-compose.yml.j2`
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

      - template: `roles/<AppId>/tasks/main.yml`
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

## Adição de AppId

O nome do AppId deve sem um nome simples e genérico, como: picking, mobile, apontamento

1. criar diretórios

    - `roles/<AppId>/`
    - `roles/<AppId>/tasks/`
    - `roles/<AppId>/templates/`
    - `roles/<AppId>/templates/consul_kv/`
    - `roles/<AppId>/templates/composes/`
    - `roles/<AppId>/templates/composes/<version>/`

2. criação de compose

    Criar aquivo  `roles/<AppId>/templates/composes/<version>/<AppId>-compose.yml.j2` com o seguinte conteúdo:

    ```yml
    version: "3.8"

    x-extra_hosts:
      &default-extra_hosts
      - "db_mssql: $DB_MSSQL"
      - "AppId_server: $AppId_SERVER"
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

    Criar arquivo `roles/<AppId>/tasks/main.yml` com o seguinte conteúdo:

      - altere todas as variáveis `<AppId>`

    ``` yml
    - name: adição de serviços de <AppId>
      ansible.builtin.include_role:
        name: utils
        tasks_from: services/add_service
      vars:
        service_name: "{{ item }}"
        consul_kv: "{{ lookup('template', 'consul_kv/{{ item | lower }}.json.j2') }}"
      loop:
        - 

    - name: configuração e transferência de arquivos de compose de <AppId>
      ansible.builtin.template:
        dest: "{{ versioned_compose_dir_path }}/{{ item[:-3] | basename }}"
        src: "composes/{{ version_without_build }}/{{ item | basename }}"
        owner: "{{ linux_korp.user }}"
        group: root
        mode: '0644'
      loop:
        "{{ lookup('fileglob', 'templates/composes/{{ version_without_build }}/*', wantlist=True) | select('search','.yml.j2') }}"

    - name: criação e inicialização de <AppId>-compose - versionado
      community.docker.docker_compose:
        project_src: "{{ versioned_compose_dir_path }}/"
        env_file: "{{ docker_env_file_path }}"
        files:
          - <AppId>-compose.yml
    ```

4. adição de role no playbook

  em `main.yml` adicione as seguintes linhas **ANTES** da linhas contendo `finishing:

  ``` yml
    - role: <AppId>
      tags:
        - <AppId>
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
