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
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
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
    # Unsplash is told first, then the image is downloaded.
    event, image = web.requests
    assert image.get_header("Authorization") is None
    assert event.full_url == "https://api.unsplash.com/photos/u1/download?ixid=abc"
    assert event.get_header("Authorization") == "Client-ID secret-unsplash-key"


def test_an_unreported_unsplash_download_is_not_downloaded(workspace, web, monkeypatch) -> None:
    keys(monkeypatch, "unsplash")
    web.by_host["images.unsplash.com"] = JPEG
    web.headers["images.unsplash.com"] = {"Content-Type": "image/jpeg"}
    web.fail["api.unsplash.com"] = 503
    module = downloader(
        web,
        monkeypatch,
        "--provider",
        "unsplash",
        "--id",
        "u 1",
        "--url",
        "https://images.unsplash.com/p",
    )
    with pytest.raises(module.StockRefused) as refused:
        module.main()
    assert "could not be reported to Unsplash, so the image was not downloaded" in str(
        refused.value
    )
    (event,) = web.requests
    assert event.full_url == "https://api.unsplash.com/photos/u%201/download"
    assert not (workspace / "images").exists()


def test_the_key_goes_to_the_provider_alone(workspace, web, monkeypatch) -> None:
    keys(monkeypatch, "unsplash")
    web.by_host["images.unsplash.com"] = JPEG
    web.headers["images.unsplash.com"] = {"Content-Type": "image/jpeg"}
    module = downloader(
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
    )
    with pytest.raises(module.StockRefused) as refused:
        module.main()
    assert "api.unsplash.com" in str(refused.value)
    assert web.requests == []


def test_a_freepik_download_is_asked_by_id(workspace, web, monkeypatch) -> None:
    keys(monkeypatch, "freepik")
    web.by_host["api.magnific.com"] = json.dumps(
        {
            "data": {
                "filename": "lake.jpg",
                "url": "https://downloadscdn5.freepik.com/lake.jpg?exp=1",
            }
        }
    ).encode()
    web.by_host["downloadscdn5.freepik.com"] = JPEG
    web.headers["downloadscdn5.freepik.com"] = {"Content-Type": "image/jpeg"}
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
    web.by_host["api.magnific.com"] = b'{"data": {"url": "https://img.freepik.com/x.jpg"}}'
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
        check=False,
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


# ---- Copilot's review of 0.7.0 ---------------------------------------------------------------


def test_a_freepik_file_or_its_redirect_goes_to_freepik_alone(workspace, web, monkeypatch) -> None:
    keys(monkeypatch, "freepik")
    web.by_host["api.magnific.com"] = b'{"data": {"url": "https://elsewhere.example/x.jpg"}}'
    module = downloader(web, monkeypatch, "--provider", "freepik", "--id", "4444")
    with pytest.raises(module.StockRefused) as refused:
        module.main()
    assert "is not where this provider serves its images" in str(refused.value)
    assert web.hosts() == ["api.magnific.com"]
    handler = module.CheckedRedirect(module.IMAGE_HOSTS["freepik"])
    handler.redirect_request(
        urllib.request.Request("https://img.freepik.com/a"),
        None,
        302,
        "Found",
        {},
        "https://downloadscdn5.freepik.com/b.jpg",
    )
    for elsewhere in ("https://elsewhere.example/a.jpg", "https://freepik.com.evil.example/a"):
        with pytest.raises(module.StockRefused):
            handler.redirect_request(None, None, 302, "Found", {}, elsewhere)


def test_a_download_connects_to_the_address_it_checked(workspace, web, monkeypatch) -> None:
    module = downloader(web, monkeypatch)
    answers = iter([[(2, 1, 6, "", ("93.184.216.34", 443))], [(2, 1, 6, "", ("10.0.0.7", 443))]])
    monkeypatch.setattr(module.socket, "getaddrinfo", lambda *a, **k: next(answers))
    opened = []

    class Wrapped(ssl.SSLContext):
        def __new__(cls):
            return super().__new__(cls, ssl.PROTOCOL_TLS_CLIENT)

        def wrap_socket(self, sock, server_hostname):
            opened.append(("tls", server_hostname))
            return sock

    def create_connection(address, *rest):
        opened.append(("tcp", address))
        return object()

    monkeypatch.setattr(module.socket, "create_connection", create_connection)
    connection = module.PinnedHTTPSConnection("images.pexels.com", 443, context=Wrapped())
    connection.connect()
    # Resolved once, connected to that address, the name kept for TLS.
    assert opened == [("tcp", ("93.184.216.34", 443)), ("tls", "images.pexels.com")]
    # A second resolution answering a private address is refused before any connection.
    with pytest.raises(module.StockRefused):
        module.PinnedHTTPSConnection("images.pexels.com", 443, context=Wrapped()).connect()
    kinds = [type(handler).__name__ for handler in module.download_handlers(("x",))]
    assert kinds == ["ProxyHandler", "PinnedHTTPSHandler", "CheckedRedirect"]


def test_a_link_in_the_workspace_is_replaced_never_followed(
    workspace, web, monkeypatch, tmp_path
) -> None:
    keys(monkeypatch, "pexels")
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"keep")
    (workspace / "photo.jpg").symlink_to(outside)
    web.by_host["images.pexels.com"] = JPEG
    web.headers["images.pexels.com"] = {"Content-Type": "image/jpeg"}
    argv = ("--provider", "pexels", "--id", "22", "--url", "https://images.pexels.com/a.jpg")
    said = downloader(web, monkeypatch, *argv, "--output", "photo").main()
    assert said["path"] == "photo.jpg"
    assert outside.read_bytes() == b"keep"
    assert not (workspace / "photo.jpg").is_symlink()
    assert (workspace / "photo.jpg").read_bytes() == JPEG
    # A folder that is a link out of the workspace is refused.
    (workspace / "out").symlink_to(tmp_path)
    module = downloader(web, monkeypatch, *argv, "--output", "out/x.jpg")
    with pytest.raises(module.StockRefused) as refused:
        module.main()
    assert "under the working directory" in str(refused.value)
    assert not (tmp_path / "x.jpg").exists()


def test_an_unlinked_name_is_escaped_in_html(workspace, web, monkeypatch) -> None:
    line = attribution(web, monkeypatch, provider="pixabay", author="<img src=x onerror=alert(1)>")
    assert "<img" not in line["html"] and "&lt;img" in line["html"]
    assert line["markdown"].startswith("Image by <img")  # Markdown and text say it as given.


def test_attribution_takes_the_underscore_spellings(workspace, web, monkeypatch) -> None:
    argv = (
        "--provider",
        "freepik",
        "--author",
        "margaret",
        "--author_url",
        "https://www.freepik.com/author/margaret",
        "--page_url",
        "https://www.freepik.com/photo/1",
        "--license_type",
        "premium",
    )
    line = script("image_attribution", web, monkeypatch, *argv).main()
    assert line["required"] is False
    assert line["markdown"] == (
        "Image by [margaret](https://www.freepik.com/author/margaret) "
        "on [Freepik](https://www.freepik.com/photo/1)"
    )


def test_a_request_whose_count_cannot_be_kept_is_not_sent(workspace, web, monkeypatch) -> None:
    keys(monkeypatch, "pexels")
    module = script("search_images", web, monkeypatch, "lake", "--provider", "pexels")

    def cannot(*args, **kwargs):
        raise OSError("no space left")

    monkeypatch.setattr(module.os, "replace", cannot)
    with pytest.raises(module.StockRefused) as refused:
        module.main()
    assert "could not be saved" in str(refused.value)
    assert web.requests == []


def test_the_count_is_kept_whole_across_processes(workspace) -> None:
    code = (
        "import importlib.util, sys\n"
        f"spec = importlib.util.spec_from_file_location('s', {str(SCRIPTS / 'search_images.py')!r})\n"
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
        "for _ in range(25):\n"
        "    m.take_request('freepik')\n"
    )
    env = {**os.environ, "FREEPIK_REQUESTS_PER_MINUTE": "600"}
    runs = [
        subprocess.Popen([sys.executable, "-c", code], env=env, stderr=subprocess.PIPE)
        for _ in range(4)
    ]
    for run in runs:
        assert run.wait(60) == 0, run.stderr.read().decode()
    kept = json.loads((workspace.parent / "state" / "rate.json").read_text())
    assert len(kept["freepik"]["calls"]) == 100


def test_a_provider_is_left_alone_for_the_whole_wait_it_asks(workspace, web, monkeypatch) -> None:
    keys(monkeypatch, "pexels")
    module = script("search_images", web, monkeypatch, "lake", "--provider", "pexels")
    assert module.wait_asked({"Retry-After": "7200"}, 60.0) == 7200.0
    assert module.wait_asked({}, 60.0) == 60.0
    assert 3590 < module.wait_asked({"X-Ratelimit-Reset": str(int(time.time()) + 3600)}, 1) <= 3600
    module.block_until("pexels", 7200.0)
    module.block_until("pexels", 60.0)  # A shorter wait leaves the longer one.
    kept = json.loads((workspace.parent / "state" / "rate.json").read_text())
    assert kept["pexels"]["blocked_until"] - time.time() > 7000

    def refused_429(request, timeout, handlers=()):
        raise urllib.error.HTTPError(
            request.full_url, 429, "slow down", {"Retry-After": "5400"}, io.BytesIO(b"")
        )

    keys(monkeypatch, "pixabay")
    other = script("search_images", web, monkeypatch, "lake", "--provider", "pixabay")
    monkeypatch.setattr(other, "open_url", refused_429)
    with pytest.raises(other.StockRefused):
        other.main()
    kept = json.loads((workspace.parent / "state" / "rate.json").read_text())
    assert kept["pixabay"]["blocked_until"] - time.time() > 5300


@pytest.mark.parametrize(
    ("per_page", "page", "window"),
    [
        (1, 1, (3, 1, 0)),
        (1, 2, (3, 1, 1)),
        (1, 3, (3, 1, 2)),
        (1, 4, (3, 2, 0)),
        (2, 2, (6, 1, 2)),
        (2, 4, (6, 2, 0)),
        (5, 3, (5, 3, 0)),
    ],
)
def test_small_pixabay_pages_skip_nothing(per_page, page, window) -> None:
    assert load("search_images").pixabay_window(per_page, page) == window


def test_pixabay_pages_of_one_follow_each_other(workspace, web, monkeypatch) -> None:
    keys(monkeypatch, "pixabay")
    hits = [
        {"id": n, "user": "u", "user_id": 1, "pageURL": "", "webformatURL": "", "largeImageURL": ""}
        for n in (1, 2, 3)
    ]
    web.by_host["pixabay.com"] = json.dumps({"hits": hits}).encode()
    ids = []
    for page in ("1", "2", "3"):
        argv = ("lake", "--provider", "pixabay", "--per-page", "1", "--page", page)
        ids += [r["id"] for r in script("search_images", web, monkeypatch, *argv).main()["results"]]
    assert ids == ["1", "2", "3"]
    assert len(web.requests) == 1  # Pixabay's one page of 3, kept for the day.


def test_every_pixabay_answer_of_the_day_is_kept(workspace, web, monkeypatch) -> None:
    keys(monkeypatch, "pixabay")
    for n in range(55):
        script("search_images", web, monkeypatch, f"lake {n}", "--provider", "pixabay").main()
    script("search_images", web, monkeypatch, "lake 0", "--provider", "pixabay").main()
    assert len(web.requests) == 55
    kept = json.loads((workspace.parent / "state" / "pixabay-cache.json").read_text())
    assert len(kept) == 55


# ---- Copilot's second review (0.7.1) ---------------------------------------------------------


def test_the_folder_is_reached_by_descriptors_without_proc(
    workspace, web, monkeypatch, tmp_path
) -> None:
    keys(monkeypatch, "pexels")
    web.by_host["images.pexels.com"] = JPEG
    web.headers["images.pexels.com"] = {"Content-Type": "image/jpeg"}
    argv = ("--provider", "pexels", "--id", "22", "--url", "https://images.pexels.com/a.jpg")
    module = downloader(web, monkeypatch, *argv, "--output", "deep/er/x.jpg")
    # No /proc to ask (macOS): nothing reads it any more.
    real_exists = module.os.path.exists
    monkeypatch.setattr(
        module.os.path, "exists", lambda p: False if str(p).startswith("/proc") else real_exists(p)
    )
    assert module.main()["path"] == os.path.join("deep", "er", "x.jpg")
    assert (workspace / "deep" / "er" / "x.jpg").read_bytes() == JPEG
    # A folder swapped for a link out of the workspace after the path was checked: the walk
    # by descriptors meets the link and refuses it.
    real_mkdir = module.os.mkdir

    def swap(name, mode=0o777, *, dir_fd=None):
        real_mkdir(name, mode, dir_fd=dir_fd)
        if name == "swapped":
            os.rmdir(workspace / "swapped")
            (workspace / "swapped").symlink_to(tmp_path)

    monkeypatch.setattr(module.os, "mkdir", swap)
    module = downloader(web, monkeypatch, *argv, "--output", "swapped/y.jpg")
    monkeypatch.setattr(module.os, "mkdir", swap)
    with pytest.raises(module.StockRefused) as refused:
        module.main()
    assert "under the working directory" in str(refused.value)
    assert not (tmp_path / "y.jpg").exists()


def test_a_writer_removes_only_its_own_temporary_file(workspace) -> None:
    module = load("download_image")
    names = [module.write_inside_workspace(str(workspace / "same.jpg"), b"1") for _ in range(2)]
    assert names[0] == names[1]
    assert sorted(p.name for p in workspace.iterdir()) == ["same.jpg"]
    # A temporary name of another writer is never this call's: each call draws its own.
    taken = {module.secrets.token_hex(8) for _ in range(50)}
    assert len(taken) == 50
    (workspace / ".other.part").write_bytes(b"theirs")
    monkey_fail = module.os.replace

    def failing(*args, **kwargs):
        raise OSError("disk full")

    module.os.replace = failing
    try:
        with pytest.raises(module.StockRefused):
            module.write_inside_workspace(str(workspace / "same.jpg"), b"2")
    finally:
        module.os.replace = monkey_fail
    assert (workspace / ".other.part").read_bytes() == b"theirs"
    assert sorted(p.name for p in workspace.iterdir()) == [".other.part", "same.jpg"]


def test_one_pixabay_page_is_asked_once_by_concurrent_searches(workspace, web, monkeypatch) -> None:
    keys(monkeypatch, "pixabay")
    code = (
        "import importlib.util, json, sys, time, urllib.parse\n"
        f"spec = importlib.util.spec_from_file_location('s', {str(SCRIPTS / 'search_images.py')!r})\n"
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
        "class A:\n"
        "    headers = {}\n"
        "    def __enter__(self): return self\n"
        "    def __exit__(self, *a): return False\n"
        "    def read(self, n=-1): return b'{\"hits\": []}'\n"
        "def answer(request, timeout, handlers=()):\n"
        "    time.sleep(0.5)\n"
        "    open(sys.argv[1], 'a').write('asked\\n')\n"
        "    return A()\n"
        "m.open_url = answer\n"
        "m.search_pixabay('secret-pixabay-key', 'lake', 5, 1, '')\n"
    )
    log = workspace / "asked.log"
    env = {**os.environ}
    runs = [
        subprocess.Popen([sys.executable, "-c", code, str(log)], env=env, stderr=subprocess.PIPE)
        for _ in range(3)
    ]
    for run in runs:
        assert run.wait(60) == 0, run.stderr.read().decode()
    assert log.read_text().splitlines() == ["asked"]


def test_whoami_takes_run_url_as_run_skill_script_sends_it(monkeypatch) -> None:
    monkeypatch.delenv("DATALAYER_RUN_URL", raising=False)
    monkeypatch.delenv("DATALAYER_API_KEY", raising=False)
    path = SCRIPTS.parents[1] / "whoami" / "scripts" / "whoami.py"
    spec = importlib.util.spec_from_file_location("whoami_script", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    args = module.arguments(["--run_url", "https://example.datalayer.run", "--api_key", "k"])
    assert (args.run_url, args.api_key) == ("https://example.datalayer.run", "k")
    args = module.arguments(["--run-url", "https://example.datalayer.run"])
    assert args.run_url == "https://example.datalayer.run"


# ---- Copilot's third review (0.7.2) ----------------------------------------------------------


def test_a_folder_moved_out_while_open_keeps_nothing_outside(workspace, tmp_path) -> None:
    module = load("download_image")
    (workspace / "moved").mkdir()
    away = tmp_path / "away"
    real_replace = module.os.replace

    def move_then_replace(*args, **kwargs):
        os.rename(workspace / "moved", away)  # The open folder leaves the workspace.
        return real_replace(*args, **kwargs)

    module.os.replace = move_then_replace
    try:
        with pytest.raises(module.StockRefused) as refused:
            module.write_inside_workspace(str(workspace / "moved" / "x.jpg"), b"1")
    finally:
        module.os.replace = real_replace
    assert "under the working directory" in str(refused.value)
    assert sorted(p.name for p in away.iterdir()) == []
    assert not (workspace / "moved").exists()


def test_a_folder_moved_before_the_write_is_refused(workspace, tmp_path) -> None:
    module = load("download_image")
    (workspace / "early").mkdir()
    real_open = module.open_folder_inside

    def open_then_move(*args):
        fd = real_open(*args)
        os.rename(workspace / "early", tmp_path / "gone")
        return fd

    module.open_folder_inside = open_then_move
    with pytest.raises(module.StockRefused):
        module.write_inside_workspace(str(workspace / "early" / "y.jpg"), b"1")
    assert list((tmp_path / "gone").iterdir()) == []


def test_a_slow_pixabay_cache_holds_up_no_other_count(workspace) -> None:
    module = load("search_images")
    started, done = module.threading.Event(), module.threading.Event()

    def slow_cache() -> None:
        with module.state_locked("pixabay-cache.json"):
            started.set()
            done.wait(5)

    holder = module.threading.Thread(target=slow_cache)
    holder.start()
    assert started.wait(5)
    counted = module.threading.Event()
    other = module.threading.Thread(target=lambda: (module.take_request("pexels"), counted.set()))
    other.start()
    # Pexels is counted while Pixabay's cache is still held.
    assert counted.wait(2)
    done.set()
    holder.join(5)
    other.join(5)
    assert module.thread_lock("rate.json") is not module.thread_lock("pixabay-cache.json")


# ---- Copilot's fourth review (0.7.3) ---------------------------------------------------------


def after_the_rename(module, then):
    real_replace = module.os.replace

    def replace(*args, **kwargs):
        real_replace(*args, **kwargs)
        then()

    module.os.replace = replace
    return real_replace


def test_bytes_another_writer_put_there_are_not_reported_as_ours(workspace) -> None:
    module = load("download_image")
    (workspace / "theirs.part").write_bytes(b"theirs")
    real = after_the_rename(
        module, lambda: os.rename(workspace / "theirs.part", workspace / "same.jpg")
    )
    try:
        with pytest.raises(module.StockRefused) as refused:
            module.write_inside_workspace(str(workspace / "same.jpg"), b"mine")
    finally:
        module.os.replace = real
    assert "replaced or removed by another writer" in str(refused.value)
    # Their file is left as they wrote it.
    assert (workspace / "same.jpg").read_bytes() == b"theirs"


def test_a_folder_moved_and_refilled_keeps_the_other_writers_file(workspace, tmp_path) -> None:
    module = load("download_image")
    (workspace / "moving").mkdir()
    away = tmp_path / "away"

    def move_and_refill() -> None:
        os.rename(workspace / "moving", away)
        (away / "other.part").write_bytes(b"theirs")
        os.rename(away / "other.part", away / "x.jpg")

    real = after_the_rename(module, move_and_refill)
    try:
        with pytest.raises(module.StockRefused):
            module.write_inside_workspace(str(workspace / "moving" / "x.jpg"), b"mine")
    finally:
        module.os.replace = real
    assert (away / "x.jpg").read_bytes() == b"theirs"


def test_a_file_removed_after_the_rename_is_a_refusal_not_a_traceback(workspace) -> None:
    module = load("download_image")
    real = after_the_rename(module, lambda: os.unlink(workspace / "gone.jpg"))
    try:
        with pytest.raises(module.StockRefused) as refused:
            module.write_inside_workspace(str(workspace / "gone.jpg"), b"mine")
    finally:
        module.os.replace = real
    assert "replaced or removed by another writer" in str(refused.value)


def test_the_folder_is_locked_from_the_rename_to_the_check(workspace, monkeypatch) -> None:
    module = load("download_image")
    calls = []
    real_flock, real_replace = module.fcntl.flock, module.os.replace

    def flock(fd, op):
        calls.append(("flock", op))
        return real_flock(fd, op)

    def replace(*args, **kwargs):
        calls.append(("replace", None))
        return real_replace(*args, **kwargs)

    monkeypatch.setattr(module.fcntl, "flock", flock)
    monkeypatch.setattr(module.os, "replace", replace)
    module.write_inside_workspace(str(workspace / "locked.jpg"), b"1")
    assert calls == [("flock", module.fcntl.LOCK_EX), ("replace", None)]


def test_whoami_activates_with_the_key_its_url_given_either_way() -> None:
    text = (SCRIPTS.parents[1] / "whoami" / "SKILL.md").read_text()
    front = text.split("---")[1]
    assert "required:\n    - DATALAYER_API_KEY\n  optional:\n    - DATALAYER_RUN_URL" in front
    assert "Either one is enough" in text
