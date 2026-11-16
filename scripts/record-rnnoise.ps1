param(
    [Parameter(Mandatory = $true)][string]$OutputFile,
    [ValidateRange(1, 60)][int]$Seconds = 30
)
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $repoRoot
$recordingPath = if ([System.IO.Path]::IsPathRooted($OutputFile)) {
    [System.IO.Path]::GetFullPath($OutputFile)
} else {
    [System.IO.Path]::GetFullPath((Join-Path $repoRoot $OutputFile))
}
if ($recordingPath.Contains('"') -or [System.IO.Path]::GetExtension($recordingPath) -ne '.wav') {
    throw 'Use a WAV path without quotation characters.'
}
git check-ignore --quiet -- $recordingPath
if ($LASTEXITCODE -ne 0 -or (Test-Path -LiteralPath $recordingPath)) {
    throw 'Choose an absent, Git-ignored WAV path under .local/.'
}
if (-not ('VoiceStarterRecorder' -as [type])) {
    Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class VoiceStarterRecorder {
    [DllImport("winmm.dll", CharSet = CharSet.Unicode)]
    public static extern uint mciSendString(string command, IntPtr result, uint size, IntPtr callback);
}
'@
}
function Send-RecorderCommand([string]$Command) {
    $code = [VoiceStarterRecorder]::mciSendString($Command, [IntPtr]::Zero, 0, [IntPtr]::Zero)
    if ($code -ne 0) { throw "Windows recording failed (MCI code $code). Check microphone privacy/default input and format support." }
}
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $recordingPath) | Out-Null
$aliasName = 'voice' + [Guid]::NewGuid().ToString('N')
try {
    Send-RecorderCommand "open new type waveaudio alias $aliasName"
    Send-RecorderCommand "set $aliasName format tag pcm channels 1 samplespersec 48000 bitspersample 16 alignment 2 bytespersec 96000"
    Write-Output "Recording the Windows default microphone for $Seconds seconds. Speak now."
    Send-RecorderCommand "record $aliasName"
    Start-Sleep -Seconds $Seconds
    Send-RecorderCommand "stop $aliasName"
    Send-RecorderCommand "save $aliasName `"$recordingPath`""
} finally {
    [void][VoiceStarterRecorder]::mciSendString("close $aliasName", [IntPtr]::Zero, 0, [IntPtr]::Zero)
}
Write-Output 'Recording saved locally. The evaluator will validate its PCM format.'
