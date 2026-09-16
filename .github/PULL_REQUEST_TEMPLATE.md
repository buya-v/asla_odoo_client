## What this changes, and why it was wrong before

## How it was tested

- [ ] `odoo -d <db> -i asla_odoo_client --test-enable --test-tags /asla_odoo_client --stop-after-init`
- [ ] A test that would have failed before this change

## Data boundaries

- [ ] Offline mode still sends nothing out of the customer's network
- [ ] Nothing new writes to the customer's database without a plan and an approval step
- [ ] No secrets, customer data or internal hostnames in the code or the logs
