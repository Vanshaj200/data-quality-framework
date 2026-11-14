# Runs every rule against the real data, writes the exceptions report and
# scorecard, then runs the pytest suite. Usage: ./scripts/run.ps1
$ErrorActionPreference = "Stop"

Write-Host "Running all rules in rules.yaml against the real data..."
.venv\Scripts\python.exe -m dq run --config rules.yaml --report

Write-Host "Running tests..."
.venv\Scripts\python.exe -m pytest

Write-Host "Done. See exports/scorecard.csv, exceptions_reports/, and logs/dq.log."
Write-Host "To see the dashboard: .venv\Scripts\streamlit.exe run src/dq/dashboard.py"
