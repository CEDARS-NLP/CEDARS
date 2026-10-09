$ErrorActionPreference = "Stop"
$previousEnvironment = $env:UV_PROJECT_ENVIRONMENT

Push-Location $PSScriptRoot
try {
    $env:UV_PROJECT_ENVIRONMENT = Join-Path $PSScriptRoot ".venv-test"

    uv sync --python 3.12 --extra dev
    if ($LASTEXITCODE -ne 0) {
        throw "uv sync failed with exit code $LASTEXITCODE"
    }

    uv run --extra dev pytest @args
    $testExitCode = $LASTEXITCODE
}
finally {
    $env:UV_PROJECT_ENVIRONMENT = $previousEnvironment
    Pop-Location
}

if ($testExitCode -ne 0) {
    throw "pytest failed with exit code $testExitCode"
}