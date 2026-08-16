[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [Alias("Host")]
    [string] $HaHost
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($HaHost)) {
    [Console]::Error.WriteLine("Error: Home Assistant host must not be empty.")
    exit 1
}

$HaHost = $HaHost.Trim()
if ($HaHost -notmatch "^[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?$") {
    [Console]::Error.WriteLine(
        "Error: Home Assistant host must be a valid hostname or IPv4 address."
    )
    exit 1
}

$source = Join-Path $PSScriptRoot "custom_components\dahua_rpc"
$destinationParent = "\\$HaHost\config\custom_components"
$destination = "$destinationParent\dahua_rpc"

if (-not (Test-Path -LiteralPath $source -PathType Container)) {
    [Console]::Error.WriteLine(
        "Error: Local integration source directory does not exist: $source"
    )
    exit 1
}

try {
    $destinationParentReachable = Test-Path `
        -LiteralPath $destinationParent `
        -PathType Container
} catch {
    $destinationParentReachable = $false
}

if (-not $destinationParentReachable) {
    [Console]::Error.WriteLine(
        "Error: Home Assistant destination parent is not reachable: $destinationParent"
    )
    exit 1
}

& robocopy.exe $source $destination /MIR /XD "__pycache__" /XF "*.pyc" "*.pyo"
$robocopyExitCode = $LASTEXITCODE

if ($robocopyExitCode -ge 8) {
    [Console]::Error.WriteLine(
        "Error: Deployment failed with robocopy exit code $robocopyExitCode."
    )
    exit $robocopyExitCode
}

Write-Host "Source: $source"
Write-Host "Destination: $destination"
Write-Host "Deployment completed successfully."
exit 0
