param(
    [string]$Repository = (Split-Path $PSScriptRoot -Parent),
    [string]$GameDirectory = 'C:\Program Files (x86)\Steam\steamapps\common\Beat Saber',
    [string]$CecilPath = 'C:\Users\Ryuichi\.nuget\packages\mono.cecil\0.11.6\lib\netstandard2.0\Mono.Cecil.dll',
    [string]$ReportPath
)
$ErrorActionPreference = 'Stop'
Add-Type -Path $CecilPath
$taskAssemblyPath = Join-Path $Repository 'JBSLViewer\bin\Release\JBSLViewer.dll'
$taskAssembly = [Mono.Cecil.AssemblyDefinition]::ReadAssembly($taskAssemblyPath)
$taskBsml = [Mono.Cecil.AssemblyDefinition]::ReadAssembly((Join-Path $GameDirectory 'Plugins\BSML.dll'))
$taskGame = [Mono.Cecil.AssemblyDefinition]::ReadAssembly((Join-Path $GameDirectory 'Beat Saber_Data\Managed\Main.dll'))
$taskHmui = [Mono.Cecil.AssemblyDefinition]::ReadAssembly((Join-Path $GameDirectory 'Beat Saber_Data\Managed\HMUI.dll'))
$taskSources = Join-Path $Repository 'JBSLViewer\Qualifier\UI'
$taskChecks = [Collections.Generic.List[object]]::new()
function Check([bool]$Condition, [string]$Name) {
    $taskChecks.Add([pscustomobject]@{name=$Name;passed=$Condition})
    if (-not $Condition) { throw "UI verification failed: $Name" }
}
function TypesIncludingNested($Type) {
    $Type
    foreach ($taskNested in $Type.NestedTypes) { TypesIncludingNested $taskNested }
}
try {
    $taskNotices = [IO.File]::ReadAllText((Join-Path $Repository 'THIRD-PARTY-NOTICES.txt'))
    $taskUrl = 'https://github.com/MatrikMoon/TournamentAssistant?tab=MIT-1-ov-file'
    # Preserve the entire license text; upstream line-ending/trailing spaces are not substantive.
    $taskUpstreamLicense = ([IO.File]::ReadAllText((Join-Path (Split-Path $Repository -Parent) 'TournamentAssistant\LICENSE')).Replace("`r`n", "`n") -replace '(?m)[ \t]+$', '').Trim()
    Check ($taskNotices.Replace("`r`n", "`n").Contains($taskUpstreamLicense)) 'Distribution notices contain the full upstream MIT license'
    $taskProps = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    foreach ($taskType in $taskBsml.MainModule.Types) {
        if (-not $taskType.FullName.StartsWith('BeatSaberMarkupLanguage.TypeHandlers.')) { continue }
        foreach ($taskMethod in $taskType.Methods) {
            if ($taskMethod.Name -ne 'get_Props' -or -not $taskMethod.HasBody) { continue }
            foreach ($taskInstruction in $taskMethod.Body.Instructions) {
                if ($taskInstruction.OpCode.Name -eq 'ldstr') { [void]$taskProps.Add([string]$taskInstruction.Operand) }
            }
        }
    }
    $taskFiles = @(Get-ChildItem -LiteralPath $taskSources -File) +
        @(Get-Item -LiteralPath (Join-Path $Repository 'JBSLViewer\Qualifier\QualifierDirectPlayController.cs')) +
        @(Get-Item -LiteralPath (Join-Path $Repository 'JBSLViewer\Views\LeaderboardMainViewController.bsml'))
    foreach ($taskSource in $taskFiles) {
        if ($taskSource.Extension -notin @('.cs','.bsml')) { continue }
        $taskText = [IO.File]::ReadAllText($taskSource.FullName).Replace("`r`n", "`n")
        $taskIsSharedLeaderboard = $taskSource.Name -eq 'LeaderboardMainViewController.bsml'
        if (-not $taskIsSharedLeaderboard) {
            $taskHeaderEnd = if ($taskSource.Extension -eq '.cs') { $taskText.IndexOf('*/') } else { $taskText.IndexOf('-->') }
            Check ($taskHeaderEnd -gt 0 -and ($taskText.StartsWith('/*') -or $taskText.StartsWith('<!--'))) ($taskSource.Name + ': attribution is the first content')
            $taskHeader = $taskText.Substring(0,$taskHeaderEnd) -replace '(?m)[ \t]+$', ''
            Check ($taskHeader.Contains($taskUrl) -and $taskHeader.Contains($taskUpstreamLicense)) ($taskSource.Name + ': exact URL and complete MIT license')
            $taskReusedPath = if ($taskSource.Name -eq 'QualifierDirectPlayController.cs') { 'JBSLViewer/Qualifier/' } else { 'JBSLViewer/Qualifier/UI/' }
            Check ($taskNotices.Contains($taskReusedPath + $taskSource.Name)) ($taskSource.Name + ': distribution lists the reused source')
        }
        if ($taskSource.Extension -ne '.bsml') { continue }
        $taskNamespace = if ($taskIsSharedLeaderboard) { 'JBSLViewer.Views.' } else { 'JBSLViewer.Qualifier.UI.' }
        # Legacy DependentUpon resources use the type name without a .bsml suffix.
        $taskResourceName = $taskNamespace + $(if ($taskIsSharedLeaderboard) { $taskSource.BaseName } else { $taskSource.Name })
        $taskResource = $taskAssembly.MainModule.Resources | Where-Object Name -eq $taskResourceName
        Check ($null -ne $taskResource) ($taskSource.Name + ': embedded resource exists')
        $taskEmbedded = [Text.Encoding]::UTF8.GetString($taskResource.GetResourceData()).Replace("`r`n", "`n").TrimStart([char]0xfeff)
        Check ($taskEmbedded.TrimEnd() -eq $taskText.TrimEnd()) ($taskSource.Name + ': built resource equals source')
        $taskXml = [xml]$taskEmbedded
        $taskController = $taskAssembly.MainModule.GetType($taskNamespace + $taskSource.BaseName)
        Check ($null -ne $taskController) ($taskSource.Name + ': matching view controller exists')
        $taskActions = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
        $taskValues = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
        $taskComponents = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
        foreach ($taskType in (TypesIncludingNested $taskController)) {
            foreach ($taskMember in @($taskType.Methods) + @($taskType.Fields) + @($taskType.Properties)) {
                foreach ($taskAttribute in $taskMember.CustomAttributes) {
                    if ($taskAttribute.ConstructorArguments.Count -eq 0) { continue }
                    $taskValue = [string]$taskAttribute.ConstructorArguments[0].Value
                    switch ($taskAttribute.AttributeType.Name) {
                        'UIAction' { [void]$taskActions.Add($taskValue) }
                        'UIValue' { [void]$taskValues.Add($taskValue) }
                        'UIComponent' { [void]$taskComponents.Add($taskValue) }
                    }
                }
            }
        }
        $taskIds = [Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
        foreach ($taskNode in $taskXml.SelectNodes('//*')) {
            if ($taskNode.HasAttribute('id')) { [void]$taskIds.Add($taskNode.GetAttribute('id')) }
            foreach ($taskAttribute in $taskNode.Attributes) {
                $taskName = $taskAttribute.Name; $taskValue = $taskAttribute.Value
                if ($taskName.StartsWith('xmlns') -or $taskName.StartsWith('xsi:')) { continue }
                # Aliases supplied by tag macros in BSML 1.6.10, in addition to type handlers.
                $taskTagAliases = @('tags','bg','bg-color','dir','src','preserve-aspect','background-color')
                Check ($taskProps.Contains($taskName) -or $taskName -in $taskTagAliases) ($taskSource.Name + ': known BSML attribute ' + $taskName)
                if ($taskName -in @('on-click','select-cell')) {
                    Check ($taskActions.Contains($taskValue)) ($taskSource.Name + ': action ' + $taskValue)
                }
                if ($taskName -eq 'contents' -or ($taskName -eq 'text' -and $taskValue.StartsWith('~'))) {
                    Check ($taskValues.Contains($taskValue.TrimStart('~'))) ($taskSource.Name + ': value ' + $taskValue)
                }
            }
        }
        foreach ($taskComponent in $taskComponents) { Check ($taskIds.Contains($taskComponent)) ($taskSource.Name + ': UI component ' + $taskComponent) }
    }
    $taskFlow = $taskAssembly.MainModule.GetType('JBSLViewer.Qualifier.UI.QualifierFlowCoordinator')
    Check (($taskFlow.Fields | Where-Object Name -eq '_ranking').FieldType.FullName -eq 'JBSLViewer.Views.LeaderboardMainViewController') 'Right screen uses the existing JBSL leaderboard controller'
    Check ($null -eq $taskAssembly.MainModule.GetType('JBSLViewer.Qualifier.UI.QualifierLeaderboardViewController')) 'Obsolete separate leaderboard controller is absent'
    Check (@($taskAssembly.MainModule.Resources | Where-Object Name -like '*QualifierLeaderboardViewController*').Count -eq 0) 'Obsolete separate leaderboard BSML is absent'
    $taskOriginalMarkup = & git -C $Repository show HEAD:JBSLViewer/Views/LeaderboardMainViewController.bsml
    if ($LASTEXITCODE -ne 0) { throw 'Could not read the original shared leaderboard layout.' }
    $taskOriginalXml = [xml]($taskOriginalMarkup -join "`n").TrimStart([char]0xfeff)
    $taskRankingXml = [xml][IO.File]::ReadAllText((Join-Path $Repository 'JBSLViewer\Views\LeaderboardMainViewController.bsml'))
    foreach ($taskButtonId in @('up_button','down_button')) {
        $taskOriginalButton = $taskOriginalXml.SelectSingleNode("//*[@id='$taskButtonId']")
        $taskOriginalButton.RemoveAttribute('on-click')
        $taskCurrentButton = $taskRankingXml.SelectSingleNode("//*[@id='$taskButtonId']")
        Check (-not $taskCurrentButton.HasAttribute('on-click') -and -not $taskCurrentButton.HasAttribute('click-event')) ($taskButtonId + ': code binding has no duplicate BSML click action')
    }
    Check ($taskRankingXml.OuterXml -eq $taskOriginalXml.OuterXml) 'Shared leaderboard keeps its complete original layout apart from the approved button binding change'
    $taskPageType = $taskAssembly.MainModule.GetType('JBSLViewer.Models.LeaderboardPageState')
    $taskPageSize = ($taskPageType.Fields | Where-Object Name -eq 'PageSize').Constant
    Check ($taskPageSize -eq 10) 'The production leaderboard preserves the original ten-record pages'
    $taskRankingType = $taskAssembly.MainModule.GetType('JBSLViewer.Views.LeaderboardMainViewController')
    $taskBind = $taskRankingType.Methods | Where-Object Name -eq 'BindPageButtons'
    $taskUnbind = $taskRankingType.Methods | Where-Object Name -eq 'UnbindPageButtons'
    $taskParse = $taskRankingType.Methods | Where-Object Name -eq 'PostParse'
    $taskDestroy = $taskRankingType.Methods | Where-Object Name -eq 'OnDestroy'
    $taskBindCalls = @($taskBind.Body.Instructions | Where-Object { $_.OpCode.Name -in @('call','callvirt') } | ForEach-Object { $_.Operand.Name })
    $taskUnbindCalls = @($taskUnbind.Body.Instructions | Where-Object { $_.OpCode.Name -in @('call','callvirt') } | ForEach-Object { $_.Operand.Name })
    $taskDelegates = @($taskBind.Body.Instructions | Where-Object { $_.OpCode.Name -eq 'ldftn' } | ForEach-Object { $_.Operand.Name })
    Check (($taskBindCalls | Where-Object { $_ -eq 'AddListener' }).Count -eq 2 -and
        $taskDelegates.Count -eq 2 -and $taskDelegates[0] -eq 'PageUp' -and $taskDelegates[1] -eq 'PageDown') 'The two native Button clicks each bind once to their own leaderboard controller'
    Check ([Array]::IndexOf($taskBindCalls, 'UnbindPageButtons') -lt [Array]::IndexOf($taskBindCalls, 'AddListener') -and
        ($taskUnbindCalls | Where-Object { $_ -eq 'RemoveListener' }).Count -eq 2) 'Reparsing removes the previous two listeners before binding'
    Check (@($taskParse.Body.Instructions | Where-Object { $_.Operand.Name -eq 'BindPageButtons' }).Count -eq 1 -and
        @($taskDestroy.Body.Instructions | Where-Object { $_.Operand.Name -eq 'UnbindPageButtons' }).Count -eq 1) 'Page listeners follow post-parse and destruction lifecycle'
    foreach ($taskButtonField in @('_pageUpButton','_pageDownButton')) {
        Check (($taskRankingType.Fields | Where-Object Name -eq $taskButtonField).FieldType.FullName -eq 'UnityEngine.UI.Button') ($taskButtonField + ': binds the actual Unity Button component')
    }
    $taskRecords = $taskRankingType.Methods | Where-Object Name -eq 'SetRecords'
    Check (@($taskRecords.Body.Instructions | Where-Object { $_.Operand.Name -eq 'ScrollToCellWithIdx' }).Count -eq 1) 'A populated page restores the native list scroll position'
    $taskButtons = $taskRankingType.Methods | Where-Object Name -eq 'UpdatePageButtons'
    Check (@($taskButtons.Body.Instructions | Where-Object { $_.Operand.Name -in @('get_CanPrevious','get_CanNext') }).Count -eq 2) 'Button interactivity follows the production page boundaries'
    $taskDisplayTotal = $taskRankingType.Methods | Where-Object Name -eq 'SetDisplayTotal'
    $taskDisplayMap = $taskRankingType.Methods | Where-Object Name -eq 'SetDisplaySelection'
    Check ($null -ne $taskDisplayTotal -and $null -ne $taskDisplayMap -and
        @($taskDisplayTotal.Body.Instructions | Where-Object { $_.OpCode.Name -eq 'ldc.i4.1' }).Count -eq 1 -and
        @($taskDisplayMap.Body.Instructions | Where-Object { $_.OpCode.Name -eq 'ldc.i4.2' }).Count -eq 1) 'Explicit total and map selection use distinct display modes'
    $taskRender = $taskFlow.Methods | Where-Object Name -eq 'RenderRanking'
    $taskRenderMembers = @($taskRender.Body.Instructions | Where-Object { $null -ne $_.Operand } | ForEach-Object { $_.Operand.Name })
    Check ($taskRenderMembers -contains '_songs' -and $taskRenderMembers -contains 'SetDisplayTotal' -and
        $taskRenderMembers -contains '_detail' -and $taskRenderMembers -contains 'SetDisplaySelection') 'The active song-list/detail view chooses total/map ranking'
    $taskLeagueLoad = $taskFlow.NestedTypes | Where-Object Name -like '<SelectLeagueAsync>*' | ForEach-Object { $_.Methods } | Where-Object Name -eq 'MoveNext'
    Check (@($taskLeagueLoad.Body.Instructions | Where-Object { $_.Operand.Name -eq 'ShowRanking' }).Count -eq 1) 'Entering the league song list presents its ranking'
    $taskBackCallbacks = @($taskFlow.NestedTypes | ForEach-Object { $_.Methods } | Where-Object { $_.Name -like '*BackButtonWasPressed*' })
    Check (@($taskBackCallbacks | Where-Object { @($_.Body.Instructions | Where-Object { $_.Operand.Name -eq 'ShowRanking' }).Count -eq 1 }).Count -eq 1) 'Returning from detail restores the song-list ranking'
    $taskDisplayMethods = @($taskRankingType.Methods | Where-Object Name -in @('SetDisplay','SetDisplaySelection','SetDisplayTotal','SetRecords'))
    $taskPanelWrites = @($taskDisplayMethods | ForEach-Object { $_.Body.Instructions } | Where-Object {
        $_.OpCode.Name -in @('call','callvirt') -and $_.Operand.DeclaringType.FullName -eq 'JBSLViewer.Views.LeaderboardPanelViewController' -and $_.Operand.Name.StartsWith('set_')
    })
    Check ($taskPanelWrites.Count -eq 0) 'Explicit leaderboard display does not overwrite the normal panel selection'
    $taskNativeStart = @($taskGame.MainModule.GetType('MenuTransitionsHelper').Methods | Where-Object { $_.Name -eq 'StartStandardLevel' -and $_.Parameters.Count -eq 14 })
    Check ($taskNativeStart.Count -eq 1 -and $taskNativeStart[0].Parameters[7].ParameterType.FullName -eq 'PracticeSettings' -and
        $taskNativeStart[0].Parameters[12].ParameterType.FullName -eq 'System.Action`2<StandardLevelScenesTransitionSetupDataSO,LevelCompletionResults>' -and
        $taskNativeStart[0].Parameters[13].ParameterType.FullName -eq 'System.Action`2<LevelScenesTransitionSetupDataSO,LevelCompletionResults>') 'Installed game exposes the TA direct-start API and both completion callbacks'
    $taskDirect = $taskAssembly.MainModule.GetType('JBSLViewer.Qualifier.QualifierDirectPlayController')
    Check ($null -ne $taskDirect -and $null -eq $taskAssembly.MainModule.GetType('JBSLViewer.Qualifier.QualifierSoloLaunchBridge')) 'Direct-play controller replaces the old Solo launch bridge'
    $taskDirectInstructions = @(TypesIncludingNested $taskDirect | ForEach-Object { $_.Methods } | Where-Object HasBody | ForEach-Object { $_.Body.Instructions })
    $taskDirectCalls = @($taskDirectInstructions | Where-Object { $_.OpCode.Name -in @('call','callvirt') } | ForEach-Object { $_.Operand })
    $taskStartCalls = @($taskDirectCalls | Where-Object { $_.DeclaringType.FullName -eq 'MenuTransitionsHelper' -and $_.Name -eq 'StartStandardLevel' })
    Check ($taskStartCalls.Count -eq 1 -and $taskStartCalls[0].FullName -eq $taskNativeStart[0].FullName) 'Built direct launch calls the exact installed game signature'
    Check (@($taskDirectCalls | Where-Object { $_.Name -in @('PresentFlowCoordinator','DismissFlowCoordinator','SelectLevel','ActionButtonWasPressed','PracticeButtonWasPressed') }).Count -eq 0) 'Dedicated direct launch does not present or operate a Solo selection flow'
    Check (@($taskDirectInstructions | Where-Object { $_.OpCode.Name -eq 'newobj' -and $_.Operand.DeclaringType.FullName -eq 'PracticeSettings' }).Count -eq 0) 'Direct PRACTICE does not construct native practice settings'
    Check (@($taskDirectCalls | Where-Object { $_.DeclaringType.FullName -like '*QualifierChallengeCoordinator' -or $_.DeclaringType.FullName -like '*QualifierOutbox' -or $_.Name -eq 'GameplayFinished' }).Count -eq 0) 'Direct UI completion does not create or submit another challenge result'
    $taskEntry = $taskAssembly.MainModule.GetType('JBSLViewer.Qualifier.UI.QualifierMenuEntry')
    $taskBegin = $taskEntry.Methods | Where-Object Name -eq 'BeginDirectLaunch'
    $taskBeginCalls = @($taskBegin.Body.Instructions | Where-Object { $_.OpCode.Name -in @('call','callvirt') } | ForEach-Object { $_.Operand.Name })
    Check ($taskBeginCalls -contains 'BeginLaunch' -and @($taskBeginCalls | Where-Object { $_ -in @('Dismiss','Present','Suspend') }).Count -eq 0 -and
        @($taskEntry.Methods | Where-Object Name -in @('Tick','SuspendForLaunch')).Count -eq 0) 'Entry retains its existing parent and flow on launch and return'
    $taskResultType = $taskGame.MainModule.GetType('ResultsViewController')
    $taskNativeInit = $taskResultType.Methods | Where-Object { $_.Name -eq 'Init' -and $_.Parameters.Count -eq 5 }
    $taskResultMethod = $taskFlow.Methods | Where-Object Name -eq 'ShowDirectResult'
    $taskResultCalls = @($taskResultMethod.Body.Instructions | Where-Object { $_.OpCode.Name -in @('call','callvirt') } | ForEach-Object { $_.Operand })
    Check (@($taskResultCalls | Where-Object { $_.FullName -eq $taskNativeInit.FullName }).Count -eq 1) 'Dedicated results use the installed native five-argument Init API'
    Check (@($taskResultCalls | Where-Object Name -eq 'InstantiatePrefabForComponent').Count -eq 1 -and
        @($taskResultCalls | Where-Object Name -eq 'PresentViewController').Count -eq 1) 'Result UI is cloned and presented under the dedicated flow'
    foreach ($taskResultEvent in @('continueButtonPressedEvent','restartButtonPressedEvent')) {
        $taskNativeEvent = $taskResultType.Events | Where-Object Name -eq $taskResultEvent
        Check ($null -ne $taskNativeEvent -and @($taskResultCalls | Where-Object { $_.FullName -eq $taskNativeEvent.AddMethod.FullName }).Count -eq 1) ($taskResultEvent + ': dedicated handler matches the installed event')
        $taskEventField = $taskResultType.Fields | Where-Object Name -eq $taskResultEvent
        Check ($null -ne $taskEventField -and -not $taskEventField.IsPublic -and
            @($taskEventField.CustomAttributes | Where-Object { $_.AttributeType.Name -in @('SerializeField','SerializeReference') }).Count -eq 0) ($taskResultEvent + ': native C# listeners are not serialized into the clone')
        $taskResultUnbind = $taskFlow.Methods | Where-Object Name -eq 'UnbindResultEvents'
        Check (@($taskResultUnbind.Body.Instructions | Where-Object { $_.Operand.FullName -eq $taskNativeEvent.RemoveMethod.FullName }).Count -eq 1) ($taskResultEvent + ': dedicated handler is removed on cleanup')
    }
    foreach ($taskRuntimeField in @('<buttonBinder>k__BackingField','_wasActivatedBefore','_isActivated')) {
        $taskField = $taskHmui.MainModule.GetType('HMUI.ViewController').Fields | Where-Object Name -eq $taskRuntimeField
        Check ($null -ne $taskField -and -not $taskField.IsPublic -and
            @($taskField.CustomAttributes | Where-Object { $_.AttributeType.Name -in @('SerializeField','SerializeReference') }).Count -eq 0) ($taskRuntimeField + ': cloned result gets fresh native activation/binding state')
    }
    foreach ($taskCleanup in @('CloseResults','RecoverAfterResultFailure','PrepareForDismiss','OnDestroy')) {
        $taskCleanupMethod = $taskFlow.Methods | Where-Object Name -eq $taskCleanup
        Check (@($taskCleanupMethod.Body.Instructions | Where-Object { $_.Operand.Name -eq 'UnbindResultEvents' }).Count -eq 1) ($taskCleanup + ': cleans up result event ownership')
    }
    $taskNativeSolo = $taskGame.MainModule.GetType('SoloFreePlayFlowCoordinator')
    foreach ($taskFieldType in @(
        @('_resultsViewController','ResultsViewController'), @('_menuLightsManager','MenuLightsManager'),
        @('_defaultLightsPreset','MenuLightsPresetSO'), @('_resultsClearedLightsPreset','MenuLightsPresetSO'), @('_resultsFailedLightsPreset','MenuLightsPresetSO')
    )) {
        Check (($taskNativeSolo.Fields | Where-Object Name -eq $taskFieldType[0]).FieldType.FullName -eq $taskFieldType[1]) ($taskFieldType[0] + ': installed native result template/light field matches')
    }
    Check (($taskResultType.Fields | Where-Object Name -eq '_restartButton').FieldType.FullName -eq 'UnityEngine.UI.Button') 'Installed native result restart button matches'
    $taskActivate = $taskFlow.Methods | Where-Object Name -eq 'DidActivate'
    Check (@($taskActivate.Body.Instructions | Where-Object { $_.Operand.Name -eq 'DirectMenuActivated' }).Count -eq 1) 'Reactivating the dedicated flow flushes any missing gameplay completion'
    $taskRestart = $taskFlow.Methods | Where-Object Name -eq 'ResultRestart'
    Check (@($taskRestart.Body.Instructions | Where-Object { $_.Operand.Name -eq 'Practice' }).Count -eq 1 -and
        @($taskRestart.Body.Instructions | Where-Object { $_.Operand.Name -eq 'CloseResults' }).Count -eq 1) 'Dedicated result restart checks the practice flag before closing'
    $taskCloseCallbacks = @($taskFlow.NestedTypes | ForEach-Object { $_.Methods } | Where-Object { $_.Name -like '*CloseResults*' })
    Check (@($taskCloseCallbacks | Where-Object { @($_.Body.Instructions | Where-Object { $_.Operand.Name -eq 'StartPracticeAsync' }).Count -eq 1 }).Count -eq 1) 'PRACTICE restarts only after the result dismissal callback'
    $taskBack = $taskAssembly.MainModule.GetType('JBSLViewer.Qualifier.QualifierBackLockPatch').Methods | Where-Object Name -eq 'Prefix'
    $taskBackCalls = @($taskBack.Body.Instructions | Where-Object { $_.OpCode.Name -in @('call','callvirt') } | ForEach-Object { $_.Operand.Name })
    Check ([Array]::IndexOf($taskBackCalls, 'CancelPendingLaunch') -ge 0 -and
        [Array]::IndexOf($taskBackCalls, 'CancelPendingLaunch') -lt [Array]::IndexOf($taskBackCalls, 'get_Locked')) 'Back patch handles preparation cancellation before the generic lock'
    $taskReport = [pscustomobject]@{
        scope='Static BSML/resources/attribution and native API/launch binding checks against installed BSML, Main.dll and HMUI.dll. Does not execute Unity or render VR screens.'
        assembly=$taskAssemblyPath
        sha256=(Get-FileHash -LiteralPath $taskAssemblyPath -Algorithm SHA256).Hash
        bsmlVersion=$taskBsml.Name.Version.ToString()
        passed=$taskChecks.Count
        checks=$taskChecks
    }
    if ($ReportPath) { $taskReport | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $ReportPath -Encoding utf8 }
    Write-Output ('UI STATIC CHECKS PASSED: ' + $taskChecks.Count)
}
finally { $taskAssembly.Dispose(); $taskBsml.Dispose(); $taskGame.Dispose(); $taskHmui.Dispose() }
