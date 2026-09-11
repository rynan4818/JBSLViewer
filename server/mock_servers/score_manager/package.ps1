[CmdletBinding()]
param([string]$OutputDirectory)

# Windows PowerShell 5.1 / .NET only. No Python, pip or running server is needed.
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$packageRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$partialZip = $null
$partialCreated = $false

function Get-SafeRelativeName([string]$Name) {
    $relative = $Name.Replace('\', '/')
    if ($relative -notmatch '^[A-Za-z0-9_-][A-Za-z0-9_.-]*(/[A-Za-z0-9_-][A-Za-z0-9_.-]*)*$') {
        throw "Invalid relative path in package-files.json: $Name"
    }
    return $relative
}

function Assert-RegularSource([string]$Path) {
    $parent = $Path
    while ($true) {
        if (([IO.File]::GetAttributes($parent) -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Links and junctions cannot be packaged: $parent"
        }
        if ($parent.Equals($packageRoot, [StringComparison]::OrdinalIgnoreCase)) { break }
        $parent = [IO.Path]::GetDirectoryName($parent)
        if (!$parent) { throw 'Source is outside the package root.' }
    }
}

function Get-SourceHash([string]$Path) {
    $sourceStream = [IO.File]::OpenRead($Path)
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($sha.ComputeHash($sourceStream)).Replace('-', '') }
    finally { $sha.Dispose(); $sourceStream.Dispose() }
}

try {
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $manifest = Get-Content -LiteralPath (Join-Path $packageRoot 'package-files.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($manifest.schemaVersion -ne 1 -or $manifest.archiveRoot -notmatch '^[A-Za-z0-9_-]+$') {
        throw 'Invalid package-files.json version or archiveRoot.'
    }
    if (@($manifest.files).Count -eq 0) { throw 'The package file list is empty.' }
    $names = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    $sources = @()
    foreach ($item in $manifest.files) {
        $sourceName = Get-SafeRelativeName ([string]$item.source)
        $targetName = Get-SafeRelativeName ([string]$item.target)
        $sourcePath = [IO.Path]::GetFullPath((Join-Path $packageRoot $sourceName))
        if (!$sourcePath.StartsWith($packageRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Source outside the package root: $sourceName"
        }
        if (!(Test-Path -LiteralPath $sourcePath -PathType Leaf)) { throw "Required file is missing: $sourceName" }
        Assert-RegularSource $sourcePath
        $archiveName = $manifest.archiveRoot + '/' + $targetName
        if (!$names.Add($archiveName)) { throw "Duplicate archive name: $archiveName" }
        $sources += [pscustomobject]@{
            Path = $sourcePath
            Name = $archiveName
            Hash = Get-SourceHash $sourcePath
        }
    }

    if (!$OutputDirectory) { $OutputDirectory = Join-Path $packageRoot 'dist' }
    $destination = [IO.Path]::GetFullPath($OutputDirectory)
    [IO.Directory]::CreateDirectory($destination) | Out-Null
    $fileName = '{0}_{1}_{2}.zip' -f $manifest.archiveRoot, (Get-Date -Format 'yyyyMMdd-HHmmss'), ([Guid]::NewGuid().ToString('N').Substring(0, 8))
    $finalZip = Join-Path $destination $fileName
    $partialZip = $finalZip + '.partial'
    $stream = [IO.File]::Open($partialZip, [IO.FileMode]::CreateNew, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    $partialCreated = $true
    try {
        $zip = [IO.Compression.ZipArchive]::new($stream, [IO.Compression.ZipArchiveMode]::Create, $true)
        try {
            foreach ($source in $sources) {
                $entry = $zip.CreateEntry($source.Name, [IO.Compression.CompressionLevel]::Optimal)
                $inputStream = [IO.File]::OpenRead($source.Path)
                try {
                    $outputStream = $entry.Open()
                    try { $inputStream.CopyTo($outputStream) } finally { $outputStream.Dispose() }
                } finally { $inputStream.Dispose() }
            }
        } finally { $zip.Dispose() }
    } finally { $stream.Dispose() }

    # Check the completed ZIP contents against the input hashes before publishing.
    $zip = [IO.Compression.ZipFile]::OpenRead($partialZip)
    try {
        if ($zip.Entries.Count -ne $sources.Count) { throw 'Archive entry count mismatch.' }
        foreach ($source in $sources) {
            $entry = $zip.GetEntry($source.Name)
            if (!$entry) { throw "Archive entry is missing: $($source.Name)" }
            $entryStream = $entry.Open()
            $sha = [Security.Cryptography.SHA256]::Create()
            try { $hash = [BitConverter]::ToString($sha.ComputeHash($entryStream)).Replace('-', '') }
            finally { $sha.Dispose(); $entryStream.Dispose() }
            if ($hash -ne $source.Hash) { throw "Archive hash mismatch: $($source.Name)" }
        }
    } finally { $zip.Dispose() }
    Move-Item -LiteralPath $partialZip -Destination $finalZip
    $partialCreated = $false
    Write-Output ("Created: " + $finalZip)
    Write-Output ("Files: " + $sources.Count + " / SHA-256 verified")
    Write-Output 'Extract the ZIP and follow its README.md to create a new environment.'
    exit 0
} catch {
    if ($partialCreated -and (Test-Path -LiteralPath $partialZip -PathType Leaf)) {
        Remove-Item -LiteralPath $partialZip -ErrorAction SilentlyContinue
    }
    [Console]::Error.WriteLine('Packaging failed: ' + $_.Exception.Message)
    exit 1
}
