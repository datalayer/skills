# Copyright (c) 2025-2026 Datalayer, Inc.
#
# BSD 3-Clause License

"""The catalogue's skills load from their modules and through the entry points, each with its
SKILL.md and its scripts."""

from __future__ import annotations

import importlib.metadata
import py_compile
import re
from pathlib import Path

import pytest
from agent_skills import AgentSkill, discover_entrypoint_skills
from agent_skills.types import Skill

SKILLS = Path(__file__).resolve().parents[1] / "datalayer_skills" / "skills"

#: Each skill's name, its module under datalayer_skills.skills, and its scripts.
CATALOGUE = {
    "accounting": ("accounting", ["reconcile", "variance", "aging", "close_summary"]),
    "crawl": (
        "crawl",
        [
            "fetch_page",
            "fetch_js_page",
            "extract_links",
            "extract_tables",
            "crawl_site",
            "check_robots",
        ],
    ),
    "events": ("events", ["event"]),
    "github": ("github", ["list_repos", "get_repo", "list_issues", "list_prs", "search_repos"]),
    "image": (
        "image",
        [
            "image_info",
            "resize_image",
            "crop_image",
            "convert_image",
            "optimize_image",
            "thumbnail_image",
            "snapshot_page",
            "snapshot_video_frame",
        ],
    ),
    "image-stock": (
        "image_stock",
        ["list_providers", "search_images", "image_attribution", "download_image"],
    ),
    "pdf": (
        "pdf",
        [
            "check_bounding_boxes",
            "check_bounding_boxes_test",
            "check_fillable_fields",
            "convert_pdf_to_images",
            "create_validation_image",
            "extract_form_field_info",
            "fill_fillable_fields",
            "fill_pdf_form_with_annotations",
        ],
    ),
    "text-summarizer": ("text_summarizer", ["summarize"]),
    "video": (
        "video",
        [
            "video_info",
            "record_page",
            "record_and_zoom",
            "save_to_space",
            "trim_video",
            "zoom_video",
            "transcode_video",
            "optimize_video",
            "video_thumbnail",
            "video_to_gif",
            "concat_videos",
        ],
    ),
    # The Traveller's (15 November 2026): instructions alone, no scripts.
    "travel-planning": ("travel_planning", []),
    "fare-and-stay-comparison": ("fare_and_stay_comparison", []),
    "dining": ("dining", []),
}

#: The skills whose SKILL.md names its scripts as `script_name: <script>`.
SCRIPT_NAMED = ("accounting", "image", "image-stock", "video")

#: The skills whose SKILL.md says they are public (`metadata.visibility: public`) and that need no
#: secret: what a company may publish to people's personal agents. `github` needs a token and
#: `events` acts as the account its runtime runs for: never public.
PUBLIC = {
    "accounting",
    "crawl",
    "image",
    "pdf",
    "text-summarizer",
    "video",
    "travel-planning",
    "fare-and-stay-comparison",
    "dining",
}


#: The skills that need no secret in the sandbox and are not public either: they act as the
#: account their runtime runs for, which the runtime holds the identity of.
ACTS_AS_ACCOUNT = {"events"}


@pytest.mark.parametrize("name", sorted(CATALOGUE))
def test_the_skill_loads_from_its_module_with_every_script(name: str) -> None:
    module, scripts = CATALOGUE[name]
    skill = AgentSkill.from_module(f"datalayer_skills.skills.{module}")
    assert skill.name == name
    assert skill.description
    scripts_dir = SKILLS / module / "scripts"
    assert sorted(path.stem for path in scripts_dir.glob("*.py")) == sorted(scripts)
    for path in scripts_dir.glob("*.py"):
        py_compile.compile(str(path), doraise=True)


def test_the_package_declares_each_skill_under_its_name() -> None:
    declared = {
        ep.name: ep.value
        for ep in importlib.metadata.entry_points(group="agent_skills.skills")
        if ep.value.startswith("datalayer_skills.")
    }
    for name, (module, _) in CATALOGUE.items():
        assert declared[name] == f"datalayer_skills.skills.{module}"


def test_agent_skills_discovers_them_with_their_scripts() -> None:
    discovered = {
        skill.name: skill
        for skill in discover_entrypoint_skills()
        if "datalayer_skills" in Path(str(skill.path)).parts
    }
    for name, (_, scripts) in CATALOGUE.items():
        assert sorted(script.name for script in discovered[name].scripts) == sorted(scripts)


@pytest.mark.parametrize("name", SCRIPT_NAMED)
def test_the_skill_md_names_every_script(name: str) -> None:
    module, scripts = CATALOGUE[name]
    text = (SKILLS / module / "SKILL.md").read_text()
    for script in scripts:
        assert f"`script_name: {script}`" in text, (name, script)


@pytest.mark.parametrize("name", sorted(CATALOGUE))
def test_a_public_skill_says_so_and_needs_no_secret(name: str) -> None:
    text = (SKILLS / CATALOGUE[name][0] / "SKILL.md").read_text()
    skill = Skill.from_skill_md(text)
    section = re.search(
        r"^## Required Environment Variables\s*$(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL
    )
    needs_a_secret = bool(section and re.search(r"`[A-Z][A-Z0-9_]+`", section.group(1)))
    # A skill that needs one key among several (its frontmatter's `env.any_of`) needs a secret too.
    declared = AgentSkill.from_module(f"datalayer_skills.skills.{CATALOGUE[name][0]}")
    needs_a_secret = needs_a_secret or bool(declared.get_any_of_env_vars())
    assert (
        bool(declared.get_required_env_vars() or declared.get_any_of_env_vars()) == needs_a_secret
    )
    assert (skill.metadata.metadata.get("visibility") == "public") == (name in PUBLIC)
    assert needs_a_secret == (name not in PUBLIC and name not in ACTS_AS_ACCOUNT), name


def test_crawl_reads_no_key() -> None:
    """The crawl skill fetches pages itself: none of its scripts reads a variable, Tavily's least of all.

    The catalogue listed ``TAVILY_API_KEY`` on it until 25 November 2026; nothing here ever read it
    (web search is the ``tavily`` MCP server's). Held so that a key is not asked for again
    without a script that reads one, and its SKILL.md saying so.
    """
    import ast

    text = (SKILLS / "crawl" / "SKILL.md").read_text()
    assert "- None required." in text
    assert "TAVILY" not in text.upper()
    declared = AgentSkill.from_module("datalayer_skills.skills.crawl")
    assert not declared.get_required_env_vars() and not declared.get_any_of_env_vars()
    for path in sorted((SKILLS / "crawl").rglob("*.py")):
        source = path.read_text()
        assert "TAVILY" not in source.upper(), path.name
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Attribute):
                assert node.attr not in ("environ", "getenv"), f"{path.name} reads the environment"
            if isinstance(node, ast.Name):
                assert node.id != "getenv", f"{path.name} reads the environment"


def test_the_text_summarizer_is_a_package_skill_too() -> None:
    from datalayer_skills.skills.text_summarizer import summarize_text

    text = "Skills are small. Skills are folders. A folder holds a SKILL.md. Cats sleep."
    assert summarize_text(text, max_sentences=1)
    assert AgentSkill.from_package(
        package="datalayer_skills.skills.text_summarizer", method="summarize_text"
    ).name
