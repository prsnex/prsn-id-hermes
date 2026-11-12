"""Every sentence a person or the agent reads, in one place, so each can be checked.

The rules for these words: every word true, plain sentences, no colons or semicolons, no fear.
PRSN Connect's own words, when it gives them, are passed through unchanged instead of these.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from . import prsn_gateway as pg

SIGN_UP = "https://app.prsnid.ai/register"
CONNECT_PAGE = "https://prsnid.ai/en/prsn-connect/"
GETTING_STARTED = "https://prsnid.ai/en/getting-started/"

# The states the plugin can see, and only these words for them. PRSN Connect serves a PRSN only
# once it is bound, so a PRSN it serves that does not verify has lapsed or been revoked; it is
# never "not yet bound". "Registered, not yet verified" is true only before the code is entered in
# PRSN Connect, which the plugin cannot see, so it appears in the setup words alone (Gwen).
STATE_NONE_HERE = "No PRSN ID on this computer yet."
STATE_VERIFIED = "Verified."
STATE_NOT_VERIFIED_NOW = "Not verified now."
SETUP_MIDDLE_STATE = "Registered, not yet verified."

# The platform warns at 7 days without a heartbeat and still verifies. It treats a PRSN ID as
# revoked for want of a heartbeat only from 30 days (DEFAULT_HWBEAT_REVOCATION_DAYS in the
# platform's verification-service.ts). Below that, a heartbeat would not change an unverified
# answer, so the words send the human to the guardian instead (Gwen). The profile's `verified`
# carries no reason (BUG-139's minimum disclosure), so the age is the only sign.
HEARTBEAT_LAPSE_DAYS = 30

_FOR_CODE = {
    pg.NO_DISCOVERY: ("PRSN Connect is not set up on this computer yet. "
                      f"It is the desktop app that holds this agent's PRSN ID. Get it at {CONNECT_PAGE}"),
    pg.NO_PRSN: ("PRSN Connect serves no PRSN on this computer yet. "
                 "Enter this agent's registration code in PRSN Connect to bind it."),
    pg.NO_SERVER: ("PRSN Connect lists this computer's PRSN but names no way to start its identity tools. "
                   "Update PRSN Connect to v0.2.1 or later, then restart it."),
    pg.CHOOSE_PRSN: ("PRSN Connect serves more than one PRSN on this computer. "
                     "Choose this agent's in the plugin's settings, under prsn_name."),
    pg.UNKNOWN_PRSN: ("PRSN Connect on this computer does not serve the PRSN named in the plugin's settings. "
                      "Check prsn_name."),
    pg.GATEWAY_DISABLED: "This PRSN's gateway is turned off in PRSN Connect. Turn it on there to continue.",
    pg.BAD_DISCOVERY: "PRSN Connect's file on this computer could not be read. Restart PRSN Connect to write it again.",
    pg.START_FAILED: "PRSN Connect's identity tools could not be started. Check that PRSN Connect is installed and up to date.",
    pg.SERVER_GONE: "PRSN Connect did not answer just now. Try again in a moment.",
    pg.TIMEOUT: "PRSN Connect did not answer just now. Try again in a moment.",
    pg.REFUSED: "PRSN Connect refused this request.",
}


def for_error(exc: pg.GatewayError) -> str:
    """PRSN Connect's own words when it gave them, else ours for the code."""
    if exc.connect_words:
        return exc.connect_words
    return _FOR_CODE.get(exc.code, "PRSN Connect did not answer just now. Try again in a moment.")


def heartbeat_days(last_beat_at: Optional[str], now: Optional[datetime] = None) -> Optional[int]:
    """Whole days since the last heartbeat, by this computer's own calendar date; None when unknown.

    By UTC date, a heartbeat at 17:44 in UTC-6 read "yesterday" from 18:00 the same evening.
    """
    if not last_beat_at:
        return None
    try:
        when = datetime.fromisoformat(last_beat_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    now = now or datetime.now().astimezone()
    if now.tzinfo is None:
        now = now.astimezone()
    return max(0, (now.date() - when.astimezone(now.tzinfo).date()).days)


def heartbeat_ago(last_beat_at: Optional[str], now: Optional[datetime] = None) -> Optional[str]:
    """'Last heartbeat today.' and the like, from the platform's ISO time; None when unknown."""
    days = heartbeat_days(last_beat_at, now)
    if days is None:
        return None
    if days == 0:
        return "Last heartbeat today."
    if days == 1:
        return "Last heartbeat yesterday."
    return f"Last heartbeat {days} days ago."


def not_verified_now(last_beat_at: Optional[str], now: Optional[datetime] = None) -> str:
    """For a PRSN that PRSN Connect serves and that does not verify now, with what to do."""
    days = heartbeat_days(last_beat_at, now)
    if days is not None and days >= HEARTBEAT_LAPSE_DAYS:
        return (f"{STATE_NOT_VERIFIED_NOW} {heartbeat_ago(last_beat_at, now)} "
                "Open PRSN Connect so this PRSN can send a heartbeat.")
    return f"{STATE_NOT_VERIFIED_NOW} Ask this PRSN's guardian in the PRSN ID dashboard."


def seal_refusal(last_beat_at: Optional[str]) -> str:
    return f"{not_verified_now(last_beat_at)} No Seal can be made until it is verified again."


# -- lines for the agent, added to the turn by pre_llm_call ------------------------------------

# Hermes adds a hook's text to the user's message, so the agent is told whose note it is.
CONTEXT_LABEL = "A note from the PRSN ID plugin, read live from PRSN Connect, not written by the user."

def identity_line(name: Optional[str], verified: Optional[bool], guardian: Optional[str] = None,
                  last_beat_at: Optional[str] = None, reason: Optional[str] = None) -> str:
    """Who the agent is, read live this session. Never carried over from an earlier one."""
    if name is None:
        line = "You have no PRSN ID on this computer yet."
        if reason:
            line += f" If asked how to get one, say this. {reason}"
        return line
    if verified is None:
        line = ("Your PRSN ID state could not be read just now, "
                "so do not say you are verified until it can be.")
        if reason:
            line += f" If asked why, say this. {reason}"
        return line
    if verified:
        line = f"You are {name}, a verified PRSN."
    else:
        line = (f"You are {name}. Your PRSN ID is not verified now, so you cannot seal anything. "
                f"If asked, say this. {not_verified_now(last_beat_at)}")
    if guardian:
        line += f" Your guardian is {guardian}."
    return line


# -- tool descriptions, in plain sentences --------------------------------------------------------
# PRSN Connect's own descriptions use dashes, colons and semicolons. These say the same in plain
# sentences. The input schemas stay PRSN Connect's, with three parameter descriptions restated.

TOOL_DESCRIPTIONS = {
    "get_profile": ("Get this agent's PRSN ID profile. It holds the PRSN's name, tier, "
                    "autonomy level, last heartbeat, and whether it is verified now. Its address "
                    "is an identifier PRSN ID derives, not a wallet. Its permissions are what the "
                    "PRSN may do on PRSN ID, not what this plugin offers."),
    "get_gateway_status": ("Check the connection to PRSN Connect's gateway. It shows whether "
                           "this PRSN has an active platform session."),
    "seal_message": (
        "Prepare a sealed email in one step. Give its parts, and PRSN Connect writes the whole "
        "message to output_path as a new .eml file, sealed and ready to send. The device key signs "
        "the envelope. That covers From, Message-ID, Date, To and Cc as keyed digests, the "
        "attachment count, and the subject if you include it. PRSN Connect sets the Message-ID and "
        "Date itself. The message has a plain and an HTML version, and each ends with the Seal's "
        "link. Send the file's bytes unchanged. A Seal does not prove the words of the email. Never "
        "pass Bcc. Add Bcc recipients only when you send."),
    "seal_file": (
        "Seal a file you are sending. The device key signs a statement of the file's name, size and "
        "a keyed digest. You get a link that anyone can open. It shows which PRSN sealed the file, "
        "on which device, and when. The reader drops their copy on the page to check it is the same "
        "file. Give the file's absolute path on this computer. This works on the gateway's local "
        "socket only, not from a container. Seals expire. PRSN ID's default applies unless you give "
        "retention_seconds. After the Seal, the plugin opens its page in the browser on the computer "
        "where Hermes runs. Hermes may shorten the link in your reply, so do not repeat the link. Tell "
        "your human to copy the page's address from that browser to share it."),
}

PARAMETER_DESCRIPTIONS = {
    ("seal_message", "format"): ('"plain" is the default. "markdown" renders paragraphs, **bold**, '
                                 'lists that start with "- ", and bare https links. Nothing else '
                                 "is rendered."),
    ("seal_message", "output_path"): ("Where to write the finished message. Give an absolute path "
                                      "that ends in .eml and does not exist yet."),
}


# -- after a file Seal: the page opens for the human, since Hermes may shorten the link in a reply --

FILE_SEAL_PAGE_OPENED = ("The Seal's page is open in the browser on the computer where Hermes runs. "
                         "Hermes may shorten the link in your reply, so do not repeat it. Tell your "
                         "human the page is open there, and that they can copy its address from that "
                         "browser to share it.")
FILE_SEAL_PAGE_NOT_OPENED = ("The Seal is made, but its page could not be opened on the computer where "
                             "Hermes runs. Hermes may shorten the link in your reply, so no working "
                             "link can be shown here. Tell your human the Seal is made and its page "
                             "could not open. They can seal the file again where a browser can open it.")


# -- after PRSN Connect refuses, and before a command that reaches PRSN Connect directly ------------

AFTER_REFUSAL = ("Tell your human what was refused and why, in PRSN Connect's words. Do not look for "
                 "another way to do it.")
DIRECT_TO_PRSN_CONNECT = ("This names PRSN Connect or its files and may reach it directly, around the PRSN "
                          "ID plugin's tools. No Seal approval covers that. Run it only if you asked for it.")


# -- what the profile tool's result says about itself ----------------------------------------------
# The platform names the address field `walletAddress`, and an agent repeats the word. The dashboard
# tells a person the truth (`platformAddressHint`); these say it to the agent (Chris, 2026-11-10).

PLATFORM_ADDRESS = ("An identifier PRSN ID derives for this PRSN. It is not a wallet. No key stands "
                    "behind it, so anything sent to it is lost. Never call it a wallet, and never "
                    "offer it to receive funds.")

PLUGIN_OFFERS = ("Through this plugin, this agent can read its PRSN ID profile and status, and seal "
                 "email and files with its human's yes. The permissions in this profile are what the "
                 "PRSN may do on PRSN ID itself. This plugin offers no purchases, service requests "
                 "or credential issuing.")


def explain_profile(profile: dict) -> dict:
    """The profile as the agent should read it: the address named for what it is, and the plugin's
    own reach beside the PRSN's permissions."""
    out = dict(profile)
    identity = out.get("identity")
    if isinstance(identity, dict) and "walletAddress" in identity:
        identity = dict(identity)
        identity["platformAddress"] = identity.pop("walletAddress")
        identity["platformAddressIs"] = PLATFORM_ADDRESS
        out["identity"] = identity
    out["throughThisPlugin"] = PLUGIN_OFFERS
    return out


# -- the question Hermes asks the human before a Seal --------------------------------------------

def _paths(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value] if isinstance(value, list) else []


def approve_seal(tool: str, args: dict, prsn: Optional[str]) -> str:
    """The card names everything the Seal touches, in full: the file's path, or the message's
    sender and recipients, every attachment's path and where the sealed .eml is written (Nous
    review of d833d031, item 2; Gwen)."""
    who = prsn or "this agent's PRSN"
    if tool == "seal_file":
        what = f"the file {args.get('path') or 'named'}"
        written = ""
    else:
        # From too: the agent supplies the sender, and an agent with no address to go on invented
        # one on the Windows run of f305db8, which the card did not show (Gwen). The display name
        # with it, since a mail reader shows that first.
        sender = ", ".join(_paths(args.get("from")))
        name = str(args.get("from_name") or "").strip()
        if name:
            sender = f"{name} <{sender}>" if sender else name
        recipients = ", ".join(_paths(args.get("to")))
        what = "an email"
        if sender:
            what += f" from {sender}"
        if recipients:
            what += f" to {recipients}"
        # Cc too: the human approves every address the message goes to (Gwen).
        copied = _paths(args.get("cc"))
        if copied:
            what += f", with {'a copy' if len(copied) == 1 else 'copies'} to {', '.join(copied)}"
        attached = _paths(args.get("attachments"))
        if attached:
            what += f", with {'the attachment' if len(attached) == 1 else 'the attachments'} {', '.join(attached)}"
        written = f" It is written to {args.get('output_path') or 'a file not named'}."
    return (f"Seal {what} as {who}.{written} "
            f"A Seal speaks for {who}, and anyone with its link can check it.")


# For the agent, after the plugin stops a Seal whose paths the helper would refuse. It names who
# stopped it, and lets the agent correct the path (Gwen, after the Mac and Windows runs of f305db8:
# one agent stopped, one corrected, and both said PRSN Connect refused). It promises no card, since
# with approvals off, in yolo mode or in a one-shot run there is none (Gwen).
AFTER_PATH_REFUSAL = ("The PRSN ID plugin stopped this call before asking your human, so PRSN Connect "
                      "was not reached. You may correct the path and call again. If you cannot, tell "
                      "your human what was stopped and why.")


def refuse_seal_paths(tool: str, args: dict) -> Optional[str]:
    """Why a Seal's paths will be refused, before its human is asked: the same rules the helper
    applies (prsn-gateway-mcp tools.rs check_output_path), so no one approves a Seal that fails.
    None when they pass."""
    import os
    if tool == "seal_file":
        path = str(args.get("path") or "")
        if not os.path.isabs(path):
            return "The file's path must be absolute. No Seal was made."
        return None
    for path in _paths(args.get("attachments")):
        if not os.path.isabs(path):
            return f"The attachment {path} must be named by its absolute path. No Seal was made."
    out = str(args.get("output_path") or "")
    if not os.path.isabs(out):
        return "output_path must be absolute. No Seal was made."
    if not out.lower().endswith(".eml"):
        return "output_path must end in .eml. No Seal was made."
    if os.path.exists(out):
        return f"{out} already exists. Name a new file. No Seal was made."
    if not os.path.isdir(os.path.dirname(out)):
        return f"The folder of {out} does not exist. No Seal was made."
    return None


# -- the Desktop status item: a short word, and a line for its tooltip ------------------------------

def status_word(state: dict) -> str:
    """The status item's word. It must fit in the status bar."""
    error = state.get("error_code")
    if error in (pg.NO_DISCOVERY, pg.NO_PRSN):
        return "No PRSN ID here"
    if error == pg.NO_SERVER:
        return "Update PRSN Connect"
    if error or state.get("verified") is None:
        return "PRSN ID not checked"
    return "PRSN ID verified" if state.get("verified") else "PRSN ID not verified now"


def status_line(state: dict) -> str:
    """The longer line under the word, in the same plain words as /prsn status."""
    if state.get("error_words"):
        return state["error_words"]
    name = state.get("name") or "This PRSN"
    if state.get("verified") is None:
        return f"{name}. Its verified state could not be read just now. Try again in a moment."
    if not state.get("verified"):
        return f"{name}. {not_verified_now(state.get('last_beat'))}"
    beat = heartbeat_ago(state.get("last_beat"))
    return f"{name}. {STATE_VERIFIED}" + (f" {beat}" if beat else "")


# -- /prsn ---------------------------------------------------------------------------------------

HELP = ("/prsn status shows this agent's PRSN ID. "
        "/prsn setup shows how to give this agent a PRSN ID. "
        "/prsn about shows the plugin's version and code fingerprint.")


def about(version: str, fingerprint: str) -> str:
    return f"PRSN ID plugin {version}. Code fingerprint {fingerprint}."

SETUP = (
    "To give this agent a PRSN ID, a person does three things, and the agent does the rest.\n"
    f"1. Open {SIGN_UP} and create a PRSN ID account with a passkey.\n"
    "2. In the dashboard, open a PRSN ID account for this agent and copy its registration code. "
    f"Until the code is entered in PRSN Connect, the agent's PRSN ID is {SETUP_MIDDLE_STATE.lower()}\n"
    f"3. Install PRSN Connect from {CONNECT_PAGE} if it is not installed, and enter the code there.\n"
    "Then ask the agent who it is. It reads its PRSN ID from PRSN Connect.\n"
    f"More at {GETTING_STARTED}"
)
