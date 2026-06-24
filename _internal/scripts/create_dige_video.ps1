param(
  [Parameter(Mandatory = $true)]
  [string]$AudioPath,

  [string]$AppId = $env:CHANJING_APP_ID,
  [string]$SecretKey = $env:CHANJING_SECRET_KEY,
  [string]$PersonId = $env:CHANJING_PERSON_ID,

  [string]$OutputDir = "D:\CODEX\数字人API\output",
  [int]$ScreenWidth = 1920,
  [int]$ScreenHeight = 1080,
  [int]$PollSeconds = 10,
  [int]$MaxPolls = 120,
  [switch]$TokenOnly
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

if (-not $AppId -or -not $SecretKey) {
  throw "missing Chanjing AppId or SecretKey"
}
if (-not $PersonId) {
  $PersonId = "C-1327db72b9334935bdeabadc83b76475"
}
$ApiBase = "https://open-api.chanjing.cc/open/v1"

function ConvertTo-Utf8Bytes {
  param([Parameter(Mandatory = $true)] [string]$Value)
  # Preserve byte[] as one Invoke-RestMethod body instead of expanding it into the pipeline.
  return ,([System.Text.Encoding]::UTF8.GetBytes($Value))
}

function Invoke-JsonPostUtf8 {
  param(
    [Parameter(Mandatory = $true)] [string]$Uri,
    [Parameter(Mandatory = $true)] [hashtable]$Headers,
    [Parameter(Mandatory = $true)] $BodyObject
  )
  $json = $BodyObject | ConvertTo-Json -Depth 20 -Compress
  return Invoke-RestMethod -Method Post -Uri $Uri -Headers $Headers -ContentType "application/json; charset=utf-8" -Body (ConvertTo-Utf8Bytes $json)
}

function Get-MimeType {
  param([Parameter(Mandatory = $true)] [string]$Path)
  switch ([System.IO.Path]::GetExtension($Path).ToLowerInvariant()) {
    ".mp3" { return "audio/mpeg" }
    ".wav" { return "audio/x-wav" }
    ".m4a" { return "audio/m4a" }
    default { return "application/octet-stream" }
  }
}

function Get-MediaDuration {
  param([Parameter(Mandatory = $true)] [string]$Path)
  try {
    $ffprobe = Get-Command ffprobe -ErrorAction Stop
    $rawDuration = & $ffprobe.Source -v error -show_entries format=duration -of default=nw=1:nk=1 $Path
    if ($LASTEXITCODE -eq 0 -and $rawDuration) {
      return [double]$rawDuration
    }
  } catch {
    return $null
  }
  return $null
}

function Test-CustomisedPersonReady {
  param(
    [Parameter(Mandatory = $true)] [string]$Id,
    [Parameter(Mandatory = $true)] [hashtable]$Headers
  )
  try {
    $resp = Invoke-RestMethod -Method Get -Uri "$ApiBase/customised_person?id=$([uri]::EscapeDataString($Id))" -Headers $Headers
    if ($resp.code -eq 0 -and $resp.data -and $resp.data.id -and $resp.data.is_open -eq 1 -and $resp.data.width -gt 0 -and $resp.data.height -gt 0) {
      return $resp.data
    }
  } catch {
    return $null
  }
  return $null
}

function Select-AvailableCustomisedPerson {
  param([Parameter(Mandatory = $true)] [hashtable]$Headers)
  try {
    $resp = Invoke-JsonPostUtf8 `
      -Uri "$ApiBase/list_customised_person" `
      -Headers $Headers `
      -BodyObject @{ page = 1; page_size = 50 }
    if ($resp.code -ne 0 -or -not $resp.data -or -not $resp.data.list) {
      return $null
    }
    foreach ($item in $resp.data.list) {
      if ($item.id -and $item.is_open -eq 1 -and $item.width -gt 0 -and $item.height -gt 0) {
        return $item
      }
    }
  } catch {
    return $null
  }
  return $null
}

if (-not (Test-Path -LiteralPath $AudioPath -PathType Leaf)) {
  throw "audio file not found: $AudioPath"
}

$resolvedAudio = (Resolve-Path -LiteralPath $AudioPath).Path
Write-Output "uploading audio: $resolvedAudio"
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$tokenResp = Invoke-JsonPostUtf8 `
  -Uri "$ApiBase/access_token" `
  -Headers @{} `
  -BodyObject @{ app_id = $AppId; secret_key = $SecretKey }

if ($tokenResp.code -ne 0) {
  throw "access_token failed: code=$($tokenResp.code) msg=$($tokenResp.msg)"
}

if ($TokenOnly) {
  [pscustomobject]@{
    ok = $true
    step = "access_token"
    expire_in = $tokenResp.data.expire_in
  } | ConvertTo-Json -Depth 5
  exit 0
}

$headersJson = @{
  access_token = $tokenResp.data.access_token
  "Content-Type" = "application/json; charset=utf-8"
}
$headersGet = @{ access_token = $tokenResp.data.access_token }

$personInfo = Test-CustomisedPersonReady -Id $PersonId -Headers $headersGet
if (-not $personInfo) {
  $autoPerson = Select-AvailableCustomisedPerson -Headers $headersJson
  if ($autoPerson) {
    $PersonId = $autoPerson.id
    $personInfo = $autoPerson
    Write-Output "auto selected Chanjing person: $($autoPerson.name) $PersonId"
  }
}

if (-not $personInfo) {
  [pscustomobject]@{
    ok = $false
    step = "select_person"
    person_id = $PersonId
    code = 50000
    msg = "No available customised Chanjing digital person was found for this AppId, or the configured PersonId does not belong to this AppId. Create or enable a customised digital person in Chanjing, or fill a valid Chanjing PersonId in settings."
  } | ConvertTo-Json -Depth 10
  exit 1
}

$audioName = [System.IO.Path]::GetFileName($resolvedAudio)
$encodedName = [uri]::EscapeDataString($audioName)
$uploadResp = Invoke-RestMethod `
  -Method Get `
  -Uri "$ApiBase/common/create_upload_url?service=make_video_audio&name=$encodedName" `
  -Headers $headersGet

if ($uploadResp.code -ne 0) {
  [pscustomobject]@{
    ok = $false
    step = "create_upload_url"
    code = $uploadResp.code
    msg = $uploadResp.msg
    trace_id = $uploadResp.trace_id
  } | ConvertTo-Json -Depth 10
  exit 1
}

$audioFileId = $uploadResp.data.file_id
if (-not $audioFileId) {
  $audioFileId = $uploadResp.data.id
}
$contentType = $uploadResp.data.mime_type
if (-not $contentType) {
  $contentType = Get-MimeType -Path $resolvedAudio
}

try {
  Invoke-WebRequest `
    -Method Put `
    -Uri $uploadResp.data.sign_url `
    -InFile $resolvedAudio `
    -ContentType $contentType `
    -TimeoutSec 300 `
    -UseBasicParsing | Out-Null
} catch {
  throw "audio upload failed: $($_.Exception.Message)"
}

$fileDetail = $null
for ($i = 1; $i -le 24; $i++) {
  $fileDetail = Invoke-RestMethod -Method Get -Uri "$ApiBase/common/file_detail?id=$audioFileId" -Headers $headersGet
  if ($fileDetail.code -ne 0 -or $fileDetail.data.status -ne 0) {
    break
  }
  Start-Sleep -Seconds 5
}

if ($fileDetail.code -ne 0 -or $fileDetail.data.status -ne 1) {
  [pscustomobject]@{
    ok = $false
    step = "file_detail"
    audio_file_id = $audioFileId
    code = $fileDetail.code
    status = $fileDetail.data.status
    msg = $fileDetail.msg
    trace_id = $fileDetail.trace_id
  } | ConvertTo-Json -Depth 10
  exit 1
}

$createBody = [ordered]@{
  person = [ordered]@{
    id = $PersonId
    x = 0
    y = 0
    width = $ScreenWidth
    height = $ScreenHeight
    drive_mode = "random"
    is_remove_bg = $false
  }
  audio = [ordered]@{
    file_id = $audioFileId
    wav_url = ""
    type = "audio"
    volume = 100
    language = "cn"
  }
  bg_color = "#EDEDED"
  screen_width = $ScreenWidth
  screen_height = $ScreenHeight
}

$createResp = Invoke-JsonPostUtf8 `
  -Uri "$ApiBase/create_video" `
  -Headers $headersJson `
  -BodyObject $createBody

if ($createResp.code -ne 0) {
  [pscustomobject]@{
    ok = $false
    step = "create_video"
    audio_file_id = $audioFileId
    code = $createResp.code
    msg = $createResp.msg
    trace_id = $createResp.trace_id
  } | ConvertTo-Json -Depth 10
  exit 1
}

$videoId = $createResp.data
Write-Output "created video task: $videoId"
$detail = $null
$history = @()

for ($i = 1; $i -le $MaxPolls; $i++) {
  $detail = Invoke-RestMethod -Method Get -Uri "$ApiBase/video?id=$videoId" -Headers $headersGet
  $history += [pscustomobject]@{
    attempt = $i
    status = $detail.data.status
    progress = $detail.data.progress
    queue_status = $detail.data.queue_status
    duration = $detail.data.duration
    msg = $detail.data.msg
  }
  Write-Output "poll video: attempt=$i status=$($detail.data.status) progress=$($detail.data.progress) queue=$($detail.data.queue_status) msg=$($detail.data.msg)"

  if ($detail.code -ne 0 -or $detail.data.status -eq 30 -or ($detail.data.status -ge 40 -and $detail.data.status -lt 60) -or $detail.data.queue_status -eq "failed") {
    break
  }
  Start-Sleep -Seconds $PollSeconds
}

$localFile = $null
$probeDuration = $null

if ($detail.code -eq 0 -and $detail.data.status -eq 30 -and $detail.data.video_url) {
  $safeStamp = Get-Date -Format "yyyyMMdd_HHmmss"
  $localFile = Join-Path $OutputDir "dige_audio_video_$($videoId)_$safeStamp.mp4"
  Write-Output "downloading video: $localFile"
  & curl.exe -L --fail --connect-timeout 20 --max-time 300 -o $localFile $detail.data.video_url | Out-Null
  if ($LASTEXITCODE -ne 0) {
    throw "download failed with curl exit code $LASTEXITCODE"
  }

  $probeDuration = Get-MediaDuration -Path $localFile
}

[pscustomobject]@{
  ok = ($detail.code -eq 0 -and $detail.data.status -eq 30)
  audio_file_id = $audioFileId
  source_audio = $resolvedAudio
  source_audio_duration = Get-MediaDuration -Path $resolvedAudio
  video_id = $videoId
  status = $detail.data.status
  progress = $detail.data.progress
  queue_status = $detail.data.queue_status
  msg = $detail.data.msg
  duration = $detail.data.duration
  probed_duration = $probeDuration
  video_url = $detail.data.video_url
  preview_url = $detail.data.preview_url
  local_file = $localFile
  history = $history
} | ConvertTo-Json -Depth 12
