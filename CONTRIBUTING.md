# Contributing

Thank you for looking at the ASLA Client Agent. It runs inside other people's ERP systems,
so the bar for changes is "could I explain this to the DBA whose database it touches".

## Running it locally

1. Odoo 18 on your own machine, self-hosted (Odoo Online cannot install custom modules).
2. Clone this repository into your addons path and restart Odoo.
3. Update the apps list and install **ASLA Client Agent**.
4. Open **AslaBot → Configuration → Settings**. Offline mode is the default and needs no account.

For grounded offline answers you need an `asla_odoo_ai` service reachable from Odoo. Without
it the module falls back to Ollama and states in its reply that the answer is not grounded.

## Tests

```bash
odoo -d <db> -i asla_odoo_client --test-enable --test-tags /asla_odoo_client --stop-after-init
```

CI runs exactly this on every pull request. A change without a test that would have failed
before it is unlikely to be merged.

## Ground rules for changes

- **Nothing new may write to the customer's database without a plan and an approval step.**
  Reads can be automatic; writes are planned, dry-run and confirmed by a person.
- `res.users`, `res.groups`, `ir.rule`, `ir.model.access`, `account.move`, `account.payment`
  and `account.bank.statement` are never automated. If you think you need an exception,
  open an issue first — the answer is probably no.
- **Offline mode must stay offline.** A change that sends anything out of the customer's
  network in offline mode is a bug, however useful the feature.
- In online mode, only the question and the *structure* of the models involved may leave —
  never the rows.
- No secrets, customer data or internal hostnames in the repository or in log lines.

## Style

- Follow the surrounding code; it is ordinary Odoo 18 Python and QWeb.
- Comments explain *why*, not *what*.
- Commit messages: a short subject line, then what changed and why it was wrong before.

## Reporting a security problem

Do not open a public issue. See [SECURITY.md](SECURITY.md).
