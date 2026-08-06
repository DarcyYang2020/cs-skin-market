# Install git pre-commit hook: run test_smoke before every commit (local CI).
# Run from cs-skin-market/:  powershell -ExecutionPolicy Bypass -File install_hooks.ps1
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$hookDir = Join-Path $repo ".git\hooks"
if (-not (Test-Path $hookDir)) { Write-Error ".git/hooks not found (not a git repo?)"; exit 1 }
$hook = Join-Path $hookDir "pre-commit"
$lines = @(
  '#!/bin/sh',
  '# CS project pre-commit: run smoke tests (installed by install_hooks.ps1).',
  'PROJ="$(dirname "$0")/../../cs-skin-market"',
  'cd "$PROJ" || { echo "[pre-commit] cannot cd to cs-skin-market"; exit 1; }',
  'echo "[pre-commit] running python tests/test_smoke.py ..."',
  'python tests/test_smoke.py',
  'status=$?',
  'if [ $status -ne 0 ]; then',
  '  echo "[pre-commit] tests FAILED - commit aborted (fix tests or use --no-verify)"',
  '  exit 1',
  'fi',
  'echo "[pre-commit] tests passed"',
  'exit 0'
)
$content = $lines -join "`n"
[System.IO.File]::WriteAllText($hook, $content, (New-Object System.Text.UTF8Encoding($false)))
Write-Host "pre-commit hook installed: $hook"