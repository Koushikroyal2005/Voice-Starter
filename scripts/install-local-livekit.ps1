param(
    [ValidatePattern('^\d+\.\d+\.\d+$')]
    [string]$Version = '1.13.11'
)

$ErrorActionPreference = 'Stop'
if ([Environment]::OSVersion.Platform -ne 'Win32NT') {
    throw 'This installer is for Windows. Use the official platform-specific release otherwise.'
}
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskTools = Join-Path $taskRoot '.local/livekit'
$architecture = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
$archiveArchitecture = switch ($architecture) {
    'X64' { 'amd64' }
    'Arm64' { 'arm64' }
    default { throw "Unsupported Windows architecture: $architecture" }
}
$archiveName = "livekit_${Version}_windows_${archiveArchitecture}.zip"
$releaseUrl = "https://github.com/livekit/livekit/releases/download/v$Version"
New-Item -ItemType Directory -Force -Path $taskTools | Out-Null
$archivePath = Join-Path $taskTools $archiveName
$checksumPath = Join-Path $taskTools 'checksums.txt'
Invoke-WebRequest -UseBasicParsing -Uri "$releaseUrl/$archiveName" -OutFile $archivePath
Invoke-WebRequest -UseBasicParsing -Uri "$releaseUrl/checksums.txt" -OutFile $checksumPath
$checksumLine = @(Get-Content -LiteralPath $checksumPath | Where-Object {
    $_ -match ('\s+' + [regex]::Escape($archiveName) + '$')
})
if ($checksumLine.Count -ne 1) { throw 'Expected exactly one official checksum entry.' }
$expected = ($checksumLine[0] -split '\s+')[0]
$actual = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash
if ($actual -ne $expected) { throw 'LiveKit archive checksum mismatch. Do not execute it.' }
# Stop your existing local server before reinstalling; Windows locks running binaries.
Expand-Archive -LiteralPath $archivePath -DestinationPath $taskTools -Force
Write-Output 'Official LiveKit archive checksum verified; installed in ignored .local/livekit.'
& (Join-Path $taskTools 'livekit-server.exe') --version
if ($LASTEXITCODE -ne 0) { throw 'Installed LiveKit binary could not start.' }
