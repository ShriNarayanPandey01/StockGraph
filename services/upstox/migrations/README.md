# Data-service schema ownership

Run `upstox-bootstrap` before starting the API, worker, and scheduler. It applies
the idempotent numeric schema and catalog/job/outbox additions, then bootstraps
the packaged seed only when the entire SQL registry is empty. API/worker startup
also performs this safe initialization. No command in this package drops data.

`adapters/repositories/timescale/numeric.py` retains the existing numeric tables;
`catalog.py` adds the SQL canonical catalog, immutable catalog revisions, durable
registration jobs, provider fundamentals, normalized news, and transactional
graph outbox. Existing provider quote/news raw vintages are preserved.
