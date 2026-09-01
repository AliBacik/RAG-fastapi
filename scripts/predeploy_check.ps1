$projectRoot = Split-Path -Parent $PSScriptRoot

Set-Location -LiteralPath $projectRoot

$python = ".\venv\Scripts\python.exe"

& $python -m evals.analyzer_check

if($LASTEXITCODE -ne 0){
    Write-Error "Analyzer eval failed. Deployment blocked."

    exit 1
}

& $python -m evals.retrieve_check


if($LASTEXITCODE -ne 0){
    Write-Error "Retrieval eval failed. Deployment blocked."

    exit 1
}

& $python -m evals.run_answer_eval

if($LASTEXITCODE -ne 0){

    Write-Error "Answer eval failed. Deployment blocked."

    exit 1
}

Write-Host "Pre-deploy checks passed. Safe to deploy."