$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$tesseractVersion = "5.4.0.20240606"
$tesseractFile = "tesseract-ocr-w64-setup-$tesseractVersion.exe"
$tesseractUrl = "https://github.com/UB-Mannheim/tesseract/releases/download/v$tesseractVersion/$tesseractFile"
$downloadDir = Join-Path ([System.IO.Path]::GetTempPath()) ("Handwritify-" + [guid]::NewGuid().ToString("N"))
$tesseractSetup = Join-Path $downloadDir $tesseractFile

$iscc = Get-Command ISCC.exe -ErrorAction Stop
Push-Location $projectRoot
try {
    python -m PyInstaller --version
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller is not available. Install requirements-desktop-build.txt first."
    }
}
finally {
    Pop-Location
}

New-Item -ItemType Directory -Path $downloadDir | Out-Null
try {
    Invoke-WebRequest -Uri $tesseractUrl -OutFile $tesseractSetup -UseBasicParsing
    if (-not (Test-Path -LiteralPath $tesseractSetup -PathType Leaf)) {
        throw "Tesseract setup download failed: $tesseractUrl"
    }

    Push-Location $projectRoot
    try {
        New-Item -ItemType Directory -Force -Path (Join-Path $projectRoot "dist\installer") | Out-Null
        python -m PyInstaller --clean --noconfirm Handwritify.spec
        if ($LASTEXITCODE -ne 0) {
            throw "PyInstaller failed with exit code $LASTEXITCODE."
        }

        & $iscc.Source "/DTesseractSetup=$tesseractSetup" (Join-Path $PSScriptRoot "Handwritify.iss")
        if ($LASTEXITCODE -ne 0) {
            throw "Inno Setup Compiler failed with exit code $LASTEXITCODE."
        }
    }
    finally {
        Pop-Location
    }
}
finally {
    Remove-Item -LiteralPath $downloadDir -Recurse -Force
}
