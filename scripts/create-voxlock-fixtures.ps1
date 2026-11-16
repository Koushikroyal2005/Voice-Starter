param(
    [string]$OutputRoot = '.local/voxlock/synthetic',
    [string]$Python = '.local/voxlock/.venv/Scripts/python.exe'
)
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $repoRoot
$outputPath = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $OutputRoot))
git check-ignore --quiet -- (Join-Path $outputPath 'probe.wav')
if ($LASTEXITCODE -ne 0 -or (Test-Path -LiteralPath $outputPath)) {
    throw 'Choose a new ignored output directory.'
}
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $available = @($synth.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name })
    foreach ($voice in @('Microsoft David Desktop', 'Microsoft Zira Desktop')) {
        if ($available -notcontains $voice) { throw "Required offline voice unavailable: $voice" }
    }
    $raw = Join-Path $outputPath 'raw'
    New-Item -ItemType Directory -Path $raw | Out-Null
    $format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(
        16000,
        [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
        [System.Speech.AudioFormat.AudioChannel]::Mono
    )
    $phrases = @(
        @('target', 'Microsoft David Desktop', 'Please calculate two plus three and keep my voice clear.'),
        @('background', 'Microsoft Zira Desktop', 'We are watching television. This voice should stay in the background.'),
        @('enrollment', 'Microsoft David Desktop', 'Hello. This is the speaker I want you to preserve. Please remember this voice for the experiment.')
    )
    foreach ($phrase in $phrases) {
        $synth.SelectVoice($phrase[1])
        $synth.Rate = 0
        $synth.Volume = 100
        $synth.SetOutputToWaveFile((Join-Path $raw ($phrase[0] + '.wav')), $format)
        $synth.Speak($phrase[2])
        $synth.SetOutputToNull()
    }
} finally { $synth.Dispose() }
$env:PYTHONPATH = Join-Path $repoRoot 'backend'
& $Python -m app.evaluation.voxlock_fixtures --raw-dir $raw --output-dir (Join-Path $outputPath 'fixtures')
if ($LASTEXITCODE -ne 0) { throw 'Synthetic fixture generation failed.' }
Write-Output 'Created four local synthetic conditions; no cloud synthesis used.'
