# Copyright (c) 2025-2026 Datalayer, Inc.
#
# BSD 3-Clause License

"""The stock image skill, against canned provider answers: no network, no real key.

Each script is loaded from its file as the sandbox runs it (its own source,
nothing imported from this package) with its one way out, ``open_url``,
replaced by a fake that records the request and answers what a provider's
documentation says it answers.
"""

from __future__ import annotations

import ast
import importlib.util
import io
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
from pathlib import Path

import pytest
from agent_skills import AgentSkill, AgentSkillsToolset, SandboxExecutor
from code_sandboxes import CodeSandboxClient

SCRIPTS = (
    Path(__file__).resolve().parents[1] / "datalayer_skills" / "skills" / "image_stock" / "scripts"
)
NAMES = ("list_providers", "search_images", "image_attribution", "download_image")
KEYS = {
    "unsplash": "UNSPLASH_ACCESS_KEY",
    "pexels": "PEXELS_API_KEY",
    "pixabay": "PIXABAY_API_KEY",
    "freepik": "FREEPIK_API_KEY",
}
EVERY_VARIABLE = [
    *KEYS.values(),
    "UNSPLASH_TIER",
    "UNSPLASH_APP_NAME",
    "FREEPIK_REQUESTS_PER_MINUTE",
    "IMAGE_STOCK_DEFAULT_PROVIDER",
    "IMAGE_STOCK_DOWNLOAD_DIR",
    "IMAGE_STOCK_TIMEOUT_SECONDS",
]

UNSPLASH = {
    "total": 1,
    "results": [
        {
            "id": "u1",
            "width": 4000,
            "height": 3000,
            "description": None,
            "alt_description": "a lake   at dawn",
            "urls": {
                "full": "https://images.unsplash.com/photo-u1?ixid=abc",
                "small": "https://images.unsplash.com/photo-u1?ixid=abc&w=400",
            },
            "links": {
                "html": "https://unsplash.com/photos/u1",
                "download_location": "https://api.unsplash.com/photos/u1/download?ixid=abc",
            },
            "user": {"name": "Ada Lovelace", "links": {"html": "https://unsplash.com/@ada"}},
        }
    ],
}
PEXELS = {
    "photos": [
        {
            "id": 22,
            "width": 3000,
            "height": 2000,
            "url": "https://www.pexels.com/photo/lake-22/",
            "photographer": "Grace Hopper",
            "photographer_url": "https://www.pexels.com/@grace",
            "alt": "Lake",
            "src": {
                "original": "https://images.pexels.com/photos/22/lake.jpeg",
                "medium": "https://images.pexels.com/photos/22/lake.jpeg?h=350",
            },
        },
        {
            "id": 23,
            "width": 100,
            "height": 100,
            "url": "https://www.pexels.com/photo/pond-23/",
            "photographer": "Grace Hopper",
            "photographer_url": "https://www.pexels.com/@grace",
            "alt": "Pond",
            "src": {"original": "https://images.pexels.com/photos/23/pond.jpeg"},
        },
    ]
}
PIXABAY = {
    "totalHits": 1,
    "hits": [
        {
            "id": 333,
            "pageURL": "https://pixabay.com/photos/lake-333/",
            "tags": "lake, water",
            "webformatURL": "https://pixabay.com/get/abc_640.jpg",
            "largeImageURL": "https://pixabay.com/get/abc_1280.jpg",
            "imageWidth": 5000,
            "imageHeight": 3000,
            "user_id": 9,
            "user": "linus",
        }
    ],
}
FREEPIK = {
    "data": [
        {
            "id": 4444,
            "title": "Lake photo",
            "url": "https://www.freepik.com/free-photo/lake_4444.htm",
            "licenses": [
                {"type": "freemium", "url": "https://www.freepik.com/profile/license/4444"}
            ],
            "image": {
                "source": {
                    "url": "https://img.freepik.com/free-photo/lake_4444.jpg",
                    "size": "740x493",
                }
            },
            "author": {"id": 5, "name": "margaret", "slug": "margaret"},
        },
        {
            "id": 4445,
            "title": "Premium lake",
            "url": "https://www.freepik.com/premium-photo/lake_4445.htm",
            "licenses": [{"type": "premium", "url": "x"}],
            "image": {"source": {"url": "https://img.freepik.com/premium-photo/lake_4445.jpg"}},
            "author": {"name": "margaret", "slug": "margaret"},
        },
    ]
}
ANSWERS = {
    "api.unsplash.com": UNSPLASH,
    "api.pexels.com": PEXELS,
    "pixabay.com": PIXABAY,
    "api.magnific.com": FREEPIK,
}


class Answer:
    def __init__(self, body: bytes, headers: dict | None = None) -> None:
        self.body, self.headers = body, headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> bool:
        return False

    def read(self, limit: int = -1) -> bytes:
        return self.body if limit < 0 else self.body[:limit]


class Web:
    """What the scripts reach: canned answers by host, every request kept."""

    def __init__(self) -> None:
        self.requests: list = []
        self.by_host: dict = {host: json.dumps(answer).encode() for host, answer in ANSWERS.items()}
        self.headers: dict = {}
        self.fail: dict = {}

    def __call__(self, request, timeout, handlers=()):
        self.requests.append(request)
        host = urllib.parse.urlsplit(request.full_url).hostname
        if host in self.fail:
            failure = self.fail[host]
            if isinstance(failure, int):
                raise urllib.error.HTTPError(
                    request.full_url, failure, "refused", {}, io.BytesIO(b"")
                )
            raise failure
        return Answer(self.by_host[host], self.headers.get(host, {}))

    def hosts(self) -> list:
        return [urllib.parse.urlsplit(request.full_url).hostname for request in self.requests]


def load(name: str):
    spec = importlib.util.spec_from_file_location(f"image_stock_{name}", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """A working directory and a state folder of the test's own, and no key set."""
    for name in EVERY_VARIABLE:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("IMAGE_STOCK_STATE_DIR", str(tmp_path / "state"))
    (tmp_path / "work").mkdir()
    monkeypatch.chdir(tmp_path / "work")
    return tmp_path / "work"


@pytest.fixture
def web():
    return Web()


def script(name: str, web: Web, monkeypatch, *argv: str):
    module = load(name)
    monkeypatch.setattr(module, "open_url", web)
    monkeypatch.setattr(sys, "argv", [f"{name}.py", *argv])
    return module


def keys(monkeypatch, *providers: str) -> None:
    for provider in providers:
        monkeypatch.setenv(KEYS[provider], f"secret-{provider}-key")


# ---- The skill and its activation ------------------------------------------------------------


def test_the_shared_block_is_the_same_in_every_script() -> None:
    start, end = "# ---- The stock image providers", "# ---- End of the stock image providers ----"
    blocks = set()
    for name in NAMES:
        text = (SCRIPTS / f"{name}.py").read_text()
        blocks.add(text[text.index(start) : text.index(end)])
    assert len(blocks) == 1


def test_the_scripts_import_the_standard_library_alone() -> None:
    for name in NAMES:
        tree = ast.parse((SCRIPTS / f"{name}.py").read_text())
        for node in ast.walk(tree):
            modules = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            for module in modules:
                assert module.split(".")[0] in sys.stdlib_module_names | {"__future__"}, module


def test_one_key_is_enough_and_none_is_required() -> None:
    skill = AgentSkill.from_module("datalayer_skills.skills.image_stock")
    assert skill.name == "image-stock"
    assert skill.get_required_env_vars() == []
    assert skill.get_any_of_env_vars() == sorted(KEYS.values())
    assert set(EVERY_VARIABLE) == set(skill.get_optional_env_vars())
    assert not skill.is_activated({})
    assert not skill.is_activated({"UNSPLASH_TIER": "production"})
    for key in KEYS.values():
        assert skill.is_activated({key: "k"})
    # What needs a secret is never published as a public skill.
    assert skill.metadata.get("visibility") != "public"


async def test_without_a_key_the_toolset_does_not_offer_it(workspace) -> None:
    skill = AgentSkill.from_module("datalayer_skills.skills.image_stock")
    toolset = AgentSkillsToolset(skills=[skill])
    assert await toolset.get_tools(None) == {}
    assert await toolset.get_instructions() == ""
    assert "image-stock" not in toolset._list_skills()
    assert "Skill not found" in toolset._load_skill("image-stock")


async def test_with_a_key_it_is_offered_and_says_which_provider(workspace, monkeypatch) -> None:
    keys(monkeypatch, "pexels")
    skill = AgentSkill.from_module("datalayer_skills.skills.image_stock")
    toolset = AgentSkillsToolset(
        skills=[skill], executor=SandboxExecutor(CodeSandboxClient.create(variant="eval"))
    )
    listed = toolset._list_skills()
    assert 'name="image-stock"' in listed
    assert "optional_env_set=PEXELS_API_KEY" in listed
    assert "secret-pexels-key" not in listed + toolset._load_skill("image-stock")
    ran = await toolset.call_tool(
        "run_skill_script",
        {"skill_name": "image-stock", "script_name": "list_providers"},
        None,
        None,
    )
    assert ran["success"] is True, ran
    said = json.loads(ran["output"])
    assert said["configured"] == ["pexels"]
    assert "secret-pexels-key" not in ran["output"]


# ---- list_providers --------------------------------------------------------------------------


def test_only_configured_providers_are_listed(workspace, web, monkeypatch) -> None:
    keys(monkeypatch, "unsplash", "pixabay")
    said = script("list_providers", web, monkeypatch).main()
    assert said["configured"] == ["unsplash", "pixabay"]
    assert [entry["provider"] for entry in said["providers"]] == ["unsplash", "pixabay"]
    assert said["not_configured"] == [
        {"provider": "pexels", "set": "PEXELS_API_KEY"},
        {"provider": "freepik", "set": "FREEPIK_API_KEY"},
    ]
    assert said["providers"][0]["rate_limit"] == "50 requests per 3600 s"
    assert "secret-" not in json.dumps(said)
    assert web.requests == []


def test_the_unsplash_tier_raises_its_limit(workspace, web, monkeypatch) -> None:
    keys(monkeypatch, "unsplash")
    monkeypatch.setenv("UNSPLASH_TIER", "production")
    said = script("list_providers", web, monkeypatch).main()
    assert said["providers"][0]["rate_limit"] == "1000 requests per 3600 s"


# ---- search_images ---------------------------------------------------------------------------

SHAPE = {
    "id",
    "provider",
    "title",
    "author",
    "author_url",
    "page_url",
    "preview_url",
    "full_url",
    "width",
    "height",
    "license",
    "credit_required",
    "credit",
}


def test_unsplash_search(workspace, web, monkeypatch) -> None:
    keys(monkeypatch, "unsplash")
    said = script(
        "search_images",
        web,
        monkeypatch,
        "lake",
        "--provider",
        "unsplash",
        "--orientation",
        "square",
    ).main()
    (request,) = web.requests
    asked = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(request.full_url).query))
    assert request.full_url.startswith("https://api.unsplash.com/search/photos?")
    assert asked == {
        "query": "lake",
        "page": "1",
        "per_page": "5",
        "content_filter": "high",
        "orientation": "squarish",
    }
    assert request.get_header("Authorization") == "Client-ID secret-unsplash-key"
    assert request.get_header("Accept-version") == "v1"
    assert request.get_header("User-agent") == "image-stock-skill/1.0"
    (result,) = said["results"]
    assert SHAPE <= set(result)
    assert result == {
        "id": "u1",
        "provider": "unsplash",
        "title": "a lake at dawn",
        "author": "Ada Lovelace",
        "author_url": "https://unsplash.com/@ada",
        "page_url": "https://unsplash.com/photos/u1",
        "preview_url": "https://images.unsplash.com/photo-u1?ixid=abc&w=400",
        "full_url": "https://images.unsplash.com/photo-u1?ixid=abc",
        "width": 4000,
        "height": 3000,
        "license": "Unsplash License: free to use, commercially too.",
        "credit_required": True,
        "credit": (
            "Photo by Ada Lovelace on Unsplash "
            "(https://unsplash.com/@ada?utm_source=image-stock-skill&utm_medium=referral "
            "https://unsplash.com?utm_source=image-stock-skill&utm_medium=referral)"
        ),
        "download_location": "https://api.unsplash.com/photos/u1/download?ixid=abc",
    }
    assert said["providers"] == ["unsplash"] and said["failed"] == {}
    assert "secret-" not in json.dumps(said)


def test_pexels_search(workspace, web, monkeypatch) -> None:
    keys(monkeypatch, "pexels")
    said = script(
        "search_images", web, monkeypatch, "lake", "--provider", "pexels", "--per-page", "200"
    ).main()
    (request,) = web.requests
    asked = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(request.full_url).query))
    assert request.full_url.startswith("https://api.pexels.com/v1/search?")
    assert asked == {"query": "lake", "page": "1", "per_page": "30"}
    assert request.get_header("Authorization") == "secret-pexels-key"
    first = said["results"][0]
    assert SHAPE <= set(first)
    assert (first["id"], first["author"], first["width"]) == ("22", "Grace Hopper", 3000)
    assert first["full_url"] == "https://images.pexels.com/photos/22/lake.jpeg"
    assert first["credit_required"] is True
    assert first["credit"].startswith("Photo by Grace Hopper on Pexels (")
    assert "https://www.pexels.com/photo/lake-22/" in first["credit"]


def test_pixabay_search_keeps_the_key_out_and_the_answer_a_day(workspace, web, monkeypatch) -> None:
    keys(monkeypatch, "pixabay")
    argv = ("lake", "--provider", "pixabay", "--per-page", "1", "--orientation", "portrait")
    said = script("search_images", web, monkeypatch, *argv).main()
    (request,) = web.requests
    asked = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(request.full_url).query))
    assert request.full_url.startswith("https://pixabay.com/api/?")
    assert asked == {
        "key": "secret-pixabay-key",
        "q": "lake",
        "image_type": "photo",
        "safesearch": "true",
        "page": "1",
        "per_page": "3",
        "orientation": "vertical",
    }
    (result,) = said["results"]
    assert SHAPE <= set(result)
    assert result["author_url"] == "https://pixabay.com/users/linus-9/"
    assert result["credit_required"] is False
    assert result["credit"].startswith("Image by linus from Pixabay (")
    assert "secret-" not in json.dumps(said)
    # The same search again is answered from what was kept: no second request.
    again = script("search_images", web, monkeypatch, *argv).main()
    assert again["results"] == said["results"]
    assert len(web.requests) == 1
    kept = (workspace.parent / "state" / "pixabay-cache.json").read_text()
    assert "secret-pixabay-key" not in kept


def test_freepik_search(workspace, web, monkeypatch) -> None:
    keys(monkeypatch, "freepik")
    said = script(
        "search_images",
        web,
        monkeypatch,
        "lake",
        "--provider",
        "freepik",
        "--orientation",
        "landscape",
    ).main()
    (request,) = web.requests
    asked = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(request.full_url).query))
    assert request.full_url.startswith("https://api.magnific.com/v1/resources?")
    assert asked == {
        "term": "lake",
        "page": "1",
        "limit": "5",
        "order": "relevance",
        "filters[content_type][photo]": "1",
        "filters[orientation][landscape]": "1",
    }
    assert request.get_header("X-magnific-api-key") == "secret-freepik-key"
    free, premium = said["results"]
    assert SHAPE <= set(free)
    assert (free["id"], free["license_type"], free["credit_required"]) == ("4444", "freemium", True)
    assert free["full_url"] == "" and free["width"] is None
    assert free["author_url"] == "https://www.freepik.com/author/margaret"
    assert free["credit"].startswith("Image by margaret on Freepik (")
    assert (premium["license_type"], premium["credit_required"]) == ("premium", False)


def test_all_searches_exactly_the_configured_providers(workspace, web, monkeypatch) -> None:
    keys(monkeypatch, "pexels", "freepik")
    said = script("search_images", web, monkeypatch, "lake").main()
    assert said["providers"] == ["pexels", "freepik"]
    assert sorted(web.hosts()) == ["api.magnific.com", "api.pexels.com"]
    # One of each provider in turn.
    assert [(r["provider"], r["id"]) for r in said["results"]] == [
        ("pexels", "22"),
        ("freepik", "4444"),
        ("pexels", "23"),
        ("freepik", "4445"),
    ]
    assert said["count"] == 4 and said["failed"] == {}
    assert set(said["terms"]) == {"pexels", "freepik"}


def test_all_says_which_provider_failed_and_keeps_the_others(workspace, web, monkeypatch) -> None:
    keys(monkeypatch, "unsplash", "pexels")
    web.fail["api.unsplash.com"] = 401
    said = script("search_images", web, monkeypatch, "lake", "--provider", "all").main()
    assert [r["provider"] for r in said["results"]] == ["pexels", "pexels"]
    assert said["failed"] == {
        "unsplash": "Unsplash refused the key in UNSPLASH_ACCESS_KEY (HTTP 401): check it."
    }


def test_all_is_refused_when_every_provider_fails(workspace, web, monkeypatch) -> None:
    keys(monkeypatch, "unsplash", "pexels")
    web.fail["api.unsplash.com"] = 500
    web.fail["api.pexels.com"] = urllib.error.URLError("timed out")
    module = script("search_images", web, monkeypatch, "lake")
    with pytest.raises(module.StockRefused) as refused:
        module.main()
    assert "Unsplash is not answering (HTTP 500)" in str(refused.value)
    assert "Pexels could not be reached (timed out)" in str(refused.value)


def test_a_provider_without_its_key_is_not_offered(workspace, web, monkeypatch) -> None:
    keys(monkeypatch, "pexels")
    module = script("search_images", web, monkeypatch, "lake", "--provider", "unsplash")
    with pytest.raises(module.StockRefused) as refused:
        module.main()
    assert str(refused.value) == "unsplash has no key set here. Configured: pexels."
    assert web.requests == []


def test_no_key_at_all_is_said_without_a_request(workspace, web, monkeypatch) -> None:
    module = script("search_images", web, monkeypatch, "lake")
    with pytest.raises(module.StockRefused) as refused:
        module.main()
    assert "no stock image provider is configured" in str(refused.value)
    assert web.requests == []


def test_the_usual_provider_is_used_when_configured(workspace, web, monkeypatch) -> None:
    keys(monkeypatch, "pexels", "pixabay")
    monkeypatch.setenv("IMAGE_STOCK_DEFAULT_PROVIDER", "pixabay")
    assert script("search_images", web, monkeypatch, "lake").main()["providers"] == ["pixabay"]
    monkeypatch.setenv("IMAGE_STOCK_DEFAULT_PROVIDER", "unsplash")
    said = script("search_images", web, monkeypatch, "lake").main()
    assert said["providers"] == ["pexels", "pixabay"]


def test_a_refusal_never_carries_a_key_or_the_request(workspace, web, monkeypatch) -> None:
    keys(monkeypatch, "pixabay")
    for failure in (400, 401, 429, 503, urllib.error.URLError("no route"), TimeoutError()):
        web.fail["pixabay.com"] = failure
        module = script(
            "search_images", web, monkeypatch, f"lake {failure!r}", "--provider", "pixabay"
        )
        monkeypatch.setenv("IMAGE_STOCK_STATE_DIR", str(workspace / f"state-{id(failure)}"))
        with pytest.raises(module.StockRefused) as refused:
            module.main()
        assert "secret-pixabay-key" not in str(refused.value)
        assert "pixabay.com/api" not in str(refused.value)


def test_the_limit_is_kept_between_runs(workspace, web, monkeypatch) -> None:
    keys(monkeypatch, "freepik")
    monkeypatch.setenv("FREEPIK_REQUESTS_PER_MINUTE", "2")
    for word in ("one", "two"):
        script("search_images", web, monkeypatch, word, "--provider", "freepik").main()
    module = script("search_images", web, monkeypatch, "three", "--provider", "freepik")
    with pytest.raises(module.StockRefused) as refused:
        module.main()
    assert "Freepik rate limit reached (2 requests per 60 s): try again in" in str(refused.value)
    assert len(web.requests) == 2


def test_a_provider_that_says_none_is_left_is_not_asked_again(workspace, web, monkeypatch) -> None:
    keys(monkeypatch, "pexels")
    web.headers["api.pexels.com"] = {"X-Ratelimit-Remaining": "0"}
    script("search_images", web, monkeypatch, "one", "--provider", "pexels").main()
    module = script("search_images", web, monkeypatch, "two", "--provider", "pexels")
    with pytest.raises(module.StockRefused):
        module.main()
    assert len(web.requests) == 1


def test_a_429_stops_the_next_request(workspace, web, monkeypatch) -> None:
    keys(monkeypatch, "pexels")
    web.fail["api.pexels.com"] = 429
    for word in ("one", "two"):
        module = script("search_images", web, monkeypatch, word, "--provider", "pexels")
        with pytest.raises(module.StockRefused):
            module.main()
    assert len(web.requests) == 1


def test_a_bad_orientation_or_an_empty_query_is_refused(workspace, web, monkeypatch) -> None:
    keys(monkeypatch, "pexels")
    for argv in (("lake", "--orientation", "diagonal"), ("   ",)):
        module = script("search_images", web, monkeypatch, *argv)
        with pytest.raises(module.StockRefused):
            module.main()
    assert web.requests == []


# ---- image_attribution -----------------------------------------------------------------------


def attribution(web, monkeypatch, **fields) -> dict:
    argv = [part for key, value in fields.items() for part in (f"--{key.replace('_', '-')}", value)]
    return script("image_attribution", web, monkeypatch, *argv).main()


def test_the_credit_line_of_each_provider(workspace, web, monkeypatch) -> None:
    monkeypatch.setenv("UNSPLASH_APP_NAME", "my app")
    unsplash = attribution(
        web,
        monkeypatch,
        provider="unsplash",
        author="Ada Lovelace",
        author_url="https://unsplash.com/@ada",
    )
    referral = "utm_source=my%20app&utm_medium=referral"
    assert unsplash["required"] is True
    assert unsplash["markdown"] == (
        f"Photo by [Ada Lovelace](https://unsplash.com/@ada?{referral}) "
        f"on [Unsplash](https://unsplash.com?{referral})"
    )
    assert unsplash["html"] == (
        f'Photo by <a href="https://unsplash.com/@ada?{referral.replace("&", "&amp;")}">Ada Lovelace</a> '
        f'on <a href="https://unsplash.com?{referral.replace("&", "&amp;")}">Unsplash</a>'
    )
    pexels = attribution(
        web,
        monkeypatch,
        provider="pexels",
        author="Grace Hopper",
        author_url="https://www.pexels.com/@grace",
        page_url="https://www.pexels.com/photo/lake-22/",
    )
    assert pexels["required"] is True
    assert pexels["markdown"] == (
        "Photo by [Grace Hopper](https://www.pexels.com/@grace) "
        "on [Pexels](https://www.pexels.com/photo/lake-22/)"
    )
    pixabay = attribution(web, monkeypatch, provider="pixabay", author="linus")
    assert pixabay["required"] is False and pixabay["rule"] == "appreciated"
    assert pixabay["markdown"] == "Image by linus from [Pixabay](https://pixabay.com)"
    free = attribution(web, monkeypatch, provider="freepik", author="margaret")
    assert free["required"] is True
    assert free["markdown"] == "Image by margaret on [Freepik](https://www.freepik.com)"
    premium = attribution(
        web, monkeypatch, provider="freepik", author="margaret", license_type="premium"
    )
    assert premium["required"] is False
    nameless = attribution(web, monkeypatch, provider="pexels")
    assert nameless["markdown"] == "Photo on [Pexels](https://www.pexels.com)"
    assert web.requests == []


def test_html_in_a_name_is_escaped(workspace, web, monkeypatch) -> None:
    line = attribution(
        web,
        monkeypatch,
        provider="pexels",
        author="<b>x</b>",
        author_url='https://www.pexels.com/@a"b',
    )
    assert "<b>" not in line["html"] and 'a"b' not in line["html"]


def test_attribution_needs_no_key_but_a_known_provider(workspace, web, monkeypatch) -> None:
    module = script("image_attribution", web, monkeypatch, "--provider", "elsewhere")
    with pytest.raises(module.StockRefused):
        module.main()


# ---- download_image --------------------------------------------------------------------------

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64


def downloader(web, monkeypatch, *argv):
    module = script("download_image", web, monkeypatch, *argv)
    monkeypatch.setattr(
        module.socket, "getaddrinfo", lambda host, *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))]
    )
    return module


def test_a_pexels_download_lands_in_the_workspace(workspace, web, monkeypatch) -> None:
    keys(monkeypatch, "pexels")
    web.by_host["images.pexels.com"] = JPEG
    web.headers["images.pexels.com"] = {"Content-Type": "image/jpeg"}
    said = downloader(
        web,
        monkeypatch,
        "--provider",
        "pexels",
        "--id",
        "22",
        "--url",
        PEXELS["photos"][0]["src"]["original"],
    ).main()
    assert said["path"] == os.path.join("images", "pexels-22.jpg")
    assert (workspace / said["path"]).read_bytes() == JPEG
    assert (said["bytes"], said["content_type"]) == (len(JPEG), "image/jpeg")
    (request,) = web.requests
    # The image host is sent no key.
    assert request.get_header("Authorization") is None
    assert "reported_to_unsplash" not in said


def test_an_unsplash_download_is_reported_to_unsplash(workspace, web, monkeypatch) -> None:
    keys(monkeypatch, "unsplash")
    web.by_host["images.unsplash.com"] = JPEG
    web.headers["images.unsplash.com"] = {"Content-Type": "image/jpeg; charset=binary"}
    web.by_host["api.unsplash.com"] = b'{"url": "https://images.unsplash.com/photo-u1"}'
    photo = UNSPLASH["results"][0]
    said = downloader(
        web,
        monkeypatch,
        "--provider",
        "unsplash",
        "--id",
        "u1",
        "--url",
        photo["urls"]["full"],
        "--download-location",
        photo["links"]["download_location"],
        "--output",
        "pictures/lake",
    ).main()
    assert said["path"] == os.path.join("pictures", "lake.jpg")
    assert said["reported_to_unsplash"] is True
    image, event = web.requests
    assert image.get_header("Authorization") is None
    assert event.full_url == "https://api.unsplash.com/photos/u1/download?ixid=abc"
    assert event.get_header("Authorization") == "Client-ID secret-unsplash-key"


def test_an_unreported_unsplash_download_says_so(workspace, web, monkeypatch) -> None:
    keys(monkeypatch, "unsplash")
    web.by_host["images.unsplash.com"] = JPEG
    web.headers["images.unsplash.com"] = {"Content-Type": "image/jpeg"}
    web.fail["api.unsplash.com"] = 503
    said = downloader(
        web,
        monkeypatch,
        "--provider",
        "unsplash",
        "--id",
        "u 1",
        "--url",
        "https://images.unsplash.com/p",
    ).main()
    assert said["reported_to_unsplash"] is False and "could not be reported" in said["warning"]
    assert web.requests[1].full_url == "https://api.unsplash.com/photos/u%201/download"
    assert (workspace / said["path"]).is_file()


def test_the_key_goes_to_the_provider_alone(workspace, web, monkeypatch) -> None:
    keys(monkeypatch, "unsplash")
    web.by_host["images.unsplash.com"] = JPEG
    web.headers["images.unsplash.com"] = {"Content-Type": "image/jpeg"}
    said = downloader(
        web,
        monkeypatch,
        "--provider",
        "unsplash",
        "--id",
        "u1",
        "--url",
        "https://images.unsplash.com/p",
        "--download-location",
        "https://elsewhere.example/photos/u1/download",
    ).main()
    assert said["reported_to_unsplash"] is False
    assert web.hosts() == ["images.unsplash.com"]


def test_a_freepik_download_is_asked_by_id(workspace, web, monkeypatch) -> None:
    keys(monkeypatch, "freepik")
    web.by_host["api.magnific.com"] = json.dumps(
        {"data": {"filename": "lake.jpg", "url": "https://downloads.example.net/lake.jpg?exp=1"}}
    ).encode()
    web.by_host["downloads.example.net"] = JPEG
    web.headers["downloads.example.net"] = {"Content-Type": "image/jpeg"}
    said = downloader(web, monkeypatch, "--provider", "freepik", "--id", "4444").main()
    api, file = web.requests
    assert api.full_url == "https://api.magnific.com/v1/resources/4444/download"
    assert api.get_header("X-magnific-api-key") == "secret-freepik-key"
    assert file.get_header("X-magnific-api-key") is None
    assert said["path"] == os.path.join("images", "freepik-4444.jpg")


@pytest.mark.parametrize(
    ("argv", "says"),
    [
        (("--url", "https://example.org/a.jpg"), "is not where this provider serves its images"),
        (("--url", "http://images.pexels.com/a.jpg"), "https address alone"),
        (("--url", "https://user:pw@images.pexels.com/a.jpg"), "https address alone"),
        ((), "give the image's full_url"),
        (
            ("--url", "https://images.pexels.com/a.jpg", "--output", "../out.jpg"),
            "under the working",
        ),
        (
            ("--url", "https://images.pexels.com/a.jpg", "--output", "/tmp/out.jpg"),
            "under the working",
        ),
    ],
)
def test_what_a_download_refuses(workspace, web, monkeypatch, argv, says) -> None:
    keys(monkeypatch, "pexels")
    module = downloader(web, monkeypatch, "--provider", "pexels", "--id", "22", *argv)
    with pytest.raises(module.StockRefused) as refused:
        module.main()
    assert says in str(refused.value)
    assert web.requests == []
    assert list(workspace.rglob("*.jpg")) == []


def test_a_private_address_is_refused(workspace, web, monkeypatch) -> None:
    keys(monkeypatch, "freepik")
    web.by_host["api.magnific.com"] = b'{"data": {"url": "https://internal.example/x.jpg"}}'
    module = downloader(web, monkeypatch, "--provider", "freepik", "--id", "4444")
    monkeypatch.setattr(
        module.socket, "getaddrinfo", lambda host, *a, **k: [(2, 1, 6, "", ("10.0.0.7", 443))]
    )
    with pytest.raises(module.StockRefused) as refused:
        module.main()
    assert "not a public address" in str(refused.value)
    assert web.hosts() == ["api.magnific.com"]


def test_what_is_no_image_or_too_big_is_not_kept(workspace, web, monkeypatch) -> None:
    keys(monkeypatch, "pexels")
    argv = ("--provider", "pexels", "--id", "22", "--url", "https://images.pexels.com/a.jpg")
    web.by_host["images.pexels.com"] = b"<html>"
    web.headers["images.pexels.com"] = {"Content-Type": "text/html"}
    module = downloader(web, monkeypatch, *argv)
    with pytest.raises(module.StockRefused) as refused:
        module.main()
    assert "did not answer with an image (text/html)" in str(refused.value)
    web.headers["images.pexels.com"] = {"Content-Type": "image/png"}
    module = downloader(web, monkeypatch, *argv)
    monkeypatch.setattr(module, "MAX_IMAGE_BYTES", 3)
    with pytest.raises(module.StockRefused) as refused:
        module.main()
    assert "not kept" in str(refused.value)
    assert not (workspace / "images").exists() or list((workspace / "images").iterdir()) == []


def test_a_redirect_is_followed_only_to_the_providers_hosts(workspace, web, monkeypatch) -> None:
    keys(monkeypatch, "pexels")
    module = downloader(web, monkeypatch)
    handler = module.CheckedRedirect(module.IMAGE_HOSTS["pexels"])
    with pytest.raises(module.StockRefused):
        handler.redirect_request(None, None, 302, "Found", {}, "https://elsewhere.example/a.jpg")
    assert module.NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://x") is None


# ---- As the sandbox runs them: a process of its own ------------------------------------------


def run_script(name: str, env: dict, cwd: Path, *argv: str) -> subprocess.CompletedProcess:
    base = {key: value for key, value in os.environ.items() if key not in EVERY_VARIABLE}
    return subprocess.run(
        [sys.executable, str(SCRIPTS / f"{name}.py"), *argv],
        env={**base, "IMAGE_STOCK_STATE_DIR": str(cwd / "state"), **env},
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_the_scripts_run_as_command_lines(tmp_path) -> None:
    listed = run_script("list_providers", {"PIXABAY_API_KEY": "secret-pixabay-key"}, tmp_path)
    assert listed.returncode == 0, listed.stderr
    assert json.loads(listed.stdout)["configured"] == ["pixabay"]
    assert "secret-pixabay-key" not in listed.stdout + listed.stderr

    none = run_script("search_images", {}, tmp_path, "lake")
    assert none.returncode == 1
    assert none.stderr.startswith("Error: no stock image provider is configured")
    assert "Traceback" not in none.stderr

    unknown = run_script("search_images", {}, tmp_path, "lake", "--nothing", "1")
    assert unknown.returncode == 2

    line = run_script(
        "image_attribution", {}, tmp_path, "--provider", "pixabay", "--author", "linus"
    )
    assert json.loads(line.stdout)["text"] == "Image by linus from Pixabay (https://pixabay.com)"
