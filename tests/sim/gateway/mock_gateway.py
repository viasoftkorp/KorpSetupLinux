#!/usr/bin/env python3
"""Mock of the Korp cloud gateway + local portal endpoints used by KorpSetupLinux.

Isolated-test only. Serves deterministic fake data; never contacts real services.
Env: SIM_VERSION (e.g. 2025.1.0), SIM_LICENSED (comma list), SIM_TENANT.
Every request is appended to /var/log/mock_gateway.jsonl for assertions.
"""
import json, os, ssl, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STATE = {"version": os.environ.get("SIM_VERSION", "2025.1.0")}
LOG = os.environ.get("SIM_LOG", "/var/log/mock_gateway.jsonl")

SECRET_PATHS = """
Global.ApiWebKey
Global.GatewayCdnUrl
Global.GatewayFrontendUrl
Global.KorpRegisterApiKey
Global.MinioConfigGateway.EndPoint
Korp.Legacy.Authentication|ClientId
Korp.Legacy.Authentication|ClientSecret
Others.ACBr.ClientId
Others.ACBr.ClientSecret
Others.CustomOauthClients|Octopus.APS
Others.CustomOauthClients|Viasoft.IntegracaoPropostaComercialWeb
Others.WatchTower.ApiToken
Others.WatchTower.WebHooks.MsTeams
Others.Zabbix.PSK.Identity
Others.Zabbix.ServerAdress
Viasoft.Approval|FirebaseMessaging.ChannelId
Viasoft.Approval|FirebaseMessaging.GoogleCredential.auth_provider_x509_cert_url
Viasoft.Approval|FirebaseMessaging.GoogleCredential.auth_uri
Viasoft.Approval|FirebaseMessaging.GoogleCredential.client_email
Viasoft.Approval|FirebaseMessaging.GoogleCredential.client_id
Viasoft.Approval|FirebaseMessaging.GoogleCredential.client_x509_cert_url
Viasoft.Approval|FirebaseMessaging.GoogleCredential.private_key
Viasoft.Approval|FirebaseMessaging.GoogleCredential.private_key_id
Viasoft.Approval|FirebaseMessaging.GoogleCredential.project_id
Viasoft.Approval|FirebaseMessaging.GoogleCredential.token_uri
Viasoft.Approval|FirebaseMessaging.GoogleCredential.type
Viasoft.Approval|FirebaseMessaging.ProjectId
Viasoft.Approval|FirebaseMessaging.SenderID
Viasoft.ELT|AppRise.TeamsWebHookUrl
Viasoft.ELT|ClientSecret
Viasoft.Faturamento.NotaFiscal.Core|NuvemFiscalEmissorNFe.Secret
Viasoft.Legacy.Authentication|ClientId
Viasoft.Legacy.Authentication|ClientSecret
Viasoft.Legacy.Authorization|ClientId
Viasoft.Legacy.Authorization|ClientSecret
Viasoft.Legacy.TenantManagement|ClientId
Viasoft.Legacy.TenantManagement|ClientSecret
Viasoft.Legacy.UserProfile|ClientId
Viasoft.Legacy.UserProfile|ClientSecret
Viasoft.TenantManagement|DatabaseVersionUpdateClientId
Viasoft.TenantManagement|DatabaseVersionUpdateClientSecret
Viasoft.WelcomePage.Dashboard|CheckEnvironmentAuthorization.Client
Viasoft.WelcomePage.Dashboard|CheckEnvironmentAuthorization.Secret
"""

def _set(d, path, value):
    # "Svc.Name|a.b" -> d["Svc.Name"]["a"]["b"]; "A.b.c" -> d["A"]["b"]["c"]; "X|Key.With.Dots" handled by last part
    if "|" in path:
        head, rest = path.split("|", 1)
        if head.startswith("Others.CustomOauthClients"):
            d.setdefault("Others", {}).setdefault("CustomOauthClients", {})[rest] = value
            return
        keys = [head] + rest.split(".")
    else:
        keys = path.split(".")
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = value

def secrets():
    """Fake values for every services_secrets path referenced by the 2024.2/2025.1 templates."""
    s = {}
    for line in SECRET_PATHS.split():
        _set(s, line, "sim-" + line.replace("|", ".").replace(".", "-").lower()[:40])
    _set(s, "Global.MinioConfigGateway.useSSL", False)
    s["Others"]["Docker"] = {"Account": "korpsim", "AccessToken": "fake-token", "ImageSuffix": ""}
    s["Others"]["DNSs"] = {"api": "korp-api.local", "cdn": "korp-cdn.local", "frontend": "korp.local"}
    s["Others"]["Zabbix"]["PSK"]["Key"] = "00" * 32
    return s

class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a):
        pass
    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def _route(self):
        p = self.path.split("?")[0]
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n).decode(errors="replace") if n else ""
        with open(LOG, "a") as f:
            f.write(json.dumps({"t": time.time(), "m": self.command, "p": p, "body": body[:500]}) + "\n")
        if p.startswith("/__sim/version/"):
            STATE["version"] = p.rsplit("/", 1)[1]
            return self._send(200, STATE)
        if "/TenantManagement/server-deploy/token/" in p:
            return self._send(200, {"tenantId": os.environ.get("SIM_TENANT", "00000000-0000-0000-0000-000000000001"),
                                    "version": STATE["version"]})
        if "/vault/manager/server-deploy/secrets/" in p:
            return self._send(200, secrets())
        if "/vault/manager/server-deploy/get-licensed-apps/" in p:
            ids = [x for x in os.environ.get("SIM_LICENSED", "").split(",") if x]
            return self._send(200, {"ids": ids})
        if "/vault/manager/server-deploy/minio-gateway-config/" in p:
            return self._send(200, {"AccessKey": "sim-access", "SecretKey": "sim-secret"})
        if "/vault/manager/server-deploy/onpremise-auth-config/" in p:
            return self._send(200, {"ClientId": "sim-onpremise", "ClientSecret": "sim-onpremise-secret"})
        if "/vault/manager/server-deploy/" in p:
            return self._send(200, {"ok": True})
        if p.endswith("/oauth/connect/token"):
            return self._send(200, {"access_token": "sim-token", "expires_in": 3600})
        if "/oauth/" in p:
            return self._send(200, {"keys": []})
        if p.endswith("/TenantManagement/environments"):
            return self._send(200, {"items": []})
        return self._send(200, {})
    do_GET = do_PUT = do_POST = do_DELETE = _route

def serve(port, tls):
    srv = ThreadingHTTPServer(("0.0.0.0", port), H)
    if tls:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(os.environ["SIM_CERT"], os.environ["SIM_KEY"])
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    srv.serve_forever()

if __name__ == "__main__":
    threading.Thread(target=serve, args=(8080, False), daemon=True).start()
    if os.environ.get("SIM_CERT"):
        threading.Thread(target=serve, args=(443, True), daemon=True).start()
    while True:
        time.sleep(3600)
