# Run in KE_KOREA_CO_LTD repository root, after finish_contract_ui.py.
$ErrorActionPreference = 'Stop'
if (-not (Test-Path '.\Quotation_KEKOREA\contracts\ui.py')) { throw 'Run from repository root.' }
if ((git branch --show-current).Trim() -ne 'contract-work-continuation') { throw 'Switch to contract-work-continuation before running.' }
Write-Host 'Checking diff scope...' -ForegroundColor Cyan
$tracked = @(git diff --name-only)
$allowed = @('Quotation_KEKOREA/contracts/ui.py', 'Quotation_KEKOREA/tests/test_contract_workspace_ui.py', 'Quotation_KEKOREA/tests/test_contract_library_ui.py', 'Quotation_KEKOREA/Team/README.md', 'Quotation_KEKOREA/Presentation/README.md')
$unexpected = @($tracked | Where-Object { $_ -and ($_ -notin $allowed) })
if ($unexpected.Count -gt 0) { throw ('Unexpected changed files: ' + ($unexpected -join ', ')) }
git diff --check
if ($LASTEXITCODE -ne 0) { throw 'git diff --check failed' }
Write-Host 'Running contract-specific tests...' -ForegroundColor Cyan
uv run --with-requirements .\Quotation_KEKOREA\requirements.txt python -m unittest discover -s .\Quotation_KEKOREA\tests -p 'test_contract*.py' -v
if ($LASTEXITCODE -ne 0) { throw 'Contract tests failed; no git changes pushed' }
Write-Host 'Contract tests passed. Running full suite for comparison...' -ForegroundColor Cyan
uv run --with-requirements .\Quotation_KEKOREA\requirements.txt python -m unittest discover -s .\Quotation_KEKOREA\tests -v 2>&1 | Tee-Object -FilePath .\contract_full_test_results.txt
$fullExit = $LASTEXITCODE
$log = Get-Content .\contract_full_test_results.txt -Raw
if ($fullExit -eq 0) { Write-Host 'Full test suite passed.' -ForegroundColor Green }
else {
  $known = 'test_annotations_load_prices_without_bypassing_product_confirmation'
  $failMatches = @([regex]::Matches($log, '(?m)^\s*FAIL:\s+([^\r\n]+)'))
  $errorMatches = @([regex]::Matches($log, '(?m)^\s*ERROR:\s+([^\r\n]+)'))
  $onlyKnownFailure = $failMatches.Count -eq 1 -and $errorMatches.Count -eq 0 -and $failMatches[0].Groups[1].Value.Contains($known) -and $log -match 'FAILED \(failures=1\)'
  if (-not $onlyKnownFailure) { throw 'Full suite has new or unexpected failures; no git changes pushed' }
  Write-Warning 'Full suite still has the pre-existing ECLADO test failure only; ECLADO code untouched. Treat as unresolved baseline issue.'
}
Write-Host 'Verification finished. Deployment not automatic: inspect and commit the scoped files after reviewing results.' -ForegroundColor Yellow
