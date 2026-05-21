"""A self-contained mock of a 'Gmail-like' product for the per-user auth demo.

One app plays two roles:
  * OAuth 2.1 Authorization Server  — /authorize, /authorize/decide, /token
  * Protected resource API          — GET /messages (requires Bearer token)

Each end user authorizes their own mailbox account; the access token maps to
that account, so /messages returns only that account's mail. This proves the
tools run in the *connecting user's* scope.

Run standalone:  uv run python examples/per-user-auth/mock_provider.py
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from typing import Any
from urllib.parse import urlencode

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

CLIENT_ID = "mailbox-client"
CLIENT_SECRET = "mailbox-secret"

# Per-account mailboxes — the whole point: different users see different mail.
MAILBOXES: dict[str, list[dict[str, Any]]] = {
    "alice@mailbox.test": [
        {
            "id": "a1",
            "sender": "billing@stripe.com",
            "subject": "Your June invoice",
            "unread": True,
        },
        {
            "id": "a2",
            "sender": "team@figma.com",
            "subject": "Alice, your design was approved",
            "unread": False,
        },
        {"id": "a3", "sender": "ci@github.com", "subject": "Build passed on main", "unread": True},
    ],
    "bob@mailbox.test": [
        {
            "id": "b1",
            "sender": "hr@acme.test",
            "subject": "Bob — sign your offer letter",
            "unread": True,
        },
        {
            "id": "b2",
            "sender": "calendar@google.com",
            "subject": "1:1 with manager at 3pm",
            "unread": False,
        },
    ],
}

# In-memory OAuth state.
_codes: dict[str, dict[str, str]] = {}  # code -> {challenge, redirect_uri, account}
_access_tokens: dict[str, str] = {}  # access_token -> account
_refresh_tokens: dict[str, str] = {}  # refresh_token -> account


def _verify_pkce(verifier: str, challenge: str) -> bool:
    digest = hashlib.sha256(verifier.encode()).digest()
    expected = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return secrets.compare_digest(expected, challenge)


def create_provider() -> FastAPI:
    app = FastAPI(redirect_slashes=False)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/authorize")
    async def authorize(request: Request) -> HTMLResponse:
        q = request.query_params
        scope = q.get("scope", "")
        body = f"""
        <p><b>MailBox Demo</b> (an Elliot connector) wants to access your mailbox.</p>
        <p>Requested scope: <code>{scope or "mail.read"}</code></p>
        <form method="post" action="/authorize/decide">
          <input type="hidden" name="redirect_uri" value="{q.get("redirect_uri", "")}">
          <input type="hidden" name="state" value="{q.get("state", "")}">
          <input type="hidden" name="code_challenge" value="{q.get("code_challenge", "")}">
          <label>Sign in as</label>
          <input name="account" value="alice@mailbox.test" data-testid="account">
          <button class="btn" type="submit" data-testid="authorize">Authorize</button>
        </form>
        """
        return HTMLResponse(_page("Sign in — MailBox", body))

    @app.post("/authorize/decide")
    async def decide(
        redirect_uri: str = Form(...),
        state: str = Form(""),
        code_challenge: str = Form(""),
        account: str = Form(...),
    ) -> RedirectResponse:
        code = secrets.token_urlsafe(16)
        _codes[code] = {
            "challenge": code_challenge,
            "redirect_uri": redirect_uri,
            "account": account,
        }
        sep = "&" if "?" in redirect_uri else "?"
        return RedirectResponse(
            f"{redirect_uri}{sep}{urlencode({'code': code, 'state': state})}", status_code=302
        )

    @app.post("/token")
    async def token(request: Request) -> JSONResponse:
        form = await request.form()
        grant = form.get("grant_type")
        if form.get("client_id") != CLIENT_ID or form.get("client_secret") != CLIENT_SECRET:
            return JSONResponse({"error": "invalid_client"}, status_code=401)

        if grant == "authorization_code":
            code = str(form.get("code", ""))
            entry = _codes.pop(code, None)
            if entry is None:
                return JSONResponse({"error": "invalid_grant"}, status_code=400)
            verifier = str(form.get("code_verifier", ""))
            if not _verify_pkce(verifier, entry["challenge"]):
                return JSONResponse({"error": "invalid_grant", "detail": "pkce"}, status_code=400)
            account = entry["account"]
        elif grant == "refresh_token":
            rt = str(form.get("refresh_token", ""))
            account = _refresh_tokens.get(rt, "")
            if not account:
                return JSONResponse({"error": "invalid_grant"}, status_code=400)
        else:
            return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)

        access = f"acc-{secrets.token_urlsafe(12)}"
        refresh = f"ref-{secrets.token_urlsafe(12)}"
        _access_tokens[access] = account
        _refresh_tokens[refresh] = account
        return JSONResponse(
            {
                "access_token": access,
                "refresh_token": refresh,
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": "mail.read",
            }
        )

    @app.get("/messages")
    async def messages(request: Request) -> JSONResponse:
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            return JSONResponse({"error": "missing_token"}, status_code=401)
        account = _access_tokens.get(auth[len("Bearer ") :])
        if not account:
            return JSONResponse({"error": "invalid_token"}, status_code=401)
        return JSONResponse({"account": account, "messages": MAILBOXES.get(account, [])})

    return app


def _page(title: str, body: str) -> str:
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{title}</title><style>body{{font-family:system-ui,sans-serif;"
        "max-width:520px;margin:60px auto;padding:0 20px;color:#1a1a2e}"
        ".btn{background:#d93025;color:#fff;padding:10px 18px;border:0;border-radius:8px;"
        "font-size:15px;cursor:pointer;margin-top:12px}label{display:block;margin-top:12px;"
        "font-size:13px;color:#555}input{width:100%;padding:10px;border:1px solid #ccc;"
        "border-radius:8px;font-size:14px;margin-top:4px}.card{background:#fff;"
        "border:1px solid #e0e0ee;border-radius:14px;padding:28px;box-shadow:0 6px 24px #0001}"
        "</style></head><body><div class='card'>"
        f"<h2 style='margin-top:0'>{title}</h2>{body}</div></body></html>"
    )


app = create_provider()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=9700, log_level="warning")
