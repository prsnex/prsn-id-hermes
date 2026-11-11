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
                    "autonomy level, last heartbeat, and whether it is verified now."),
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


# -- the question Hermes asks the human before a Seal --------------------------------------------

def approve_seal(tool: str, args: dict, prsn: Optional[str]) -> str:
    who = prsn or "this agent's PRSN"
    if tool == "seal_file":
        path = str(args.get("path") or "a file")
        name = path.replace("\\", "/").rsplit("/", 1)[-1]
        what = f"the file {name}"
    else:
        to = args.get("to") or []
        recipients = ", ".join(str(t) for t in to) if isinstance(to, list) else str(to)
        what = f"an email to {recipients}" if recipients else "an email"
    return (f"Seal {what} as {who}. "
            f"A Seal speaks for {who}, and anyone with its link can check it.")


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
