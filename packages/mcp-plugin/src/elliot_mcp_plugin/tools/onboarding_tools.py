"""Onboarding tools — capture product intent and import an API collection.

These power the `onboard_product` workflow: instead of letting an agent see a
data source and guess at tools, the agent first imports the user's existing API
description and interviews them about how agents should use the product.
"""

from __future__ import annotations

import json
import re

import structlog

from elliot_core.audit.models import ProductIntent
from elliot_core.errors import ElliotError, to_mcp_error_content
from elliot_core.mcp_compat import FastMCP
from elliot_mcp_plugin.session import ElliotSession

log = structlog.get_logger(__name__)


def register_onboarding_tools(mcp: FastMCP, session: ElliotSession) -> None:
    @mcp.tool()
    def elliot_record_product_intent(
        agent_consumers: list[str] | None = None,
        jobs_to_be_done: list[str] | None = None,
        exposed_operations: list[str] | None = None,
        destructive_operations: list[str] | None = None,
        sensitive_fields: list[str] | None = None,
        scale_notes: str = "",
        notes: str = "",
    ) -> dict:  # type: ignore[type-arg]
        """Record what the user wants from their agentic product.

        Call this after interviewing the user — before designing tools. The
        answers drive tool design, the linter's sensitive-field check, and the
        seeds used by the connector audit.

        - agent_consumers: who the agents are (e.g. "support bot").
        - jobs_to_be_done: concrete tasks agents must accomplish.
        - exposed_operations / destructive_operations: what to expose, and
          which operations mutate or are irreversible.
        - sensitive_fields: field names that must never reach an agent.
        """
        try:
            intent = ProductIntent(
                agent_consumers=agent_consumers or [],
                jobs_to_be_done=jobs_to_be_done or [],
                exposed_operations=exposed_operations or [],
                destructive_operations=destructive_operations or [],
                sensitive_fields=sensitive_fields or [],
                scale_notes=scale_notes,
                notes=notes,
            )
            session.product_intent = intent
            session.save()
            log.info(
                "onboarding.intent.recorded",
                jobs=len(intent.jobs_to_be_done),
                sensitive=len(intent.sensitive_fields),
            )
            return {
                "status": "recorded",
                "jobs_to_be_done": len(intent.jobs_to_be_done),
                "sensitive_fields": len(intent.sensitive_fields),
                "next": (
                    "Design one tool per job-to-be-done, then build, scan, and audit the connector."
                ),
            }
        except Exception as exc:
            log.error("onboarding.intent.failed", error=str(exc), exc_info=True)
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    def elliot_get_product_intent() -> dict:  # type: ignore[type-arg]
        """Return the product intent captured during onboarding, if any."""
        if session.product_intent is None:
            return {
                "recorded": False,
                "note": "No product intent yet — call elliot_record_product_intent.",
            }
        return {"recorded": True, "intent": session.product_intent.model_dump()}

    @mcp.tool()
    def elliot_getting_started() -> dict:  # type: ignore[type-arg]
        """Return Elliot's getting-started guide: principles, workflow, recovery.

        The same content as the ``getting_started`` MCP prompt, exposed as a
        tool for clients that cannot fetch prompts programmatically. Call it
        once at the start of a session before building.
        """
        try:
            from elliot_mcp_plugin.prompts import load_skills

            for skill in load_skills():
                if "getting" in skill.name.lower().replace("-", "_"):
                    return {"guide": skill.body, "source": skill.name}
            return {
                "error": (
                    "getting-started guide not found in the skills directory — "
                    "set ELLIOT_SKILLS_DIR or reinstall the plugin package."
                )
            }
        except Exception as exc:
            log.error("onboarding.getting_started.failed", error=str(exc), exc_info=True)
            return to_mcp_error_content(ElliotError("INTERNAL_ERROR", str(exc)))

    @mcp.tool()
    def elliot_import_api_collection(collection: str) -> dict:  # type: ignore[type-arg]
        """Import the user's API description into a proposed connector.

        Accepts an OpenAPI 3.x spec, a Swagger 2.0 spec (auto-converted), or a
        Postman Collection — pass a URL, raw JSON, or pasted YAML. Returns
        proposed tools (with token-risk hints) plus a ready ``auth`` block for
        the agent to review with the user before building. For freeform docs
        that are none of these formats, normalise them into one first.
        """
        try:
            collection = collection.strip()

            from elliot_core.openapi_analyzer import analyze_spec, parse_spec_text
            from elliot_core.postman_analyzer import analyze_postman, is_postman_collection

            if collection.startswith(("http://", "https://")):
                # A URL — analyze_spec fetches it and resolves relative server
                # URLs against it, so the proposed base_url comes out absolute.
                proposed = analyze_spec(collection)
                fmt = "openapi"
            else:
                data: dict | None = None  # type: ignore[type-arg]
                if collection.startswith("{"):
                    data = json.loads(collection)
                else:
                    # Pasted YAML (or JSON without a leading brace).
                    try:
                        data = parse_spec_text(collection)
                    except Exception as exc:
                        raise ElliotError(
                            "UNRECOGNISED_COLLECTION",
                            "Could not parse the pasted text as JSON or YAML. Pass a "
                            "URL, an OpenAPI/Swagger spec, or a Postman Collection.",
                        ) from exc
                if is_postman_collection(data):
                    proposed = analyze_postman(data)
                    fmt = "postman"
                elif "openapi" in data or "swagger" in data:
                    proposed = analyze_spec(data)
                    fmt = "openapi"
                else:
                    raise ElliotError(
                        "UNRECOGNISED_COLLECTION",
                        "The document is neither an OpenAPI 3.x / Swagger 2.0 spec "
                        "('openapi'/'swagger' key) nor a Postman Collection ('item' "
                        "array). Convert it to one first.",
                    )

            next_steps = (
                "Review the proposed tools with the user, drop what agents "
                "don't need, then create a draft."
            )
            first_source = proposed.sources[0] if proposed.sources else None
            proposed_auth = getattr(first_source, "auth", None)
            if proposed_auth:
                placeholders = ", ".join(
                    sorted(
                        set(
                            re.findall(r"\{\{\s*env:([A-Z0-9_]+)\s*\}\}", json.dumps(proposed_auth))
                        )
                    )
                )
                next_steps += (
                    f" Auth detected ({proposed_auth.get('type')}): pass sources[0].auth as "
                    "the auth block to elliot_discover_source"
                    + (f" after creating secret(s): {placeholders}." if placeholders else ".")
                )

            log.info(
                "onboarding.collection.imported",
                format=fmt,
                slug=proposed.slug,
                tools=len(proposed.tools),
            )
            return {
                "status": "imported",
                "format": fmt,
                "proposed": proposed.model_dump(),
                "next": next_steps,
            }
        except ElliotError as exc:
            return to_mcp_error_content(exc)
        except Exception as exc:
            log.error("onboarding.collection.failed", error=str(exc), exc_info=True)
            return to_mcp_error_content(ElliotError("IMPORT_FAILED", str(exc)))
