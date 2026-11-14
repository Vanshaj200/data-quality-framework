# Traceability Matrix

business requirement -> rule id -> check -> latest result.

Regenerate this table at any time with:

```sql
SELECT rule_id, description, table_name, check_type, severity,
       total_rows, failed_rows, ROUND(fail_rate*100,4) AS fail_rate_pct,
       ROUND(threshold*100,4) AS threshold_pct, passed
FROM dq_results WHERE run_id = (SELECT MAX(run_id) FROM dq_runs)
ORDER BY rule_id;
```

Data below is from the run captured when this file was written (`dq_runs.run_id`
visible via `python -m dq report`); re-run `python -m dq run --config rules.yaml`
to refresh it against the current data.

| Rule | Business requirement | Table | Check | Severity | Total | Failed | Fail % | Threshold % | Result |
|---|---|---|---|---|---:|---:|---:|---:|---|
| DQ-001 | Account identifiers must never be null | account | completeness | critical | 4,500 | 0 | 0.00 | 0.00 | PASS |
| DQ-002 | District 1995 unemployment rate present (known 1-district gap tolerated) | district | completeness | low | 77 | 1 | 1.30 | 2.00 | PASS |
| DQ-003 | District 1995 crime count present (known 1-district gap tolerated) | district | completeness | low | 77 | 1 | 1.30 | 2.00 | PASS |
| DQ-004 | account_id unique | account | uniqueness | critical | 4,500 | 0 | 0.00 | 0.00 | PASS |
| DQ-005 | client_id unique | client | uniqueness | critical | 5,369 | 0 | 0.00 | 0.00 | PASS |
| DQ-006 | At most one loan per account | loan | uniqueness | critical | 682 | 0 | 0.00 | 0.00 | PASS |
| DQ-007 | A client holds at most one disposition per account | disposition | uniqueness | high | 5,369 | 0 | 0.00 | 0.00 | PASS |
| DQ-008 | client.district_id references an existing district | client | referential_integrity | critical | 5,369 | 0 | 0.00 | 0.00 | PASS |
| DQ-009 | account.district_id references an existing district | account | referential_integrity | critical | 4,500 | 0 | 0.00 | 0.00 | PASS |
| DQ-010 | disposition.client_id references an existing client | disposition | referential_integrity | critical | 5,369 | 0 | 0.00 | 0.00 | PASS |
| DQ-011 | disposition.account_id references an existing account | disposition | referential_integrity | critical | 5,369 | 0 | 0.00 | 0.00 | PASS |
| DQ-012 | loan.account_id references an existing account | loan | referential_integrity | critical | 682 | 0 | 0.00 | 0.00 | PASS |
| DQ-013 | card.disp_id references an existing disposition | card | referential_integrity | critical | 892 | 0 | 0.00 | 0.00 | PASS |
| DQ-014 | permanent_order.account_id references an existing account | permanent_order | referential_integrity | critical | 6,471 | 0 | 0.00 | 0.00 | PASS |
| DQ-015 | transactions.account_id references an existing account | transactions | referential_integrity | critical | 1,056,320 | 0 | 0.00 | 0.00 | PASS |
| DQ-016 | loan.status is A/B/C/D | loan | validity | high | 682 | 0 | 0.00 | 0.00 | PASS |
| DQ-017 | account.frequency is one of 3 documented codes | account | validity | medium | 4,500 | 0 | 0.00 | 0.00 | PASS |
| DQ-018 | disposition.type is OWNER/DISPONENT | disposition | validity | medium | 5,369 | 0 | 0.00 | 0.00 | PASS |
| DQ-019 | card.type is junior/classic/gold | card | validity | low | 892 | 0 | 0.00 | 0.00 | PASS |
| DQ-020 | district.urban_ratio_pct is 0-100 | district | validity | medium | 77 | 0 | 0.00 | 0.00 | PASS |
| DQ-021 | transactions.type is only PRIJEM/VYDAJ | transactions | validity | medium | 1,056,320 | 16,666 | 1.58 | 1.00 | **FAIL (by design)** |
| DQ-022 | loan.amount = payments x duration | loan | consistency | high | 682 | 0 | 0.00 | 0.00 | PASS |
| DQ-023 | account final balance reconciles to sum of transactions | transactions | reconciliation | high | 4,500 | 64 | 1.42 | 2.00 | PASS |

## Notes on the two non-trivial results

**DQ-021 fails on purpose.** 16,666 of 1,056,320 transaction rows (1.58%)
use `"VYBER"` instead of the documented `"VYDAJ"`. This is deliberately
set below the real observed rate (threshold 1%) so the framework
demonstrably catches it, rather than being calibrated to always pass.
Cross-referenced against `retail-banking-analytics`'s independent
discovery of the same issue (verified there against account 485's balance
history) - two different analyses of the same raw data landed on the same
number, which is itself a form of validation.

**DQ-023's investigation.** The reconciliation rule went through three
iterations before landing on a defensible methodology - documented in full
in `docs/interview_notes.md`, summarized here: a naive per-transaction or
cumulative-sum check produced a nonsensical 50-85% "failure" rate, traced
to `trans_id` not reflecting true same-day transaction order (interest
postings use a separate ID series) and small rounding differences
compounding when carried forward cumulatively. The final check compares
only each account's *final* balance against the sum of all its deltas
(order-independent by construction, sidestepping the ordering problem
entirely): 4,436 of 4,500 accounts (98.6%) reconcile within $1, and every
single account reconciles within $5 - consistent with ordinary
floating-point rounding over a multi-year history, not a data defect.
