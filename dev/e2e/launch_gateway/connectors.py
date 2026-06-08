"""Ten real connectors + agent tasks for the launch-gateway AX test.

Each ``Connector`` is something a product engineer would actually build with
Elliot against a real public API. Each carries ``tasks`` — natural-language
goals a downstream agent must accomplish using ONLY the tools the connector
exposes. ``run_agents.py`` deploys each connector and turns a heuristic
"agent" loose on the tasks to measure Agent Experience (AX): can a consumer
pick the right tool from its description, fill the parameters from the schema,
call it, and get a usable answer?
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

JP = "https://jsonplaceholder.typicode.com"
RC = "https://restcountries.com/v3.1"
POKE = "https://pokeapi.co/api/v2"
DJ = "https://dummyjson.com"


@dataclass
class Src:
    name: str
    config: dict
    data_path: str | None = None
    source_type: str = "rest"

    def discover_config(self) -> dict:
        cfg = dict(self.config)
        if self.data_path:
            cfg["data_path"] = self.data_path
        return cfg


@dataclass
class Tool:
    name: str
    description: str
    sql: str
    parameters: list = field(default_factory=list)
    category: str = "READ"


@dataclass
class Task:
    goal: str  # natural-language instruction the agent receives
    inputs: dict = field(default_factory=dict)  # values the "user" handed the agent
    # check(rows) -> (ok, detail). rows is the list of result rows.
    check: Callable[[list[dict[str, Any]]], tuple[bool, str]] = lambda rows: (
        len(rows) > 0,
        f"rows={len(rows)}",
    )


@dataclass
class Connector:
    id: str
    title: str
    sources: list[Src]
    tools: list[Tool]
    tasks: list[Task]


def _nonempty(rows: list[dict]) -> tuple[bool, str]:
    return len(rows) > 0, f"rows={len(rows)}"


def _all_eq(field_name: str, value: Any) -> Callable[[list[dict]], tuple[bool, str]]:
    def check(rows: list[dict]) -> tuple[bool, str]:
        if not rows:
            return False, "no rows"
        bad = [r for r in rows if str(r.get(field_name)) != str(value)]
        return (not bad), f"rows={len(rows)} mismatched={len(bad)}"

    return check


def _count_at_least(n: int) -> Callable[[list[dict]], tuple[bool, str]]:
    return lambda rows: (len(rows) >= n, f"rows={len(rows)} (need >= {n})")


def build_connectors() -> list[Connector]:
    c: list[Connector] = []

    # C01 — blog: posts + users + comments (cross-source) ────────────────────
    c.append(
        Connector(
            id="c01",
            title="Blog ops (jsonplaceholder posts/users/comments)",
            sources=[
                Src("c01_posts", {"url": f"{JP}/posts"}),
                Src("c01_users", {"url": f"{JP}/users"}),
                Src("c01_comments", {"url": f"{JP}/comments"}),
            ],
            tools=[
                Tool(
                    "list_posts_by_author",
                    "List all blog posts written by a given author, by their user id.",
                    'SELECT id, userid, title, body FROM "c01_posts" WHERE userid = :user_id',
                    [
                        {
                            "name": "user_id",
                            "type": "integer",
                            "required": True,
                            "description": "author user id",
                        }
                    ],
                ),
                Tool(
                    "most_active_commenters",
                    "Rank commenter email addresses by how many comments each has left.",
                    'SELECT email, COUNT(*) AS comment_count FROM "c01_comments" '
                    "GROUP BY email ORDER BY comment_count DESC LIMIT :limit",
                    [
                        {
                            "name": "limit",
                            "type": "integer",
                            "required": False,
                            "description": "how many to return",
                            "default": 10,
                        }
                    ],
                ),
                Tool(
                    "user_directory",
                    "Return the directory of all users with their name and email.",
                    'SELECT id, name, email FROM "c01_users" ORDER BY id',
                ),
            ],
            tasks=[
                Task(
                    "List all posts written by author with user id 1.",
                    {"user_id": 1},
                    _all_eq("userid", 1),
                ),
                Task("Who are the most active commenters on the blog?", {}, _count_at_least(5)),
                Task("Show me the full user directory.", {}, _count_at_least(10)),
            ],
        )
    )

    # C02 — shop products (dummyjson) ────────────────────────────────────────
    c.append(
        Connector(
            id="c02",
            title="Product catalog (dummyjson /products)",
            sources=[
                Src("c02_products", {"url": f"{DJ}/products?limit=100"}, data_path="products")
            ],
            tools=[
                Tool(
                    "most_expensive_products",
                    "List the most expensive products, highest price first.",
                    'SELECT id, title, price, category FROM "c02_products" '
                    "ORDER BY price DESC LIMIT :limit",
                    [
                        {
                            "name": "limit",
                            "type": "integer",
                            "required": False,
                            "description": "how many products",
                            "default": 5,
                        }
                    ],
                ),
                Tool(
                    "products_in_category",
                    "List products that belong to a specific product category.",
                    'SELECT id, title, price, category FROM "c02_products" WHERE category = :category',
                    [
                        {
                            "name": "category",
                            "type": "string",
                            "required": True,
                            "description": "product category slug, e.g. 'smartphones'",
                        }
                    ],
                ),
            ],
            tasks=[
                Task("What are the five most expensive products?", {}, _nonempty),
                Task(
                    "List the products in the 'beauty' category.",
                    {"category": "beauty"},
                    _all_eq("category", "beauty"),
                ),
            ],
        )
    )

    # C03 — carts with nested line items (dummyjson) ─────────────────────────
    c.append(
        Connector(
            id="c03",
            title="Shopping carts (dummyjson /carts, nested products)",
            sources=[Src("c03_carts", {"url": f"{DJ}/carts"}, data_path="carts")],
            tools=[
                Tool(
                    "cart_line_items",
                    "List the line items (product, quantity, price) in a given shopping cart.",
                    "SELECT li.title, li.quantity, li.price "
                    'FROM "c03_carts" c JOIN "c03_carts_products" li ON li._parent_id = c._id '
                    "WHERE c.id = :cart_id",
                    [
                        {
                            "name": "cart_id",
                            "type": "integer",
                            "required": True,
                            "description": "cart id",
                        }
                    ],
                ),
            ],
            tasks=[
                Task("What products are in shopping cart number 1?", {"cart_id": 1}, _nonempty),
            ],
        )
    )

    # C04 — countries (restcountries) ────────────────────────────────────────
    c.append(
        Connector(
            id="c04",
            title="World countries (restcountries Europe)",
            sources=[Src("c04_countries", {"url": f"{RC}/region/europe"})],
            tools=[
                Tool(
                    "most_populous_countries",
                    "List the most populous countries, largest population first.",
                    'SELECT name_common, population FROM "c04_countries" '
                    "ORDER BY population DESC LIMIT :limit",
                    [
                        {
                            "name": "limit",
                            "type": "integer",
                            "required": False,
                            "description": "how many countries",
                            "default": 10,
                        }
                    ],
                ),
                Tool(
                    "find_country_by_name",
                    "Look up a single country by its common name.",
                    'SELECT name_common, capital, population, region FROM "c04_countries" '
                    "WHERE name_common = :name",
                    [
                        {
                            "name": "name",
                            "type": "string",
                            "required": True,
                            "description": "country common name, e.g. 'Germany'",
                        }
                    ],
                ),
            ],
            tasks=[
                Task("Which are the most populous countries in Europe?", {}, _count_at_least(5)),
                Task(
                    "Look up the country named Germany.",
                    {"name": "Germany"},
                    _all_eq("name_common", "Germany"),
                ),
            ],
        )
    )

    # C05 — pokemon index (pokeapi envelope) ─────────────────────────────────
    c.append(
        Connector(
            id="c05",
            title="Pokemon index (pokeapi /pokemon)",
            sources=[Src("c05_pokemon", {"url": f"{POKE}/pokemon?limit=200"}, data_path="results")],
            tools=[
                Tool(
                    "find_pokemon_by_name",
                    "Find a pokemon entry by its exact name.",
                    'SELECT name, url FROM "c05_pokemon" WHERE name = :name',
                    [
                        {
                            "name": "name",
                            "type": "string",
                            "required": True,
                            "description": "pokemon name, e.g. 'pikachu'",
                        }
                    ],
                ),
            ],
            tasks=[
                Task(
                    "Find the pokemon named pikachu.",
                    {"name": "pikachu"},
                    _all_eq("name", "pikachu"),
                ),
            ],
        )
    )

    # C06 — crypto markets (coingecko) ───────────────────────────────────────
    c.append(
        Connector(
            id="c06",
            title="Crypto markets (coingecko)",
            sources=[
                Src(
                    "c06_coins",
                    {
                        "url": "https://api.coingecko.com/api/v3/coins/markets"
                        "?vs_currency=usd&per_page=100&page=1"
                    },
                )
            ],
            tools=[
                Tool(
                    "top_coins_by_market_cap",
                    "List the top cryptocurrencies ranked by market capitalisation.",
                    'SELECT id, symbol, current_price, market_cap FROM "c06_coins" '
                    "ORDER BY market_cap DESC LIMIT :limit",
                    [
                        {
                            "name": "limit",
                            "type": "integer",
                            "required": False,
                            "description": "how many coins",
                            "default": 10,
                        }
                    ],
                ),
                Tool(
                    "coin_price",
                    "Return the current USD price for a specific coin by its id.",
                    'SELECT id, symbol, current_price FROM "c06_coins" WHERE id = :coin_id',
                    [
                        {
                            "name": "coin_id",
                            "type": "string",
                            "required": True,
                            "description": "coingecko coin id, e.g. 'bitcoin'",
                        }
                    ],
                ),
            ],
            tasks=[
                Task("Show the top 10 cryptocurrencies by market cap.", {}, _count_at_least(5)),
                Task(
                    "What is the current price of bitcoin?",
                    {"coin_id": "bitcoin"},
                    _all_eq("id", "bitcoin"),
                ),
            ],
        )
    )

    # C07 — cat facts (catfact envelope) ─────────────────────────────────────
    c.append(
        Connector(
            id="c07",
            title="Cat facts (catfact.ninja)",
            sources=[Src("c07_facts", {"url": "https://catfact.ninja/facts"}, data_path="data")],
            tools=[
                Tool(
                    "longest_cat_facts",
                    "Return the longest cat facts, longest first.",
                    'SELECT fact, length FROM "c07_facts" ORDER BY length DESC LIMIT :limit',
                    [
                        {
                            "name": "limit",
                            "type": "integer",
                            "required": False,
                            "description": "how many facts",
                            "default": 5,
                        }
                    ],
                ),
            ],
            tasks=[
                Task("Give me the three longest cat facts.", {}, _nonempty),
            ],
        )
    )

    # C08 — todos (jsonplaceholder) ──────────────────────────────────────────
    c.append(
        Connector(
            id="c08",
            title="Task tracker (jsonplaceholder /todos)",
            sources=[Src("c08_todos", {"url": f"{JP}/todos"})],
            tools=[
                Tool(
                    "incomplete_todos_for_user",
                    "List the incomplete (not yet completed) todos for a given user id.",
                    'SELECT id, title FROM "c08_todos" WHERE userid = :user_id AND completed = 0',
                    [
                        {
                            "name": "user_id",
                            "type": "integer",
                            "required": True,
                            "description": "user id",
                        }
                    ],
                ),
                Tool(
                    "completion_summary",
                    "Summarise how many todos are completed versus still open.",
                    'SELECT completed, COUNT(*) AS n FROM "c08_todos" GROUP BY completed',
                ),
            ],
            tasks=[
                Task("Show the incomplete todos for user 1.", {"user_id": 1}, _nonempty),
                Task("Summarise completed versus open todos.", {}, _count_at_least(2)),
            ],
        )
    )

    # C09 — weather (open-meteo, single object) ──────────────────────────────
    c.append(
        Connector(
            id="c09",
            title="Weather forecast (open-meteo)",
            sources=[
                Src(
                    "c09_weather",
                    {
                        "url": "https://api.open-meteo.com/v1/forecast"
                        "?latitude=48.85&longitude=2.35&hourly=temperature_2m"
                    },
                )
            ],
            tools=[
                Tool(
                    "forecast_location",
                    "Return the latitude, longitude and timezone the forecast is for.",
                    'SELECT latitude, longitude, timezone FROM "c09_weather"',
                ),
            ],
            tasks=[
                Task("What location and timezone is this forecast for?", {}, _nonempty),
            ],
        )
    )

    # C10 — photo library (jsonplaceholder albums/photos) ────────────────────
    c.append(
        Connector(
            id="c10",
            title="Photo library (jsonplaceholder /photos)",
            sources=[Src("c10_photos", {"url": f"{JP}/photos"})],
            tools=[
                Tool(
                    "photos_in_album",
                    "List the photos that belong to a given album id.",
                    'SELECT id, albumid, title, url FROM "c10_photos" WHERE albumid = :album_id',
                    [
                        {
                            "name": "album_id",
                            "type": "integer",
                            "required": True,
                            "description": "album id",
                        }
                    ],
                ),
                Tool(
                    "photo_count_per_album",
                    "Count how many photos each album contains, busiest album first.",
                    'SELECT albumid, COUNT(*) AS n FROM "c10_photos" '
                    "GROUP BY albumid ORDER BY n DESC LIMIT :limit",
                    [
                        {
                            "name": "limit",
                            "type": "integer",
                            "required": False,
                            "description": "how many albums",
                            "default": 10,
                        }
                    ],
                ),
            ],
            tasks=[
                Task(
                    "List the photos that are in album 1.",
                    {"album_id": 1},
                    _all_eq("albumid", 1),
                ),
                Task("Which albums have the most photos?", {}, _count_at_least(5)),
            ],
        )
    )

    return c


CONNECTORS = build_connectors()
