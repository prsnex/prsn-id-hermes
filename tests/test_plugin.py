"""Tests for the plugin's registration, hooks, tools and words, with a stand-in for Hermes's ctx.

Run from the repository's root:  python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
import tempfile
import time
import types
import unittest
from unittest import mock
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_prsn_gateway import DiscoveryFile, entry_json  # noqa: E402
from fake_gateway_mcp import SEAL_LINK  # noqa: E402


def load_plugin():
    """Load the repository as a package, as Hermes does, so its relative imports work."""
    spec = importlib.util.spec_from_file_location(
        "prsn_id_plugin", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
    module = importlib.util.module_from_spec(spec)
    sys.modules["prsn_id_plugin"] = module
    spec.loader.exec_module(module)
    return module


plugin = load_plugin()
pg = sys.modules["prsn_id_plugin.prsn_gateway"]
words = sys.modules["prsn_id_plugin.words"]
LABEL = words.CONTEXT_LABEL


class FakeCtx:
    """Records what register() asks of Hermes; settings come from a dict."""

    def __init__(self, settings=None):
        self.settings = settings or {}
        self.tools, self.hooks, self.commands = {}, {}, {}

    def get_config(self, key, default=None):
        return self.settings.get(key, default)

    def register_tool(self, name, toolset, schema, handler, **kwargs):
        self.tools[name] = {"toolset": toolset, "schema": schema, "handler": handler, **kwargs}

    def register_hook(self, name, callback, **kwargs):
        self.hooks[name] = callback

    def register_command(self, name, handler, **kwargs):
        self.commands[name] = {"handler": handler, **kwargs}


class TestRegister(unittest.TestCase):
    def test_registers_six_tools_three_hooks_one_command(self):
        ctx = FakeCtx()
        plugin.register(ctx)
        self.assertEqual(sorted(ctx.tools), sorted(plugin.TOOLS))
        self.assertEqual(sorted(ctx.hooks), ["post_compaction", "pre_llm_call", "pre_tool_call"])
        self.assertEqual(list(ctx.commands), ["prsn"])
        for name, tool in ctx.tools.items():
            self.assertEqual(tool["schema"]["name"], name)
            self.assertEqual(tool["schema"]["parameters"]["type"], "object")
            self.assertNotIn("$schema", tool["schema"]["parameters"])

    def test_nothing_else_is_offered(self):
        for forbidden in ("purchase_service", "issue_credential", "revoke_issued_credential",
                          "discard_credential", "get_verification_url", "identify_as"):
            self.assertNotIn(forbidden, plugin.TOOLS.values())

    def test_the_header_and_footer_email_seal_is_not_offered(self):
        # Hermes masks the statement in what the agent writes, so the header and footer would break.
        self.assertNotIn("prsn_id_seal_email", plugin.TOOLS)
        self.assertNotIn("seal_email", plugin.TOOLS.values())
        self.assertEqual(plugin.SEAL_TOOLS, {"prsn_id_seal_message", "prsn_id_seal_file"})

    def test_seal_tools_keep_connects_required_fields(self):
        schemas = plugin._load_tool_schemas()
        self.assertEqual(schemas["prsn_id_seal_file"]["parameters"]["required"], ["path"])
        self.assertIn("output_path", schemas["prsn_id_seal_message"]["parameters"]["required"])


class RuntimeCase(unittest.TestCase):
    def runtime(self, mode="normal", settings=None, served=True):
        f = DiscoveryFile(entry_json("test-prsn.prsn.eth", "0xabc", mode=mode)) if served else DiscoveryFile()
        self.addCleanup(f.cleanup)
        ctx = FakeCtx(settings)
        gateway = pg.Gateway(prsn_name=lambda: (ctx.settings.get("prsn_name") or None), path=f.path)
        self.addCleanup(gateway.close)
        status_dir = tempfile.TemporaryDirectory()
        self.addCleanup(status_dir.cleanup)
        self.status_folder = Path(status_dir.name)
        self.opened = []  # pages the plugin asked the browser to open; no real browser in tests
        self.browser_works = True

        def fake_open(link):
            self.opened.append(link)
            return self.browser_works

        return plugin.Runtime(ctx, gateway=gateway, status_folder=self.status_folder,
                              open_page=fake_open)


class TestApproval(RuntimeCase):
    def test_each_seal_asks_the_human(self):
        rt = self.runtime()
        for tool in plugin.SEAL_TOOLS:
            directive = rt.pre_tool_call(tool_name=tool, args={"to": ["a@example.com"], "path": "/x/report.pdf"})
            self.assertEqual(directive["action"], "approve")
            self.assertIn("A Seal speaks for", directive["message"])
            self.assertTrue(directive["rule_key"].startswith("prsn-id:"))

    def test_reads_and_other_tools_are_not_asked_about(self):
        rt = self.runtime()
        for tool in ("prsn_id_profile", "prsn_id_status", "terminal", "read_file"):
            self.assertIsNone(rt.pre_tool_call(tool_name=tool, args={}))

    def test_the_question_names_what_and_who(self):
        rt = self.runtime(settings={"prsn_name": "test-prsn.prsn.eth"})
        email = rt.pre_tool_call(tool_name="prsn_id_seal_message", args={"to": ["a@example.com", "b@example.com"]})
        self.assertIn("an email to a@example.com, b@example.com as test-prsn.prsn.eth", email["message"])
        file = rt.pre_tool_call(tool_name="prsn_id_seal_file", args={"path": "/tmp/q3/report.pdf"})
        self.assertIn("the file report.pdf", file["message"])


class TestTools(RuntimeCase):
    def test_profile_through_the_tool(self):
        rt = self.runtime()
        out = json.loads(rt.handle_tool("prsn_id_profile", {}))
        self.assertEqual(out["identity"]["ensName"], "test-prsn.prsn.eth")

    def test_a_seal_by_a_verified_prsn_goes_through(self):
        rt = self.runtime()
        out = json.loads(rt.handle_tool("prsn_id_seal_file", {"path": "/tmp/x"}))
        self.assertTrue(out["ok"])

    def test_a_file_seal_opens_its_page_for_the_human(self):
        rt = self.runtime()
        out = json.loads(rt.handle_tool("prsn_id_seal_file", {"path": "/tmp/x"}))
        self.assertEqual(self.opened, [SEAL_LINK])
        self.assertTrue(out["page_opened"])
        self.assertEqual(out["note"], words.FILE_SEAL_PAGE_OPENED)
        self.assertEqual(out["link"], SEAL_LINK)  # the result keeps the link

    def test_no_browser_still_gives_the_seal_and_says_so(self):
        rt = self.runtime()
        self.browser_works = False
        out = json.loads(rt.handle_tool("prsn_id_seal_file", {"path": "/tmp/x"}))
        self.assertTrue(out["ok"])
        self.assertFalse(out["page_opened"])
        self.assertEqual(out["note"], words.FILE_SEAL_PAGE_NOT_OPENED)

    def test_an_email_seal_opens_no_page(self):
        rt = self.runtime()
        json.loads(rt.handle_tool("prsn_id_seal_message", {"to": ["a@example.com"]}))
        self.assertEqual(self.opened, [])

    def test_only_a_prsn_id_seal_page_is_ever_opened(self):
        rt = self.runtime()
        for link in ("https://example.com/s/x",
                     "https://verify.prsnid.ai/s/../x",
                     "https://verify.prsnid.ai/s/" + "A" * 43,
                     "https://verify.prsnid.ai/s/" + "A" * 43 + "#eyJ2IjoxfQ.MEUC/../x",
                     "https://verify.prsnid.ai.example.com/s/" + "A" * 43 + "#eyJ2.MEUC"):
            rt.gateway.call = lambda name, args=None, _l=link, **kw: {"ok": True, "link": _l}
            out = json.loads(rt.handle_tool("prsn_id_seal_file", {"path": "/tmp/x"}))
            self.assertNotIn("page_opened", out, link)
        self.assertEqual(self.opened, [])

    def test_linux_with_no_display_opens_nothing(self):
        with mock.patch.object(plugin.sys, "platform", "linux"), \
                mock.patch.dict(plugin.os.environ, {}, clear=True), \
                mock.patch.object(plugin.webbrowser, "open") as opener:
            self.assertFalse(plugin.open_in_browser(SEAL_LINK))
            opener.assert_not_called()
        with mock.patch.object(plugin.sys, "platform", "linux"), \
                mock.patch.dict(plugin.os.environ, {"WAYLAND_DISPLAY": "wayland-0"}, clear=True), \
                mock.patch.object(plugin.webbrowser, "open", return_value=True):
            self.assertTrue(plugin.open_in_browser(SEAL_LINK))

    def test_a_raising_browser_is_caught(self):
        with mock.patch.object(plugin.webbrowser, "open", side_effect=RuntimeError("no display")):
            self.assertFalse(plugin.open_in_browser(SEAL_LINK))

    def test_a_prsn_not_verified_now_is_told_plainly_it_cannot_seal(self):
        rt = self.runtime(mode="unverified")
        out = json.loads(rt.handle_tool("prsn_id_seal_file", {"path": "/tmp/x"}))
        self.assertTrue(out["error"].startswith(words.STATE_NOT_VERIFIED_NOW))
        self.assertIn("No Seal can be made until it is verified again.", out["error"])
        self.assertNotIn("Registered", out["error"])

    def test_connects_refusal_words_reach_the_agent_unchanged(self):
        rt = self.runtime(mode="refuse")
        out = json.loads(rt.handle_tool("prsn_id_status", {}))
        self.assertEqual(out["error"], "PRSN Connect is not running. Start it, then try again.")
        self.assertEqual(out["note"], words.AFTER_REFUSAL)  # tell the human; no way around it

    def test_a_prsn_not_verified_is_also_told_to_stop(self):
        rt = self.runtime(mode="unverified")
        out = json.loads(rt.handle_tool("prsn_id_seal_file", {"path": "/tmp/x"}))
        self.assertEqual(out["note"], words.AFTER_REFUSAL)


class TestDirectToPrsnConnect(RuntimeCase):
    """Seen 2026-11-10: after a refusal an agent planned to start PRSN Connect's server itself."""

    REACHES = [
        ("terminal", {"command": "Get-Content $HOME\\.prsn-id\\gateway.json"}),
        ("terminal", {"command": "cat ~/.prsn-id/gateway.json"}),
        ("terminal", {"command": '"C:/Users/a/AppData/Local/PRSN Connect/prsn-gateway-mcp.exe" --prsn-address 0x1'}),
        ("execute_code", {"code": "open(r'\\\\.\\pipe\\prsn-connect-efa2')"}),
        ("read_file", {"path": "C:/Users/a/AppData/Roaming/prsn-connect/tokens/0xabc.token"}),
        ("terminal", {"command": "curl -s http://127.0.0.1:7331/self/capabilities"}),
        ("process_manage", {"command": "start", "args": ["localhost:7334"]}),
        ("browser_cdp", {"url": "http://127.0.0.1:7331/self/capabilities"}),
        ("skill_manage", {"action": "create", "content": "subprocess.run(['prsn-gateway-mcp', '--prsn-address', a])"}),
        ("cronjob_manage", {"script": "curl http://host.docker.internal:7331/"}),
        ("terminal", {"command": "find / -name gateway.json"}),
    ]
    LEAVES = [
        ("terminal", {"command": "ls ~/Desktop"}),
        ("terminal", {"command": "himalaya smtp send -f a@example.com -t b@example.com -- /tmp/x.eml"}),
        ("read_file", {"path": "/home/a/notes.md"}),
        ("session_search", {"query": "PRSN Connect"}),   # not a command or file tool
        ("prsn_id_status", {}),
    ]

    def test_a_command_that_reaches_prsn_connect_asks_the_human(self):
        rt = self.runtime()
        for tool, args in self.REACHES:
            directive = rt.pre_tool_call(tool_name=tool, args=args)
            self.assertIsNotNone(directive, (tool, args))
            self.assertEqual(directive["action"], "approve")
            self.assertEqual(directive["message"], words.DIRECT_TO_PRSN_CONNECT)
            self.assertTrue(directive["rule_key"].startswith("prsn-id:direct-to-prsn-connect:"))

    def test_each_call_has_its_own_rule_key(self):
        # One key for every call would let one "Always allow" switch the guard off for good.
        rt = self.runtime()
        keys = {rt.pre_tool_call(tool_name=t, args=a)["rule_key"] for t, a in self.REACHES}
        self.assertEqual(len(keys), len(self.REACHES))
        again = rt.pre_tool_call(tool_name=self.REACHES[0][0], args=dict(self.REACHES[0][1]))
        self.assertIn(again["rule_key"], keys)  # the same call asks under the same key

    def test_other_commands_and_tools_are_left_alone(self):
        rt = self.runtime()
        for tool, args in self.LEAVES:
            self.assertIsNone(rt.pre_tool_call(tool_name=tool, args=args), (tool, args))


class TestTurns(RuntimeCase):
    def test_identity_on_the_first_turn_only(self):
        rt = self.runtime()
        first = rt.pre_llm_call(session_id="s1", user_message="hi", is_first_turn=True)
        self.assertEqual(first["context"], LABEL + "\nYou are test-prsn.prsn.eth, a verified PRSN.")
        self.assertIsNone(rt.pre_llm_call(session_id="s1", user_message="again", is_first_turn=False))

    def test_identity_again_after_a_compaction(self):
        rt = self.runtime()
        rt.pre_llm_call(session_id="s1", user_message="hi", is_first_turn=True)
        rt.post_compaction(session_id="s1", kind="summarize", reason="overflow")
        again = rt.pre_llm_call(session_id="s1", user_message="go on", is_first_turn=False)
        self.assertEqual(again["context"], LABEL + "\nYou are test-prsn.prsn.eth, a verified PRSN.")

    def test_guardian_only_when_set(self):
        rt = self.runtime(settings={"guardian": "sam.prsn.eth"})
        line = rt.pre_llm_call(session_id="s1", user_message="hi", is_first_turn=True)["context"]
        self.assertTrue(line.endswith("Your guardian is sam.prsn.eth."))

    def test_identity_when_not_verified_now(self):
        rt = self.runtime(mode="unverified")
        line = rt.pre_llm_call(session_id="s1", user_message="hi", is_first_turn=True)["context"]
        self.assertIn("Your PRSN ID is not verified now, so you cannot seal anything.", line)
        self.assertNotIn("registered", line.lower())

    def test_the_line_says_why_when_a_setting_is_needed(self):
        f = DiscoveryFile(entry_json("a.prsn.eth", "0xa"), entry_json("b.prsn.eth", "0xb"))
        self.addCleanup(f.cleanup)
        ctx = FakeCtx()
        gateway = pg.Gateway(prsn_name=lambda: None, path=f.path)
        self.addCleanup(gateway.close)
        rt = plugin.Runtime(ctx, gateway=gateway)
        line = rt.pre_llm_call(session_id="s1", user_message="hi", is_first_turn=True)["context"]
        self.assertIn("could not be read just now", line)
        self.assertIn("under prsn_name", line)

    def test_no_prsn_on_this_computer(self):
        rt = self.runtime(served=False)
        line = rt.pre_llm_call(session_id="s1", user_message="hi", is_first_turn=True)["context"]
        self.assertTrue(line.startswith(LABEL + "\nYou have no PRSN ID on this computer yet."))
        self.assertIn("registration code in PRSN Connect", line)

    def test_never_guesses_when_the_gateway_cannot_answer(self):
        rt = self.runtime(mode="refuse")
        line = rt.pre_llm_call(session_id="s1", user_message="hi", is_first_turn=True)["context"]
        self.assertIn("could not be read just now", line)
        self.assertNotIn("a verified PRSN", line)

    def test_a_message_naming_prsns_makes_no_gateway_call(self):
        # BUG-229: nothing answers about another account, so the plugin asks about no one.
        rt = self.runtime()
        rt.pre_llm_call(session_id="s1", user_message="hi", is_first_turn=True)
        calls = []
        real = rt.gateway.call
        rt.gateway.call = lambda tool, *a, **k: (calls.append(tool), real(tool, *a, **k))[1]
        msg = [{"type": "text", "text": "bob.prsn.eth and team.alice.prsn.eth wrote"}]
        self.assertIsNone(rt.pre_llm_call(session_id="s1", user_message=msg, is_first_turn=False))
        self.assertIsNone(rt.pre_llm_call(session_id="s1", user_message="carol.prsn.eth", is_first_turn=False))
        self.assertEqual(calls, [])

    def test_own_verified_comes_from_the_profile_in_one_call(self):
        rt = self.runtime()
        calls = []
        real = rt.gateway.call
        rt.gateway.call = lambda tool, *a, **k: (calls.append(tool), real(tool, *a, **k))[1]
        self.assertTrue(rt.state()["verified"])
        self.assertEqual(calls, ["get_profile"])
        self.assertFalse(self.runtime(mode="unverified").state()["verified"])

    def test_a_platform_without_the_field_reads_unknown_never_false(self):
        rt = self.runtime(mode="no_verified")
        state = rt.state()
        self.assertEqual(state["name"], "test-prsn.prsn.eth")
        self.assertIsNone(state["verified"])
        # True whether the field is missing or Connect failed (Gwen, on 214f439).
        self.assertIn("Its verified state could not be read just now.", rt.command("status"))
        self.assertNotIn("PRSN Connect did not answer", rt.command("status"))

    def test_a_session_first_seen_mid_way_is_told_who_it_is(self):
        # After Hermes restarts, a session already under way is new to this process.
        rt = self.runtime()
        out = rt.pre_llm_call(session_id="s9", user_message="go on", is_first_turn=False)
        self.assertEqual(out["context"], LABEL + "\nYou are test-prsn.prsn.eth, a verified PRSN.")


class TestCommand(RuntimeCase):
    def test_status(self):
        rt = self.runtime()
        out = rt.command("status")
        self.assertTrue(out.startswith("PRSN ID test-prsn.prsn.eth\nVerified."))

    def test_status_with_no_prsn_here(self):
        rt = self.runtime(served=False)
        self.assertTrue(rt.command("").startswith(words.STATE_NONE_HERE))

    def test_about_names_the_version_and_the_loaded_code(self):
        rt = self.runtime()
        fp = sys.modules["prsn_id_plugin.fingerprint"]
        expected = fp.code_fingerprint(ROOT)
        self.assertEqual(rt.command("about"), f"PRSN ID plugin {plugin.plugin_version()}. Code fingerprint {expected}.")
        self.assertEqual(plugin.CODE_FINGERPRINT, expected)

    def test_setup_and_help_and_no_verify(self):
        rt = self.runtime()
        self.assertEqual(rt.command("verify bob.prsn.eth"), words.HELP)  # BUG-229: no check of another
        self.assertNotIn("verify", words.HELP)
        self.assertIn("registration code", rt.command("setup"))
        self.assertEqual(rt.command("anything"), words.HELP)


class TestStatusRecord(RuntimeCase):
    def read(self):
        return json.loads((self.status_folder / "status.json").read_text(encoding="utf-8"))

    def test_a_read_writes_the_status_for_desktop(self):
        rt = self.runtime()
        rt.state()
        record = self.read()
        self.assertEqual(record["name"], "test-prsn.prsn.eth")
        self.assertTrue(record["verified"])
        self.assertEqual(record["word"], "PRSN ID verified")
        self.assertTrue(record["line"].startswith("test-prsn.prsn.eth. Verified."))

    def test_the_record_holds_no_token_or_address(self):
        rt = self.runtime()
        rt.state()
        self.assertEqual(sorted(self.read()), sorted(
            ["name", "verified", "last_beat", "error_code", "error_words", "checked_at", "word", "line"]))

    def test_not_verified_now_and_no_prsn_here(self):
        rt = self.runtime(mode="unverified")
        rt.state()
        self.assertEqual(self.read()["word"], "PRSN ID not verified now")
        rt2 = self.runtime(served=False)
        rt2.state()
        self.assertEqual(self.read()["word"], "No PRSN ID here")


def load_dashboard():
    """The dashboard route needs FastAPI, which Hermes provides. A stand-in serves for tests."""
    if "fastapi" not in sys.modules:
        try:
            import fastapi  # noqa: F401
        except ImportError:
            stub = types.ModuleType("fastapi")

            class APIRouter:
                def get(self, path):
                    return lambda fn: fn
            stub.APIRouter = APIRouter
            sys.modules["fastapi"] = stub
    spec = importlib.util.spec_from_file_location("prsn_id_dashboard", ROOT / "dashboard" / "plugin_api.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestDashboard(unittest.TestCase):
    def live(self, record=None, setting=None):
        """A stale or missing record, two PRSNs served by a fake PRSN Connect, and the setting."""
        dash = load_dashboard()
        dash._runtime, dash._runtime_name = None, None
        f = DiscoveryFile(entry_json("test-prsn.prsn.eth", "0xabc"), entry_json("other.prsn.eth", "0xdef"))
        self.addCleanup(f.cleanup)
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        folder = Path(d.name)
        if record is not None:
            (folder / "status.json").write_text(json.dumps(record), encoding="utf-8")
        out = dash.status_answer(folder=folder, now=10_000.0, setting=lambda: setting, discovery=f.path)
        if dash._runtime is not None:
            self.addCleanup(dash._runtime.gateway.close)
        return out

    def test_stale_record_with_a_name_reads_live_for_that_name(self):
        out = self.live(record={"name": "test-prsn.prsn.eth", "checked_at": 1.0, "word": "old"})
        self.assertEqual(out["word"], "PRSN ID verified")
        self.assertTrue(out["line"].startswith("test-prsn.prsn.eth."))

    def test_missing_record_uses_the_setting(self):
        out = self.live(setting="test-prsn.prsn.eth")
        self.assertEqual(out["word"], "PRSN ID verified")

    def test_missing_record_no_setting_several_served_says_why(self):
        out = self.live()
        self.assertEqual(out["word"], "PRSN ID not checked")
        self.assertIn("under prsn_name", out["line"])

    def test_the_setting_is_read_each_time_not_frozen(self):
        # One module, two stale reads: first with nothing chosen, then with the setting set.
        dash = load_dashboard()
        dash._runtime, dash._runtime_name = None, None
        f = DiscoveryFile(entry_json("test-prsn.prsn.eth", "0xabc"), entry_json("other.prsn.eth", "0xdef"))
        self.addCleanup(f.cleanup)
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        folder, chosen = Path(d.name), {"name": None}
        import time as _time
        first = dash.status_answer(folder=folder, setting=lambda: chosen["name"], discovery=f.path)
        self.assertEqual(first["word"], "PRSN ID not checked")
        chosen["name"] = "test-prsn.prsn.eth"
        later = _time.time() + dash.FRESH_SECONDS + 1  # the first record is stale by then
        second = dash.status_answer(folder=folder, now=later, setting=lambda: chosen["name"], discovery=f.path)
        self.addCleanup(dash._runtime.gateway.close)
        self.assertEqual(second["word"], "PRSN ID verified")

    def test_a_fresh_record_is_returned_without_a_live_read(self):
        dash = load_dashboard()
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            (folder / "status.json").write_text(json.dumps(
                {"word": "PRSN ID verified", "line": "x. Verified.", "verified": True,
                 "checked_at": 1000.0}), encoding="utf-8")
            dash._runtime = None
            out = dash.status_answer(folder=folder, now=1100.0, setting=lambda: None)
        self.assertEqual(out, {"word": "PRSN ID verified", "line": "x. Verified.", "verified": True,
                               "checked_at": 1000.0})
        self.assertIsNone(dash._runtime)  # no live read was started

    def test_the_route_is_not_async(self):
        # An async route would block Hermes's web server during a live read.
        import inspect
        dash = load_dashboard()
        self.assertFalse(inspect.iscoroutinefunction(dash.status))

    def test_answers_carry_only_words_and_a_yes_or_no(self):
        dash = load_dashboard()
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            (folder / "status.json").write_text(json.dumps(
                {"word": "w", "line": "l", "verified": True, "checked_at": 1000.0,
                 "name": "x.prsn.eth", "error_code": None}), encoding="utf-8")
            out = dash.status_answer(folder=folder, now=1001.0, setting=lambda: None)
        self.assertEqual(sorted(out), ["checked_at", "line", "verified", "word"])


class TestFingerprint(unittest.TestCase):
    def test_a_one_byte_change_changes_it(self):
        import shutil
        fp = sys.modules["prsn_id_plugin.fingerprint"]
        with tempfile.TemporaryDirectory() as d:
            copy = Path(d) / "copy"
            shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns(".git", "__pycache__"))
            before = fp.code_fingerprint(copy)
            self.assertEqual(before, fp.code_fingerprint(ROOT))
            words_py = copy / "words.py"
            words_py.write_bytes(words_py.read_bytes() + b" ")
            self.assertNotEqual(before, fp.code_fingerprint(copy))

    def test_tests_and_readme_do_not_change_it(self):
        import shutil
        fp = sys.modules["prsn_id_plugin.fingerprint"]
        with tempfile.TemporaryDirectory() as d:
            copy = Path(d) / "copy"
            shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns(".git", "__pycache__"))
            (copy / "README.md").write_text("changed", encoding="utf-8")
            self.assertEqual(fp.code_fingerprint(copy), fp.code_fingerprint(ROOT))


class TestWords(unittest.TestCase):
    """Chris's rule for words people read: no colons or semicolons, outside of web addresses."""

    def user_strings(self):
        strings = [words.STATE_NONE_HERE, words.STATE_VERIFIED, words.STATE_NOT_VERIFIED_NOW,
                   words.SETUP_MIDDLE_STATE, words.HELP, words.SETUP, *words._FOR_CODE.values(),
                   words.not_verified_now("2026-10-01T00:00:00Z"), words.not_verified_now(None),
                   words.seal_refusal(None),
                   words.identity_line("", None, reason=words._FOR_CODE[pg.CHOOSE_PRSN]),
                   words.identity_line("a.prsn.eth", False, last_beat_at="2026-10-01T00:00:00Z"),
                   words.identity_line(None, None), words.identity_line("a.prsn.eth", None),
                   words.identity_line("a.prsn.eth", True, "g.prsn.eth"),
                   words.identity_line("a.prsn.eth", False),
                   words.approve_seal("seal_message", {"to": ["a@example.com"]}, "a.prsn.eth"),
                   words.approve_seal("seal_file", {"path": "/a/b.pdf"}, None),
                   words.FILE_SEAL_PAGE_OPENED, words.FILE_SEAL_PAGE_NOT_OPENED,
                   words.AFTER_REFUSAL, words.DIRECT_TO_PRSN_CONNECT,
                   words.heartbeat_ago("2026-11-01T00:00:00Z"), words.CONTEXT_LABEL,
                   words.status_line({"name": "a.prsn.eth", "verified": True, "last_beat": None}),
                   words.status_line({"name": "a.prsn.eth", "verified": False, "last_beat": None}),
                   words.status_line({"name": "a.prsn.eth", "verified": None}),
                   words.status_word({"verified": True}), words.status_word({"verified": False}),
                   words.status_word({"error_code": pg.NO_PRSN}),
                   words.status_word({"error_code": pg.NO_SERVER}),
                   words.about("0.1.0", "abcdef123456"),
                   *re.findall(r"'([A-Z][^'\n]*)'", (ROOT / "desktop" / "plugin.js").read_text(encoding="utf-8"))]
        manifest = (ROOT / "plugin.yaml").read_text(encoding="utf-8")
        strings += re.findall(r"description: (.+)", manifest)
        return strings

    FORBIDDEN = (":", ";", "\u2014", "\u2013")  # colon, semicolon, em dash, en dash

    def assert_plain(self, text, where):
        bare = re.sub(r"https?://\S+", "", text)
        for mark in self.FORBIDDEN:
            self.assertNotIn(mark, bare, f"{where}: {text!r}")

    def test_no_colons_semicolons_or_dashes_in_words(self):
        for text in self.user_strings():
            self.assert_plain(text, "words")

    def test_tool_and_parameter_descriptions_are_plain(self):
        for name, schema in plugin._load_tool_schemas().items():
            self.assert_plain(schema["description"], name)
            for param, spec in schema["parameters"].get("properties", {}).items():
                self.assert_plain(spec.get("description", ""), f"{name}.{param}")

    def test_readme_prose_is_plain(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        text = re.sub(r"```.*?```", "", text, flags=re.S)       # code blocks
        text = re.sub(r"<!--.*?-->", "", text, flags=re.S)      # notes for us, not readers
        text = re.sub(r"`[^`]*`", "", text)                     # inline code
        for line in text.splitlines():
            if re.fullmatch(r"\|?[\s|:-]+\|?", line.strip() or "x"):
                continue                                        # a table's rule row
            self.assert_plain(line, "README")

    def test_not_verified_now_words_by_heartbeat_age(self):
        from datetime import datetime, timezone
        now = datetime(2026, 11, 7, 23, 0, tzinfo=timezone.utc)
        self.assertEqual(words.not_verified_now("2026-10-07T13:00:00Z", now),
                         "Not verified now. Last heartbeat 31 days ago. "
                         "Open PRSN Connect so this PRSN can send a heartbeat.")
        self.assertEqual(words.not_verified_now("2026-11-07T13:00:00Z", now),
                         "Not verified now. Ask this PRSN's guardian in the PRSN ID dashboard.")
        # Between the platform's 7-day warning and its 30-day lapse a heartbeat changes nothing.
        self.assertEqual(words.not_verified_now("2026-10-28T13:00:00Z", now),
                         "Not verified now. Ask this PRSN's guardian in the PRSN ID dashboard.")
        self.assertIn("Last heartbeat 30 days ago", words.not_verified_now("2026-10-08T13:00:00Z", now))
        self.assertEqual(words.not_verified_now(None, now),
                         "Not verified now. Ask this PRSN's guardian in the PRSN ID dashboard.")

    def test_registered_not_yet_verified_only_in_the_setup_words(self):
        self.assertIn("registered, not yet verified", words.SETUP)

    @unittest.skipUnless(hasattr(time, "tzset"), "needs time.tzset")
    def test_a_heartbeat_this_evening_reads_today(self):
        # Chris's box, 2026-11-10: a beat at 17:44 UTC-6 read "yesterday" at 18:47, by UTC date.
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                instant = datetime(2026, 11, 11, 0, 47, tzinfo=timezone.utc)
                return instant.astimezone(tz) if tz else datetime.fromtimestamp(instant.timestamp())
        with mock.patch.dict(os.environ, {"TZ": "Etc/GMT+6"}):
            time.tzset()
            try:
                with mock.patch.object(words, "datetime", Clock):
                    self.assertEqual(words.heartbeat_ago("2026-11-10T23:44:12Z"), "Last heartbeat today.")
                    self.assertEqual(words.heartbeat_ago("2026-11-09T23:44:12Z"), "Last heartbeat yesterday.")
            finally:
                pass
        time.tzset()

    def test_no_server_tells_the_human_to_update_prsn_connect(self):
        self.assertEqual(words.status_word({"error_code": pg.NO_SERVER}), "Update PRSN Connect")
        self.assertIn("Update PRSN Connect to v0.2.1 or later", words._FOR_CODE[pg.NO_SERVER])

    def test_heartbeat_words(self):
        from datetime import datetime, timezone
        now = datetime(2026, 11, 7, 23, 0, tzinfo=timezone.utc)
        self.assertEqual(words.heartbeat_ago("2026-11-07T13:57:16Z", now), "Last heartbeat today.")
        self.assertEqual(words.heartbeat_ago("2026-11-06T13:57:16Z", now), "Last heartbeat yesterday.")
        self.assertEqual(words.heartbeat_ago("2026-10-29T13:57:16Z", now), "Last heartbeat 9 days ago.")
        self.assertIsNone(words.heartbeat_ago("not a time", now))


if __name__ == "__main__":
    unittest.main()
