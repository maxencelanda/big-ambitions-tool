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
$shell = New-Object -ComObject WScript.Shell
$s = $shell.CreateShortcut($link)
$s.TargetPath = Join-Path $PSScriptRoot "start.cmd"
$s.WorkingDirectory = $PSScriptRoot
$s.WindowStyle = 7  # minimized: the console only hosts the server
$s.IconLocation = "$env:SystemRoot\System32\imageres.dll,144"
$s.Description = "Big Ambitions save analytics (http://127.0.0.1:8765)"
$s.Save()
Write-Host "Created $link"
