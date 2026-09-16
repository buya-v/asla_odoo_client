# ASLA Client Agent (`asla_odoo_client`)

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
# put it on your addons path, then restart Odoo
```

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

## Support

Issues and pull requests are welcome on this repository. For the hosted service, prices and credits,
see <https://odoo.asla.mn>.
