# Security

## Credentials

- No credentials are hardcoded. `src/dq/db.py` reads everything from
  `.env` via `python-dotenv`. `.env` is gitignored; `.env.example` ships
  with placeholder values only.
- Two dedicated MySQL users, neither of them root:
  - **`dq_app`**: `SELECT` on `retail_banking` (read-only on the source
    data), full DML/DDL on `data_quality` and `dq_defect_copy` only.
    Verified directly: `UPDATE retail_banking.account` as `dq_app` is
    denied (`ERROR 1142`).
  - **`dq_dashboard`**: `SELECT`-only on `data_quality`. No access to
    `retail_banking` or `dq_defect_copy` at all. Verified directly: both
    a write attempt (`DELETE FROM dq_results`) and a read of
    `retail_banking.account` are denied for this user.
- **Limit, stated honestly**: `dq_app` has `CREATE`/`ALTER`/`DROP` on its
  two schemas because the engine recreates `dq_results`/`dq_exceptions`
  and the defect-injection script recreates the entire `dq_defect_copy`
  schema from scratch. A stricter setup would split this into a
  migration-only role and a DML-only app role, as noted for the sibling
  `retail-banking-analytics` project's `retail_app` user; not done here
  for the same reason - one developer, one schema, reused for both.

## SQL injection

- **No user-typed SQL anywhere.** `rules.yaml` is the only input surface
  this project has, and every table/column name it names is checked
  against `information_schema` (`src/dq/validation.py`) before any check
  in `src/dq/checks.py` builds a query with it - an unknown name is
  rejected with a clear error (`UnknownIdentifierError`), not silently
  used. Verified with a test that passes a classic injection-shaped
  string (`"...; DROP TABLE account"`) as a table name and confirms it's
  rejected (`tests/test_validation.py`).
- **Consistency and reconciliation rules can't carry arbitrary SQL at
  all.** `rules.yaml` only lets them name a fixed `formula` string (e.g.
  `loan_amount_equals_payments_times_duration`), which is looked up in a
  closed Python dict (`_CONSISTENCY_FORMULAS` / `_RECONCILIATION_FORMULAS`
  in `checks.py`). There's no code path from config text to a SQL
  expression for these two check types.
- **Every VALUE is bound, not interpolated** - `allowed_values`,
  `min_value`/`max_value`, `min_date`/`max_date` all go through SQLAlchemy
  bound parameters (`:name` placeholders, with an expanding `bindparam`
  for the `IN` list), even though pydantic already constrains their
  types. Only *identifiers* (already validated) are ever placed directly
  into an f-string.
- `bandit`'s B608 rule still flags every one of those identifier
  f-strings, since it can't see the validation that already happened -
  each is suppressed with an inline `# nosec B608` and a comment
  explaining why, never a bare suppression. One of the first attempts at
  this (in the reconciliation query) placed the `# nosec` comment just
  after an opening triple-quote, which would have landed the comment
  text *inside* the SQL string rather than suppressing anything -caught
  and fixed before it shipped (MySQL would have silently tolerated it as
  a `#`-comment inside the string, which is exactly the kind of "works
  by accident" bug this review process is meant to catch).

## Streamlit

- `.streamlit/config.toml`: bound to `127.0.0.1` (not `0.0.0.0`), no file
  uploads (`maxUploadSize = 0`), `developmentMode = false`,
  `showErrorDetails = false` (no stack traces/internals leaked to the
  viewer).
- The dashboard connects as `dq_dashboard` - even a bug in the dashboard
  code that tried to write would be rejected by MySQL itself, not just
  by the Python code's intentions.

## Dependency scanning

- `bandit -r src/` - 0 real findings (all B608s are the documented false
  positives above). `tests/` is intentionally not scanned: its only
  finding category is B101 (`assert` used), which is simply how pytest
  works and not a security concern.
- `pip-audit -r requirements.txt` - 0 known vulnerabilities as of this
  writing.
- Dependencies are pinned to exact versions, installed into a
  project-local `.venv` (never the global interpreter - this project's
  sibling, `retail-banking-analytics`, documents a real cross-project
  version conflict that motivated this).

## Data handling

- `data/raw/` (not used by this project directly, but shared with the
  sibling project) and `.env` are gitignored.
- `exceptions_reports/*.csv` are gitignored - they contain record-level
  failing keys (account IDs, loan IDs, etc.) by design, since that's the
  "drill down to failed records" requirement. `exports/scorecard.csv`
  **is** committed - aggregate pass/fail counts by table and check type
  only, no individual record ever appears in it.
- `dq_defect_copy` is a clearly-named, clearly-documented copy used only
  to prove the checks work; defects are planted and read there, never on
  `retail_banking`, verified directly after every injection run
  (`SELECT COUNT(*) FROM retail_banking.account` etc. unchanged at
  4500/682/5369 throughout this project's development).

## What this does *not* cover

- No authentication/authorization layer in front of the Streamlit
  dashboard itself - `127.0.0.1` binding is the only access control,
  appropriate for local development, not for exposing this on a network.
- No TLS on the MySQL connection (plain TCP to `127.0.0.1`).
- No automated CI re-running bandit/pip-audit on future changes - every
  scan in this file was run by hand in this session.
