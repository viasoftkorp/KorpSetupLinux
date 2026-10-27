#!/usr/bin/env python3
"""Dump determinístico do estado que o setup produz num host (ambiente isolado de testes).

Uso (dentro do host isolado, como root):
    python3 state_dump.py OUT.json --mssql-host H --mssql-user U --mssql-password-file F

Inclui: KVs do Consul, tabelas OAuth do Viasoft_Authentication, bancos/usuários MSSQL, bancos/roles
Postgres, árvore /etc/korp (metadados; conteúdo apenas onde é determinístico), crontab do korp e
containers (nome, imagem, labels Compose relevantes, estado).
Segredos aleatórios não são gravados: apenas um hash (para provar preservação entre execuções).
"""
import argparse
import base64
import grp
import hashlib
import json
import os
import pwd
import stat
import subprocess
import urllib.request

SECRET_PATHS = (("Authorization", "Secret"),)
HASH_DIRS = ("/etc/korp/composes", "/etc/korp/configs", "/etc/korp/scripts", "/etc/korp/logrotate.d")
META_ONLY_DIRS = ("/etc/korp/certs", "/etc/korp/dados-docker", "/etc/korp/atualizacao-sistema")
SKIP_DIRS = ("/etc/korp/ansible", "/etc/korp/lost+found")
# arquivos de dados escritos pelos próprios containers (não pelo setup)
SKIP_UNDER = ("/etc/korp/dados-docker/",)


SECRET_KEY_HINTS = ("password", "secret", "key", "token", "pass")
INVENTORY_SECRETS = []
# Authorization.Secret de cada KV (chave -> segredo); usado apenas em memória para comparar com o
# hash gravado em ClientSecrets e nunca gravado no dump.
KV_SECRETS = {}


def inventory_secrets():
    """Valores sensíveis gerados no inventário (senhas aleatórias criadas pelo inventory-playbook).

    São substituídos por <inventory> antes de registrar/hashear, para que duas instalações novas
    (cada uma com suas senhas aleatórias) possam ser comparadas."""
    try:
        import yaml
        out = subprocess.run(["ansible-vault", "view", "/etc/korp/ansible/inventory.yml",
                              "--vault-id", "/etc/korp/ansible/.vault_key"], capture_output=True, text=True)
        data = yaml.safe_load(out.stdout) or {}
    except Exception:
        return []
    found = []

    def walk(node, key=""):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, str(k).lower())
        elif isinstance(node, list):
            for v in node:
                walk(v, key)
        elif isinstance(node, str) and len(node) >= 8 and any(h in key for h in SECRET_KEY_HINTS):
            found.append(node)
    walk(data)
    return sorted(set(found), key=len, reverse=True)


def norm(text):
    for value in INVENTORY_SECRETS:
        text = text.replace(value, "<inventory>")
    return text


def sha(data):
    return hashlib.sha256(data if isinstance(data, bytes) else str(data).encode()).hexdigest()[:16]


def mask_secrets(obj):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k == "Authorization" and isinstance(v, dict) and "Secret" in v:
                v = dict(v)
                v["Secret"] = "<secret:%s>" % sha(v["Secret"])
            out[k] = mask_secrets(v)
        return out
    if isinstance(obj, list):
        return [mask_secrets(x) for x in obj]
    return obj


def consul_kv():
    try:
        raw = urllib.request.urlopen("http://127.0.0.1:8500/v1/kv/?recurse=true", timeout=10).read()
    except Exception as exc:  # consul ainda não existe
        return {"<error>": str(exc)}
    result = {}
    for item in json.loads(raw):
        value = base64.b64decode(item["Value"]).decode("utf-8", "replace") if item.get("Value") else None
        value = norm(value) if value is not None else None
        try:
            parsed = json.loads(value) if value is not None else None
            text = value
            secret = ((parsed or {}).get("Authorization") or {}).get("Secret") if isinstance(parsed, dict) else None
            if isinstance(secret, str) and secret:
                KV_SECRETS[item["Key"]] = secret
                text = text.replace(secret, "<secret>")
            # formatação exata (to_nice_json) comparável mesmo com segredo aleatório
            result[item["Key"]] = {"json": mask_secrets(parsed), "text_sha": sha(text)}
        except ValueError:
            result[item["Key"]] = {"text": value}
    return result


def mssql(host, user, password):
    try:
        import pymssql
    except ImportError:
        return {"<error>": "pymssql ausente"}
    out = {}
    conn = pymssql.connect(server=host, user=user, password=password, database="master", autocommit=True)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sys.databases WHERE database_id > 4 ORDER BY name")
    dbs = [r[0] for r in cur.fetchall()]
    out["databases"] = {}
    for db in dbs:
        cur.execute("USE [%s]; SELECT dp.name, dp.type, ISNULL(r.name,'') FROM sys.database_principals dp "
                    "LEFT JOIN sys.database_role_members m ON m.member_principal_id = dp.principal_id "
                    "LEFT JOIN sys.database_principals r ON r.principal_id = m.role_principal_id "
                    "WHERE dp.type IN ('S','U') AND dp.name NOT IN ('dbo','guest','INFORMATION_SCHEMA','sys') "
                    "ORDER BY 1,3" % db)
        out["databases"][db] = [list(r) for r in cur.fetchall()]
    cur.execute("USE [master]; SELECT name, type FROM sys.server_principals WHERE type='S' "
                "AND name NOT LIKE '##%' ORDER BY 1")
    out["logins"] = [list(r) for r in cur.fetchall()]
    if "Viasoft_Authentication" in dbs or any(d.startswith("Viasoft_Authentication") for d in dbs):
        auth = [d for d in dbs if d.startswith("Viasoft_Authentication")][0]
        cur.execute("USE [%s]" % auth)
        queries = {
            "ApiResources": "SELECT Name, DisplayName, Enabled, NonEditable, ShowInDiscoveryDocument FROM ApiResources",
            "ApiScopes": "SELECT Name, DisplayName, Required, Emphasize, ShowInDiscoveryDocument, Enabled FROM ApiScopes",
            "Clients": "SELECT ClientId, Enabled, ProtocolType, RequireClientSecret, AccessTokenLifetime, "
                       "AllowOfflineAccess, ClientClaimsPrefix, NonEditable FROM Clients",
            "ClientGrantTypes": "SELECT c.ClientId, g.GrantType FROM ClientGrantTypes g JOIN Clients c ON c.Id = g.ClientId",
            "ClientScopes": "SELECT c.ClientId, s.Scope FROM ClientScopes s JOIN Clients c ON c.Id = s.ClientId",
            "ClientSecrets": "SELECT c.ClientId, s.Type, s.Value FROM ClientSecrets s JOIN Clients c ON c.Id = s.ClientId",
        }
        oauth = {}
        for name, q in queries.items():
            cur.execute(q)
            rows = [[str(x) for x in r] for r in cur.fetchall()]
            if name == "ClientSecrets":
                # invariante: ClientSecrets.Value == base64(sha256(Authorization.Secret do KV)); só o booleano é gravado
                matches = {}
                for r in rows:
                    if r[0] in KV_SECRETS:
                        expected = base64.b64encode(hashlib.sha256(KV_SECRETS[r[0]].encode("utf-8")).digest()).decode("ascii")
                        matches[r[0]] = matches.get(r[0], False) or r[2] == expected
                oauth["secret_matches_kv"] = matches
                rows = [[r[0], r[1], "<secret:%s>" % sha(r[2])] for r in rows]
            oauth[name] = sorted(rows)
        out["oauth"] = oauth
    conn.close()
    return out


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def postgres():
    r = run(["docker", "exec", "postgres", "psql", "-U", "postgres", "-tA", "-F", "|", "-c",
             "SELECT datname, pg_get_userbyid(datdba) FROM pg_database WHERE NOT datistemplate ORDER BY 1"])
    roles = run(["docker", "exec", "postgres", "psql", "-U", "postgres", "-tA", "-F", "|", "-c",
                 "SELECT rolname, rolsuper, rolcreatedb, rolcanlogin FROM pg_roles WHERE rolname NOT LIKE 'pg_%' ORDER BY 1"])
    return {"databases": r.stdout.split(), "roles": roles.stdout.split(), "rc": [r.returncode, roles.returncode]}


def files():
    out = {}
    for root, dirs, names in os.walk("/etc/korp"):
        if root.startswith(SKIP_DIRS):
            dirs[:] = []
            continue
        dirs.sort()
        for entry in [root] + [os.path.join(root, n) for n in sorted(names)]:
            if entry.startswith(SKIP_UNDER) and not os.path.isdir(entry):
                continue
            try:
                st = os.lstat(entry)
            except FileNotFoundError:
                continue
            info = {
                "type": "d" if stat.S_ISDIR(st.st_mode) else ("l" if stat.S_ISLNK(st.st_mode) else "f"),
                "mode": oct(stat.S_IMODE(st.st_mode)),
                "owner": pwd.getpwuid(st.st_uid).pw_name if st.st_uid in [p.pw_uid for p in pwd.getpwall()] else st.st_uid,
                "group": grp.getgrgid(st.st_gid).gr_name if st.st_gid in [g.gr_gid for g in grp.getgrall()] else st.st_gid,
            }
            if info["type"] == "f" and entry.startswith(HASH_DIRS) and not entry.startswith(META_ONLY_DIRS):
                with open(entry, "rb") as fh:
                    info["sha"] = sha(norm(fh.read().decode("utf-8", "surrogateescape")).encode("utf-8", "surrogateescape"))
            out[entry] = info
    # dados-docker: apenas os diretórios criados pelo setup (subdiretórios de dados dos serviços são dos containers)
    return out


def containers():
    r = run(["docker", "ps", "-a", "--format", "{{json .}}"])
    out = {}
    for line in r.stdout.splitlines():
        c = json.loads(line)
        inspect = json.loads(run(["docker", "inspect", c["ID"]]).stdout)[0]
        labels = inspect["Config"].get("Labels") or {}
        out[c["Names"]] = {
            "image": inspect["Config"]["Image"],
            "running": inspect["State"]["Running"],
            "project": labels.get("com.docker.compose.project"),
            "service": labels.get("com.docker.compose.service"),
            "oneoff": labels.get("com.docker.compose.oneoff"),
            "config_hash": labels.get("com.docker.compose.config-hash"),
            "restart": inspect["HostConfig"].get("RestartPolicy", {}).get("Name"),
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--mssql-host", required=True)
    ap.add_argument("--mssql-user", default="sa")
    ap.add_argument("--mssql-password-file", required=True)
    a = ap.parse_args()
    password = open(a.mssql_password_file).read().strip()
    INVENTORY_SECRETS.extend(inventory_secrets())
    cron = run(["crontab", "-l", "-u", "korp"])
    state = {
        "consul_kv": consul_kv(),
        "mssql": mssql(a.mssql_host, a.mssql_user, password),
        "postgres": postgres(),
        "files": files(),
        "korp_crontab": cron.stdout.splitlines(),
        "containers": containers(),
        "networks": sorted(run(["docker", "network", "ls", "--format", "{{.Name}}"]).stdout.split()),
    }
    with open(a.out, "w") as fh:
        json.dump(state, fh, indent=1, sort_keys=True, default=str)


if __name__ == "__main__":
    main()
