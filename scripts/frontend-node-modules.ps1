# Keep the web UI's node_modules and .next OUT of the OneDrive-synced repository folder.
#
# A Node project is about 12,000 files in node_modules alone, and the build cache changes constantly. OneDrive would
# sync all of it. This script moves both folders to C:\dev\frontend and leaves a junction (a folder shortcut that needs
# no admin rights) in their place, the same way the Python venv lives in C:\dev\venvs.
#
# Run it after EVERY `npm install`: npm treats a junction as "not a directory" and replaces it with a real folder.
# Safe to run any time: a folder that is already a junction is left alone.
#
#   powershell -File scripts\frontend-node-modules.ps1
#   powershell -File scripts\frontend-node-modules.ps1 -Target D:\dev\frontend
param([string]$Target = "C:\dev\frontend")

$ErrorActionPreference = "Stop"
$frontend = Join-Path (Split-Path $PSScriptRoot -Parent) "frontend"
if (-not (Test-Path $frontend)) { throw "No frontend folder at $frontend" }

$stores = [ordered]@{ "node_modules" = "node_modules"; ".next" = "next-cache" }
foreach ($name in $stores.Keys) {
    $link = Join-Path $frontend $name
    $store = Join-Path $Target $stores[$name]
    New-Item -ItemType Directory -Force -Path $store | Out-Null

    $item = Get-Item $link -Force -ErrorAction SilentlyContinue
    if ($item -and $item.LinkType -eq "Junction") {
        "{0}: already a junction to {1}" -f $name, ($item.Target -join ", ")
        continue
    }
    if ($item) {
        # A real folder: move what is in it, then take the (now empty) folder away so a junction can take its name.
        robocopy $link $store /E /MOVE /NFL /NDL /NJH /NJS /NP /R:1 /W:1 | Out-Null
        if ($LASTEXITCODE -ge 8) { throw "Moving $name failed (robocopy exit code $LASTEXITCODE). Nothing was deleted." }
        if (Test-Path $link) { Remove-Item $link -Recurse -Force }
    }
    New-Item -ItemType Junction -Path $link -Target $store | Out-Null
    "{0}: moved to {1} and linked" -f $name, $store
}
