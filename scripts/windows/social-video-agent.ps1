<#
.SYNOPSIS
    Run the Linux editing engine from a native Windows agent.

.DESCRIPTION
    The agent may be a native Windows Codex process. The editing engine is not:
    FFmpeg, FFprobe, Python, Node, Remotion, its Chromium and local
    transcription live inside WSL2 and stay there. This adapter is the only
    supported bridge between the two.

    Usage:

        social-video-agent.ps1 [-Distribution <name>] [--] <engine arguments...>

    Every argument after the optional adapter options goes to the engine
    unchanged, so `social-video-agent.ps1 doctor` runs the engine's `doctor`.
    `-Distribution <name>`, `-Distribution:<name>` and `--distribution <name>`
    are recognised only before the first engine argument; `--` ends adapter
    options explicitly.

    What it deliberately does not do:

    * build a command string. Every argument is passed through as a separate
      argv element, and the engine is started with `wsl.exe --exec`, which runs
      one program without the Linux shell. A path with spaces, Polish
      characters, brackets or a dollar sign is a filename and not shell syntax.
    * use Invoke-Expression, `sh -lc` or a login shell to find the engine.
    * fall back to ffmpeg.exe, Windows Python or Windows Node. A run that mixed
      Windows and Linux binaries would produce a different result from the one
      that was reviewed, so it fails instead.
    * install anything. If WSL or the engine is missing it says exactly what is
      missing and stops.

    The engine is located by absolute path, because `wsl.exe --exec` uses the
    non-interactive PATH, which does not contain ~/.local/bin where the
    bootstrap installs it. $env:SOCIAL_VIDEO_WSL_ENGINE (a Linux path) wins;
    otherwise ~/.local/bin, /usr/local/bin and /usr/bin are tried in order.

    The engine is told that the agent is on Windows (SOCIAL_VIDEO_AGENT_PLATFORM,
    shared through WSLENV), so its diagnostics and runtime.json record the
    windows-agent-wsl-runtime mode rather than wsl-native.

    stdout and stderr are passed through and the engine's exit code becomes
    this script's exit code, so a caller can branch on it. Adapter failures
    exit with 3 and name one problem each.

.PARAMETER Distribution
    WSL distribution to run in. Defaults to $env:SOCIAL_VIDEO_WSL_DISTRIBUTION,
    then to the WSL default. With several WSL2 distributions and no default it
    stops rather than choosing one for you.

.EXAMPLE
    .\social-video-agent.ps1 doctor

.EXAMPLE
    .\social-video-agent.ps1 -Distribution Ubuntu-24.04 workflow init "C:\Users\User\Videos\Mój film.mp4" --project-root "C:\Users\User\projects\reel"
#>

# No param() block on purpose. PowerShell binds positional arguments to
# declared parameters, which made `social-video-agent.ps1 doctor` set the
# distribution to "doctor", and it would read engine flags such as -v as its
# own. The adapter's options are parsed by hand from $args instead.

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$EngineCommand = 'social-video-agent'
$Utf8 = New-Object System.Text.UTF8Encoding $false

function Fail {
    param([string]$Problem, [string]$Message)
    # One machine-readable problem name per failure: a caller has to be able to
    # tell a missing WSL install from a missing engine inside a working one.
    [Console]::Error.WriteLine("social-video-agent: ${Problem}: ${Message}")
    exit 3
}

function Split-AdapterArgument {
    param([object[]]$Arguments)
    $distribution = $env:SOCIAL_VIDEO_WSL_DISTRIBUTION
    $index = 0
    while ($index -lt $Arguments.Count) {
        $current = [string]$Arguments[$index]
        if ($current -eq '--') {
            $index++
            break
        }
        if ($current -ieq '-Distribution' -or $current -ieq '--distribution') {
            if ($index + 1 -ge $Arguments.Count) {
                Fail 'usage' "$current needs a distribution name."
            }
            $distribution = [string]$Arguments[$index + 1]
            $index += 2
            continue
        }
        if ($current -match '^(?i)(-Distribution|--distribution)[:=](.+)$') {
            $distribution = $Matches[2]
            $index++
            continue
        }
        break
    }
    $engine = @()
    if ($index -lt $Arguments.Count) {
        $engine = @($Arguments[$index..($Arguments.Count - 1)] | ForEach-Object { [string]$_ })
    }
    return [pscustomobject]@{ Distribution = $distribution; EngineArgs = $engine }
}

function Get-WslBinary {
    # System32 first: it is the real binary. The WindowsApps execution alias
    # is a second wsl.exe on PATH, and Get-Command returns both.
    $system = [Environment]::GetFolderPath('System')
    if ($system) {
        $native = Join-Path $system 'wsl.exe'
        if (Test-Path -LiteralPath $native -PathType Leaf) {
            return $native
        }
    }
    $candidates = @(Get-Command 'wsl.exe' -CommandType Application -ErrorAction SilentlyContinue)
    if ($candidates.Count -eq 0) {
        Fail 'wsl_missing' @'
wsl.exe was not found, so the Linux editing engine cannot be reached.
Install WSL2 and a distribution with `wsl --install`, then reopen this session.
Nothing is installed for you, and no Windows FFmpeg/Python/Node is used instead.
'@
    }
    return [string]$candidates[0].Source
}

function Invoke-Native {
    # Runs one native command with an argv array and captures its output,
    # decoded with the encoding that program actually writes.
    param([string]$Program, [string[]]$Arguments, [System.Text.Encoding]$Encoding)
    $previous = [Console]::OutputEncoding
    try {
        [Console]::OutputEncoding = $Encoding
        $output = & $Program @Arguments 2>$null
    } finally {
        [Console]::OutputEncoding = $previous
    }
    return [pscustomobject]@{ ExitCode = $LASTEXITCODE; Output = @($output) }
}

function Get-WslDistribution {
    param([string]$Wsl)
    # WSL writes this listing in UTF-16LE; decoding it as anything else yields
    # NUL bytes between every character and no distribution is ever matched.
    $listing = Invoke-Native -Program $Wsl -Arguments @('--list', '--verbose') -Encoding ([System.Text.Encoding]::Unicode)
    if ($listing.ExitCode -ne 0) {
        Fail 'wsl_broken' "``wsl --list --verbose`` failed: $($listing.Output -join ' ')"
    }
    $found = @()
    foreach ($line in $listing.Output) {
        $text = ([string]$line -replace "`0", '').Trim()
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
        $named = @($Found | Where-Object { $_.Name -ieq $Requested })
        if ($named.Count -eq 0) {
            $names = ($Found | ForEach-Object { $_.Name }) -join ', '
            Fail 'distribution_not_found' "the requested WSL distribution '$Requested' is not installed (found: $names)."
        }
        if ($named[0].Version -lt 2) {
            Fail 'wsl1_only' "'$($named[0].Name)' is WSL $($named[0].Version); the engine needs WSL 2. Convert it with ``wsl --set-version $($named[0].Name) 2``."
        }
        return $named[0].Name
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

function Find-Engine {
    param([string]$Wsl, [string]$Name)
    # `--exec` runs one program with this argv and no shell, so nothing here
    # is ever parsed as shell syntax. Linux output is UTF-8.
    $candidates = @()
    if ($env:SOCIAL_VIDEO_WSL_ENGINE) {
        $candidates += $env:SOCIAL_VIDEO_WSL_ENGINE
    }
    $homeProbe = Invoke-Native -Program $Wsl -Arguments @('--distribution', $Name, '--exec', '/usr/bin/printenv', 'HOME') -Encoding $Utf8
    $linuxHome = ($homeProbe.Output | Select-Object -First 1)
    if ($homeProbe.ExitCode -eq 0 -and $linuxHome) {
        $candidates += "$(([string]$linuxHome).TrimEnd('/'))/.local/bin/$EngineCommand"
    }
    $candidates += "/usr/local/bin/$EngineCommand", "/usr/bin/$EngineCommand"
    foreach ($candidate in $candidates) {
        $test = Invoke-Native -Program $Wsl -Arguments @('--distribution', $Name, '--exec', '/usr/bin/test', '-x', $candidate) -Encoding $Utf8
        if ($test.ExitCode -eq 0) {
            return $candidate
        }
    }
    Fail 'engine_missing' @"
'$EngineCommand' was not found inside '$Name'. Looked for: $($candidates -join ', ').
Install the engine in that distribution (clone the repository there and run
./scripts/wsl/bootstrap.sh), or set `$env:SOCIAL_VIDEO_WSL_ENGINE to its Linux
path. Do not install FFmpeg, Node or Python on the Windows side: the hybrid mode
delegates all media work to WSL on purpose.
"@
}

function Assert-Engine {
    param([string]$Wsl, [string]$Name, [string]$Engine)
    $version = Invoke-Native -Program $Wsl -Arguments @('--distribution', $Name, '--exec', $Engine, 'version') -Encoding $Utf8
    if ($version.ExitCode -ne 0) {
        Fail 'engine_broken' "'$Engine' exists inside '$Name' but ``version`` failed (exit $($version.ExitCode)). Rerun ./scripts/wsl/bootstrap.sh there."
    }
}

function Export-EngineEnvironment {
    # WSLENV names the Windows variables wsl.exe copies into Linux. Only these
    # two are added; nothing else about the Windows environment crosses.
    param([string]$Name)
    $env:SOCIAL_VIDEO_AGENT_PLATFORM = 'windows'
    $env:SOCIAL_VIDEO_WSL_DISTRIBUTION = $Name
    $shared = @()
    if ($env:WSLENV) { $shared = @($env:WSLENV -split ':' | Where-Object { $_ }) }
    foreach ($variable in 'SOCIAL_VIDEO_AGENT_PLATFORM', 'SOCIAL_VIDEO_WSL_DISTRIBUTION') {
        if (-not ($shared | Where-Object { ($_ -split '/')[0] -ieq $variable })) {
            $shared += $variable
        }
    }
    $env:WSLENV = $shared -join ':'
}

$parsed = Split-AdapterArgument -Arguments $args
$engineArgs = @($parsed.EngineArgs)
if ($engineArgs.Count -eq 0) {
    $engineArgs = @('--help')
}

$wsl = Get-WslBinary
$distribution = Select-Distribution -Found (Get-WslDistribution -Wsl $wsl) -Requested $parsed.Distribution
$engine = Find-Engine -Wsl $wsl -Name $distribution
Assert-Engine -Wsl $wsl -Name $distribution -Engine $engine
Export-EngineEnvironment -Name $distribution

# The argument array is passed straight through. No quoting, no joining, no
# escaping: PowerShell hands each element to wsl.exe as its own argv entry,
# `--exec` hands them to the engine without a shell, and the engine normalises
# any Windows path it receives exactly once with wslpath. Output is decoded as
# UTF-8, which is what the Linux engine writes.
[Console]::OutputEncoding = $Utf8
& $wsl --distribution $distribution --exec $engine @engineArgs
exit $LASTEXITCODE
