param(
    [Parameter(Mandatory = $true)][string]$GameDirectory,
    [string]$ModReferencesDir = $GameDirectory,
    [string]$PluginPath = (Join-Path $PSScriptRoot '../JBSLViewer/bin/Release/JBSLViewer.dll'),
    [string]$CecilPath
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
# Read metadata only: Unity assemblies are never executed by this check.
if (!$CecilPath) {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
    $vs = & $vswhere -latest -property installationPath
    $CecilPath = Join-Path $vs 'Common7/IDE/Extensions/TestPlatform/Extensions/Mono.Cecil.dll'
}
Add-Type -Path $CecilPath
$resolver = [Mono.Cecil.DefaultAssemblyResolver]::new()
foreach ($directory in $resolver.GetSearchDirectories()) { $resolver.RemoveSearchDirectory($directory) }
foreach ($directory in @(
    (Join-Path $GameDirectory 'Beat Saber_Data/Managed'),
    (Join-Path $ModReferencesDir 'Plugins'), (Join-Path $ModReferencesDir 'Libs'),
    (Join-Path $ModReferencesDir 'Beat Saber_Data/Managed'),
    [Runtime.InteropServices.RuntimeEnvironment]::GetRuntimeDirectory()
)) { $resolver.AddSearchDirectory($directory) }
$parameters = [Mono.Cecil.ReaderParameters]::new()
$parameters.AssemblyResolver = $resolver
$plugin = [Mono.Cecil.AssemblyDefinition]::ReadAssembly((Resolve-Path -LiteralPath $PluginPath).Path, $parameters)
$script:checks = 0
$script:failures = [Collections.Generic.List[string]]::new()
function Check([bool]$condition, [string]$description) {
    if ($condition) { $script:checks++ } else { $script:failures.Add($description) }
}
function Find-Field($type, [string]$name) {
    while ($null -ne $type) {
        $field = $type.Fields | Where-Object Name -EQ $name | Select-Object -First 1
        if ($field) { return $field }
        $type = if ($type.BaseType) { $type.BaseType.Resolve() } else { $null }
    }
}
function All-Types($types) {
    foreach ($type in $types) { $type; All-Types $type.NestedTypes }
}
function Validate-Patch($patch, $original) {
    foreach ($handler in $patch.Methods | Where-Object { $_.Name -in @('Prefix', 'Postfix', 'Finalizer') }) {
        foreach ($argument in $handler.Parameters) {
            $name = $argument.Name
            if ($name.StartsWith('___')) {
                $field = Find-Field $original.DeclaringType $name.Substring(3)
                Check ($null -ne $field -and $field.FieldType.FullName -eq $argument.ParameterType.FullName) "$($patch.Name): injected field $name"
            } elseif ($name -notin @('__instance', '__exception', '__state', '__originalMethod', '__runOriginal')) {
                if ($name -eq '__result') { $actual = $original.ReturnType }
                elseif ($name -match '^__(\d+)$') { $actual = $original.Parameters[[int]$Matches[1]].ParameterType }
                else {
                    $parameter = $original.Parameters | Where-Object Name -EQ $name | Select-Object -First 1
                    $actual = if ($parameter) { $parameter.ParameterType } else { $null }
                }
                Check ($null -ne $actual -and $actual.FullName -eq $argument.ParameterType.FullName) "$($patch.Name): argument $name"
            }
        }
    }
}
try {
    $types = @(All-Types $plugin.MainModule.Types)
    foreach ($reference in $plugin.MainModule.GetMemberReferences()) {
        if ($reference.DeclaringType.Scope.Name -match '^(mscorlib|netstandard|System(\.|$)|Newtonsoft\.Json$)') { continue }
        try { Check ($null -ne $reference.Resolve()) "Unresolved member: $reference" }
        catch { $script:failures.Add("Unresolved member: $reference -- $($_.Exception.Message)") }
    }
    # Check Harmony attributes, including arguments matched by name (invisible to the compiler).
    foreach ($type in $types) {
        foreach ($attribute in $type.CustomAttributes | Where-Object { $_.AttributeType.FullName -eq 'HarmonyLib.HarmonyPatch' -and $_.ConstructorArguments.Count -ge 2 }) {
            $targetType = $attribute.ConstructorArguments[0].Value.Resolve()
            $methodName = $attribute.ConstructorArguments[1].Value
            $methods = @($targetType.Methods | Where-Object Name -EQ $methodName)
            if ($attribute.ConstructorArguments.Count -gt 2) {
                $signature = ($attribute.ConstructorArguments[2].Value | ForEach-Object { $_.Value.FullName }) -join ','
                $methods = @($methods | Where-Object { ($_.Parameters | ForEach-Object { $_.ParameterType.FullName }) -join ',' -eq $signature })
            }
            Check ($methods.Count -eq 1) "Ambiguous/missing patch: $($targetType.FullName).$methodName"
            if ($methods.Count -eq 1) { Validate-Patch $type $methods[0] }
        }
        # Extract literal GetField<TField, TOwner>("name") calls from the actual output IL.
        foreach ($method in $type.Methods | Where-Object HasBody) {
            foreach ($instruction in $method.Body.Instructions) {
                $call = $instruction.Operand
                if ($call -isnot [Mono.Cecil.GenericInstanceMethod] -or $call.Name -ne 'GetField' -or $call.GenericArguments.Count -ne 2) { continue }
                $previous = $instruction.Previous
                if ($previous.OpCode.Code.ToString() -ne 'Ldstr') { throw "Non-literal reflected field in $method" }
                $field = Find-Field $call.GenericArguments[1].Resolve() $previous.Operand
                Check ($null -ne $field -and $field.FieldType.FullName -eq $call.GenericArguments[0].FullName) "Reflected field: $($call.GenericArguments[1]).$($previous.Operand)"
            }
        }
    }
    # Targets obtained dynamically by AccessTools are listed explicitly; reject new overload ambiguity.
    $dynamicTargets = @(
        @('SiraUtil', 'SiraUtil.Submissions.Submission', '.ctor', $null, 'QualifierSiraConstructorPatch'),
        @('SiraUtil', 'SiraUtil.Submissions.Submission', 'DisableScoreSubmission', $null, 'QualifierSiraChangedPatch'),
        @('SiraUtil', 'SiraUtil.Submissions.Submission', 'Remove', 'SiraUtil.Submissions.Ticket', 'QualifierSiraChangedPatch'),
        @('SiraUtil', 'SiraUtil.Submissions.Submission', 'Remove', 'System.String', 'QualifierSiraChangedPatch'),
        @('SiraUtil', 'SiraUtil.Submissions.SubmissionDataContainer', 'SSS', 'System.Boolean', 'QualifierSiraSSSPatch'),
        @('BS_Utils', 'BS_Utils.Gameplay.ScoreSubmission', 'DisableSubmission', $null, 'QualifierBsUtilsChangedPatch'),
        @('BS_Utils', 'BS_Utils.Gameplay.ScoreSubmission', 'ProlongedDisableSubmission', $null, 'QualifierBsUtilsChangedPatch'),
        @('BS_Utils', 'BS_Utils.Gameplay.ScoreSubmission', 'RemoveProlongedDisable', $null, 'QualifierBsUtilsChangedPatch'),
        @('BS_Utils', 'BS_Utils.Gameplay.ScoreSubmission', 'DisableScoreSaberScoreSubmission', $null, 'QualifierBsUtilsSubmissionPatch')
    )
    foreach ($target in $dynamicTargets) {
        $assembly = $resolver.Resolve([Mono.Cecil.AssemblyNameReference]::new($target[0], [Version]'0.0.0.0'))
        $type = $assembly.MainModule.GetType($target[1])
        $methods = @($type.Methods | Where-Object Name -EQ $target[2])
        if ($null -ne $target[3]) { $methods = @($methods | Where-Object { ($_.Parameters | ForEach-Object { $_.ParameterType.FullName }) -join ',' -eq $target[3] }) }
        Check ($methods.Count -eq 1) "Dynamic target: $($target[1]).$($target[2])"
        if ($methods.Count -eq 1) { Validate-Patch ($types | Where-Object Name -EQ $target[4]) $methods[0] }
    }
    $sira = $resolver.Resolve([Mono.Cecil.AssemblyNameReference]::new('SiraUtil', [Version]'0.0.0.0'))
    $eligibility = $sira.MainModule.GetType('SiraUtil.Submissions.SiraLevelCompletionResults').Properties | Where-Object Name -EQ 'ShouldSubmitScores'
    Check ($null -ne $eligibility -and $eligibility.PropertyType.FullName -eq 'System.Boolean') 'Sira result submission eligibility'
    $manifest = $plugin.MainModule.Resources | Where-Object Name -EQ 'JBSLViewer.manifest.json'
    $reader = [IO.StreamReader]::new($manifest.GetResourceStream())
    try { $metadata = $reader.ReadToEnd() | ConvertFrom-Json } finally { $reader.Dispose() }
    Check ($metadata.gameVersion -eq '1.40.8') 'Dedicated manifest game version'
    Check ($metadata.version -eq $plugin.Name.Version.ToString(3)) 'Manifest/assembly version consistency'
    if ($script:failures.Count) { throw ($script:failures -join "`n") }
    Write-Output "API CHECK PASSED: $script:checks checks; game=$GameDirectory; mods=$ModReferencesDir"
} finally { $plugin.Dispose(); $resolver.Dispose() }
