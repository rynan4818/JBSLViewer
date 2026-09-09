param(
    [string]$GameDirectory = 'C:/Program Files (x86)/Steam/steamapps/common/Beat Saber_1.39.1SS',
    [string]$ModReferencesDir,
    [string]$MSBuildPath,
    [string]$LocalNuGetFeed,
    [string]$CecilPath
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if (!$ModReferencesDir) { $ModReferencesDir = $GameDirectory }
$GameDirectory = (Resolve-Path -LiteralPath $GameDirectory).Path
$ModReferencesDir = (Resolve-Path -LiteralPath $ModReferencesDir).Path
if (!(Test-Path -LiteralPath (Join-Path $GameDirectory 'Beat Saber_Data/Managed/Main.dll'))) { throw 'Main.dll is missing from GameDirectory.' }
if (!$MSBuildPath) {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
    $MSBuildPath = & $vswhere -latest -requires Microsoft.Component.MSBuild -find 'MSBuild/**/Bin/MSBuild.exe' | Select-Object -First 1
}
if (!$MSBuildPath -or !(Test-Path -LiteralPath $MSBuildPath)) { throw 'Specify a Visual Studio MSBuild.exe with -MSBuildPath.' }
$manifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'JBSLViewer/manifest.json') -Raw | ConvertFrom-Json
$output = Join-Path $PSScriptRoot ('artifacts/BS' + $manifest.gameVersion + '/' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
New-Item -ItemType Directory -Path $output -Force | Out-Null
$arguments = @('/restore', '/t:Rebuild', '/p:Configuration=Release', ('/p:BeatSaberDir=' + $GameDirectory),
    ('/p:GameDirectory=' + $GameDirectory), ('/p:ModReferencesDir=' + $ModReferencesDir),
    '/p:DisableCopyToGame=True', '/p:DisableCopyToPlugins=True', '/p:DisableZipRelease=True',
    '/p:NuGetAudit=false', '/v:minimal', '/nologo', '/nr:false', '/clp:ErrorsOnly', '/fl',
    ('/flp:logfile=' + (Join-Path $output 'build.log') + ';verbosity=normal;encoding=UTF-8'),
    ('/p:RestorePackagesPath=' + (Join-Path $PSScriptRoot 'JBSLViewer/obj/nuget-packages')))
if ($LocalNuGetFeed) { $arguments += '/p:RestoreSources=' + (Resolve-Path -LiteralPath $LocalNuGetFeed).Path }
# Worktrees may have been created by a sandbox account. Trust only this build's repository,
# only for this process and its children; do not change global Git configuration.
$oldGitCount = [Environment]::GetEnvironmentVariable('GIT_CONFIG_COUNT', 'Process')
$gitIndex = if ($oldGitCount) { [int]$oldGitCount } else { 0 }
$gitKey = 'GIT_CONFIG_KEY_' + $gitIndex
$gitValue = 'GIT_CONFIG_VALUE_' + $gitIndex
$oldGitKey = [Environment]::GetEnvironmentVariable($gitKey, 'Process')
$oldGitValue = [Environment]::GetEnvironmentVariable($gitValue, 'Process')
[Environment]::SetEnvironmentVariable('GIT_CONFIG_COUNT', ($gitIndex + 1).ToString(), 'Process')
[Environment]::SetEnvironmentVariable($gitKey, 'safe.directory', 'Process')
[Environment]::SetEnvironmentVariable($gitValue, $PSScriptRoot.Replace('\', '/'), 'Process')
Push-Location -LiteralPath $PSScriptRoot
try {
    & $MSBuildPath 'JBSLViewer.sln' @arguments
    if ($LASTEXITCODE -ne 0) { throw "Build failed; see $output/build.log" }
    & './JBSLViewer.Qualifier.Tests/bin/Release/JBSLViewer.Qualifier.Tests.exe' 2>&1 |
        Tee-Object -FilePath (Join-Path $output 'self-test.log') | Select-Object -Last 1
    if ($LASTEXITCODE -ne 0) { throw "Self-test failed; see $output/self-test.log" }
    $audit = @{ GameDirectory = $GameDirectory; ModReferencesDir = $ModReferencesDir }
    if ($CecilPath) { $audit.CecilPath = $CecilPath }
    & './tools/verify_game_api.ps1' @audit | Tee-Object -FilePath (Join-Path $output 'api-check.log')
    $package = Join-Path $output 'package'
    New-Item -ItemType Directory -Path (Join-Path $package 'Plugins') -Force | Out-Null
    Copy-Item -LiteralPath 'JBSLViewer/bin/Release/JBSLViewer.dll' -Destination (Join-Path $package 'Plugins/JBSLViewer.dll')
    Copy-Item -LiteralPath 'THIRD-PARTY-NOTICES.txt' -Destination $package
    $archive = Join-Path $output ("JBSLViewer-$($manifest.version)-BS$($manifest.gameVersion).zip")
    Compress-Archive -LiteralPath (Join-Path $package 'Plugins'), (Join-Path $package 'THIRD-PARTY-NOTICES.txt') -DestinationPath $archive
    $versionFile = Join-Path $GameDirectory 'BeatSaberVersion.txt'
    [ordered]@{
        target = $manifest.gameVersion
        gameDirectory = $GameDirectory
        gameBuild = $(if (Test-Path -LiteralPath $versionFile) { (Get-Content -LiteralPath $versionFile -Raw).Trim() } else { 'See game DLL metadata' })
        modReferencesDir = $ModReferencesDir
        dllSha256 = (Get-FileHash -LiteralPath (Join-Path $package 'Plugins/JBSLViewer.dll')).Hash
        archiveSha256 = (Get-FileHash -LiteralPath $archive).Hash
    } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $output 'build-info.json') -Encoding utf8
    Write-Output "Build and checks passed: $archive"
} finally {
    Pop-Location
    [Environment]::SetEnvironmentVariable('GIT_CONFIG_COUNT', $oldGitCount, 'Process')
    [Environment]::SetEnvironmentVariable($gitKey, $oldGitKey, 'Process')
    [Environment]::SetEnvironmentVariable($gitValue, $oldGitValue, 'Process')
}
