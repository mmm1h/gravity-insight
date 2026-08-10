param(
  [int]$RefreshWithinHours = 48,
  [switch]$Force,
  [switch]$SelfTest
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$envPath = Join-Path $repoRoot ".env.gravity.local"
$statePath = Join-Path $repoRoot "tmp\scheduled-tasks\gravity-token-refresh.latest.json"

function Read-LocalEnv {
  param([Parameter(Mandatory = $true)][string]$Path)

  $values = @{}
  if (-not (Test-Path -LiteralPath $Path)) {
    return $values
  }

  foreach ($line in Get-Content -LiteralPath $Path) {
    if ($line -match "^\s*#" -or $line -match "^\s*$") {
      continue
    }
    if ($line -match "^\s*([^=\s]+)\s*=\s*(.*)\s*$") {
      $value = $Matches[2].Trim()
      if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
        $value = $value.Substring(1, $value.Length - 2)
      }
      $values[$Matches[1]] = $value
    }
  }

  $values
}

function Write-LocalEnv {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][hashtable]$Values
  )

  Set-Content -LiteralPath $Path -Encoding UTF8 -Value @(
    "# Local Gravity SQL auth. This file is ignored by git.",
    "# Do not commit, paste, or print these values.",
    "GRAVITY_USERNAME=$($Values.GRAVITY_USERNAME)",
    "GRAVITY_PASSWORD=$($Values.GRAVITY_PASSWORD)",
    "GRAVITY_AUTH_TOKEN=$($Values.GRAVITY_AUTH_TOKEN)",
    "GRAVITY_AUTH_TOKEN_EXPIRES_AT_ASIA_SHANGHAI=$($Values.GRAVITY_AUTH_TOKEN_EXPIRES_AT_ASIA_SHANGHAI)",
    "GRAVITY_AUTH_UPDATED_AT=$($Values.GRAVITY_AUTH_UPDATED_AT)"
  )
}

function ConvertFrom-Base64Url {
  param([Parameter(Mandatory = $true)][string]$Value)

  $padded = $Value.Replace("-", "+").Replace("_", "/")
  switch ($padded.Length % 4) {
    0 { }
    2 { $padded += "==" }
    3 { $padded += "=" }
    default { throw "Invalid base64url payload length." }
  }
  [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($padded))
}

function Get-JwtStatus {
  param([string]$Token)

  try {
    $parts = $Token -split "\."
    if ([string]::IsNullOrWhiteSpace($Token) -or $parts.Count -lt 2) {
      return $null
    }
    $payload = ConvertFrom-Base64Url -Value $parts[1] | ConvertFrom-Json
    if (-not $payload.exp) {
      return $null
    }
    $timezone = [TimeZoneInfo]::FindSystemTimeZoneById("China Standard Time")
    $expiresAt = [TimeZoneInfo]::ConvertTime([DateTimeOffset]::FromUnixTimeSeconds([int64]$payload.exp), $timezone)
    $now = [TimeZoneInfo]::ConvertTime([DateTimeOffset]::UtcNow, $timezone)
    $hoursLeft = ($expiresAt - $now).TotalHours
    [pscustomobject]@{
      ExpiresAt = $expiresAt
      HoursLeft = $hoursLeft
      NeedsRefresh = $hoursLeft -le $RefreshWithinHours
    }
  }
  catch {
    $null
  }
}

function ConvertTo-Md5Hex {
  param([Parameter(Mandatory = $true)][string]$Value)

  $md5 = [Security.Cryptography.MD5]::Create()
  try {
    $hashBytes = $md5.ComputeHash([Text.Encoding]::UTF8.GetBytes($Value))
    -join ($hashBytes | ForEach-Object { $_.ToString("x2") })
  }
  finally {
    $md5.Dispose()
  }
}

function Invoke-GravityLogin {
  param(
    [Parameter(Mandatory = $true)][string]$Username,
    [Parameter(Mandatory = $true)][string]$Password
  )

  $body = @{
    action_type = "email"
    username = $Username
    password = ConvertTo-Md5Hex -Value $Password.Trim()
    product_name = "turbo"
    free_login_day = 7
  } | ConvertTo-Json -Compress

  $response = Invoke-RestMethod `
    -Method Post `
    -Uri "https://api-insight.gravity-engine.com/account_center/api/v1/user_login/v2/" `
    -Headers @{
      "Content-Type" = "application/json"
      "Origin" = "https://web.gravity-engine.com"
      "Referer" = "https://web.gravity-engine.com/"
    } `
    -Body $body

  if ($response.code -ne 0) {
    throw "Gravity login failed: code=$($response.code), msg=$($response.msg)"
  }
  $user = if ($response.data.user) { $response.data.user } else { $response.user }
  if (-not $user -or [string]::IsNullOrWhiteSpace($user.Authorization)) {
    throw "Gravity login succeeded but no Authorization token was returned."
  }
  $user.Authorization
}

function Invoke-GravitySmokeTest {
  param([Parameter(Mandatory = $true)][string]$Token)

  $body = @{ sql = "SELECT 1 AS ok"; tabId = "1" } | ConvertTo-Json -Compress
  for ($attempt = 1; $attempt -le 3; $attempt++) {
    try {
      $response = Invoke-WebRequest `
        -UseBasicParsing `
        -Method Post `
        -Uri "https://api-insight.gravity-engine.com/custom_sql/api/sql/execute" `
        -Headers @{
          authorization = $Token
          origin = "https://bi.gravity-engine.com"
          referer = "https://bi.gravity-engine.com/"
          accept = "*/*"
        } `
        -ContentType "application/json; charset=utf-8" `
        -Body ([Text.Encoding]::UTF8.GetBytes($body))
      $payload = $response.Content | ConvertFrom-Json
      $apiStatus = [string]$payload.data.status
      return [pscustomobject]@{
        Ok = [int]$response.StatusCode -eq 200 -and $apiStatus -ieq "success"
        Http = [int]$response.StatusCode
        ApiCode = $payload.code
        Status = $apiStatus
        Message = $payload.msg
      }
    }
    catch {
      $http = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { $null }
      if ($attempt -eq 3 -or $http -notin @(429, 500, 502, 503, 504)) {
        return [pscustomobject]@{
          Ok = $false
          Http = $http
          ApiCode = $null
          Status = "request_failed"
          Message = $_.Exception.Message
        }
      }
      Start-Sleep -Seconds (2 * $attempt)
    }
  }
}

function Write-State {
  param([Parameter(Mandatory = $true)]$State)

  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $statePath) | Out-Null
  $State | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $statePath -Encoding UTF8
}

function Invoke-GitHubCredentialSync {
  if ($env:GRAVITY_CREDENTIAL_AUTO_PUSH -ne "1") {
    return "disabled"
  }
  $python = Join-Path $repoRoot ".venv\Scripts\python.exe"
  if (-not (Test-Path -LiteralPath $python)) {
    $python = (Get-Command python -ErrorAction Stop).Source
  }
  & $python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
  if ($LASTEXITCODE -ne 0) {
    throw "Credential sync requires Python 3.11+."
  }
  Push-Location $repoRoot
  try {
    $output = & $python -m gravity_sdk sql credentials push --if-enabled
    if ($LASTEXITCODE -ne 0) {
      throw "GitHub credential sync failed: $output"
    }
    try {
      return [string](($output | ConvertFrom-Json -ErrorAction Stop).status)
    }
    catch {
      throw "GitHub credential sync returned an invalid response."
    }
  }
  finally {
    Pop-Location
  }
}

if ($SelfTest) {
  $RefreshWithinHours = 3
  $expiration = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() + 7200
  $payload = @{ exp = $expiration } | ConvertTo-Json -Compress
  $encoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($payload)).TrimEnd("=").Replace("+", "-").Replace("/", "_")
  $status = Get-JwtStatus -Token "e30.$encoded.signature"
  if (-not $status -or -not $status.NeedsRefresh -or $status.HoursLeft -lt 1.9 -or (Get-JwtStatus -Token "invalid")) {
    throw "Gravity token refresh self-test failed."
  }
  Write-Output "PASS Gravity token refresh self-test"
  exit 0
}

try {
  $localEnv = Read-LocalEnv -Path $envPath
  if ([string]::IsNullOrWhiteSpace($localEnv.GRAVITY_USERNAME) -or [string]::IsNullOrWhiteSpace($localEnv.GRAVITY_PASSWORD)) {
    throw "Missing GRAVITY_USERNAME or GRAVITY_PASSWORD in $envPath"
  }

  $status = Get-JwtStatus -Token $localEnv.GRAVITY_AUTH_TOKEN
  $action = "kept_local_token"
  if (-not $status -or $Force -or $status.NeedsRefresh) {
    $localEnv.GRAVITY_AUTH_TOKEN = Invoke-GravityLogin -Username $localEnv.GRAVITY_USERNAME -Password $localEnv.GRAVITY_PASSWORD
    $status = Get-JwtStatus -Token $localEnv.GRAVITY_AUTH_TOKEN
    if (-not $status) {
      throw "Gravity login returned a token without a valid expiration."
    }
    $localEnv.GRAVITY_AUTH_TOKEN_EXPIRES_AT_ASIA_SHANGHAI = $status.ExpiresAt.ToString("yyyy-MM-dd HH:mm:ss zzz")
    $localEnv.GRAVITY_AUTH_UPDATED_AT = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
    Write-LocalEnv -Path $envPath -Values $localEnv
    $action = "refreshed_local_token"
  }

  [Environment]::SetEnvironmentVariable("GRAVITY_AUTH_TOKEN", $localEnv.GRAVITY_AUTH_TOKEN, "User")
  $env:GRAVITY_AUTH_TOKEN = $localEnv.GRAVITY_AUTH_TOKEN
  $smoke = Invoke-GravitySmokeTest -Token $localEnv.GRAVITY_AUTH_TOKEN
  $credentialSync = if ($action -eq "refreshed_local_token") { Invoke-GitHubCredentialSync } else { "unchanged" }
  $result = [ordered]@{
    TimestampAsiaShanghai = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
    Status = if ($smoke.Ok) { "success" } else { "warning" }
    Action = $action
    ExpirationAsiaShanghai = $status.ExpiresAt.ToString("yyyy-MM-dd HH:mm:ss zzz")
    HoursLeft = [math]::Round($status.HoursLeft, 2)
    UserEnvironmentSynced = $true
    SmokeHttp = $smoke.Http
    SmokeApiCode = $smoke.ApiCode
    SmokeStatus = $smoke.Status
    CredentialSync = $credentialSync
  }
  Write-State -State $result
  Write-Output ([pscustomobject]$result)
  exit 0
}
catch {
  $failure = [ordered]@{
    TimestampAsiaShanghai = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
    Status = "failed"
    Error = $_.Exception.Message
  }
  try { Write-State -State $failure } catch { }
  Write-Error "Gravity token refresh failed: $($failure.Error)"
  exit 1
}
