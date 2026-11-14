# One-time setup: create an isolated venv, install dependencies, apply the
# results schema. Usage: ./scripts/setup.ps1
$ErrorActionPreference = "Stop"

if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment (.venv)..."
    python -m venv .venv
}

Write-Host "Installing Python dependencies into .venv (not the global interpreter)..."
.venv\Scripts\python.exe -m pip install --quiet --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt -e .

if (-not (Test-Path ".env")) {
    Write-Host "No .env found - copying .env.example. Edit it with your MySQL credentials before running run.ps1." -ForegroundColor Yellow
    Copy-Item ".env.example" ".env"
}

. "$PSScriptRoot\find_mysql.ps1"

$envVars = @{}
Get-Content ".env" | Where-Object { $_ -match "=" -and $_ -notmatch "^\s*#" } | ForEach-Object {
    $key, $value = $_ -split "=", 2
    $envVars[$key.Trim()] = $value.Trim()
}

Write-Host "Applying results schema to data_quality (sql/results_schema.sql)..."
$env:MYSQL_PWD = $envVars["DQ_MYSQL_PASSWORD"]
try {
    Get-Content "sql\results_schema.sql" | & $MySqlExe -u $envVars["DQ_MYSQL_USER"] -h $envVars["SOURCE_MYSQL_HOST"] $envVars["DQ_MYSQL_DB"]
} finally {
    Remove-Item Env:\MYSQL_PWD
}

Write-Host "Setup complete. Next: ./scripts/run.ps1"
