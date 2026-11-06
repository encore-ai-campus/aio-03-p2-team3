# Run this from the KE_KOREA_CO_LTD repository root in a PowerShell terminal.
# Safety: only push main after both targeted and full regression tests succeed.
$ErrorActionPreference = 'Stop'
function Run-Checked([string]$Description, [scriptblock]$Command) {
    Write-Host "`n== $Description ==" -ForegroundColor Cyan
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$Description failed (exit code $LASTEXITCODE). Main was not updated." }
}
if (-not (Test-Path '.\Quotation_KEKOREA\contracts\ui.py')) {
    throw 'Run this script from the KE_KOREA_CO_LTD repository root.'
}
$branch = (& git branch --show-current).Trim()
if ($branch -ne 'contract-work-continuation') {
    throw "Current branch is '$branch'. Switch to contract-work-continuation first."
}
if ((& git status --porcelain).Length -gt 0) {
    throw 'Working tree is not clean. Save or stash other changes before applying the patch.'
}
$patch = Join-Path $PSScriptRoot 'contract_work_fix.patch'
if (-not (Test-Path $patch)) { throw 'Cannot find contract_work_fix.patch next to this script.' }
Run-Checked 'Check patch can be applied' { git apply --check $patch }
Run-Checked 'Apply code, test, and README changes' { git apply $patch }
Run-Checked 'Check patch whitespace' { git diff --check }
Run-Checked 'Check Python compilation' { uv run --with-requirements .\Quotation_KEKOREA\requirements.txt python -m compileall -q .\Quotation_KEKOREA\contracts .\Quotation_KEKOREA\tests }
Run-Checked 'Contract workspace UI regression tests' { uv run --with-requirements .\Quotation_KEKOREA\requirements.txt python -m unittest Quotation_KEKOREA.tests.test_contract_workspace_ui }
Run-Checked 'All project regression tests' { uv run --with-requirements .\Quotation_KEKOREA\requirements.txt python -m unittest discover -s .\Quotation_KEKOREA\tests }
Run-Checked 'Commit verified work to continuation branch' { git add Quotation_KEKOREA/contracts/ui.py Quotation_KEKOREA/tests/test_contract_workspace_ui.py Quotation_KEKOREA/Team/README.md Quotation_KEKOREA/Presentation/README.md; git commit -m 'Fix contract list crash and document workflow verification' }
Run-Checked 'Push verified continuation branch' { git push origin contract-work-continuation }
Run-Checked 'Update local main without rewriting history' { git switch main; git pull --ff-only origin main }
Run-Checked 'Fast-forward main to verified work' { git merge --ff-only contract-work-continuation }
Run-Checked 'Push main' { git push origin main }
Write-Host "`nMain updated. Live Render/Streamlit deployment still requires separate verification." -ForegroundColor Green
