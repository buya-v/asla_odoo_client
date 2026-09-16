# ASLA Client Agent (`asla_odoo_client`)

[![CI](https://github.com/buya-v/asla_odoo_client/actions/workflows/ci.yml/badge.svg)](https://github.com/buya-v/asla_odoo_client/actions/workflows/ci.yml) [![Licence: LGPL-3.0](https://img.shields.io/badge/licence-LGPL--3.0-blue.svg)](LICENSE) [![Odoo 18](https://img.shields.io/badge/Odoo-18.0-875A7B.svg)](https://www.odoo.com)

A free, open-source Odoo 18 module that puts an AI agent **inside your own Odoo**: it answers your
team's Odoo questions, takes support tickets, and prepares administration work for a person to
approve. It runs offline on your own machine, or online through the ASLA Hub when you want a larger
model and ASLA's Odoo knowledge.

Licence: **LGPL-3**. The paid part of ASLA is the hub, not this module — so you can read, audit and
change everything that touches your database.

## What it does today

- **AslaBot in Discuss** — ask how to do something in Odoo and get an answer, in Mongolian, grounded
  in your own configuration.
- **Support tickets** (`asla_client.ticket`) — raised inside your Odoo; the answer comes back into
  the ticket's chatter.
- **Administration with a plan** (`asla_client.operation`, `operation_plan`) — anything that changes
  data is planned and dry-run first and waits for approval.

## What leaves your network

| Mode | What is sent |
|---|---|
| **Offline** (default, `export_rfp`) | Nothing. The model runs next to your Odoo. |
| **Online** (`online`) | Your question and the **structure** of the models it touches — field names and types — never the rows in them. |

Reads run automatically. Writes are planned, dry-run and approved by a person. `res.users`,
`res.groups`, `ir.rule`, `ir.model.access`, `account.move`, `account.payment` and
`account.bank.statement` are **never** changed automatically, and that list lives in your database
(`SENSITIVE_MODELS`), not in ours.

## Requirements

- Odoo **18**, self-hosted or on Odoo.sh. Odoo Online (odoo.com) cannot install custom modules.
- For grounded **offline** answers: an `asla_odoo_ai` service reachable from Odoo (default
  `http://localhost:8080`). Without it the module falls back to Ollama directly
  (`http://localhost:11434`, `gemma4:e2b`); answers are then **not** grounded in your system, and
  AslaBot says so in its reply.
- A folder on your Odoo's `--addons-path`, writable by the Odoo user, if you want generated modules
  written there.

## Install

```bash
git clone https://github.com/buya-v/asla_odoo_client.git
# add the repository itself to --addons-path (it contains the module folder),
# then restart Odoo
```

The repository holds one folder, `asla_odoo_client/`, which is the module. Point Odoo's
`--addons-path` at the **repository**, not at the folder inside it.

Update the apps list, install **ASLA Client Agent**, then open
**AslaBot → Configuration → Settings**:

| Setting | Meaning |
|---|---|
| Operation Mode | `Offline Mode: Export RFP` (default), `Offline Mode: Import Generated App`, or `Online API` |
| Language Service URL | local `asla_odoo_ai` for grounded offline answers |
| Ollama URL / Model | ungrounded fallback |
| Generated Addons Path | where a generated module is written; must be on the addons path and writable |
| ASLA AI API Key / Server URL | for online mode |

## Connecting to the ASLA Hub

Online mode is currently set up **with ASLA staff**: we create your account, pair your Odoo with the
hub and check the first request with you. Write to us at <https://odoo.asla.mn/contactus>.

## Not built yet

- Pairing your Odoo from its own settings screen.
- Sending a module request from your Odoo to the hub.
- Requesting a module fully offline, by exporting a file and importing the result (today's upload is
  a placeholder).
- `asla_client.mcp.plan`'s own dry-run and execute buttons: the permission tiering on that model is
  real and reused, but there is no MCP call behind those two actions, so they refuse rather than
  report a success. The model that validates and executes is `asla_client.mcp.operation`.

## Support

Issues and pull requests are welcome on this repository. For the hosted service, prices and credits,
see <https://odoo.asla.mn>.
