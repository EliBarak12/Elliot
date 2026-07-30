"""Tests for the MCP OAuth authorization server (auth boundary 1)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from elliot_connector_runtime.mcp_oauth import TokenStore, verify_pkce
from elliot_connector_runtime.oauth_flow import generate_pkce
from elliot_connector_runtime.server import create_app

# A connector with no per_user source: /authorize issues a code immediately
# (no upstream chaining), which isolates the boundary-1 AS for these tests.
SHARED_CONNECTOR = {
    "name": "Pets",
    "slug": "pets",
    "version": "1.0.0",
    "sources": [
        {
            "id": "animals",
            "name": "Animals API",
            "type": "rest",
            "url": "https://api.example.com/animals",
            "data_path": "items",
        }
    ],
    "tools": [
        {
            "id": "list_animals",
            "name": "List animals",
            "description": "Return all animals",
            "category": "READ",
            "sql": "SELECT * FROM animals",
            "parameters": [],
        }
    ],
    "skills": [],
}


@pytest.fixture()
def oauth_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("ELLIOT_MCP_OAUTH", "1")
    monkeypatch.setenv("ELLIOT_VAULT_DB", ":memory:")
    cfile = tmp_path / "pets.connector.json"
    cfile.write_text(json.dumps(SHARED_CONNECTOR))
    # Enter the context so the FastMCP session manager lifespan runs.
    with TestClient(create_app(connector_path=str(cfile), secrets={})) as client:
        yield client


# ── TokenStore unit ────────────────────────────────────────────────────────────


def test_verify_pkce_roundtrip() -> None:
    verifier, challenge = generate_pkce()
    assert verify_pkce(verifier, challenge) is True
    assert verify_pkce("wrong", challenge) is False


def test_token_store_code_to_token_with_pkce() -> None:
    store = TokenStore()
    client_id = store.register_client(["https://c/cb"])
    verifier, challenge = generate_pkce()
    _, login = store.new_login(
        client_id=client_id,
        redirect_uri="https://c/cb",
        state="st",
        code_challenge=challenge,
        pending=[],
    )
    code = store.issue_code(login)
    # wrong verifier rejected
    assert (
        store.redeem_code(code, client_id=client_id, redirect_uri="https://c/cb", code_verifier="x")
        is None
    )
    # the real code was consumed on the failed attempt; re-issue and redeem
    code = store.issue_code(login)
    user_id = store.redeem_code(
        code, client_id=client_id, redirect_uri="https://c/cb", code_verifier=verifier
    )
    assert user_id == login.user_id
    access, refresh = store.mint_tokens(user_id)
    assert store.validate_access(access) == user_id
    new_access, _ = store.refresh_tokens(refresh)  # type: ignore[misc]
    assert store.validate_access(new_access) == user_id


def test_token_store_rejects_unknown_client_redirect() -> None:
    store = TokenStore()
    cid = store.register_client(["https://c/cb"])
    assert store.client_allows(cid, "https://c/cb") is True
    assert store.client_allows(cid, "https://evil/cb") is False
    assert store.client_allows("nope", "https://c/cb") is False


# ── HTTP discovery + flow ────────────────────────────────────────────────────


def test_protected_resource_metadata(oauth_client: TestClient) -> None:
    r = oauth_client.get("/.well-known/oauth-protected-resource")
    assert r.status_code == 200
    body = r.json()
    assert body["resource"].endswith("/mcp")
    assert body["authorization_servers"]


def test_authorization_server_metadata(oauth_client: TestClient) -> None:
    r = oauth_client.get("/.well-known/oauth-authorization-server")
    assert r.status_code == 200
    body = r.json()
    assert body["authorization_endpoint"].endswith("/authorize")
    assert body["token_endpoint"].endswith("/token")
    assert body["registration_endpoint"].endswith("/register")
    assert "S256" in body["code_challenge_methods_supported"]


def test_mcp_requires_bearer_and_advertises_metadata(oauth_client: TestClient) -> None:
    r = oauth_client.get("/mcp/", headers={"Accept": "text/event-stream"})
    assert r.status_code == 401
    assert "resource_metadata=" in r.headers.get("www-authenticate", "")


def test_full_authorization_code_flow(oauth_client: TestClient) -> None:
    # 1. dynamic client registration
    reg = oauth_client.post("/register", json={"redirect_uris": ["https://client.example/cb"]})
    assert reg.status_code == 201
    client_id = reg.json()["client_id"]

    # 2. authorize (no per_user sources -> immediate code redirect)
    verifier, challenge = generate_pkce()
    auth = oauth_client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": "https://client.example/cb",
            "state": "xyz",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )
    assert auth.status_code == 302
    loc = auth.headers["location"]
    q = parse_qs(urlsplit(loc).query)
    assert q["state"] == ["xyz"]
    code = q["code"][0]

    # 3. token exchange
    tok = oauth_client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "redirect_uri": "https://client.example/cb",
            "code_verifier": verifier,
        },
    )
    assert tok.status_code == 200
    access = tok.json()["access_token"]
    assert access

    # 4. /mcp now accepts the bearer (no 401 challenge). Probe with a POST
    # initialize — on the stateless transport a GET opens an unbounded SSE
    # stream that TestClient would wait on forever.
    r = oauth_client.post(
        "/mcp/",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "probe", "version": "0"},
            },
        },
        headers={
            "Authorization": f"Bearer {access}",
            "Accept": "application/json, text/event-stream",
        },
    )
    assert r.status_code != 401


def test_authorize_rejects_unregistered_client(oauth_client: TestClient) -> None:
    _, challenge = generate_pkce()
    r = oauth_client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": "never-registered",
            "redirect_uri": "https://x/cb",
            "state": "s",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_client"
