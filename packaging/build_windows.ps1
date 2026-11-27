# Builds the program folder, the installer and the portable zip.
#   powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
# Needs Python 3.10+ on PATH.  Inno Setup 6 is optional: without it you still get dist\TxBridge and the zip.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

$version = (Select-String -Path txbridge\__init__.py -Pattern '__version__ = "([^"]+)"').Matches[0].Groups[1].Value
Write-Host "Building TxBridge $version"

if (-not (Test-Path .venv)) { py -3 -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip | Out-Null
& .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

# optional Xbox 360 output; the build still works without it
& .\.venv\Scripts\python.exe -m pip install -r requirements-xbox.txt
if ($LASTEXITCODE -ne 0) { Write-Warning "vgamepad did not install, so this build will not have the Xbox 360 output." }

& .\.venv\Scripts\python.exe -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "tests failed" }

& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean packaging\TxBridge.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

# portable zip: a data folder next to the exe switches TxBridge to portable mode
New-Item -ItemType Directory -Force dist\TxBridge\data | Out-Null
$zip = "dist\TxBridge-$version-portable.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path dist\TxBridge -DestinationPath $zip
Remove-Item -Recurse -Force dist\TxBridge\data

$iscc = @("$env:ProgramFiles(x86)\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
          "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($iscc) {
    & $iscc "/DAppVersion=$version" packaging\installer.iss
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
} else {
    Write-Warning "Inno Setup 6 not found, skipping the installer. Get it from https://jrsoftware.org/isdl.php"
}
Write-Host "`nDone. Output is in dist\"
Get-ChildItem dist -File | Format-Table Name, @{n="MB";e={[math]::Round($_.Length/1MB,1)}}
