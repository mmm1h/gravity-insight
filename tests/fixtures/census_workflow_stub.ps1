$ErrorActionPreference = 'Stop'
$script:call = 0
$script:scenario = Get-Content -Raw -LiteralPath $env:CENSUS_SCENARIO | ConvertFrom-Json
New-Item -ItemType Directory -Force -Path (Join-Path $env:RUNNER_TEMP 'gravity-drift') | Out-Null
function Start-Sleep { param($Seconds) }
function Start-Process {
    param($FilePath, $ArgumentList, [switch]$PassThru, $WindowStyle, $RedirectStandardOutput, $RedirectStandardError)
    if ($WindowStyle -ne 'Hidden') { throw 'Visible background helper' }
    Set-Content -LiteralPath $RedirectStandardOutput -Value ''
    Set-Content -LiteralPath $RedirectStandardError -Value ''
    $unquoted = @($ArgumentList | ForEach-Object { $_.Substring(1, $_.Length - 2).Replace('\"', '"') })
    gravity @unquoted
    $process = [pscustomobject]@{ExitCode = $global:LASTEXITCODE}
    $process | Add-Member ScriptMethod WaitForExit {
        if ($args.Count -gt 0) { return -not $script:scenario[$script:call - 1].timeout }
    }
    $process | Add-Member ScriptMethod Kill {
        Set-Content -LiteralPath (Join-Path $env:RUNNER_TEMP 'gravity-drift/child-killed.txt') -Value 'true'
    }
    return $process
}
function gravity {
    $arguments = @($args)
    if ($arguments[0] -ne 'census' -or $arguments[1] -ne 'fetch') { throw 'Unexpected command' }
    function Option($name) { $arguments[[Array]::IndexOf($arguments, $name) + 1] }
    if ((Option '--max-attempts') -ne 1) { throw 'Nested resource retry enabled' }
    $row = $script:scenario[$script:call]
    $script:call++
    $limit = [int](Option '--max-requests')
    [ordered]@{ limit = $limit; elapsed = [double](Option '--max-elapsed-seconds') } |
        ConvertTo-Json -Compress | Add-Content -LiteralPath (Join-Path $env:RUNNER_TEMP 'calls.jsonl')
    if ($row.crash) { throw 'Injected process failure' }
    $complete = $row.complete -eq $true
    $failure = $null
    if (-not $complete) {
        $failure = [ordered]@{
            failure_class = $row.failure_class
            retryable = $row.failure_class -in @('transport_failure', 'upstream_capacity')
            cooldown_remaining_ms = 0
            next_action = 'Inspect offline injected failure'
        }
    }
    $step = [ordered]@{
        schema_version = 'gravity-census.step-output.v1'
        complete = $complete
        failure_class = $row.failure_class
        failure = $failure
        request_budget = [ordered]@{used = [int]$row.used; limit = $limit; remaining = $limit - $row.used}
    }
    $step | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Option '--step-output')
    if ($failure) { $failure | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Option '--failure-output') }
    if ($row.elapsed_seconds) {
        $script:clock = [pscustomobject]@{Elapsed = [pscustomobject]@{TotalSeconds = $row.elapsed_seconds}}
    }
    $global:LASTEXITCODE = if ($complete) {0} else {3}
}
