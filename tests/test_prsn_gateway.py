"""Tests for prsn_gateway: discovery, choosing a PRSN, and the MCP client against a fake server.

Run from the repository's root:  python3 -m unittest discover -s tests -v
Standard library only.
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import prsn_gateway as pg  # noqa: E402

FAKE = str(Path(__file__).resolve().parent / "fake_gateway_mcp.py")


def entry_json(name: str, address: str, mode: str = "normal", enabled: bool = True,
               locked: bool = True) -> dict:
    args = [FAKE, "--mode", mode]
    if locked:
        args += ["--prsn-address", address]
    return {"ensName": name, "walletAddress": address, "gatewayEnabled": enabled,
            "mcpConfig": {"command": sys.executable, "args": args}}


class DiscoveryFile:
    """A temporary gateway.json in the version 3 shape PRSN Connect writes."""

    def __init__(self, *entries: dict):
        self._dir = tempfile.TemporaryDirectory()
        self.path = Path(self._dir.name) / "gateway.json"
        self.write(*entries)

    def write(self, *entries: dict) -> None:
        self.path.write_text(json.dumps({
            "version": 3, "transport": {"tcp": {"host": "127.0.0.1", "port": 7331}, "socket": "x"},
            "prsns": list(entries), "trustPolicy": "scoped", "learnMore": "https://prsnid.ai",
        }), encoding="utf-8")

    def cleanup(self) -> None:
        self._dir.cleanup()


class TestDiscovery(unittest.TestCase):
    def test_missing_file(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(pg.GatewayError) as cm:
                pg.read_discovery(Path(d) / "gateway.json")
        self.assertEqual(cm.exception.code, pg.NO_DISCOVERY)

    def test_unreadable_json(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "gateway.json"
            p.write_text("{not json", encoding="utf-8")
            with self.assertRaises(pg.GatewayError) as cm:
                pg.read_discovery(p)
        self.assertEqual(cm.exception.code, pg.BAD_DISCOVERY)

    def test_reads_entries_and_skips_one_without_a_command(self):
        broken = {"ensName": "b.prsn.eth", "walletAddress": "0x2", "gatewayEnabled": True}
        f = DiscoveryFile(entry_json("a.prsn.eth", "0x1"), broken)
        try:
            entries = pg.read_discovery(f.path)
        finally:
            f.cleanup()
        self.assertEqual([e.ens_name for e in entries], ["a.prsn.eth"])
        self.assertIn("--prsn-address", entries[0].args)


class TestChoosePrsn(unittest.TestCase):
    def setUp(self):
        self.a = pg.PrsnEntry("a.prsn.eth", "0xAAA", True, "cmd", ("--prsn-address", "0xAAA"))
        self.b = pg.PrsnEntry("b.prsn.eth", "0xBBB", True, "cmd", ("--prsn-address", "0xBBB"))

    def code(self, entries, name):
        with self.assertRaises(pg.GatewayError) as cm:
            pg.choose_prsn(entries, name)
        return cm.exception.code

    def test_none_served(self):
        self.assertEqual(self.code([], None), pg.NO_PRSN)

    def test_only_one_is_chosen(self):
        self.assertIs(pg.choose_prsn([self.a], None), self.a)

    def test_several_need_the_setting(self):
        self.assertEqual(self.code([self.a, self.b], None), pg.CHOOSE_PRSN)

    def test_setting_by_name_or_address_any_case(self):
        self.assertIs(pg.choose_prsn([self.a, self.b], "B.PRSN.ETH"), self.b)
        self.assertIs(pg.choose_prsn([self.a, self.b], "0xbbb"), self.b)

    def test_setting_names_an_unknown_prsn(self):
        self.assertEqual(self.code([self.a], "c.prsn.eth"), pg.UNKNOWN_PRSN)

    def test_disabled_gateway(self):
        off = pg.PrsnEntry("a.prsn.eth", "0xAAA", False, "cmd", ("--prsn-address", "0xAAA"))
        self.assertEqual(self.code([off], None), pg.GATEWAY_DISABLED)

    def test_never_starts_an_unlocked_server(self):
        unlocked = pg.PrsnEntry("a.prsn.eth", "0xAAA", True, "cmd", ())
        self.assertEqual(self.code([unlocked], None), pg.BAD_DISCOVERY)


class GatewayCase(unittest.TestCase):
    """A Gateway over a fake server; each test names the fake's mode."""

    def gateway(self, mode: str = "normal") -> pg.Gateway:
        f = DiscoveryFile(entry_json("test-prsn.prsn.eth", "0xabc", mode=mode))
        self.addCleanup(f.cleanup)
        g = pg.Gateway(path=f.path)
        self.addCleanup(g.close)
        self.discovery = f
        return g


class TestGateway(GatewayCase):
    def test_reads_profile_and_status(self):
        g = self.gateway()
        profile = g.call("get_profile")
        self.assertEqual(profile["identity"]["ensName"], "test-prsn.prsn.eth")
        self.assertEqual(profile["hwbeat"]["status"], "on-time")
        self.assertEqual(g.call("get_gateway_status")["gateway_state"], "connected")
        self.assertEqual(g.entry.ens_name, "test-prsn.prsn.eth")

    def test_profile_carries_own_verified(self):
        # v0.2.1 (BUG-229): a PRSN reads its own standing in its profile; nothing asks about another.
        g = self.gateway()
        self.assertIs(g.call("get_profile")["identity"]["verified"], True)

    def test_server_started_once_for_many_calls(self):
        g = self.gateway()
        g.call("get_profile")
        first = g._client
        g.call("get_gateway_status")
        self.assertIs(g._client, first)

    def test_a_changed_prsn_name_starts_the_named_prsns_server(self):
        # Found in the onboarding test, 2026-11-09: a prsn_name set after the server started was
        # ignored until Hermes restarted. Now the next call speaks for the PRSN the setting names.
        f = DiscoveryFile(entry_json("a.prsn.eth", "0xaaa"), entry_json("b.prsn.eth", "0xbbb"))
        self.addCleanup(f.cleanup)
        name = {"value": "a.prsn.eth"}
        g = pg.Gateway(prsn_name=lambda: name["value"], path=f.path)
        self.addCleanup(g.close)
        g.call("get_profile")
        first = g._client
        self.assertEqual(g.entry.ens_name, "a.prsn.eth")
        g.call("get_profile")
        self.assertIs(g._client, first)  # the same name keeps its server
        name["value"] = "B.prsn.eth"
        g.call("get_profile")
        self.assertIsNot(g._client, first)
        self.assertFalse(first.alive)
        self.assertEqual(g.entry.ens_name, "b.prsn.eth")

    def test_refusal_passes_connect_words_through(self):
        g = self.gateway("refuse")
        with self.assertRaises(pg.GatewayError) as cm:
            g.call("get_profile")
        self.assertEqual(cm.exception.code, pg.REFUSED)
        self.assertEqual(cm.exception.connect_words,
                         "PRSN Connect is not running. Start it, then try again.")

    def test_server_exits_mid_call(self):
        g = self.gateway("exit_call")
        with self.assertRaises(pg.GatewayError) as cm:
            g.call("get_profile")
        # It restarts once and the new server exits too, so the call ends as gone.
        self.assertEqual(cm.exception.code, pg.SERVER_GONE)

    def test_hung_server_times_out_and_is_dropped(self):
        g = self.gateway("hang_call")
        started = time.monotonic()
        with self.assertRaises(pg.GatewayError) as cm:
            g.call("get_profile", timeout=0.5)
        self.assertEqual(cm.exception.code, pg.TIMEOUT)
        self.assertLess(time.monotonic() - started, 5)
        self.assertIsNone(g._client)  # the next call starts afresh

    def test_slow_start_within_the_limit(self):
        g = self.gateway("slow_start")
        self.assertEqual(g.call("get_gateway_status")["gateway_state"], "connected")

    def test_noise_and_a_server_ping_are_handled(self):
        g = self.gateway("noise")
        self.assertEqual(g.call("get_profile")["identity"]["ensName"], "test-prsn.prsn.eth")

    def test_a_listed_prsn_with_no_server_says_update_prsn_connect(self):
        # PRSN Connect v0.2.0 on Windows and Linux (BUG-231): the PRSN listed, no mcpConfig.
        bare = {"ensName": "win.prsn.eth", "walletAddress": "0x58b8", "gatewayEnabled": True}
        f = DiscoveryFile(bare)
        self.addCleanup(f.cleanup)
        with self.assertRaises(pg.GatewayError) as cm:
            pg.read_discovery(f.path)
        self.assertEqual(cm.exception.code, pg.NO_SERVER)
        f.write()  # nothing listed at all is still no PRSN
        self.assertEqual(pg.read_discovery(f.path), [])

    def test_a_prsn_bound_mid_session_is_found(self):
        f = DiscoveryFile()  # nothing served yet
        self.addCleanup(f.cleanup)
        g = pg.Gateway(path=f.path)
        self.addCleanup(g.close)
        with self.assertRaises(pg.GatewayError) as cm:
            g.call("get_profile")
        self.assertEqual(cm.exception.code, pg.NO_PRSN)
        f.write(entry_json("test-prsn.prsn.eth", "0xabc"))  # PRSN Connect binds one
        self.assertEqual(g.call("get_profile")["identity"]["ensName"], "test-prsn.prsn.eth")

    def test_the_reader_thread_runs_in_the_callers_context(self):
        import contextvars
        marker = contextvars.ContextVar("profile_home_marker", default="root")
        seen = {}
        original = pg.McpClient._read_loop

        def spy(client):
            seen["value"] = marker.get()
            return original(client)

        pg.McpClient._read_loop = spy
        self.addCleanup(setattr, pg.McpClient, "_read_loop", original)
        token = marker.set("prsn-id-test")
        self.addCleanup(marker.reset, token)
        g = self.gateway()
        g.call("get_gateway_status")
        self.assertEqual(seen.get("value"), "prsn-id-test")

    def test_server_log_is_kept_only_when_asked(self):
        f = DiscoveryFile(entry_json("test-prsn.prsn.eth", "0xabc"))
        self.addCleanup(f.cleanup)
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        log = Path(d.name) / "server.log"
        g = pg.Gateway(path=f.path, server_log=lambda: log)
        self.addCleanup(g.close)
        g.call("get_gateway_status")
        g.close()
        self.assertIn("fake prsn-gateway-mcp started", log.read_text(encoding="utf-8"))
        g2 = pg.Gateway(path=f.path)
        self.addCleanup(g2.close)
        g2.call("get_gateway_status")
        self.assertEqual(sorted(p.name for p in Path(d.name).iterdir()), ["server.log"])

    def test_missing_program(self):
        f = DiscoveryFile({"ensName": "a.prsn.eth", "walletAddress": "0x1", "gatewayEnabled": True,
                           "mcpConfig": {"command": "/nonexistent/prsn-gateway-mcp",
                                         "args": ["--prsn-address", "0x1"]}})
        self.addCleanup(f.cleanup)
        g = pg.Gateway(path=f.path)
        self.addCleanup(g.close)
        with self.assertRaises(pg.GatewayError) as cm:
            g.call("get_profile")
        self.assertEqual(cm.exception.code, pg.START_FAILED)


if __name__ == "__main__":
    unittest.main()
