-- Dashboard: Data Quality → results of the most recent DQ gate run.
SELECT run_ts, severity, check_name, value, passed
FROM gp_gold.dq_results
WHERE run_ts = (SELECT max(run_ts) FROM gp_gold.dq_results)
ORDER BY severity, passed, check_name
