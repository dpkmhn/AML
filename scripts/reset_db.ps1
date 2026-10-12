# Drop the database volume and start a fresh Postgres; init scripts in db/init re-run.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
docker compose down -v
docker compose up -d --wait
Write-Host "Database reset. Load data with: uv run python -m data.generator.generate --reset"
