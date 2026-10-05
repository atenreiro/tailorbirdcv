# AutoCV installer for Windows (Windows PowerShell 5.1 or PowerShell 7).
#
#   irm https://raw.githubusercontent.com/atenreiro/autocv/main/install.ps1 | iex
#
# What it does, and nothing else:
#   1. installs uv (Astral's Python tool installer) into %USERPROFILE%\.local\bin, unless you already have it;
#   2. installs or upgrades AutoCV from PyPI (`autocv-app`) in its own environment, on a Python that uv
#      downloads and manages itself: any Python you already have is never used or changed;
#   3. makes sure the `autocv` command is on your PATH, in this window and new ones;
#   4. starts AutoCV, which opens in your browser.
# No administrator rights, nothing outside your user folder. Run it again to update.
#
# Options, set before running:
#   $env:AUTOCV_NO_LAUNCH = "1"   install or update only; don't start AutoCV
#   $env:AUTOCV_UNINSTALL = "1"   remove AutoCV (your profile and applications are kept); cleared afterwards
#   $env:AUTOCV_PACKAGE = "..."   what to install (default: autocv-app; e.g. autocv-app==0.2.0)
#
# It runs inside your own PowerShell window (through `iex`), so it never calls `exit`. Kept to plain
# ASCII so Windows PowerShell 5.1 reads it correctly however it's saved or downloaded.

& {
    $ErrorActionPreference = 'Stop'
    # Windows PowerShell 5.1 may not offer TLS 1.2 by default; PyPI, GitHub and astral.sh require it.
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    # The Python AutoCV runs on: one CI tests, so every dependency has a ready-made wheel for it.
    $pythonVersion = '3.13'

    function Find-Uv {
        $cmd = Get-Command uv -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($cmd) { return $cmd.Source }
        $candidates = @()
        if ($env:XDG_BIN_HOME) { $candidates += Join-Path $env:XDG_BIN_HOME 'uv.exe' }
        $candidates += Join-Path $env:USERPROFILE '.local\bin\uv.exe'
        $candidates += Join-Path $env:USERPROFILE '.cargo\bin\uv.exe'
        foreach ($c in $candidates) { if (Test-Path -LiteralPath $c) { return $c } }
        return $null
    }

    function Invoke-Checked([string]$what, [scriptblock]$run) {
        & $run
        if ($LASTEXITCODE -ne 0) { throw "$what failed (exit code $LASTEXITCODE)." }
    }

    function Test-OnUserPath([string]$dir) {
        $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
        if (-not $userPath) { return $false }
        foreach ($p in $userPath.Split(';')) {
            if ($p -and ($p.TrimEnd('\') -ieq $dir.TrimEnd('\'))) { return $true }
        }
        return $false
    }

    # Windows locks the files of a running program: updating or removing a running AutoCV would fail halfway.
    function Assert-NotRunning([string]$uv) {
        $toolDir = (& $uv tool dir | Out-String).Trim().TrimEnd('\') + '\autocv-app\'
        $binDir = (& $uv tool dir --bin | Out-String).Trim().TrimEnd('\') + '\'
        $running = Get-Process -ErrorAction SilentlyContinue | Where-Object {
            $_.Path -and ($_.Path.StartsWith($toolDir, [StringComparison]::OrdinalIgnoreCase) -or
                          $_.Path -ieq ($binDir + 'autocv.exe') -or $_.Path -ieq ($binDir + 'autocv-app.exe'))
        }
        if ($running) {
            throw 'AutoCV is running. Stop it first (press Ctrl+C in the window where it runs), then run this again.'
        }
    }

    # uv settings for this run only: put back as they were when the script ends (it runs in your window).
    $uvSettings = @{}
    foreach ($name in 'UV_SYSTEM_CERTS', 'UV_NATIVE_TLS', 'UV_MANAGED_PYTHON') {
        $uvSettings[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
    }

    try {
        # Use Windows' certificate store (works behind company proxies that inspect HTTPS), and only
        # uv-managed Pythons (never one from python.org, the Microsoft Store or Anaconda).
        if (-not $env:UV_SYSTEM_CERTS) { $env:UV_SYSTEM_CERTS = '1' }
        if (-not $env:UV_NATIVE_TLS) { $env:UV_NATIVE_TLS = '1' }
        $env:UV_MANAGED_PYTHON = '1'

        $uv = Find-Uv

        if ($env:AUTOCV_UNINSTALL -eq '1') {
            Remove-Item Env:AUTOCV_UNINSTALL  # so running the installer again in this window installs
            if (-not $uv) { throw "uv isn't installed, so AutoCV isn't either." }
            Assert-NotRunning $uv
            Invoke-Checked 'Removing AutoCV' { & $uv tool uninstall autocv-app }
            Write-Host ''
            Write-Host 'AutoCV is removed. Your profile and applications are still in your data folder:'
            Write-Host "  $env:LOCALAPPDATA\AutoCV"
            Write-Host 'Delete that folder yourself if you want them gone. uv stays installed.'
            return
        }

        if (-not $uv) {
            Write-Host 'Installing uv (https://docs.astral.sh/uv/) into your user folder...'
            Invoke-Checked 'Installing uv' {
                powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex" | Out-Null
            }
            $uv = Find-Uv
            if (-not $uv) { throw 'uv was installed but cannot be found. Open a new PowerShell window and run this again.' }
        } else {
            Write-Host "Using uv at $uv"
        }

        $bindir = (& $uv tool dir --bin | Out-String).Trim()
        if ($LASTEXITCODE -ne 0 -or -not $bindir) {
            throw "your uv is too old. Update it (uv self update, or winget upgrade astral-sh.uv if you installed it with winget), then run this again."
        }
        Assert-NotRunning $uv
        if (-not (Test-OnUserPath $bindir)) {
            # new windows find `autocv` (Continue: in PowerShell 5.1, redirected stderr would otherwise stop the script)
            & { $ErrorActionPreference = 'Continue'; & $uv tool update-shell 2>&1 | Out-Null }
        }
        if (-not (($env:Path -split ';') -contains $bindir)) { $env:Path = "$bindir;$env:Path" }  # and this one

        $package = if ($env:AUTOCV_PACKAGE) { $env:AUTOCV_PACKAGE } else { 'autocv-app' }
        Write-Host "Installing AutoCV ($package)..."
        Invoke-Checked 'Installing AutoCV' { & $uv tool install --upgrade --python $pythonVersion $package }
        $autocv = Join-Path $bindir 'autocv.exe'
        if (-not (Test-Path -LiteralPath $autocv)) { throw "AutoCV was installed but $autocv is missing." }

        $version = (& $autocv --version | Out-String).Trim()
        Write-Host ''
        Write-Host "$version is installed."
        Write-Host '  Start it any time with:  autocv serve'
        Write-Host '  Update with:             the same command you just ran'
        Write-Host '  Check your setup with:   autocv doctor'

        if ($env:AUTOCV_NO_LAUNCH -ne '1') {
            Write-Host ''
            Write-Host 'Starting AutoCV. It opens in your browser; press Ctrl+C here to stop it.'
            & $autocv serve
        }
    } catch {
        Write-Host "AutoCV installer: $($_.Exception.Message)" -ForegroundColor Red
        Write-Host 'If this keeps happening, install uv yourself (https://docs.astral.sh/uv/getting-started/installation/), then run: uv tool install autocv-app'
    } finally {
        foreach ($name in $uvSettings.Keys) { [Environment]::SetEnvironmentVariable($name, $uvSettings[$name], 'Process') }
    }
}
