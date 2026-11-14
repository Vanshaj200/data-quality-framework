# Interview Notes

## Design decisions and trade-offs

**Append-only run history, not truncate-and-reload.** Unlike the sibling
`retail-banking-analytics` project's loader (which truncates and reloads
every run, because the source data is a static snapshot), `dq_runs`/
`dq_results`/`dq_exceptions` grow with every run and are never truncated.
The dashboard's "trend across runs" requirement only makes sense if
history is kept — truncating would make every run look identical to the
last.

**No arbitrary SQL from `rules.yaml`, by construction, not by convention.**
Two separate mechanisms enforce this: every table/column name a rule
mentions is checked against `information_schema` before any check builds
SQL with it (`validation.py`), and `consistency`/`reconciliation` rules
can only name a fixed `formula` string that's looked up in a closed
Python dict — there's no field in the config schema that could ever hold
a raw SQL fragment or expression. A YAML-driven engine that lets config
build arbitrary `WHERE` clauses is a much easier initial design, but it's
exactly the injection surface the ground rules (and common sense) rule
out.

**`dq_dashboard` is a separate, more restricted user from `dq_app`.**
`dq_app` needs real DML/DDL rights to run the engine and defect
injection; the dashboard only ever reads. Giving the dashboard `dq_app`'s
credentials would work functionally, but a bug in dashboard code
couldn't write anything even if it tried — verified directly (a `DELETE`
attempt as `dq_dashboard` is rejected by MySQL, not just by the Python
code's good intentions).

**The defect-injection copy's constraints had to be understood, not just
copied.** `CREATE TABLE ... LIKE` copies indexes but not foreign keys
(verified directly against `information_schema` rather than assumed) -
so the FK-drop I initially wrote for the "orphan district" defect was
both unnecessary and wrong. Two *other* constraints genuinely needed
relaxing on the copy only (`loan.account_id`'s `UNIQUE` index,
`loan.status`'s strict-mode `ENUM`) - without that, two defects would
have been silently rejected by MySQL before any DQ rule ever ran,
making the demo prove nothing.

**Reconciliation only checks each account's final day, not every
transaction - and the defect-injection script had to respect that.** My
first attempt at the "corrupt a transaction's balance" defect targeted
8 arbitrary low-trans_id rows; the reconciliation check's failure count
didn't move at all, because those weren't any account's *last*
transaction and the check doesn't look at anything else. The fix had to
target genuinely final-day transactions - a reminder that a defect which
doesn't change the thing it's meant to break isn't actually testing
anything.

## Ten likely interview questions

**1. Walk me through what `python -m dq run --config rules.yaml` does.**
Loads and pydantic-validates `rules.yaml`, opens one run record in
`dq_runs`, then for each of the 23 rules: validates its table/column
names against `information_schema`, dispatches to one of six check
functions, compares the observed failure rate to the rule's threshold,
and writes one row to `dq_results` plus up to 50 sample failing records
to `dq_exceptions`. Exits 1 if any rule failed its threshold.

**2. How do you know the checks themselves are correct, not just that
they ran?** `tests/test_checks.py` asserts the exact real numbers for
each check type against the live data (e.g. the district completeness
gap is exactly 1/77, the VYBER anomaly is exactly 16,666/1,056,320) - a
future change to `checks.py` that silently breaks the logic fails a test
immediately, not just whenever someone next eyeballs a report.

**3. Why six check types instead of a more general "write any SQL" rule
type?** A general type would be simpler to build and more "powerful," but
it's also exactly the SQL-injection surface the project is meant to
avoid, and it would let a careless rule silently check the wrong thing
with no schema-level guardrails. Six named types means every rule's
intent is explicit and every rule's SQL is one of six well-tested
patterns, not a bespoke string.

**4. Explain the reconciliation check's methodology and why it changed.**
Documented in full in the sibling project's and this project's
traceability matrix: a naive per-transaction or cumulative-sum approach
gave a nonsensical 50-85% "failure" rate, traced to two real issues (no
intra-day ordering key; tiny rounding compounding when carried forward
cumulatively). The shipped version only compares each account's *final*
balance to the sum of all its deltas - correct by construction because
sum is order-independent, sidestepping the ordering problem entirely.

**5. What happens if `rules.yaml` has a typo in a column name?**
`validation.py`'s `validate_column` catches it before any SQL runs,
raising `UnknownIdentifierError` with the exact bad name and which
schema it checked - not a MySQL syntax error three layers down, and
never a silent no-op.

**6. How did you verify the defect-injection script actually proves
anything, rather than just not crashing?** Checked three things
explicitly: the five targeted rules (`DQ-006/007/009/016/022`) flip to
FAIL with `failed_rows` matching the exact count of rows I injected; the
reconciliation rule's exceptions table contains precisely the 8
account_ids I planted (checked by direct query, not inferred from the
aggregate); and every untouched rule, including the pre-existing
`DQ-021` anomaly, is bit-for-bit unchanged. Also re-ran against
`--source original` afterward and confirmed `retail_banking`'s row
counts never moved.

**7. Found any real bugs along the way?** Several, each caught by
actually running things rather than trusting the code: `CREATE TABLE
... LIKE` not copying foreign keys (assumed otherwise, verified and
corrected); stale InnoDB statistics after a bulk `INSERT ... SELECT`
making a query 40x+ slower until `ANALYZE TABLE` was added; a pydantic
v2 gotcha where a field validator silently never fires for a field left
at its default unless `validate_default=True` is set, which I only
caught because I wrote a test for the rejection path and it didn't
reject; and twice, `~some_column` on a pandas int64 (not bool) column
doing bitwise NOT instead of logical negation - caught once after
shipping (the scorecard's overall row showing -45 failures) and once
before (same pattern, different file, caught by recognizing it on sight
the second time).

**8. Why does `dq_app` have DDL rights on its own schemas?** Same honest
trade-off as the sibling project's `retail_app`: the engine recreates
`dq_results`/`dq_exceptions` and the defect script recreates all of
`dq_defect_copy` from scratch, so DML-only wouldn't be enough without a
separate migration role - not done here for the same single-developer
reason, stated plainly rather than glossed over.

**9. What's the weakest part of this project?** The reconciliation
check's threshold (2%) was calibrated to the real data's natural
rounding noise (1.42% baseline), which means a *small* number of newly
injected defects (8 accounts, pushing the rate to 1.6%) doesn't flip the
rule to FAIL even though every single planted defect is correctly
recorded in the exceptions table. That's arguably correct behavior (the
threshold shouldn't cry wolf over noise it's designed to tolerate), but
it means the scorecard alone isn't sufficient proof the check works -
you have to look at the exceptions, which the dashboard's drill-down
makes easy but which isn't obvious from the aggregate number alone.

**10. What would you improve with more time?** (1) A migration-only DB
role separate from `dq_app`, matching the sibling project's noted
improvement. (2) A day-level (not just final-day) reconciliation
variant, now that the ordering problem is well understood, to catch a
defect planted mid-history rather than only on an account's last day.
(3) CI running pytest/ruff/bandit/pip-audit on every push. (4) A
"freshness" check type (e.g. "this table should have rows from the last
N days") - not meaningful for this static historical dataset, but a real
gap for any project this framework might be pointed at next that isn't
frozen in 1998.

## Resume bullet options

(All numbers from `docs/traceability_matrix.md` and this session's
verified test runs, reproducible via `python -m dq run --config
rules.yaml`.)

1. Built a config-driven data quality framework (Python/pydantic/
   SQLAlchemy/MySQL 8) with 23 rules across 6 check types, enforcing
   zero-SQL-injection-surface by validating every rule's identifiers
   against `information_schema` and routing formula-based checks through
   a closed registry rather than ever evaluating config-supplied SQL.
2. Designed and validated a defect-injection harness that clones a
   1M+-row production-shaped dataset into a labelled copy, plants 6
   documented errors, and verifies 100% detection at the individual
   record level - catching and fixing 2 defects that initially landed on
   the wrong rows/constraints and would have proven nothing.
3. Shipped a Streamlit dashboard (scorecard, failed-record drill-down,
   cross-run trend) backed by a read-only database role verified unable
   to write even on a code-level bug, after finding and fixing a pandas
   bitwise-NOT bug that silently corrupted an aggregate metric.
