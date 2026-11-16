# GitHub Windows runner의 기존 PostgreSQL에 고정한 pgvector를 빌드한다.
$ErrorActionPreference = 'Stop'
$serviceName = (Get-Service -Name 'postgresql-x64-*' | Select-Object -First 1).Name
$pgService = Get-CimInstance Win32_Service -Filter "Name='$serviceName'"
if (-not $pgService -or $pgService.PathName -notmatch '"([^\"]+)\\bin\\pg_ctl.exe"') {
    throw 'PostgreSQL 서비스의 설치 경로를 찾을 수 없습니다.'
}
$pgRoot = $Matches[1]
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
$visualStudio = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $visualStudio) { throw 'Visual C++ 빌드 도구가 필요합니다.' }
$compiler = Join-Path $visualStudio 'Common7\Tools\VsDevCmd.bat'
$directory = Join-Path $env:RUNNER_TEMP 'knowledge-pgvector'
git clone https://github.com/pgvector/pgvector.git $directory
if ($LASTEXITCODE) { throw 'pgvector 소스를 받지 못했습니다.' }
git -C $directory checkout f37c13f68b57d2c3472b2214fbcff699d6d34876
if ($LASTEXITCODE) { throw '고정한 pgvector 0.8.7 커밋을 찾지 못했습니다.' }
$batch = Join-Path $directory 'build-runner.cmd'
@"
@echo off
call "$compiler" -arch=x64 -host_arch=x64
if errorlevel 1 exit /b %errorlevel%
set "PGROOT=$pgRoot"
cd /d "$directory"
nmake /F Makefile.win
if errorlevel 1 exit /b %errorlevel%
nmake /F Makefile.win install
"@ | Set-Content -Path $batch -Encoding ascii
& cmd.exe /c $batch
if ($LASTEXITCODE) { throw 'Windows pgvector 빌드/설치에 실패했습니다.' }
