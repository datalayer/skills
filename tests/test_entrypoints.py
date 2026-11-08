# Copyright (c) 2025-2026 Datalayer, Inc.
#
# BSD 3-Clause License

"""The skills are found through the agent_skills.skills entry points, by agent-skills itself."""

from __future__ import annotations

import importlib.metadata
from pathlib import Path

from agent_skills import AgentSkill, discover_entrypoint_skills

MEMORY_SKILLS = {
    "datalayer-memory-add": ("datalayer_skills.skills.memory_add", ["add"]),
    "datalayer-memory-search": ("datalayer_skills.skills.memory_search", ["search"]),
    "datalayer-memory-list": ("datalayer_skills.skills.memory_list", ["list_memories"]),
    "datalayer-memory-delete": ("datalayer_skills.skills.memory_delete", ["delete", "delete_all"]),
}


def _ours() -> dict[str, str]:
    return {
        ep.name: ep.value
        for ep in importlib.metadata.entry_points(group="agent_skills.skills")
        if ep.value.startswith("datalayer_skills.")
    }


def test_the_package_declares_each_skill_under_its_name() -> None:
    declared = _ours()
    assert declared["datalayer-whoami"] == "datalayer_skills.skills.whoami"
    for name, (module, _) in MEMORY_SKILLS.items():
        assert declared[name] == module


def test_agent_skills_discovers_them_with_their_scripts() -> None:
    discovered = {skill.name: skill for skill in discover_entrypoint_skills()}
    for name, (_, scripts) in MEMORY_SKILLS.items():
        skill = discovered[name]
        assert sorted(script.name for script in skill.scripts) == sorted(scripts)
        assert all(script.path and Path(script.path).is_file() for script in skill.scripts)
        # No environment variable is required: the runtime is on the loopback.
        assert skill.get_required_env_vars() == []
        assert "memory" in skill.tags


def test_each_entry_point_names_the_skill_its_skill_md_declares() -> None:
    # The runtime selects an entry-point skill by its SKILL.md name, the
    # name an agentspec lists: the two must be the same.
    for name, value in _ours().items():
        assert AgentSkill.from_module(value).name == name


def test_the_runtime_api_block_is_the_same_in_every_script() -> None:
    root = Path(__file__).resolve().parents[1] / "datalayer_skills" / "skills"
    start, end = "# ---- The runtime's memory API", "# ---- End of the runtime's memory API ----"
    blocks = {}
    for script in root.glob("memory_*/scripts/*.py"):
        text = script.read_text()
        blocks[script.name] = text[text.index(start) : text.index(end)]
    assert len(blocks) == 5
    assert len(set(blocks.values())) == 1
