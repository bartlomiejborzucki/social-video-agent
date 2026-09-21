<#
.SYNOPSIS
    Run the Linux editing engine from a native Windows agent.

.DESCRIPTION
    The agent may be a native Windows Codex process. The editing engine is not:
    FFmpeg, FFprobe, Python, Node, Remotion, its Chromium and local
    transcription live inside WSL2 and stay there. This adapter is the only
    supported bridge between the two.

    What it deliberately does not do:

    * build a command string. Every argument is passed through as a separate
      argv element, so a path with spaces, Polish characters, brackets or a
      dollar sign is a filename and not shell syntax.
    * use Invoke-Expression, or hand anything to `sh -lc`.
    * fall back to ffmpeg.exe, Windows Python or Windows Node. A run that mixed
      Windows and Linux binaries would produce a different result from the one
      that was reviewed, so it fails instead.
    * install anything. If WSL or the engine is missing it says exactly what is
      missing and stops.

    stdout and stderr are passed through untouched and the engine's exit code
    becomes this script's exit code, so a caller can branch on it. Ctrl+C is
    forwarded to the engine rather than orphaning it.

.PARAMETER Distribution
    WSL distribution to run in. Defaults to $env:SOCIAL_VIDEO_WSL_DISTRIBUTION,
    then to the WSL default. With several WSL2 distributions and no default it
    stops rather than choosing one for you.

.EXAMPLE
    .\social-video-agent.ps1 doctor

.EXAMPLE
    .\social-video-agent.ps1 workflow init "C:\Users\User\Videos\Mój film.mp4" --project-root "C:\Users\User\projects\reel"
#>
[CmdletBinding()]
param(
    [string]$Distribution = $env:SOCIAL_VIDEO_WSL_DISTRIBUTION,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$EngineArgs
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$EngineCommand = 'social-video-agent'

function Fail {
    param([string]$Problem, [string]$Message)
    # One machine-readable problem name per failure: a caller has to be able to
    # tell a missing WSL install from a missing engine inside a working one.
    [Console]::Error.WriteLine("social-video-agent: ${Problem}: ${Message}")
    exit 3
}

function Get-WslBinary {
    $candidate = Get-Command 'wsl.exe' -CommandType Application -ErrorAction SilentlyContinue
    if (-not $candidate) {
        Fail 'wsl_missing' @'
wsl.exe was not found, so the Linux editing engine cannot be reached.
Install WSL2 and a distribution with `wsl --install`, then reopen this session.
Nothing is installed for you, and no Windows FFmpeg/Python/Node is used instead.
'@
    }
    return $candidate.Source
}

function Get-Distributions {
    param([string]$Wsl)
    # WSL writes UTF-16LE here; decoding it as anything else yields NUL bytes
    # between every character and no distribution is ever matched.
    $previous = [Console]::OutputEncoding
    try {
        [Console]::OutputEncoding = [System.Text.Encoding]::Unicode
        $raw = & $Wsl --list --verbose 2>&1
    } finally {
        [Console]::OutputEncoding = $previous
    }
    if ($LASTEXITCODE -ne 0) {
        Fail 'wsl_broken' "``wsl --list --verbose`` failed: $($raw -join ' ')"
    }
    $found = @()
    foreach ($line in $raw) {
        $text = ($line -replace "`0", '').Trim()
        if (-not $text) { continue }
        $isDefault = $text.StartsWith('*')
        $text = $text.TrimStart('*').Trim()
        $parts = $text -split '\s+'
        if ($parts.Count -lt 3) { continue }
        $version = $parts[-1]
        if ($version -notmatch '^\d+$') { continue }   # the localised header row
        $found += [pscustomobject]@{
            Name    = ($parts[0..($parts.Count - 3)] -join ' ')
            Version = [int]$version
            Default = $isDefault
        }
    }
    return $found
}

function Select-Distribution {
    param([object[]]$Found, [string]$Requested)
    if ($Found.Count -eq 0) {
        Fail 'no_distribution' 'WSL is installed but has no distribution. Install one with `wsl --install -d Ubuntu`.'
    }
    if ($Requested) {
        $named = $Found | Where-Object { $_.Name -ieq $Requested }
        if (-not $named) {
            $names = ($Found | ForEach-Object { $_.Name }) -join ', '
            Fail 'distribution_not_found' "the requested WSL distribution '$Requested' is not installed (found: $names)."
        }
        if ($named.Version -lt 2) {
            Fail 'wsl1_only' "'$($named.Name)' is WSL $($named.Version); the engine needs WSL 2. Convert it with ``wsl --set-version $($named.Name) 2``."
        }
        return $named.Name
    }
    $modern = @($Found | Where-Object { $_.Version -ge 2 })
    if ($modern.Count -eq 0) {
        $names = ($Found | ForEach-Object { "$($_.Name) (WSL $($_.Version))" }) -join ', '
        Fail 'wsl1_only' "no WSL 2 distribution is installed: $names. Convert one with ``wsl --set-version <name> 2``."
    }
    $default = @($modern | Where-Object { $_.Default })
    if ($default.Count -eq 1) { return $default[0].Name }
    if ($modern.Count -eq 1) { return $modern[0].Name }
    $names = ($modern | ForEach-Object { $_.Name }) -join ', '
    Fail 'no_distribution' "several WSL 2 distributions are installed ($names) and none is the default. Name one with -Distribution or `$env:SOCIAL_VIDEO_WSL_DISTRIBUTION; choosing one for you would run the edit on a machine you did not pick."
}

function Assert-Engine {
    param([string]$Wsl, [string]$Name)
    # `--` ends wsl's own option parsing, so nothing after it is read as a flag
    # for wsl itself. Each element stays a separate argv entry.
    & $Wsl --distribution $Name -- $EngineCommand version *> $null
    if ($LASTEXITCODE -ne 0) {
        Fail 'engine_missing' @"
'$EngineCommand' is not runnable inside '$Name'.
Install the engine in that distribution (clone the repository there and run
./scripts/wsl/bootstrap.sh). Do not install FFmpeg, Node or Python on the
Windows side: the hybrid mode delegates all media work to WSL on purpose.
"@
    }
}

$wsl = Get-WslBinary
$distribution = Select-Distribution -Found (Get-Distributions -Wsl $wsl) -Requested $Distribution
Assert-Engine -Wsl $wsl -Name $distribution

if (-not $EngineArgs -or $EngineArgs.Count -eq 0) {
    $EngineArgs = @('--help')
}

# The argument array is passed straight through. No quoting, no joining, no
# escaping: PowerShell hands each element to wsl.exe as its own argv entry, and
# the engine normalises any Windows path it receives exactly once with wslpath.
& $wsl --distribution $distribution -- $EngineCommand @EngineArgs
exit $LASTEXITCODE
