# Security policy

## Supported versions

The `18.0` series, latest release. This module is developed against Odoo 18.

## Reporting a vulnerability

**Please do not open a public issue.**

- Preferred: GitHub's private vulnerability reporting, from the **Security** tab of this
  repository.
- Or email **devops@itauco.mn** with "SECURITY" in the subject.

Please include the Odoo version, whether the instance runs in offline or online mode, the
steps to reproduce, and what an attacker gains. A proof of concept helps; please do not test
against anyone else's instance.

**What to expect:** an acknowledgement within 3 working days, an assessment within 10, and
credit in the release notes unless you prefer otherwise.

## What this module exposes

- `/asla/bot/rpc` — a machine endpoint (the hub calls it) with no Odoo session. It requires a
  bearer token that is compared in constant time, refuses bodies over 1 MB, returns generic
  errors, and dispatches as superuser only after the token matches. **It answers at all only
  when the instance has been paired.**
- `/my/ai` and `/my/ai/upload_rfp` — portal pages for signed-in users.

Anything that changes data goes through a plan that a person approves; users, permissions
and accounting records are never changed automatically, and that list lives in the
customer's own database.
