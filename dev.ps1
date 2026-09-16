param(
    [string]$Command = "help"
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot

switch ($Command) {
    "install" {
        Push-Location "$Root\api"
        & .\venv\Scripts\pip install -r requirements.txt
        Pop-Location
        Push-Location "$Root\client"
        & npm install
        Pop-Location
    }
    "backend" {
        Push-Location "$Root\api"
        & .\venv\Scripts\uvicorn main:app --reload --host 0.0.0.0 --port 8000
        Pop-Location
    }
    "frontend" {
        Push-Location "$Root\client"
        & npm run dev
        Pop-Location
    }
    default {
        Write-Host @"
Usage: .\dev.ps1 <command>

Commands:
  install   - Install all dependencies
  backend   - Start API server (port 8000)
  frontend  - Start Vite dev server (port 3000)
"@
    }
}
