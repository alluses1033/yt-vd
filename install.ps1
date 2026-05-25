$ErrorActionPreference = "Stop"
$ProgressPreference = "Continue"

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Repo = "alluses1033/yt-vd"
$InstallDir = Join-Path $env:LOCALAPPDATA "Programs\yt-vd"
$Bin = Join-Path $InstallDir "yt-vd.exe"
$ApiUrl = "https://api.github.com/repos/$Repo/releases/latest"

function Format-Bytes {
    param([long]$Bytes)

    if ($Bytes -ge 1GB) {
        return "{0:N1} GB" -f ($Bytes / 1GB)
    }

    if ($Bytes -ge 1MB) {
        return "{0:N1} MB" -f ($Bytes / 1MB)
    }

    if ($Bytes -ge 1KB) {
        return "{0:N1} KB" -f ($Bytes / 1KB)
    }

    return "$Bytes B"
}

function Get-ReleaseAsset {
    param(
        [Parameter(Mandatory = $true)]$Release,
        [Parameter(Mandatory = $true)][string]$Name
    )

    $Asset = $Release.assets | Where-Object { $_.name -eq $Name } | Select-Object -First 1
    if (-not $Asset) {
        $Names = ($Release.assets | ForEach-Object { $_.name }) -join ", "
        if (-not $Names) {
            $Names = "none"
        }

        throw "Release $($Release.tag_name) does not include $Name. Available assets: $Names"
    }

    return $Asset
}

function Download-Asset {
    param(
        [Parameter(Mandatory = $true)]$Asset,
        [Parameter(Mandatory = $true)][string]$OutFile
    )

    $Name = $Asset.name
    $Url = $Asset.browser_download_url
    [long]$ExpectedSize = $Asset.size
    $TempFile = "$OutFile.download"

    Write-Host "Downloading $Name ($(Format-Bytes $ExpectedSize))..." -ForegroundColor Cyan

    if (Test-Path -LiteralPath $TempFile) {
        Remove-Item -LiteralPath $TempFile -Force
    }

    $Response = $null
    $InputStream = $null
    $OutputStream = $null

    try {
        $Request = [System.Net.HttpWebRequest]::Create($Url)
        $Request.UserAgent = "yt-vd-installer"
        $Request.AllowAutoRedirect = $true
        $Request.Timeout = 300000
        $Request.ReadWriteTimeout = 300000

        $Response = $Request.GetResponse()
        [long]$TotalSize = $Response.ContentLength
        if ($TotalSize -le 0 -and $ExpectedSize -gt 0) {
            $TotalSize = $ExpectedSize
        }

        $InputStream = $Response.GetResponseStream()
        $OutputStream = [System.IO.File]::Open(
            $TempFile,
            [System.IO.FileMode]::Create,
            [System.IO.FileAccess]::Write,
            [System.IO.FileShare]::None
        )

        $Buffer = New-Object byte[] 131072
        [long]$Downloaded = 0
        $LastUpdate = Get-Date

        while (($Read = $InputStream.Read($Buffer, 0, $Buffer.Length)) -gt 0) {
            $OutputStream.Write($Buffer, 0, $Read)
            $Downloaded += $Read

            $Now = Get-Date
            if (($Now - $LastUpdate).TotalMilliseconds -ge 200 -or ($TotalSize -gt 0 -and $Downloaded -eq $TotalSize)) {
                if ($TotalSize -gt 0) {
                    $Percent = [Math]::Min(100, [Math]::Round(($Downloaded / $TotalSize) * 100))
                    $Status = "${Name}: $(Format-Bytes $Downloaded) / $(Format-Bytes $TotalSize)"
                    Write-Progress -Activity "Installing yt-vd" -Status $Status -PercentComplete $Percent
                } else {
                    Write-Progress -Activity "Installing yt-vd" -Status "${Name}: $(Format-Bytes $Downloaded)"
                }

                $LastUpdate = $Now
            }
        }
    } finally {
        if ($OutputStream) { $OutputStream.Dispose() }
        if ($InputStream) { $InputStream.Dispose() }
        if ($Response) { $Response.Dispose() }
        Write-Progress -Activity "Installing yt-vd" -Completed
    }

    $ActualSize = (Get-Item -LiteralPath $TempFile).Length
    if ($ExpectedSize -gt 0 -and $ActualSize -ne $ExpectedSize) {
        Remove-Item -LiteralPath $TempFile -Force
        throw "Downloaded $Name but the size did not match. Expected $(Format-Bytes $ExpectedSize), got $(Format-Bytes $ActualSize)."
    }

    Move-Item -LiteralPath $TempFile -Destination $OutFile -Force
    Write-Host "Saved $Name to $OutFile" -ForegroundColor Green
}

Write-Host "Installing yt-vd..." -ForegroundColor Cyan
Write-Host "Repository: https://github.com/$Repo"

New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

Write-Host "Checking latest release..." -ForegroundColor Cyan
$Headers = @{ "User-Agent" = "yt-vd-installer" }
$Release = Invoke-RestMethod -Uri $ApiUrl -Headers $Headers
Write-Host "Found $($Release.tag_name)." -ForegroundColor Green

$CliAsset = Get-ReleaseAsset -Release $Release -Name "yt-vd.exe"

Download-Asset -Asset $CliAsset -OutFile $Bin

$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (($UserPath -split ";") -notcontains $InstallDir) {
    [Environment]::SetEnvironmentVariable("Path", "$UserPath;$InstallDir", "User")
    $env:Path = "$env:Path;$InstallDir"
    Write-Host "Added $InstallDir to your user PATH." -ForegroundColor Green
}

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Host "FFmpeg was not found. Install it with: winget install Gyan.FFmpeg" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "yt-vd installed successfully." -ForegroundColor Green
Write-Host "Open a new PowerShell window, then run:"
Write-Host "  yt-vd --help"
