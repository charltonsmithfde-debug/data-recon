<#
.SYNOPSIS
    Export the Windows certificate stores to a PEM bundle so gcloud's IAP tunnel works.

.DESCRIPTION
    This workstation is behind Zscaler TLS interception. gcloud validates TLS against its own
    bundled CA store, which contains no Zscaler root; the Windows store does. The result is that
    `gcloud compute start-iap-tunnel` and `gcloud compute ssh --tunnel-through-iap` fail with

        [SSL: CERTIFICATE_VERIFY_FAILED] unable to get local issuer certificate

    while ordinary gcloud API calls succeed, because they take a different code path. That split
    is why the problem read as intermittent.

    Exporting LocalMachine\Root, LocalMachine\CA and CurrentUser\Root to one PEM and pointing
    CLOUDSDK_CORE_CUSTOM_CA_CERTS_FILE at it fixes every tunnel call. Roughly 190 certificates,
    about 330 KB.

    The bundle contains only public certificates -- no private keys, nothing secret. It is
    written outside the repo regardless, because it is machine-specific and would be noise in
    a diff.

.PARAMETER OutFile
    Where to write the bundle. Defaults to $HOME\.scbi-runbook\win-ca-bundle.pem, which is where
    lib/common.sh looks for it.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\blocked\00_export_ca_bundle.ps1
#>

[CmdletBinding()]
param(
    [string]$OutFile = (Join-Path $HOME '.scbi-runbook\win-ca-bundle.pem')
)

$ErrorActionPreference = 'Stop'

$stores = @(
    'Cert:\LocalMachine\Root',
    'Cert:\LocalMachine\CA',
    'Cert:\CurrentUser\Root'
)

$outDir = Split-Path -Parent $OutFile
if (-not (Test-Path $outDir)) {
    New-Item -ItemType Directory -Path $outDir -Force | Out-Null
}

$builder = New-Object System.Text.StringBuilder
$seen = New-Object 'System.Collections.Generic.HashSet[string]'
$exported = 0
$skipped = 0

foreach ($store in $stores) {
    if (-not (Test-Path $store)) {
        Write-Warning "store not present, skipping: $store"
        continue
    }

    $certs = Get-ChildItem -Path $store
    Write-Host ("  {0,-28} {1,4} certificates" -f $store, $certs.Count)

    foreach ($cert in $certs) {
        # Thumbprint de-duplicates: the same root is commonly in more than one store, and a
        # duplicated PEM entry is harmless but makes the bundle larger and the count misleading.
        if (-not $seen.Add($cert.Thumbprint)) {
            $skipped++
            continue
        }

        $base64 = [System.Convert]::ToBase64String(
            $cert.RawData, [System.Base64FormattingOptions]::InsertLineBreaks)

        [void]$builder.AppendLine("# subject: $($cert.Subject)")
        [void]$builder.AppendLine("# thumbprint: $($cert.Thumbprint)")
        [void]$builder.AppendLine('-----BEGIN CERTIFICATE-----')
        [void]$builder.AppendLine($base64)
        [void]$builder.AppendLine('-----END CERTIFICATE-----')
        $exported++
    }
}

if ($exported -eq 0) {
    throw 'No certificates were exported. Nothing would verify; not writing an empty bundle.'
}

# ASCII, no BOM. Python's ssl module and gcloud's bundled requests both read this file directly,
# and a UTF-8 BOM ahead of the first '-----BEGIN CERTIFICATE-----' makes it unparseable.
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($OutFile, $builder.ToString(), $utf8NoBom)

$size = [math]::Round((Get-Item $OutFile).Length / 1KB, 1)
Write-Host ''
Write-Host "  Wrote $exported certificates ($skipped duplicates skipped), $size KB"
Write-Host "  -> $OutFile"
Write-Host ''
Write-Host '  The runbook scripts pick this up automatically. For an ad-hoc gcloud call:'
Write-Host ''
Write-Host ('    $env:CLOUDSDK_CORE_CUSTOM_CA_CERTS_FILE = "{0}"' -f $OutFile)
Write-Host ('    export CLOUDSDK_CORE_CUSTOM_CA_CERTS_FILE="{0}"   # Git Bash' -f ($OutFile -replace '\\', '/'))
Write-Host ''
Write-Host '  To make it permanent for your user (survives a new shell):'
Write-Host ''
Write-Host ('    setx CLOUDSDK_CORE_CUSTOM_CA_CERTS_FILE "{0}"' -f $OutFile)
