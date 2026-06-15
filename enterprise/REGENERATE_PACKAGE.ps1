$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $projectRoot "venv\Scripts\python.exe"
$htmlPath = Join-Path $PSScriptRoot "ENERWISE_ENTERPRISE_BRIEFING.html"
$pdfPath = Join-Path $PSScriptRoot "ENERWISE_ENTERPRISE_BRIEFING.pdf"

if (-not (Test-Path $python)) {
    throw "Project Python environment not found at $python"
}

Push-Location $projectRoot
try {
    & $python -m app.benchmarks.enterprise_benchmark
    if ($LASTEXITCODE -ne 0) {
        throw "Enterprise benchmark failed with exit code $LASTEXITCODE"
    }

    & $python -m app.benchmarks.render_enterprise_briefing
    if ($LASTEXITCODE -ne 0) {
        throw "Enterprise briefing render failed with exit code $LASTEXITCODE"
    }

    $edgeCandidates = @(
        "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
        "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe"
    )
    $edge = $edgeCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

    if (-not $edge) {
        Write-Warning "Microsoft Edge not found. HTML generated; PDF was not refreshed."
        return
    }

    $htmlUri = [System.Uri]::new($htmlPath).AbsoluteUri
    $runId = [System.Guid]::NewGuid().ToString("N")
    $temporaryPdf = Join-Path $env:TEMP "enerwise-briefing-$runId.pdf"
    $edgeProfile = Join-Path $env:TEMP "enerwise-edge-$runId"
    $arguments = @(
        "--headless",
        "--disable-gpu",
        "--no-pdf-header-footer",
        "--user-data-dir=$edgeProfile",
        "--print-to-pdf=$temporaryPdf",
        $htmlUri
    )
    try {
        $process = Start-Process `
            -FilePath $edge `
            -ArgumentList $arguments `
            -WindowStyle Hidden `
            -Wait `
            -PassThru
        if ($process.ExitCode -ne 0) {
            throw "PDF generation failed with exit code $($process.ExitCode)"
        }

        $deadline = (Get-Date).AddSeconds(15)
        while ((-not (Test-Path $temporaryPdf)) -and (Get-Date) -lt $deadline) {
            Start-Sleep -Milliseconds 250
        }
        if (-not (Test-Path $temporaryPdf)) {
            throw "PDF generation completed without producing a file"
        }

        Move-Item -LiteralPath $temporaryPdf -Destination $pdfPath -Force
    }
    finally {
        if (Test-Path $temporaryPdf) {
            Remove-Item -LiteralPath $temporaryPdf -Force
        }
        if (Test-Path $edgeProfile) {
            Remove-Item -LiteralPath $edgeProfile -Recurse -Force
        }
    }

    Write-Host "Enterprise package regenerated:"
    Write-Host "  Evidence: $PSScriptRoot\evidence"
    Write-Host "  Briefing: $htmlPath"
    Write-Host "  PDF:      $pdfPath"
}
finally {
    Pop-Location
}
