-- Preserve source payloads while retiring funds and debt imported as stocks.
-- Keep this applied migration immutable; domain.equity governs future imports.
SELECT pg_advisory_xact_lock(72201701);
UPDATE equity_instruments SET active=false
WHERE active AND NOT (
    isin NOT ILIKE 'INF%'
    AND coalesce(
        (exchange='NSE' AND payload->>'instrument_type'='EQ')
        OR (exchange='BSE' AND payload->>'instrument_type' IN
            ('A','B','T','X','XT','Z','P','ZP','M','MT','MS','TS')),
        false
    )
);
UPDATE equity_universe_refresh r
SET instrument_count=(SELECT count(*) FROM equity_instruments e
                      WHERE e.exchange=r.source_id AND e.active);
