"""A stand-in for PRSN Connect's prsn-gateway-mcp, for tests only.

It answers the MCP handshake and the six tools the plugin offers in the shapes the real server
used when read on 2026-11-07 (server 0.2.0, protocol 2025-06-18). ``--mode`` picks a behaviour:

  normal      answers everything
  refuse      answers every tool call with isError and PRSN Connect's own words
  exit_call   exits as soon as a tool call arrives
  hang_call   reads a tool call and never answers it
  slow_start  waits before answering initialize
  noise       writes non-protocol lines and a server ping before each answer
  unverified  the profile says this PRSN is not verified now
  no_verified the profile carries no verified field, as a platform before v0.2.1
"""

from __future__ import annotations

import argparse
import json
import sys
import time

REFUSAL = "PRSN Connect is not running. Start it, then try again."

PROFILE = {
    "identity": {"ensName": "test-prsn.prsn.eth", "walletAddress": "0xabc", "tier": "free",
                 "modelIdentity": "Test", "modelProvider": "Test", "prsnId": "p-1"},
    "hwbeat": {"lastBeatAt": "2026-11-07T13:52:56.529Z", "nextDueAt": "2026-11-08T13:52:56.529Z",
               "status": "on-time", "streak": 3},
    "autonomy": {"level": 1, "name": "Presenter"},
}


# A Seal link of the real shape: the 43-character id, then the signed statement.
SEAL_LINK = "https://verify.prsnid.ai/s/" + "A" * 43 + "#eyJ2IjoxfQ.MEUCIQ"

def answer(tool: str, arguments: dict, address: str, mode: str = "normal") -> dict:
    if tool == "get_profile":
        identity = dict(PROFILE["identity"])
        if mode != "no_verified":
            identity["verified"] = mode != "unverified"
        return {**PROFILE, "identity": identity}
    if tool == "get_gateway_status":
        return {"gateway_state": "connected", "ok": True, "prsn_address": address,
                "session_valid": True}
    if tool in ("seal_message", "seal_email", "seal_file"):
        return {"ok": True, "tool": tool, "link": SEAL_LINK}
    return {"error": f"unknown tool {tool}"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prsn-address", required=True)
    parser.add_argument("--mode", default="normal")
    opts = parser.parse_args()
    sys.stderr.write("fake prsn-gateway-mcp started\n")
    sys.stderr.flush()

    def send(message: dict) -> None:
        sys.stdout.write(json.dumps(message) + "\n")
        sys.stdout.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        message = json.loads(line)
        method, request_id = message.get("method"), message.get("id")
        if request_id is None:
            continue  # a notification
        if method is None:
            continue  # a reply to our ping
        if opts.mode == "noise":
            sys.stdout.write("server log line, not protocol\n")
            send({"jsonrpc": "2.0", "id": "srv-1", "method": "ping"})
        if method == "initialize":
            if opts.mode == "slow_start":
                time.sleep(2)
            send({"jsonrpc": "2.0", "id": request_id, "result": {
                "protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                "serverInfo": {"name": "prsn-gateway-mcp", "version": "0.2.0"}}})
        elif method == "tools/call":
            if opts.mode == "exit_call":
                sys.exit(3)
            if opts.mode == "hang_call":
                continue
            params = message.get("params") or {}
            if opts.mode == "refuse":
                send({"jsonrpc": "2.0", "id": request_id, "result": {
                    "content": [{"type": "text", "text": REFUSAL}], "isError": True}})
                continue
            body = answer(params.get("name", ""), params.get("arguments") or {}, opts.prsn_address,
                          opts.mode)
            send({"jsonrpc": "2.0", "id": request_id, "result": {
                "content": [{"type": "text", "text": json.dumps(body, indent=2)}],
                "isError": False}})
        else:
            send({"jsonrpc": "2.0", "id": request_id,
                  "error": {"code": -32601, "message": "Method not found"}})


if __name__ == "__main__":
    main()
