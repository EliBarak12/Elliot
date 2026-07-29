"""Onboarding tools — capture product intent and import an API collection.

These power the `onboard_product` workflow: instead of letting an agent see a
data source and guess at tools, the agent first imports the user's existing API
description and interviews them about how agents should use the product.
"""

from __future__ import annotations

import json

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
    def elliot_import_api_collection(collection: str) -> dict:  # type: ignore[type-arg]
        """Import the user's API description into a proposed connector.

        Accepts an OpenAPI 3.x spec or a Postman Collection — pass a URL, or
        the raw JSON. Returns proposed tools (with token-risk hints) for the
        agent to review with the user before building. For freeform docs that
        are neither format, normalise them into one of the two first.
        """
        try:
            collection = collection.strip()
            data: dict | None = None  # type: ignore[type-arg]
            if collection.startswith("{"):
                data = json.loads(collection)

            from elliot_core.openapi_analyzer import analyze_spec
            from elliot_core.postman_analyzer import analyze_postman, is_postman_collection

            if data is not None and is_postman_collection(data):
                proposed = analyze_postman(data)
                fmt = "postman"
            elif data is not None and "openapi" in data:
                proposed = analyze_spec(data)
                fmt = "openapi"
            elif data is not None:
                raise ElliotError(
                    "UNRECOGNISED_COLLECTION",
                    "JSON is neither an OpenAPI 3.x spec ('openapi' key) nor a "
                    "Postman Collection ('item' array). Convert it to one first.",
                )
            else:
                # A bare URL — assume an OpenAPI spec endpoint.
                proposed = analyze_spec(collection)
                fmt = "openapi"

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
                "next": (
                    "Review the proposed tools with the user, drop what agents "
                    "don't need, then create a draft."
                ),
            }
        except ElliotError as exc:
            return to_mcp_error_content(exc)
        except Exception as exc:
            log.error("onboarding.collection.failed", error=str(exc), exc_info=True)
            return to_mcp_error_content(ElliotError("IMPORT_FAILED", str(exc)))
