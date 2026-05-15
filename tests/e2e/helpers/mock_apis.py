"""Local mock REST APIs that mirror the *shape* of real public services.

Each mock returns nested JSON in the same structure as a well-known public
endpoint, so Elliot's flattener / schema detector / column namer exercise
their real code paths against realistic-looking data. The point is to make
the e2e test reproducible without depending on outbound network — when the
suite is run on an unrestricted machine you can flip the URL base via env
to point at the actual public hosts (their schemas match by design).

Endpoints (all served from a single FastAPI app, dispatched by path prefix):

* ``/users``                — jsonplaceholder-shape: nested ``address.geo`` +
                              ``company``. Adds ``plan`` and ``mrr`` so we
                              can build enterprise/plan-tier business tools.
* ``/products``             — dummyjson-shape: nested ``dimensions`` +
                              ``meta`` + arrays (``tags``, ``images``,
                              ``reviews``).
* ``/orders``               — stripe/commercejs-shape: nested ``customer``,
                              ``billing_address``, arrays of ``line_items``.
* ``/reviews``              — flat per-product reviews keyed by ``product_id``
                              with nested ``reviewer`` and ``response``.

The dataset is the same across runs — no randomness — so eval assertions
are deterministic.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException

# ── Seed data ────────────────────────────────────────────────────────────────

USERS: list[dict[str, Any]] = [
    {
        "id": 1,
        "name": "Alice Chen",
        "email": "alice@acme.example.com",
        "plan": "enterprise",
        "mrr": 4990,
        "status": "active",
        "address": {
            "street": "1 Market St",
            "city": "San Francisco",
            "zipcode": "94105",
            "geo": {"lat": "37.7937", "lng": "-122.3965"},
        },
        "company": {"name": "Acme Corp", "industry": "saas", "size": 250},
    },
    {
        "id": 2,
        "name": "Bob Martinez",
        "email": "bob@globex.example.com",
        "plan": "pro",
        "mrr": 199,
        "status": "active",
        "address": {
            "street": "742 Evergreen Tr",
            "city": "Austin",
            "zipcode": "78701",
            "geo": {"lat": "30.2672", "lng": "-97.7431"},
        },
        "company": {"name": "Globex", "industry": "retail", "size": 80},
    },
    {
        "id": 3,
        "name": "Carol White",
        "email": "carol@initech.example.com",
        "plan": "enterprise",
        "mrr": 7990,
        "status": "active",
        "address": {
            "street": "500 Innovation Blvd",
            "city": "Seattle",
            "zipcode": "98109",
            "geo": {"lat": "47.6205", "lng": "-122.3493"},
        },
        "company": {"name": "Initech", "industry": "fintech", "size": 600},
    },
    {
        "id": 4,
        "name": "David Park",
        "email": "david@hooli.example.com",
        "plan": "starter",
        "mrr": 29,
        "status": "active",
        "address": {
            "street": "1600 Tech Way",
            "city": "Palo Alto",
            "zipcode": "94303",
            "geo": {"lat": "37.4419", "lng": "-122.1430"},
        },
        "company": {"name": "Hooli", "industry": "saas", "size": 12},
    },
    {
        "id": 5,
        "name": "Eva Müller",
        "email": "eva@umbrella.example.org",
        "plan": "enterprise",
        "mrr": 12990,
        "status": "active",
        "address": {
            "street": "Berliner Str 1",
            "city": "Berlin",
            "zipcode": "10115",
            "geo": {"lat": "52.5305", "lng": "13.3849"},
        },
        "company": {"name": "Umbrella", "industry": "healthcare", "size": 1200},
    },
    {
        "id": 6,
        "name": "Frank Liu",
        "email": "frank@pied-piper.example.com",
        "plan": "pro",
        "mrr": 199,
        "status": "churned",
        "address": {
            "street": "100 Compression Ln",
            "city": "San Jose",
            "zipcode": "95110",
            "geo": {"lat": "37.3382", "lng": "-121.8863"},
        },
        "company": {"name": "Pied Piper", "industry": "saas", "size": 6},
    },
]

PRODUCTS: list[dict[str, Any]] = [
    {
        "id": 101,
        "title": "Pro Wireless Headphones",
        "category": "audio",
        "price": 249.99,
        "stock": 42,
        "tags": ["wireless", "noise-cancelling", "audio"],
        "dimensions": {"width": 18.0, "height": 20.0, "depth": 8.0},
        "meta": {"sku": "HP-PRO-101", "warranty": "2 years"},
    },
    {
        "id": 102,
        "title": "Ergonomic Mesh Chair",
        "category": "office",
        "price": 449.0,
        "stock": 12,
        "tags": ["office", "ergonomic", "furniture"],
        "dimensions": {"width": 70.0, "height": 120.0, "depth": 70.0},
        "meta": {"sku": "CH-ERG-102", "warranty": "5 years"},
    },
    {
        "id": 103,
        "title": "Standing Desk Converter",
        "category": "office",
        "price": 299.0,
        "stock": 0,
        "tags": ["office", "ergonomic", "furniture"],
        "dimensions": {"width": 80.0, "height": 50.0, "depth": 50.0},
        "meta": {"sku": "DK-CONV-103", "warranty": "3 years"},
    },
    {
        "id": 104,
        "title": "Mechanical Keyboard 75%",
        "category": "computing",
        "price": 159.0,
        "stock": 200,
        "tags": ["keyboard", "mechanical", "computing"],
        "dimensions": {"width": 32.0, "height": 4.0, "depth": 14.0},
        "meta": {"sku": "KB-MECH-104", "warranty": "1 year"},
    },
    {
        "id": 105,
        "title": "4K Webcam Pro",
        "category": "computing",
        "price": 199.99,
        "stock": 88,
        "tags": ["webcam", "4k", "computing"],
        "dimensions": {"width": 12.0, "height": 5.0, "depth": 5.0},
        "meta": {"sku": "WC-4KP-105", "warranty": "1 year"},
    },
]

ORDERS: list[dict[str, Any]] = [
    {
        "id": 9001,
        "customer_id": 1,
        "status": "fulfilled",
        "total": 658.98,
        "created_at": "2026-04-10T09:12:00Z",
        "line_items": [
            {"product_id": 101, "quantity": 2, "unit_price": 249.99},
            {"product_id": 104, "quantity": 1, "unit_price": 159.00},
        ],
        "billing_address": {"city": "San Francisco", "zipcode": "94105"},
    },
    {
        "id": 9002,
        "customer_id": 3,
        "status": "pending",
        "total": 449.00,
        "created_at": "2026-05-01T14:30:00Z",
        "line_items": [
            {"product_id": 102, "quantity": 1, "unit_price": 449.00},
        ],
        "billing_address": {"city": "Seattle", "zipcode": "98109"},
    },
    {
        "id": 9003,
        "customer_id": 3,
        "status": "fulfilled",
        "total": 998.97,
        "created_at": "2026-03-22T11:00:00Z",
        "line_items": [
            {"product_id": 101, "quantity": 2, "unit_price": 249.99},
            {"product_id": 105, "quantity": 2, "unit_price": 199.99},
            {"product_id": 104, "quantity": 1, "unit_price": 99.99},
        ],
        "billing_address": {"city": "Seattle", "zipcode": "98109"},
    },
    {
        "id": 9004,
        "customer_id": 5,
        "status": "pending",
        "total": 1545.99,
        "created_at": "2026-05-12T08:00:00Z",
        "line_items": [
            {"product_id": 102, "quantity": 3, "unit_price": 449.00},
            {"product_id": 105, "quantity": 1, "unit_price": 198.99},
        ],
        "billing_address": {"city": "Berlin", "zipcode": "10115"},
    },
    {
        "id": 9005,
        "customer_id": 2,
        "status": "fulfilled",
        "total": 199.99,
        "created_at": "2026-05-08T16:45:00Z",
        "line_items": [
            {"product_id": 105, "quantity": 1, "unit_price": 199.99},
        ],
        "billing_address": {"city": "Austin", "zipcode": "78701"},
    },
    {
        "id": 9006,
        "customer_id": 1,
        "status": "pending",
        "total": 159.00,
        "created_at": "2026-05-13T12:15:00Z",
        "line_items": [
            {"product_id": 104, "quantity": 1, "unit_price": 159.00},
        ],
        "billing_address": {"city": "San Francisco", "zipcode": "94105"},
    },
]

REVIEWS: list[dict[str, Any]] = [
    {
        "id": 7001,
        "product_id": 101,
        "rating": 5,
        "title": "Best headphones I've owned",
        "body": "Crystal clear audio and comfortable for long sessions.",
        "created_at": "2026-04-12T10:00:00Z",
        "reviewer": {"id": 1, "name": "Alice Chen", "verified": True},
        "response": {"author": "support", "body": "Thanks Alice!", "ts": "2026-04-12T18:00:00Z"},
    },
    {
        "id": 7002,
        "product_id": 101,
        "rating": 4,
        "title": "Great, battery could be better",
        "body": "20 hours not 30 as advertised.",
        "created_at": "2026-04-15T09:00:00Z",
        "reviewer": {"id": 2, "name": "Bob Martinez", "verified": True},
        "response": None,
    },
    {
        "id": 7003,
        "product_id": 102,
        "rating": 5,
        "title": "Saved my back",
        "body": "Worth every penny.",
        "created_at": "2026-03-25T12:30:00Z",
        "reviewer": {"id": 3, "name": "Carol White", "verified": True},
        "response": None,
    },
    {
        "id": 7004,
        "product_id": 104,
        "rating": 5,
        "title": "Tactile bliss",
        "body": "The switches feel amazing.",
        "created_at": "2026-04-02T08:00:00Z",
        "reviewer": {"id": 1, "name": "Alice Chen", "verified": True},
        "response": None,
    },
    {
        "id": 7005,
        "product_id": 105,
        "rating": 3,
        "title": "Decent webcam",
        "body": "4K is good but autofocus hunts.",
        "created_at": "2026-04-20T15:00:00Z",
        "reviewer": {"id": 5, "name": "Eva Müller", "verified": True},
        "response": None,
    },
]


def build_app() -> FastAPI:
    app = FastAPI(title="Elliot E2E Mock APIs")

    @app.get("/users")
    def list_users() -> list[dict[str, Any]]:
        return USERS

    @app.get("/users/{user_id}")
    def get_user(user_id: int) -> dict[str, Any]:
        for u in USERS:
            if u["id"] == user_id:
                return u
        raise HTTPException(status_code=404, detail="user not found")

    @app.get("/products")
    def list_products() -> list[dict[str, Any]]:
        return PRODUCTS

    @app.get("/products/{product_id}")
    def get_product(product_id: int) -> dict[str, Any]:
        for p in PRODUCTS:
            if p["id"] == product_id:
                return p
        raise HTTPException(status_code=404, detail="product not found")

    @app.get("/orders")
    def list_orders() -> list[dict[str, Any]]:
        return ORDERS

    @app.get("/reviews")
    def list_reviews() -> list[dict[str, Any]]:
        return REVIEWS

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


class MockAPIServer:
    """Run the mock API in a background thread for the test lifetime."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8181) -> None:
        self.host = host
        self.port = port
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self) -> None:
        config = uvicorn.Config(
            build_app(),
            host=self.host,
            port=self.port,
            log_level="warning",
            lifespan="off",
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()

        import httpx

        for _ in range(50):
            try:
                if httpx.get(f"{self.base_url}/health", timeout=1.0).status_code == 200:
                    return
            except Exception:
                pass
            time.sleep(0.1)
        raise RuntimeError(f"mock API failed to come up on {self.base_url}")

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=5)
