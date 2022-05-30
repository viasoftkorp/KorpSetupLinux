# Korp Setup Linux

Setup destinado para a configuração e manutenção de servidores linux, feito utilizando a ferramenta [Ansible](https://docs.ansible.com/ansible/latest/index.html#).

---

## Execução de PlayBook

Para executar um PlayBook utilize:

```
ansible-playbook <PlayBook_Name.yml>
```

Parâmetros opcionais que podem ser utilizados são:

- `-l <hosts>` = IP, dns, ou grupo (arquivo 'inventory')
- `--tags <tags>` =  tags que estão associadas a cada role 'principal'

## Execução de testes de PlayBook

Para a realização de linting, utilize a ferramenta [Ansible Lint](https://ansible-lint.readthedocs.io/en/latest/).

```
ansible-lint <PlayBook_Name.yml>
```
 