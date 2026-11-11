# PRSN ID for Hermes

The PRSN ID platform provides verifiable digital credentials for AI agents and humans. With PRSN ID credentials, an AI agent can prove its identity and other credential claims to anyone.

A PRSN, pronounced "person", is an AI agent or AI entity with a PRSN ID.

PRSN ID establishes identity for an AI agent by binding the agent to a signing key on the computer it runs on (macOS, Windows or Linux) and to a human guardian who answers for it. An agent proves who it is through a link it offers, such as a Seal on an email or file it sends. Anyone who opens the link can check which PRSN it came from, and whether that PRSN is verified now.

The PRSN ID plugin for Hermes connects AI agents operating with Hermes Agent or Hermes Desktop to PRSN ID platform features.


## What you need

- Hermes 0.23.0 or later.
- PRSN Connect v0.2.1 or later, on the same computer and under the same user account as Hermes. PRSN Connect is a desktop app for macOS, Windows and Linux. It keeps the agent's signing key in the computer's secure hardware. A server with no desktop cannot run it today.
- A free PRSN ID account for you and your AI agent(s). The steps are below.


## What the plugin does

- **The agent knows who it is.** At the start of each session, the plugin tells the agent its PRSN ID and whether it is verified. It reads this live from PRSN Connect. It tells the agent again after Hermes compacts a long session.
- **It seals email and files.** Any person who receives a sealed email or file can check which PRSN sent it. Hermes asks you before each Seal, unless you choose otherwise. After a file Seal, the Seal's page opens in the browser on the computer where Hermes runs. See more about Seals below.
- **`/prsn` shows the state.** `/prsn status` shows this agent's PRSN ID. `/prsn setup` shows how to give the agent a PRSN ID.
- **`/prsn about` names the code.** It shows the plugin's version and a code fingerprint, so you can tell which code Hermes has loaded.
- **Hermes Desktop shows the state.** A status bar item shows this agent's PRSN ID state.

The plugin runs no separate program or service of its own, and it keeps no keys or tokens. It offers four of the identity tools that PRSN Connect already provides. Two read and two seal. It never looks up another agent. It never offers purchases, credential issuing or sharing links. It reaches the PRSN ID platform only through PRSN Connect.


## Give your agent PRSN ID

A person does three things to get started with PRSN ID. The agent does the rest.

1. Open https://app.prsnid.ai/register and create a PRSN ID account with a passkey.
2. In the dashboard, open a PRSN ID account for your agent. Copy its registration code.
3. Install PRSN Connect from https://prsnid.ai/en/prsn-connect/ and enter the code there.

When you enter the code, PRSN Connect binds the agent's key to this computer and sends its first heartbeat. Then ask your agent who it is. Once it is verified, it can seal emails and files. More at https://prsnid.ai/en/getting-started/


## Install in Hermes Desktop

1. Open Capabilities, then Plugins, and choose Install from Git.
2. Paste `https://github.com/prsnex/prsn-id-hermes` and choose Review repository. Desktop shows what the repository holds before it installs anything.
3. Pick the profile your agent uses. If Desktop offers Enable agent plugin after install, keep it on. Then choose Install.

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

A Seal lets the person who receives an email or file check that it came from a particular AI agent. The plugin offers two Seal tools.

| Tool | What it seals |
|---|---|
| `prsn_id_seal_file` | A file. The Seal's page opens in the browser on the computer where Hermes runs. Share the page's address with the reader. The reader opens it and drops their copy of the file on the page to check it is the same file. |
| `prsn_id_seal_message` | A whole email. PRSN Connect writes it as a new `.eml` file, sealed and ready to send. |

The person who receives a sealed email opens the link in its footer. The page shows which PRSN sealed it, and when. The reader can also check that the email was sent to them. A Seal does not prove the email's words.

A sealed email must be sent exactly as it was sealed. Hermes's email gateway, which answers mail sent to the agent, builds its own message. So it cannot send a sealed email unchanged.

The agent can send the sealed `.eml` file with Himalaya 2, the email client that Hermes's bundled email skill uses. Himalaya 2's raw send passes the file to your mail server as it is. The command below is for Himalaya 2. Hermes's skill describes older Himalaya commands.

```bash
himalaya smtp send -f you@example.com -t reader@example.com -- /path/to/sealed.eml
```

Use the same From address that the Seal names, and send from that mailbox. Any other program that sends a file's bytes unchanged works too. The reader can drop their copy of the email on the Seal page to check that it matches.

PRSN ID sets a daily allowance of Seals for each PRSN. A Seal expires after a time that PRSN ID sets.


### Your yes before each Seal

A Seal speaks for your agent's PRSN, and anyone with its link can check it. So Hermes asks you before each Seal, with its own approval prompt. If no one is there to answer, the Seal is not made. A Hermes run that asks nothing is the exception, as the end of this section says.

In Hermes Desktop the request is a card headed Command details, which says what will be sealed and as which PRSN. Its notification is titled Approval needed. Run makes the Seal. Reject stops it.

The prompt also offers two more choices. Allow this session stops Hermes asking until the session ends. Always allow stops it asking for that kind of Seal from then on, in every session. Choose it only if you trust every Seal of that kind your agent might make.

Hermes's own settings can also allow approvals in single-query runs started with `hermes chat -q` (`approvals.single_query_mode`) and in scheduled jobs (`approvals.cron_mode`). Each of these is your choice.

The approval covers the plugin's Seal tools. An agent that can run commands as you could also reach PRSN Connect another way, for example by starting PRSN Connect's own server itself. So the plugin also asks you before a terminal command, file action, script, scheduled job or browser action of Hermes's own that names PRSN Connect, its server, its folders or its local gateway. Run it only if you asked for it. Allow this session and Always allow then cover that one call only. This catches an agent that goes around the plugin. It is not a wall, since a command can hide what it reaches, and the tools of other plugins and MCP servers are not covered. The approval covers an agent that uses the tools it is given. An agent with command access that sets out to go around it is stopped only where it names what it reaches.

With Hermes's approvals off, in yolo mode, or in a one-shot run started with `hermes -z`, Hermes asks nothing, this check and each Seal included. An agent that can run commands can start such a run itself.


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

The plugin's code, fingerprint `dae383b93c7b`, is tested on macOS with Hermes 0.23.0, and on Windows 11 and Ubuntu with Hermes 0.23.1, each with PRSN Connect v0.2.1. On Windows and Ubuntu, an agent sealed an email that verified on its Seal page. On macOS and Ubuntu, it sealed a file, and the Seal's page opened by itself and verified. On Windows, file Seals are refused, and a sealed message cannot carry attachments. On macOS, with the plugin's earlier code, an agent sealed an email and sent it with Himalaya 2.2.1, and the received copy matched on its Seal page.


## Sharing a computer

PRSN Connect serves every PRSN bound on this computer under the same user account. Any program running as that user can reach its gateway, an agent's own commands included. On a shared computer, give each agent its own user account and its own PRSN Connect. PRSN ID does not keep one agent on a computer from using another agent's gateway. The user account does.


## What the plugin reads, runs and sends

- It reads `~/.prsn-id/gateway.json`. PRSN Connect writes this file to say which PRSNs it serves. The file holds no token.
- It starts `prsn-gateway-mcp`, a program that PRSN Connect installed. It starts it when one of its tools is first called. It talks to it on this computer over standard input and output. It stops it when Hermes exits.
- For the Desktop status item, its backend route may start a second copy of `prsn-gateway-mcp`. That copy lives as long as the route's process. It reads the state at most once every fifteen minutes.
- It writes the last state it read to `status.json` in its own data folder, for the Desktop status item. That file holds a name, a yes or no, a heartbeat time and words. It holds no token and no address.
- PRSN Connect makes the calls to `api.prsnid.ai`. A Seal's link opens `verify.prsnid.ai`.
- Before a terminal command, file action, script, scheduled job or browser action of Hermes's own that names PRSN Connect, its server, its folders or its local gateway, it asks you through Hermes's approval prompt.
- After a file Seal, it opens the Seal's page at `verify.prsnid.ai` in the default browser of the computer where Hermes runs. Hermes masks the link's signed part in the agent's replies, so the page opens there instead. It opens no other address. On Linux it opens the page only when a display is present.
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
