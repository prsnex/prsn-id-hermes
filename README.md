# PRSN ID for Hermes

The PRSN ID platform provides verifiable digital credentials for AI agents and humans. With PRSN ID credentials, an AI agent can prove its identity and other credential claims to anyone.

A PRSN, pronounced "person", is an AI agent or AI entity with a PRSN ID.

PRSN ID establishes identity for an AI agent by binding the agent to a signing key on the computer it runs on (macOS, Windows or Linux) and to a human guardian who answers for it. An agent proves who it is through a link it offers, such as a Seal on an email or file it sends. Anyone who opens the link can check which PRSN it came from, and whether that PRSN is verified now.

The PRSN ID plugin for Hermes connects AI agents operating with Hermes Agent or Hermes Desktop to PRSN ID platform features.


## What you need

- Hermes 0.23.0 or later.
- PRSN Connect v0.2.0 or later, on the same computer and under the same user account as Hermes. PRSN Connect is a desktop app for macOS, Windows and Linux. It keeps the agent's signing key in the computer's secure hardware. A server with no desktop cannot run it today.
- A free PRSN ID account for you and your AI agent(s). The steps are below.


## What the plugin does

- **The agent knows who it is.** At the start of each session, the plugin tells the agent its PRSN ID and whether it is verified. It reads this live from PRSN Connect. It tells the agent again after Hermes compacts a long session.
- **It seals email and files.** Any person who receives a sealed email or file can check which PRSN sent it. Hermes asks you before each Seal, unless you choose otherwise. See more about Seals below.
- **`/prsn` shows the state.** `/prsn status` shows this agent's PRSN ID. `/prsn setup` shows how to give the agent a PRSN ID.
- **`/prsn about` names the code.** It shows the plugin's version and a code fingerprint, so you can tell which code Hermes has loaded.
- **Hermes Desktop shows the state.** A status bar item shows this agent's PRSN ID state.

The plugin runs no separate program or service of its own, and it keeps no keys or tokens. It offers five of the identity tools that PRSN Connect already provides. Two read and three seal. It never looks up another agent. It never offers purchases, credential issuing or sharing links. It reaches the PRSN ID platform only through PRSN Connect.


## Give your agent PRSN ID

A person does three things to get started with PRSN ID. The agent does the rest.

1. Open https://app.prsnid.ai/register and create a PRSN ID account with a passkey.
2. In the dashboard, open a PRSN ID account for your agent. Copy its registration code.
3. Install PRSN Connect from https://prsnid.ai/en/prsn-connect/ and enter the code there.

When you enter the code, PRSN Connect binds the agent's key to this computer and sends its first heartbeat. Then ask your agent who it is. Once it is verified, it can seal emails and files. More at https://prsnid.ai/en/getting-started/


## Install in Hermes Desktop

1. Open Capabilities, then Plugins, and choose Install from Git.
2. Paste `https://github.com/prsnex/prsn-id-hermes` and choose Review repository. Desktop shows what the repository holds before it installs anything.
3. Pick the profile your agent uses. Make sure Enable agent plugin after install is on. Then choose Install.

Desktop installs both halves of the plugin, the agent's and the status item's.


## Install from the terminal

```bash
hermes plugins install prsnex/prsn-id-hermes
hermes plugins enable prsn-id
```

To add the status item to Hermes Desktop, open Capabilities, then Plugins, and click Rescan. Then turn on PRSN ID. Desktop also finds it the next time it starts.


## More than one PRSN on this computer

PRSN Connect may serve more than one PRSN on this computer. In that case, name this agent's PRSN.

```bash
hermes config set plugins.entries.prsn-id.settings.prsn_name your-agent.prsn.eth
```


## Seals

A Seal lets the person who receives an email or file check that it came from a particular AI agent. The plugin offers three Seal tools.

| Tool | What it seals |
|---|---|
| `prsn_id_seal_file` | A file. The agent gets a link. The reader opens the link and drops their copy of the file on the page to check it is the same file. |
| `prsn_id_seal_message` | A whole email. PRSN Connect writes it as a new `.eml` file, sealed and ready to send. |
| `prsn_id_seal_email` | An email the agent is about to send another way. It returns a header and a footer with a link, to add before sending. |

The person who receives a sealed email opens the link in its footer. The page shows which PRSN sealed it, and when. The reader can also check that the email was sent to them. A Seal does not prove the email's words.

A sealed email must be sent exactly as it was sealed. Hermes's own email platform builds its own message, so it cannot send a sealed email unchanged yet. Send a sealed `.eml` file with a program that sends a file's bytes unchanged.

PRSN ID sets a daily allowance of Seals for each PRSN. A Seal expires after a time that PRSN ID sets.


### Your yes before each Seal

A Seal speaks for your agent's PRSN, and anyone with its link can check it. So Hermes asks you before each Seal, with its own approval prompt. If no one is there to answer, the Seal is not made.

In Hermes Desktop the request is titled Approval needed. Run makes the Seal. Reject stops it.

The prompt also offers two more choices. Allow this session stops Hermes asking until the session ends. Always allow stops it asking for that kind of Seal from then on, in every session. Choose it only if you trust every Seal of that kind your agent might make.

Hermes's own settings can also allow approvals in one-shot runs (`approvals.single_query_mode`) and in scheduled jobs (`approvals.cron_mode`). Each of these is your choice.


## Settings

| Setting | What it does |
|---|---|
| `prsn_name` | This agent's PRSN name. Needed only when PRSN Connect serves more than one PRSN on this computer. |
| `guardian` | The guardian's name, for the agent to say. PRSN Connect does not report it. |
| `server_log` | Keeps PRSN Connect's server log in the plugin's data folder, for finding a fault. Off by default. |


## What the agent is told

| What PRSN Connect shows | The words |
|---|---|
| No PRSN on this computer | No PRSN ID on this computer yet. |
| A PRSN that verifies | Verified. |
| A PRSN that does not verify now | Not verified now. The words then say what to do. |

A PRSN that does not verify now has missed its heartbeats or has been revoked. If its last heartbeat is thirty or more days old, the words say to open PRSN Connect so that it can send one. Otherwise they send you to its guardian, who can look in the PRSN ID dashboard.

A PRSN can seal only when it is verified. The plugin checks this live at each Seal.


## Where it is tested

The plugin is tested on macOS with Hermes 0.23.0 and PRSN Connect v0.2.0. On Windows, file Seals are refused, and a sealed message cannot carry attachments. PRSN Connect makes email Seals on all three systems. The plugin's Windows and Linux tests follow.


## Sharing a computer

PRSN Connect serves every PRSN bound on this computer under the same user account. Any program running as that user can reach its gateway. On a shared computer, give each agent its own user account and its own PRSN Connect. PRSN ID does not keep one agent on a computer from using another agent's gateway. The user account does.


## What the plugin reads, runs and sends

- It reads `~/.prsn-id/gateway.json`. PRSN Connect writes this file to say which PRSNs it serves. The file holds no token.
- It starts `prsn-gateway-mcp`, a program that PRSN Connect installed. It starts it when one of its tools is first called. It talks to it on this computer over standard input and output. It stops it when Hermes exits.
- For the Desktop status item, its backend route may start a second copy of `prsn-gateway-mcp`. That copy lives as long as the route's process. It reads the state at most once every fifteen minutes.
- It writes the last state it read to `status.json` in its own data folder, for the Desktop status item. That file holds a name, a yes or no, a heartbeat time and words. It holds no token and no address.
- PRSN Connect makes the calls to `api.prsnid.ai`. A Seal's link opens `verify.prsnid.ai`.
- With the `server_log` setting on, it writes PRSN Connect's server log to `server.log` in its own data folder. That log holds addresses and connection states. It holds no token.
- The plugin makes no network call of its own. It stores no credential. It sends no telemetry.


## When something is not working

After Hermes restarts, the Desktop status item can read PRSN ID not checked for up to five minutes, until its next check.

1. **Read PRSN Connect's words first.** When PRSN Connect refuses a request or cannot be reached, the plugin passes on its words unchanged. Those words say what to do.
2. **Open an issue in this repository.** Say what you did and what you saw. Add your PRSN's name if you are happy to share it. Never paste the contents of files from PRSN Connect's folders. Some of them hold your tokens.
3. **Write to hello@prsnid.ai.** A team in Canada reads it and replies within two business days.


## Development

The agent half uses only Python's standard library. The Desktop half's backend route uses FastAPI, which Hermes provides. The tests run against a stand-in for PRSN Connect's server.

```bash
python3 -m unittest discover -s tests -v
hermes plugins validate .
```


## Licence

MIT. Copyright 2026 PRSN EX Inc.
