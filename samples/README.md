# Sample files

Used by the unit tests, the e2e tests and the dashboard's "Simulate a partner
upload" button. All data is fictitious.

The demo partner accepts `orders_*.csv` and `orders_*.json` with schema
`orders_v1`: `order_id`, `sku`, `quantity` (integer >= 1), `unit_price`
(>= 0, at most 2 decimals), `currency` (ISO 4217, e.g. CHF).

| File | Expected outcome | Why |
|---|---|---|
| `valid/orders_basic.csv` | DELIVERED | |
| `valid/orders_extra_column.csv` | DELIVERED | extra columns are allowed |
| `valid/orders_batch.json` | DELIVERED | |
| `invalid/orders_missing_currency.csv` | REJECTED | missing column |
| `invalid/orders_negative_quantity.json` | REJECTED | quantity must be >= 1 |
| `invalid/orders_header_only.csv` | REJECTED | no data rows |
| `invalid/orders_broken.json` | REJECTED | invalid JSON |
| `invalid/invoice_2026.pdf.txt` | REJECTED | file name does not match the allowed patterns |
