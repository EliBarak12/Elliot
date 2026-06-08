"""Real-world connector-build scenarios for the launch-gateway E2E harness.

Each scenario is one "user/agent" building a connector against a REAL public
API (no auth required, reachable from CI). The set is deliberately chosen to
exercise the response shapes that the clean in-repo mock APIs never produce:

* pagination envelopes ({count,next,results:[...]})  — pokeapi
* dynamic-key objects ({"EUR": {...}, "USD": {...}}) — restcountries currencies
* deep nesting + arrays-of-objects                   — pokeapi, restcountries
* large flat arrays (5000 rows)                       — jsonplaceholder /photos
* booleans / null fields / unicode                    — todos, restcountries

Table-name convention (must match the flattener): a source named ``foo``
loads into table ``foo``; a nested array key ``bar`` under it becomes the
child table ``foo_bar``. Scenario ids are kept lowercase+underscore so the
discover ``name`` sanitizes to itself and the SQL below can reference it
verbatim.
"""

from __future__ import annotations

from dataclasses import dataclass, field

JP = "https://jsonplaceholder.typicode.com"
RC = "https://restcountries.com/v3.1"
POKE = "https://pokeapi.co/api/v2"


@dataclass
class SourceDef:
    name: str  # also the SQLite table prefix
    source_type: str
    config: dict
    min_rows: int = 1
    expect_columns: tuple[str, ...] = ()


@dataclass
class ToolDef:
    name: str
    description: str
    category: str
    sql: str
    parameters: list = field(default_factory=list)
    preview_params: dict = field(default_factory=dict)
    expect_nonempty: bool = True


@dataclass
class Scenario:
    id: str
    title: str
    sources: list[SourceDef]
    tools: list[ToolDef]
    deploy: bool = False  # start the runtime + hit /v1/health for this one


def _jp_resource(idx: int, resource: str, min_rows: int, cols: tuple[str, ...]) -> Scenario:
    """A simple single-table jsonplaceholder build (the bread-and-butter case)."""
    name = f"s{idx:03d}_{resource}"
    return Scenario(
        id=name,
        title=f"jsonplaceholder /{resource} — list + count",
        sources=[
            SourceDef(
                name, "rest", {"url": f"{JP}/{resource}"}, min_rows=min_rows, expect_columns=cols
            )
        ],
        tools=[
            ToolDef(
                name=f"{name}_recent",
                description=f"List the first :limit rows from {resource}, newest id first.",
                category="READ",
                sql=f'SELECT * FROM "{name}" ORDER BY id DESC LIMIT :limit',
                parameters=[
                    {
                        "name": "limit",
                        "type": "integer",
                        "required": False,
                        "description": "max rows",
                        "default": 5,
                    }
                ],
                preview_params={"limit": 3},
            ),
            ToolDef(
                name=f"{name}_count",
                description=f"Return the total number of {resource}.",
                category="READ",
                sql=f'SELECT COUNT(*) AS total FROM "{name}"',
                preview_params={},
            ),
        ],
    )


def build_scenarios() -> list[Scenario]:
    s: list[Scenario] = []

    # ── jsonplaceholder: the common, well-behaved REST case ──────────────────
    # NOTE: expected columns use Elliot's normalized (lowercased) names — see
    # OBS-1 in LAUNCH_TEST_FINDINGS.md. API field `userId` -> column `userid`.
    s.append(_jp_resource(1, "posts", 100, ("id", "title", "body", "userid")))
    s.append(_jp_resource(2, "comments", 500, ("id", "postid", "email", "body")))
    s.append(_jp_resource(3, "todos", 200, ("id", "title", "completed", "userid")))
    s.append(_jp_resource(4, "albums", 100, ("id", "title", "userid")))

    # /users — nested address{geo{}}, company{} → flattener must explode.
    s.append(
        Scenario(
            id="s005_users",
            title="jsonplaceholder /users — nested address + company flattening",
            sources=[
                SourceDef(
                    "s005_users",
                    "rest",
                    {"url": f"{JP}/users"},
                    min_rows=10,
                    expect_columns=(
                        "id",
                        "name",
                        "email",
                        "address_city",
                        "address_geo_lat",
                        "company_name",
                    ),
                )
            ],
            tools=[
                ToolDef(
                    "s005_users_by_city",
                    description="Find users whose city matches :city (exact).",
                    category="READ",
                    sql="SELECT id, name, email, address_city, company_name "
                    'FROM "s005_users" WHERE address_city = :city',
                    parameters=[
                        {
                            "name": "city",
                            "type": "string",
                            "required": True,
                            "description": "address city",
                        }
                    ],
                    preview_params={"city": "Gwenborough"},
                ),
                ToolDef(
                    "s005_users_domains",
                    description="Count users grouped by email domain.",
                    category="READ",
                    sql="SELECT substr(email, instr(email,'@')+1) AS domain, COUNT(*) AS n "
                    'FROM "s005_users" GROUP BY domain ORDER BY n DESC',
                    preview_params={},
                ),
            ],
            deploy=True,  # representative full deploy
        )
    )

    # /photos — large array (5000 rows) → stress the loader + row caps.
    s.append(
        Scenario(
            id="s006_photos",
            title="jsonplaceholder /photos — 5000-row load + aggregate",
            sources=[
                SourceDef(
                    "s006_photos",
                    "rest",
                    {"url": f"{JP}/photos"},
                    min_rows=5000,
                    expect_columns=("id", "albumid", "title", "url"),
                )
            ],
            tools=[
                ToolDef(
                    "s006_photos_per_album",
                    description="Count photos per album, busiest first.",
                    category="READ",
                    sql='SELECT albumId, COUNT(*) AS n FROM "s006_photos" '
                    "GROUP BY albumId ORDER BY n DESC LIMIT :limit",
                    parameters=[
                        {
                            "name": "limit",
                            "type": "integer",
                            "required": False,
                            "description": "albums",
                            "default": 10,
                        }
                    ],
                    preview_params={"limit": 5},
                ),
            ],
        )
    )

    # ── restcountries: deep nesting + dynamic-key objects (the hard case) ─────
    # currencies/languages are objects keyed by code (EUR/USD/eng), not arrays.
    s.append(
        Scenario(
            id="s007_country_fr",
            title="restcountries /name/france — deep nesting + dynamic-key currencies",
            sources=[
                SourceDef(
                    "s007_country_fr",
                    "rest",
                    {"url": f"{RC}/name/france"},
                    min_rows=1,
                    expect_columns=("name_common", "region"),
                )
            ],
            tools=[
                ToolDef(
                    "s007_fr_summary",
                    description="Return France's common name, region and population.",
                    category="READ",
                    sql='SELECT name_common, region, subregion, population FROM "s007_country_fr"',
                    preview_params={},
                ),
            ],
        )
    )
    s.append(
        Scenario(
            id="s008_region_eu",
            title="restcountries /region/europe — ~50 nested countries",
            sources=[
                SourceDef(
                    "s008_region_eu",
                    "rest",
                    {"url": f"{RC}/region/europe"},
                    min_rows=40,
                    expect_columns=("name_common", "population", "region"),
                )
            ],
            tools=[
                ToolDef(
                    "s008_eu_most_populous",
                    description="Top :limit European countries by population.",
                    category="READ",
                    sql='SELECT name_common, population FROM "s008_region_eu" '
                    "ORDER BY population DESC LIMIT :limit",
                    parameters=[
                        {
                            "name": "limit",
                            "type": "integer",
                            "required": False,
                            "description": "n",
                            "default": 10,
                        }
                    ],
                    preview_params={"limit": 5},
                ),
                ToolDef(
                    "s008_eu_by_subregion",
                    description="Count European countries per subregion.",
                    category="READ",
                    sql='SELECT subregion, COUNT(*) AS n FROM "s008_region_eu" '
                    "GROUP BY subregion ORDER BY n DESC",
                    preview_params={},
                ),
            ],
        )
    )

    # ── pokeapi: pagination envelope (needs data_path=results) ────────────────
    s.append(
        Scenario(
            id="s009_pokemon_list",
            title="pokeapi /pokemon?limit=100 — envelope unwrap via data_path=results",
            sources=[
                SourceDef(
                    "s009_pokemon_list",
                    "rest",
                    {"url": f"{POKE}/pokemon?limit=100", "data_path": "results"},
                    min_rows=100,
                    expect_columns=("name", "url"),
                )
            ],
            tools=[
                ToolDef(
                    "s009_pokemon_find",
                    description="Find a pokemon row by exact :name.",
                    category="READ",
                    sql='SELECT name, url FROM "s009_pokemon_list" WHERE name = :name',
                    parameters=[
                        {
                            "name": "name",
                            "type": "string",
                            "required": True,
                            "description": "pokemon name",
                        }
                    ],
                    preview_params={"name": "pikachu"},
                ),
            ],
        )
    )
    # pokeapi single object with deep arrays-of-objects (abilities/stats/types).
    s.append(
        Scenario(
            id="s010_ditto",
            title="pokeapi /pokemon/ditto — single deep object + nested stat arrays",
            sources=[
                SourceDef(
                    "s010_ditto",
                    "rest",
                    {"url": f"{POKE}/pokemon/ditto"},
                    min_rows=1,
                    expect_columns=("name", "id"),
                )
            ],
            tools=[
                ToolDef(
                    "s010_ditto_base",
                    description="Return ditto's id, name, height and weight.",
                    category="READ",
                    sql='SELECT id, name, height, weight FROM "s010_ditto"',
                    preview_params={},
                ),
            ],
        )
    )

    return s


SCENARIOS = build_scenarios()
