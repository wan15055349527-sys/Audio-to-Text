$ErrorActionPreference = 'Stop'
$source = $PSScriptRoot
$artifacts = Join-Path $source 'build'
$python = if ($env:TINGGAO_PYTHON) { $env:TINGGAO_PYTHON } else { 'python' }
$models = if ($env:TINGGAO_MODELS) { $env:TINGGAO_MODELS } else { Join-Path $source 'models' }
foreach ($required in @('whisper-base/model.bin','whisper-base/config.json','whisper-base/tokenizer.json','whisper-base/vocabulary.txt','paraformer/model.int8.onnx','paraformer/tokens.txt')) {
    if (-not (Test-Path (Join-Path $models $required) -PathType Leaf)) { throw "Missing model file: $required" }
}
Push-Location $source
try {
    & $python -m PyInstaller --noconfirm --onedir --windowed --noupx --name TingGao `
        --log-level WARN --specpath $artifacts --workpath (Join-Path $artifacts 'work') `
        --distpath (Join-Path $artifacts 'dist') --add-data ((Join-Path $source 'web') + ';web') `
        --collect-data faster_whisper --collect-binaries sherpa_onnx `
        --collect-all webview --collect-all pythonnet --collect-all clr_loader `
        --hidden-import webview.platforms.edgechromium launch.py
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed ($LASTEXITCODE)." }
    $app = Join-Path $artifacts 'dist\TingGao'
    foreach ($file in @('whisper-base/model.bin','whisper-base/config.json','whisper-base/tokenizer.json','whisper-base/vocabulary.txt','paraformer/model.int8.onnx','paraformer/tokens.txt')) {
        $dest = Join-Path (Join-Path $app 'models') $file
        New-Item -ItemType Directory -Path (Split-Path $dest) -Force | Out-Null
        Copy-Item -LiteralPath (Join-Path $models $file) -Destination $dest
    }
    Copy-Item -LiteralPath 'README.md','THIRD-PARTY.md' -Destination $app
    & $python 'collect-licenses.py' (Join-Path $app 'licenses')
    if ($LASTEXITCODE -ne 0) { throw "License notice collection failed ($LASTEXITCODE)." }
    Write-Output $app
} finally {
    Pop-Location
}
