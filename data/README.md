# Source data (not in Git)

Place the source CSVs here before running `make seed ENV=dev`:

| File | Rows | Notes |
|---|---|---|
| `order_items.csv` | 203,519 | one row per order line |
| `order_item_options.csv` | 193,017 | add-ons per order line |

The files are too large for GitHub and are excluded by `.gitignore` (only this README is tracked).
`date_dim` is not needed: the gold job generates the calendar.
Keep a backup outside the repo: the daily `make destroy` deletes the copies in S3.
