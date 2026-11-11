"""PRSN Connect's gateway, reached through PRSN Connect's own MCP server.

The plugin keeps no secret and makes no network call of its own. It reads the discovery file
PRSN Connect writes (``~/.prsn-id/gateway.json``), starts PRSN Connect's own ``prsn-gateway-mcp``
exactly as that file says (the arguments lock it to one PRSN with ``--prsn-address``), and speaks
MCP to it over standard input and output. PRSN Connect makes the calls to the PRSN ID platform.

The server is started on the first call and lives as long as this process. It is not stopped
per turn: Hermes's ``on_session_end`` fires after every turn.

Standard library only.
"""

from __future__ import annotations

import atexit
import contextvars
import itertools
import json
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

PROTOCOL_VERSION = "2025-06-18"
CLIENT_NAME = "prsn-id-hermes"
CLIENT_VERSION = "0.1.0"

# Hermes skips a hook callback that runs past 30 seconds, so a call must end well before that.
CALL_TIMEOUT_SECONDS = 12.0
START_TIMEOUT_SECONDS = 10.0


class GatewayError(Exception):
    """A failure with a code the plugin turns into plain words.

    ``connect_words`` carries PRSN Connect's own words when the server gave them, so the plugin
    passes them through unchanged rather than writing its own.
    """

    def __init__(self, code: str, detail: str = "", connect_words: Optional[str] = None):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail
        self.connect_words = connect_words


# Codes. Words for people live in words.py, not here.
NO_DISCOVERY = "no_discovery"          # gateway.json missing: PRSN Connect not installed or never run
BAD_DISCOVERY = "bad_discovery"        # gateway.json unreadable or not the shape we know
NO_PRSN = "no_prsn"                    # PRSN Connect serves no PRSN under this user account
NO_SERVER = "no_server"                # PRSNs listed, none with a way to start its server (BUG-231)
CHOOSE_PRSN = "choose_prsn"            # several PRSNs served, and the setting names none
UNKNOWN_PRSN = "unknown_prsn"          # the setting names a PRSN this PRSN Connect does not serve
GATEWAY_DISABLED = "gateway_disabled"  # the chosen PRSN's gateway is switched off in PRSN Connect
START_FAILED = "start_failed"          # the server program could not be started
SERVER_GONE = "server_gone"            # the server exited or stopped answering
TIMEOUT = "timeout"                    # no answer in time
REFUSED = "refused"                    # the server answered with an error (PRSN Connect's words)


def discovery_path() -> Path:
    """Where PRSN Connect writes its discovery file, on macOS, Windows and Linux alike."""
    return Path.home() / ".prsn-id" / "gateway.json"


@dataclass(frozen=True)
class PrsnEntry:
    ens_name: str
    address: str
    enabled: bool
    command: str
    args: tuple[str, ...]


def read_discovery(path: Optional[Path] = None) -> list[PrsnEntry]:
    """Read the PRSNs PRSN Connect serves under this user account. Never reads a token."""
    path = path or discovery_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise GatewayError(NO_DISCOVERY, str(path)) from None
    except OSError as exc:
        raise GatewayError(BAD_DISCOVERY, f"{path}: {exc.strerror}") from None
    try:
        data = json.loads(raw)
        listed = data.get("prsns", [])
        entries = []
        for item in listed:
            mcp = item.get("mcpConfig") or {}
            command, args = mcp.get("command"), mcp.get("args", [])
            if not isinstance(command, str) or not command or not isinstance(args, list):
                continue  # an entry with no way to start its server is not one we can use
            entries.append(PrsnEntry(
                ens_name=str(item.get("ensName") or ""),
                address=str(item.get("walletAddress") or ""),
                enabled=bool(item.get("gatewayEnabled", False)),
                command=command,
                args=tuple(str(a) for a in args),
            ))
    except (ValueError, AttributeError, TypeError) as exc:
        raise GatewayError(BAD_DISCOVERY, f"{path}: {exc}") from None
    if listed and not entries:
        # PRSN Connect v0.2.0 on Windows and Linux lists its PRSNs but names no server (BUG-231).
        raise GatewayError(NO_SERVER, str(path))
    return entries


def choose_prsn(entries: list[PrsnEntry], prsn_name: Optional[str]) -> PrsnEntry:
    """Pick this agent's PRSN: the one named in the setting, else the only one served."""
    if not entries:
        raise GatewayError(NO_PRSN)
    if prsn_name:
        wanted = prsn_name.strip().lower()
        matches = [e for e in entries
                   if e.ens_name.lower() == wanted or e.address.lower() == wanted]
        if not matches:
            raise GatewayError(UNKNOWN_PRSN, prsn_name)
        chosen = matches[0]
    elif len(entries) == 1:
        chosen = entries[0]
    else:
        raise GatewayError(CHOOSE_PRSN, ", ".join(e.ens_name for e in entries))
    if not chosen.enabled:
        raise GatewayError(GATEWAY_DISABLED, chosen.ens_name)
    if "--prsn-address" not in chosen.args:
        # Locked mode is what keeps identify_as from switching PRSNs; never start unlocked.
        raise GatewayError(BAD_DISCOVERY, f"{chosen.ens_name}: server not locked to its PRSN")
    return chosen


class McpClient:
    """A minimal MCP client over stdio: one server process, newline-delimited JSON-RPC."""

    def __init__(self, command: str, args: tuple[str, ...] | list[str],
                 server_log: Optional[Path] = None):
        self._argv = [command, *args]
        self._server_log = server_log
        self._proc: Optional[subprocess.Popen] = None
        self._ids = itertools.count(1)
        self._write_lock = threading.Lock()
        self._pending: dict[int, dict[str, Any]] = {}
        self._pending_lock = threading.Lock()
        self._reader: Optional[threading.Thread] = None
        self.server_info: dict[str, Any] = {}

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> None:
        log = None
        try:
            if self._server_log is not None:
                # PRSN Connect's server log names addresses and connection states, never a token.
                log = open(self._server_log, "ab")
            self._proc = subprocess.Popen(
                self._argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=log if log is not None else subprocess.DEVNULL,
                text=True, encoding="utf-8", bufsize=1,
            )
        except OSError as exc:
            self._proc = None
            raise GatewayError(START_FAILED, exc.strerror or str(exc)) from None
        finally:
            if log is not None:
                log.close()  # the server keeps its own handle
        # Hermes keeps a served profile's home and secret scope in ContextVars, and a new thread
        # does not inherit them. The reader needs neither today, but it runs in the caller's
        # context so a later change to it cannot read another profile's home (Gus, 2026-11-07).
        context = contextvars.copy_context()
        self._reader = threading.Thread(target=context.run, args=(self._read_loop,),
                                        name="prsn-id-mcp", daemon=True)
        self._reader.start()
        result = self._request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": CLIENT_NAME, "version": CLIENT_VERSION},
        }, timeout=START_TIMEOUT_SECONDS)
        self.server_info = dict(result.get("serverInfo") or {})
        self._notify("notifications/initialized")

    def call_tool(self, name: str, arguments: dict[str, Any],
                  timeout: float = CALL_TIMEOUT_SECONDS) -> Any:
        """Call one tool. Returns its JSON answer parsed, or its text when it isn't JSON."""
        result = self._request("tools/call", {"name": name, "arguments": arguments}, timeout=timeout)
        text = "\n".join(c.get("text", "") for c in result.get("content", [])
                         if isinstance(c, dict) and c.get("type") == "text")
        if result.get("isError"):
            raise GatewayError(REFUSED, name, connect_words=text.strip() or None)
        try:
            return json.loads(text)
        except ValueError:
            return text

    def close(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
            proc.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            proc.kill()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass
        # The reader ends at the closed pipe's end of file; then its stream can be closed.
        if self._reader is not None and self._reader is not threading.current_thread():
            self._reader.join(timeout=3)
        if proc.stdout is not None:
            try:
                proc.stdout.close()
            except OSError:
                pass
        self._fail_pending(SERVER_GONE)

    # -- wire --------------------------------------------------------------------------------

    def _send(self, message: dict[str, Any]) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None or proc.poll() is not None:
            raise GatewayError(SERVER_GONE, "not running")
        with self._write_lock:
            try:
                proc.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
                proc.stdin.flush()
            except (OSError, ValueError):
                raise GatewayError(SERVER_GONE, "write failed") from None

    def _notify(self, method: str, params: Optional[dict[str, Any]] = None) -> None:
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self._send(message)

    def _request(self, method: str, params: dict[str, Any], timeout: float) -> dict[str, Any]:
        request_id = next(self._ids)
        slot: dict[str, Any] = {"event": threading.Event()}
        with self._pending_lock:
            self._pending[request_id] = slot
        try:
            self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
            if not slot["event"].wait(timeout):
                raise GatewayError(TIMEOUT, method)
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)
        if "gone" in slot:
            raise GatewayError(SERVER_GONE, method)
        message = slot["message"]
        if "error" in message:
            error = message["error"] or {}
            raise GatewayError(REFUSED, method, connect_words=str(error.get("message") or "") or None)
        return message.get("result") or {}

    def _read_loop(self) -> None:
        proc = self._proc
        stream = proc.stdout if proc else None
        if stream is None:
            return
        for line in stream:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except ValueError:
                continue  # not a protocol line; the server writes its logs elsewhere
            if not isinstance(message, dict):
                continue
            if "id" in message and "method" in message:
                self._answer_server_request(message)
            elif "id" in message:
                with self._pending_lock:
                    slot = self._pending.get(message["id"])
                if slot is not None:
                    slot["message"] = message
                    slot["event"].set()
            # Notifications from the server are ignored.
        self._fail_pending(SERVER_GONE)

    def _answer_server_request(self, message: dict[str, Any]) -> None:
        reply: dict[str, Any] = {"jsonrpc": "2.0", "id": message["id"]}
        if message.get("method") == "ping":
            reply["result"] = {}
        else:
            reply["error"] = {"code": -32601, "message": "Method not found"}
        try:
            self._send(reply)
        except GatewayError:
            pass

    def _fail_pending(self, code: str) -> None:
        with self._pending_lock:
            slots = list(self._pending.values())
        for slot in slots:
            slot["gone"] = code
            slot["event"].set()


class Gateway:
    """This process's way to the chosen PRSN's gateway: started on first use, restarted once if
    the server has gone, stopped when the process exits."""

    def __init__(self, prsn_name: Callable[[], Optional[str]] = lambda: None,
                 path: Optional[Path] = None,
                 server_log: Callable[[], Optional[Path]] = lambda: None):
        self._prsn_name = prsn_name
        self._path = path
        self._server_log = server_log
        self._client: Optional[McpClient] = None
        self._entry: Optional[PrsnEntry] = None
        self._started_for: Optional[str] = None  # the prsn_name setting the server started under
        self._lock = threading.Lock()
        atexit.register(self.close)

    @property
    def entry(self) -> Optional[PrsnEntry]:
        """The PRSN this gateway speaks for, once it has started."""
        return self._entry

    def call(self, tool: str, arguments: Optional[dict[str, Any]] = None,
             timeout: float = CALL_TIMEOUT_SECONDS) -> Any:
        arguments = arguments or {}
        with self._lock:
            client = self._ensure_started()
        try:
            return client.call_tool(tool, arguments, timeout=timeout)
        except GatewayError as exc:
            if exc.code == TIMEOUT:
                # A hung server is dropped so the next call starts afresh. No retry here: two
                # waits and a start could outlast Hermes's 30-second hook limit.
                self._drop(client)
                raise
            if exc.code != SERVER_GONE:
                raise
            # The server went away: start afresh once, and try again.
            self._drop(client)
            with self._lock:
                client = self._ensure_started()
            return client.call_tool(tool, arguments, timeout=timeout)

    def _drop(self, client: McpClient) -> None:
        with self._lock:
            if self._client is client:
                client.close()
                self._client = None

    def close(self) -> None:
        with self._lock:
            if self._client is not None:
                self._client.close()
                self._client = None

    def _ensure_started(self) -> McpClient:
        # A changed prsn_name setting takes effect at the next call: the server speaks for one
        # PRSN, so one started under another name is stopped and a new one started.
        wanted = (self._prsn_name() or "").strip().lower() or None
        if self._client is not None and self._client.alive and wanted == self._started_for:
            return self._client
        if self._client is not None:
            self._client.close()
            self._client = None
        # Read the discovery file afresh each start, so a PRSN bound mid-session is found.
        entry = choose_prsn(read_discovery(self._path), wanted)
        client = McpClient(entry.command, entry.args, server_log=self._server_log())
        try:
            client.start()
        except GatewayError:
            client.close()
            raise
        self._client, self._entry, self._started_for = client, entry, wanted
        return client
