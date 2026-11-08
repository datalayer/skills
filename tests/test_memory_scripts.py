# Copyright (c) 2025-2026 Datalayer, Inc.
#
# BSD 3-Clause License

"""Each memory script against a fake runtime, run as the sandbox runs it: a process of its own."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[1] / "datalayer_skills" / "skills"
SCRIPTS = {
    "add": SKILLS / "memory_add" / "scripts" / "add.py",
    "search": SKILLS / "memory_search" / "scripts" / "search.py",
    "list": SKILLS / "memory_list" / "scripts" / "list_memories.py",
    "delete": SKILLS / "memory_delete" / "scripts" / "delete.py",
    "delete_all": SKILLS / "memory_delete" / "scripts" / "delete_all.py",
}


def run(script: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS[script]), *args],
        capture_output=True,
        check=False,
        text=True,
        env=dict(os.environ),
        timeout=60,
    )


def ok(script: str, *args: str) -> dict:
    done = run(script, *args)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_add_keeps_the_words_for_the_runtimes_only_agent(runtime) -> None:
    runtime.agent("default")
    assert ok("add", "--content", "Prefers answers in French") == {
        "agent": "default",
        "added": 1,
        "content": "Prefers answers in French",
    }
    (kept,) = runtime.memories["default"]
    assert kept["content"] == "Prefers answers in French"
    assert kept["metadata"] == {"source": "datalayer-memory-add"}
    # Only the words and their source are sent: no user, no scope.
    method, url, body = runtime.requests[-1]
    assert (method, url) == ("POST", "/api/v1/agents/default/memory")
    assert set(body) == {"content", "metadata"}


def test_search_answers_the_closest_up_to_the_limit(runtime) -> None:
    runtime.agent("default")
    for words in ("likes French", "works in French and English", "uses Python"):
        runtime.keep("default", words)
    found = ok("search", "--query", "french", "--limit", "1")
    assert found["count"] == 1 and found["query"] == "french"
    assert found["memories"][0]["content"] == "likes French"


def test_list_answers_newest_first_with_ids_and_the_total(runtime) -> None:
    runtime.agent("default")
    runtime.keep("default", "first")
    runtime.keep("default", "second")
    listed = ok("list", "--limit", "1")
    assert listed["total"] == 2 and listed["count"] == 1
    assert listed["memories"][0]["content"] == "second"
    assert listed["memories"][0]["id"] == "mem-2"


def test_delete_forgets_one_and_an_unknown_id_is_not_found(runtime) -> None:
    runtime.agent("default")
    runtime.keep("default", "first")
    runtime.keep("default", "second")
    assert ok("delete", "--id", "mem-1")["forgotten"] == 1
    assert [e["content"] for e in runtime.memories["default"]] == ["second"]
    refused = run("delete", "--id", "mem-1")
    assert refused.returncode == 1
    assert "remembers nothing as mem-1" in refused.stderr


def test_delete_all_forgets_only_up_to_the_confirmed_count(runtime) -> None:
    runtime.agent("default")
    for words in ("one", "two", "three"):
        runtime.keep("default", words)
    refused = run("delete_all", "--count", "2")
    assert refused.returncode == 1
    assert "more than the 2 you confirmed" in refused.stderr
    assert len(runtime.memories["default"]) == 3
    assert ok("delete_all", "--count", "3") == {"agent": "default", "forgotten": 3}
    assert runtime.memories["default"] == []


def test_delete_all_needs_the_count(runtime) -> None:
    runtime.agent("default")
    assert run("delete_all").returncode == 2


def test_the_agent_is_named_when_several_run(runtime, monkeypatch) -> None:
    runtime.agent("crawler")
    runtime.agent("writer")
    refused = run("list")
    assert refused.returncode == 1
    assert "Several agents run on this runtime (crawler, writer)" in refused.stderr
    runtime.keep("writer", "a writer's memory")
    assert ok("list", "--agent", "writer")["total"] == 1
    monkeypatch.setenv("AGENT_RUNTIMES_AGENT_ID", "crawler")
    assert ok("list")["agent"] == "crawler"


def test_an_agent_without_durable_memory_says_so(runtime) -> None:
    runtime.agent("default")
    refused = run("add", "--content", "x", "--agent", "elsewhere")
    assert refused.returncode == 1
    assert "has no durable memory" in refused.stderr


def test_a_runtime_that_cannot_keep_memories_says_why(runtime) -> None:
    runtime.agent("default")
    runtime.refusal = "Memories cannot be kept on this runtime: no PostgreSQL is configured."
    refused = run("add", "--content", "x")
    assert refused.returncode == 1
    assert runtime.refusal in refused.stderr


def test_an_unreachable_runtime_is_said(runtime) -> None:
    refused = run("list", "--agent", "default", "--runtime-url", "http://127.0.0.1:9")
    assert refused.returncode == 1
    assert "cannot be reached" in refused.stderr


def test_the_runtime_on_the_loopback_by_default(monkeypatch) -> None:
    monkeypatch.delenv("AGENT_RUNTIMES_URL", raising=False)
    monkeypatch.setenv("AGENT_RUNTIMES_PORT", "9")
    refused = run("list", "--agent", "default")
    assert refused.returncode == 1
    assert "http://127.0.0.1:9 cannot be reached" in refused.stderr
