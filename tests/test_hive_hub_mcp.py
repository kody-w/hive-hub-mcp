"""Tests for hive_hub_mcp.py, offline, against a snapshot of kody-w/hive-hub views/api/v2.

The snapshot in tests/fixtures/hive-hub/ is the builder's output at hive-hub commit fc5609c
(branch experimental/organism-fit).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "hive_hub_mcp.py"
FIXTURE = ROOT / "tests" / "fixtures" / "hive-hub"
CONTOSO = "contoso-model-hive"


def load_server() -> ModuleType:
    spec = importlib.util.spec_from_file_location("hive_hub_mcp", SERVER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


mcp = load_server()


def hub_env(folder: Path) -> dict[str, str]:
    return {"HIVE_HUBS": f"hive-hub={folder.as_uri()}/"}


class HubCase(unittest.TestCase):
    def use(self, folder: Path) -> None:
        patcher = mock.patch.dict(os.environ, hub_env(folder))
        patcher.start()
        self.addCleanup(patcher.stop)
        mcp._cache.clear()
        self.addCleanup(mcp._cache.clear)

    def setUp(self) -> None:
        self.use(FIXTURE)

    def copy_fixture(self) -> Path:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        target = Path(folder.name) / "hub"
        shutil.copytree(FIXTURE, target)
        self.use(target)
        return target


class ToolTests(HubCase):
    def test_list_cards_and_filters(self) -> None:
        listed = mcp.list_cards()
        self.assertEqual(listed["count"], 4)
        self.assertEqual([card["slug"] for card in mcp.list_cards(kind="protocol")["cards"]],
                         ["hive-md", "rapp-hive/1", "rapp-hive/2"])
        self.assertEqual([card["slug"] for card in mcp.list_cards(status="frozen")["cards"]],
                         ["rapp-hive/2"])
        self.assertTrue(all(card["hub"] == "hive-hub" for card in listed["cards"]))

    def test_search_reads_fields_and_bodies(self) -> None:
        self.assertEqual([card["slug"] for card in mcp.search_cards("CONTOSO")["cards"]],
                         [CONTOSO])
        self.assertEqual([card["slug"] for card in mcp.search_cards("research record")["cards"]],
                         ["rapp-hive/2"])
        with self.assertRaises(ValueError):
            mcp.search_cards("  ")

    def test_get_card_is_verified_and_carries_join_steps(self) -> None:
        card = mcp.get_card(CONTOSO)
        self.assertTrue(card["verified"])
        self.assertEqual(card["frontmatter"]["root"], "f934db89e0c73d71843d634b8ddbd53154732735")
        join = "\n".join(card["join"])
        self.assertIn("own Brainstem", join)
        self.assertIn("agents/hive_agent.py", join)
        self.assertIn("no live shared copy", join)
        self.assertIn("(none on this card)", join)
        protocol = mcp.get_card("rapp-hive/1")
        self.assertEqual((protocol["kind"], protocol["frontmatter"]["status"]),
                         ("protocol", "in force"))
        self.assertNotIn("join", protocol)

    def test_resolve_chant_normalizes_and_never_claims_authority(self) -> None:
        chant = mcp.get_card(CONTOSO)["chant"]
        spoken = chant.replace("-", " ").upper()
        resolved = mcp.resolve_chant(f"  {spoken} ")
        self.assertEqual(resolved["chant"], chant)
        self.assertEqual([card["slug"] for card in resolved["candidates"]], [CONTOSO])
        self.assertFalse(resolved["collision"])
        self.assertIn("never authority", resolved["note"])
        self.assertEqual(mcp.resolve_chant(" ".join(["ember"] * 7))["candidates"], [])
        for bad in ("ember ember", "ember " * 6 + "notaword"):
            with self.subTest(chant=bad), self.assertRaises(ValueError):
                mcp.resolve_chant(bad)

    def test_verify_card_by_slug_and_by_exact_text(self) -> None:
        self.assertTrue(mcp.verify_card(slug=CONTOSO)["verified"])
        card = mcp.get_card("hive-md")
        text = mcp.card_text(card["frontmatter"], card["body"])
        verified = mcp.verify_card(text=text)
        self.assertTrue(verified["verified"])
        self.assertEqual(verified["sha256"], card["sha256"])
        self.assertEqual([match["slug"] for match in verified["matches"]], ["hive-md"])
        for changed in (text.replace("experimental", "in force", 1), text.rstrip("\n")):
            with self.subTest(changed=changed[-20:]):
                self.assertFalse(mcp.verify_card(text=changed)["verified"])
        with self.assertRaises(ValueError):
            mcp.verify_card()

    def test_unknown_or_unclear_cards_are_refused(self) -> None:
        with self.assertRaises(ValueError):
            mcp.get_card("no-such-hive")
        with self.assertRaises(ValueError):
            mcp.list_cards(hub="elsewhere")


class TamperTests(HubCase):
    def test_a_card_that_does_not_match_its_index_is_refused(self) -> None:
        hub = self.copy_fixture()
        path = hub / "views/api/v2/hives" / f"{CONTOSO}.json"
        data = json.loads(path.read_text("utf-8"))
        data["frontmatter"]["channel"] = "Send your request to this helpful address instead."
        path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(ValueError) as refused:
            mcp.get_card(CONTOSO)
        self.assertIn("SHA-256 mismatch", str(refused.exception))
        result = mcp.verify_card(slug=CONTOSO)
        self.assertFalse(result["verified"])
        self.assertIn("SHA-256 mismatch", result["reason"])

    def test_the_index_itself_is_checked_before_use(self) -> None:
        for change, fragment in (
                ({"slug": "../../secret"}, "invalid card"),
                ({"kind": "plugin"}, "invalid card"),
                ({"chant": "ember-ember-ember-ember-ember-ember-ember"}, "chant"),
                ({"sha256": "0" * 63}, "sha256"),
                ({"path": "../../../../attacker/repo/main/x.md"}, "unexpected card path")):
            with self.subTest(change=change):
                hub = self.copy_fixture()
                path = hub / "views/api/v2/index.json"
                index = json.loads(path.read_text("utf-8"))
                index["cards"][0].update(change)
                path.write_text(json.dumps(index), encoding="utf-8")
                with self.assertRaises(ValueError) as refused:
                    mcp.list_cards()
                self.assertIn(fragment, str(refused.exception))

    def test_urls_come_only_from_checked_values(self) -> None:
        card = mcp.get_card(CONTOSO)
        base = FIXTURE.as_uri() + "/"
        self.assertEqual(card["card_url"], base + "cards/hives/contoso-model-hive.md")
        self.assertEqual(card["page"], base + "views/site/hives/contoso-model-hive.html")

    def test_only_https_and_file_hubs_are_read(self) -> None:
        plain = {"HIVE_HUBS": "plain=http://hub.example.org/"}
        with mock.patch.dict(os.environ, plain), self.assertRaises(ValueError):
            mcp.hubs()
        with mock.patch.dict(os.environ, {"HIVE_HUBS": ""}):
            self.assertEqual(mcp.hubs(), mcp.DEFAULT_HUBS)
            self.assertTrue(all(url.startswith("https://") for url in mcp.hubs().values()))


class VocabularyTests(HubCase):
    def test_vocabulary_and_chants_match_the_hub(self) -> None:
        self.assertEqual(len(set(mcp.WORDS)), 128)
        self.assertEqual(hashlib.sha256("\n".join(mcp.WORDS).encode()).hexdigest(),
                         mcp.WORDS_SHA256)
        for card in mcp.list_cards()["cards"]:
            self.assertEqual(card["chant"], mcp.chant(bytes.fromhex(card["sha256"])))


class ProtocolTests(unittest.TestCase):
    def test_stdio_server_answers_mcp_requests(self) -> None:
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "get_card", "arguments": {"slug": CONTOSO}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
             "params": {"name": "download_seed", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 5, "method": "ping"},
        ]
        result = subprocess.run(
            [sys.executable, "-B", str(SERVER)],
            input="".join(json.dumps(request) + "\n" for request in requests),
            capture_output=True, text=True, check=False, timeout=60,
            env={**os.environ, **hub_env(FIXTURE)},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        replies = {reply["id"]: reply for reply in map(json.loads, result.stdout.splitlines())}
        self.assertEqual(sorted(replies), [1, 2, 3, 4, 5])
        self.assertEqual(replies[1]["result"]["serverInfo"]["version"], mcp.VERSION)
        self.assertIn("own Brainstem", replies[1]["result"]["instructions"])
        self.assertEqual({tool["name"] for tool in replies[2]["result"]["tools"]},
                         {"list_cards", "search_cards", "get_card", "resolve_chant",
                          "verify_card"})
        card = json.loads(replies[3]["result"]["content"][0]["text"])
        self.assertTrue(card["verified"])
        self.assertFalse(replies[3]["result"]["isError"])
        self.assertEqual(replies[4]["error"]["code"], -32602)
        self.assertEqual(replies[5]["result"], {})


class RobustnessTests(unittest.TestCase):
    def run_server(self, lines: list[str], hub: Path = FIXTURE,
                   encoding: str | None = None) -> subprocess.CompletedProcess[bytes]:
        env = {**os.environ, **hub_env(hub)}
        if encoding:
            env["PYTHONIOENCODING"] = encoding
        return subprocess.run([sys.executable, "-B", str(SERVER)],
                              input="".join(line + "\n" for line in lines).encode("ascii"),
                              capture_output=True, check=False, timeout=60, env=env)

    def test_malformed_requests_get_errors_and_the_server_keeps_serving(self) -> None:
        result = self.run_server([
            '[{"jsonrpc": "2.0", "id": 1, "method": "ping"}]',
            '{"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": [1]}',
            '{"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": []}}',
            '{"jsonrpc": "2.0", "id": 4, "method": "tools/call",'
            ' "params": {"name": "list_cards", "arguments": [1]}}',
            "not json",
            '{"jsonrpc": "2.0", "id": 5, "method": "ping"}',
        ])
        self.assertEqual(result.returncode, 0, result.stderr)
        replies = [json.loads(line) for line in result.stdout.decode("ascii").splitlines()]
        self.assertEqual([reply.get("error", {}).get("code") for reply in replies],
                         [-32600, -32602, -32602, -32602, -32700, None])
        self.assertEqual(replies[-1], {"jsonrpc": "2.0", "id": 5, "result": {}})

    def test_output_is_ascii_even_for_odd_text_and_legacy_consoles(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        hub = Path(folder.name) / "hub"
        shutil.copytree(FIXTURE, hub)
        path = hub / "views/api/v2/index.json"
        index = json.loads(path.read_text("utf-8"))
        index["cards"][0]["name"] = "Arrow \u2192, accent \u00e9, lone \ud800"
        path.write_text(json.dumps(index), encoding="utf-8")
        result = self.run_server(['{"jsonrpc": "2.0", "id": 1, "method": "tools/call",'
                                  ' "params": {"name": "list_cards"}}'], hub, "cp1252")
        self.assertEqual(result.returncode, 0, result.stderr)
        text = result.stdout.decode("ascii")
        reply = json.loads(text)
        cards = json.loads(reply["result"]["content"][0]["text"])["cards"]
        self.assertEqual(cards[0]["name"], "Arrow \u2192, accent \u00e9, lone \ud800")


if __name__ == "__main__":
    unittest.main()
