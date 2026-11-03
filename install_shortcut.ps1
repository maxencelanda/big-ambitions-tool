# Adds "Big Ambitions Analytics" to the Windows Start menu (current user). Run once:
#   powershell -ExecutionPolicy Bypass -File install_shortcut.ps1
# Pass -Remove to delete the shortcut.
param([switch]$Remove)

$link = Join-Path ([Environment]::GetFolderPath("Programs")) "Big Ambitions Analytics.lnk"
if ($Remove) {
    Remove-Item $link -ErrorAction SilentlyContinue
    Write-Host "Removed $link"
    exit
}
$pythonw = Join-Path $PSScriptRoot ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $pythonw) -or -not (Test-Path (Join-Path $PSScriptRoot "web\dist\index.html"))) {
    Write-Host "Run start.cmd once first (it installs Python packages and builds the interface)."
    exit 1
}
$shell = New-Object -ComObject WScript.Shell
$s = $shell.CreateShortcut($link)
# pythonw: no console window. Stop the server with the Quit button; the log goes to out\app.log.
$s.TargetPath = $pythonw
$s.Arguments = "app.py"
$s.WorkingDirectory = $PSScriptRoot
$s.IconLocation = "$env:SystemRoot\System32\imageres.dll,144"
$s.Description = "Big Ambitions save analytics (http://127.0.0.1:8765)"
$s.Save()
Write-Host "Created $link"
