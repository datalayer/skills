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

LIBRARY_SKILL = {
    "datalayer-library-publish": (
        "datalayer_skills.skills.library_publish",
        ["publish_item"],
    )
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
    for name, (module, _) in LIBRARY_SKILL.items():
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
    for name, (_, scripts) in LIBRARY_SKILL.items():
        skill = discovered[name]
        assert [script.name for script in skill.scripts] == scripts
        assert skill.get_required_env_vars() == []


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


def test_every_skill_says_what_it_does_and_when_to_use_it() -> None:
    """A page lists a skill by what its SKILL.md says where no catalogue names it, and a model
    chooses it by the same sentence: each of the nineteen says what it does, in a sentence or
    two, and when to use it, with a version, tags and an author."""
    discovered = {skill.name: skill for skill in discover_entrypoint_skills()}
    ours = _ours()
    assert len(ours) == 19
    for name in ours:
        skill = discovered[name]
        description = skill.description.strip()
        assert 60 <= len(description) <= 420, name
        assert description.endswith("."), name
        assert skill.tags, name
        front_matter = (
            (Path(__file__).resolve().parents[1].joinpath(*ours[name].split("."), "SKILL.md"))
            .read_text()
            .split("---")[1]
        )
        assert f"\nname: {name}\n" in front_matter, name
        assert "\nversion: " in front_matter, name
        assert "\nauthor: Datalayer" in front_matter, name
