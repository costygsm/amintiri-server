import hashlib
import hmac

import pytest
from starlette.testclient import TestClient

from poze import lan
from poze.app import create_app
from tests.test_library import headers


def test_lan_info_and_proof(client, env, monkeypatch):
    monkeypatch.setenv("POZE_LAN_URL", "http://192.168.0.127:8090")
    info = client.get("/api/lan", headers=headers(env)).json()
    assert info["url"] == "http://192.168.0.127:8090" and len(info["key"]) == 64
    nonce = "a" * 32
    proof = client.get("/api/lan/proof", params={"user": "ana", "nonce": nonce}).json()["proof"]
    assert proof == hmac.new(bytes.fromhex(info["key"]), nonce.encode(), hashlib.sha256).hexdigest()
    # alt utilizator, altă cheie; cheia rămâne aceeași la cereri repetate
    assert client.get("/api/lan", headers=headers(env, "bogdan")).json()["key"] != info["key"]
    assert client.get("/api/lan", headers=headers(env)).json()["key"] == info["key"]


def test_lan_info_needs_token(client):
    assert client.get("/api/lan").status_code == 401


def test_proof_rejects_short_nonce(client):
    assert client.get("/api/lan/proof", params={"user": "ana", "nonce": "scurt"}).status_code == 422


def test_no_lan_url_when_only_local(monkeypatch):
    monkeypatch.delenv("POZE_LAN_URL", raising=False)
    monkeypatch.setenv("POZE_HOST", "127.0.0.1")
    assert lan.lan_url() is None


@pytest.mark.parametrize("server, peer, path, ok", [
    (("127.0.0.1", 8090), "8.8.8.8", "/api/health", True),   # prin proxy-ul DSM
    (("192.168.0.127", 8090), "192.168.0.50", "/api/health", True),  # telefonul de acasă
    (("192.168.0.127", 8090), "8.8.8.8", "/api/health", False),  # de pe internet, direct
    (("192.168.0.127", 8090), "192.168.0.50", "/", True),  # pagina web acasă, ca la Emby: http://NAS:port
    (("192.168.0.127", 8090), "8.8.8.8", "/", False),
])
def test_only_lan_peers_on_direct_address(env, server, peer, path, ok):
    app = create_app(start_indexer=False)

    async def with_server(scope, receive, send):
        scope["server"] = server  # adresa pe care a venit conexiunea
        await app(scope, receive, send)

    r = TestClient(with_server, client=(peer, 1234)).get(path)
    assert (r.status_code == 200) == ok
