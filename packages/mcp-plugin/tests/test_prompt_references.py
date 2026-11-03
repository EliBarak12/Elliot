"""Prompts must only send an agent to tools the server actually serves.

The onboarding prompt's "first move" once named a tool that did not exist,
and others pointed at local-only or Studio-only tools. This checks every
skill, rendered for the local server, against what an agent sees in
tools/list.
"""

from __future__ import annotations

from pathlib import Path

from elliot_mcp_plugin.prompts import (
    load_skills,
    referenced_tools,
    register_prompts,
    render_skill_body,
)
from elliot_mcp_plugin.server import _DESTRUCTIVE_TOOL_NAMES, create_elliot_server
from elliot_mcp_plugin.session import ElliotSession


def test_local_prompts_only_name_tools_an_agent_can_call(tmp_path: Path) -> None:
    mcp = create_elliot_server(ElliotSession(cwd=str(tmp_path)))
    served = {t.name for t in mcp._tool_manager.list_tools()} - set(_DESTRUCTIVE_TOOL_NAMES)
    skills = load_skills()
    assert skills, "no skills found"
    for skill in skills:
        body = render_skill_body(skill.body, hosted=False)
        # elliot_cloud_* tools are the hosted builder's; the plugin's skills
        # mention them for agents connected to Elliot Cloud.
        missing = sorted(
            t for t in referenced_tools(body) - served if not t.startswith("elliot_cloud_")
        )
        assert not missing, f"{skill.name} names tools agents cannot call: {missing}"


def test_markers_select_the_deployment_text() -> None:
    body = (
        "Start.\n"
        "<!-- local-only -->\nRun `elliot_start_runtime`.\n<!-- /local-only -->\n"
        "<!-- hosted-only\nCall `elliot_cloud_publish`.\n-->\n"
        "Inline<!-- local-only --> (local bit)<!-- /local-only -->. Use `elliot_upload_file`."
    )
    local = render_skill_body(body)
    assert "elliot_start_runtime" in local and "elliot_cloud_publish" not in local
    assert "(local bit)" in local and "<!--" not in local
    hosted = render_skill_body(
        body, hosted=True, substitutions={"elliot_upload_file": "elliot_request_file_upload"}
    )
    assert "elliot_start_runtime" not in hosted and "Call `elliot_cloud_publish`." in hosted
    assert "(local bit)" not in hosted and "elliot_request_file_upload" in hosted
    assert "<!--" not in hosted


def test_register_prompts_honours_overrides_and_exclusions(tmp_path: Path) -> None:
    from elliot_core.mcp_compat import FastMCP

    mcp = FastMCP("t")
    names = {s.name.replace("-", "_") for s in load_skills()}
    count = register_prompts(
        mcp,
        hosted=True,
        overrides={"getting_started": "Short hosted guide."},
        exclude=("observe_agent_runs",),
    )
    served = {p.name for p in mcp._prompt_manager.list_prompts()}
    assert count == len(names) - 1
    assert "observe_agent_runs" not in served and "getting_started" in served
