# Copyright (c) 2025-2026 Datalayer, Inc.
#
# BSD 3-Clause License

"""The memory skills through agent-skills' own toolset, as an agent runtime runs them.

The toolset discovers them through the entry points and runs their scripts in
an eval sandbox (the script's source sent to it, as SandboxExecutor does for a
Jupyter sandbox), against the fake runtime.
"""

from __future__ import annotations

import json

import pytest
from agent_skills import AgentSkillsToolset, SandboxExecutor
from code_sandboxes import CodeSandboxClient


@pytest.fixture
def toolset():
    client = CodeSandboxClient.create(variant="eval")
    return AgentSkillsToolset(
        discover_entrypoints=True,
        executor=SandboxExecutor(client),
    )


async def _run(toolset, skill: str, script: str, **kwargs) -> dict:
    return await toolset.call_tool(
        "run_skill_script",
        {"skill_name": skill, "script_name": script, "kwargs": kwargs},
        None,
        None,
    )


async def test_the_toolset_lists_and_loads_the_memory_skills(toolset) -> None:
    listed = await toolset.call_tool("list_skills", {}, None, None)
    for name in (
        "datalayer-memory-add",
        "datalayer-memory-search",
        "datalayer-memory-list",
        "datalayer-memory-delete",
    ):
        assert name in listed
    loaded = await toolset.call_tool(
        "load_skill", {"skill_name": "datalayer-memory-delete"}, None, None
    )
    assert "delete_all" in loaded
    assert "explicit confirmation" in loaded


async def test_keep_search_list_and_forget_through_the_toolset(toolset, runtime) -> None:
    runtime.agent("default")
    kept = await _run(toolset, "datalayer-memory-add", "add", content="Prefers answers in French")
    assert kept["success"] is True, kept
    assert json.loads(kept["output"])["added"] == 1

    found = await _run(toolset, "datalayer-memory-search", "search", query="french")
    assert found["success"] is True, found
    (memory,) = json.loads(found["output"])["memories"]
    assert memory["content"] == "Prefers answers in French"

    listed = await _run(toolset, "datalayer-memory-list", "list_memories", limit=10)
    assert json.loads(listed["output"])["total"] == 1

    forgotten = await _run(toolset, "datalayer-memory-delete", "delete", id=memory["id"])
    assert json.loads(forgotten["output"])["forgotten"] == 1
    assert runtime.memories["default"] == []


async def test_forget_everything_through_the_toolset_holds_the_count(toolset, runtime) -> None:
    runtime.agent("default")
    runtime.keep("default", "one")
    runtime.keep("default", "two")
    refused = await _run(toolset, "datalayer-memory-delete", "delete_all", count=1)
    assert refused["success"] is False
    assert len(runtime.memories["default"]) == 2
    done = await _run(toolset, "datalayer-memory-delete", "delete_all", count=2)
    assert done["success"] is True, done
    assert json.loads(done["output"])["forgotten"] == 2
