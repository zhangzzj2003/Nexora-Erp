$ErrorActionPreference = 'Stop'
$service = Join-Path $PWD 'release/win-unpacked/resources/backend-service/nexora-server.exe'
$desktop = Join-Path $PWD 'release/win-unpacked/Nexora ERP.exe'
if (-not (Test-Path $service) -or -not (Test-Path $desktop)) {
  throw 'Windows 安装包缺少桌面程序或 FastAPI 服务程序。'
}

# 在 CI 的临时目录启动打包后的真实服务，验证证书、数据库和 HTTPS 监听。
$dataDir = Join-Path $env:RUNNER_TEMP 'nexora-packaged-smoke'
$process = Start-Process -FilePath $service -ArgumentList @('--data-dir', "`"$dataDir`"", '--name', '"CI ERP"', '--port', '18751') -PassThru -WindowStyle Hidden
try {
  $healthy = $false
  for ($attempt = 0; $attempt -lt 60; $attempt++) {
    if ($process.HasExited) { throw '打包后的服务程序提前退出。' }
    try {
      $response = Invoke-RestMethod 'https://127.0.0.1:18751/api/v1/health' -SkipCertificateCheck -TimeoutSec 1
      if ($response.status -eq 'ok' -and $response.service -eq 'nexora-api') {
        $healthy = $true
        break
      }
    } catch { Start-Sleep -Milliseconds 250 }
  }
  if (-not $healthy) { throw '打包后的服务程序没有通过 HTTPS 健康检查。' }
} finally {
  if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force }
}

# CI 运行器以管理员身份执行时，验证 SCM 接管、停止和重新启动打包后的服务。
function Assert-ServiceHealthy {
  param([int]$Port = 18762)
  for ($attempt = 0; $attempt -lt 60; $attempt++) {
    try {
      $response = Invoke-RestMethod "https://127.0.0.1:$Port/api/v1/health" -SkipCertificateCheck -TimeoutSec 1
      if ($response.status -eq 'ok' -and $response.service -eq 'nexora-api') { return }
    } catch {
      # 服务控制器返回后，HTTPS 监听可能还需要短暂初始化。
    }
    Start-Sleep -Milliseconds 250
  }
  throw 'Windows 系统服务没有通过 HTTPS 健康检查。'
}

function Assert-TestSupplier {
  param([int]$Port, [string]$Password, [int]$SupplierId)
  # 每次重登并经业务接口读取，证明数据库和鉴权会话都能被重启或恢复后的服务使用。
  $loginBody = @{ username = 'ci_admin'; password = $Password } | ConvertTo-Json -Compress
  $login = Invoke-RestMethod "https://127.0.0.1:$Port/api/v1/auth/login" -Method Post `
    -ContentType 'application/json' -Body $loginBody -SkipCertificateCheck
  # 重启、升级和独立恢复均须沿用数据库规则，不能重新进入首次设置。
  $numbering = Invoke-RestMethod "https://127.0.0.1:$Port/api/v1/system/document-numbering" -Headers @{
    Authorization = "Bearer $($login.token)"
  } -SkipCertificateCheck
  if (-not $numbering.configured -or $numbering.style -ne 'english' -or
      $numbering.timezone_mode -ne 'specified' -or $numbering.timezone -ne 'America/New_York') {
    throw "Windows 服务端口 $Port 的编号规则发生变化。"
  }
  $suppliers = Invoke-RestMethod "https://127.0.0.1:$Port/api/v1/suppliers" -Headers @{
    Authorization = "Bearer $($login.token)"
  } -SkipCertificateCheck
  $matching = @($suppliers | Where-Object { $_.id -eq $SupplierId -and $_.name -eq 'CI 验收供应商' })
  if ($matching.Count -ne 1) { throw "Windows 服务端口 $Port 的测试供应商资料缺失。" }
}

$request = Join-Path $env:RUNNER_TEMP 'nexora-service-request.json'
$serviceData = Join-Path $env:RUNNER_TEMP 'nexora-system-service-data'
@{ name = 'CI 固定主机'; data_dir = $serviceData; port = 18762 } | ConvertTo-Json | Set-Content -Path $request -Encoding utf8
$serviceStartedAt = Get-Date
& $service install --request $request --source (Split-Path $service -Parent)
if ($LASTEXITCODE -ne 0) {
  # 安装命令回滚服务注册后，保留系统事件记录以区分权限、程序路径和进程内部错误。
  $serviceLog = Join-Path $env:ProgramData 'Nexora ERP/logs/host.err.log'
  if (Test-Path $serviceLog) { Get-Content $serviceLog -Tail 80 | Write-Host }
  Get-WinEvent -FilterHashtable @{ LogName = 'System'; ProviderName = 'Service Control Manager'; StartTime = $serviceStartedAt } -ErrorAction SilentlyContinue |
    Select-Object -First 8 TimeCreated, Id, Message | Format-List | Out-String | Write-Host
  throw 'Windows 系统服务安装失败。'
}
try {
  $running = $false
  for ($attempt = 0; $attempt -lt 60; $attempt++) {
    $status = (& $service status | ConvertFrom-Json)
    if ($status.running) { $running = $true; break }
    Start-Sleep -Milliseconds 250
  }
  if (-not $running) {
    # 进程可能已退出；先保留状态、服务自身日志和系统事件，再报告检查失败。
    & sc.exe queryex NexoraERPHost
    $serviceLog = Join-Path $env:ProgramData 'Nexora ERP/logs/host.err.log'
    if (Test-Path $serviceLog) { Get-Content $serviceLog -Tail 80 | Write-Host }
    Get-WinEvent -FilterHashtable @{ LogName = 'Application'; StartTime = $serviceStartedAt } -ErrorAction SilentlyContinue |
      Select-Object -First 8 TimeCreated, Id, ProviderName, Message | Format-List | Out-String | Write-Host
    throw 'SCM 没有保持固定主机运行。'
  }
  # SCM 状态只能证明进程仍在；还要从打包后的系统服务实际读取 HTTPS 接口。
  Assert-ServiceHealthy
  # 只在 CI 临时实例创建测试账号与供应商，后续每次服务重启都经 HTTPS 核对资料。
  $adminPassword = 'CiSmoke-' + [Guid]::NewGuid().ToString('N')
  $setupBody = @{ username = 'ci_admin'; password = $adminPassword } | ConvertTo-Json -Compress
  Invoke-RestMethod 'https://127.0.0.1:18762/api/v1/setup/admin' -Method Post `
    -ContentType 'application/json' -Body $setupBody -SkipCertificateCheck | Out-Null
  $loginBody = @{ username = 'ci_admin'; password = $adminPassword } | ConvertTo-Json -Compress
  $login = Invoke-RestMethod 'https://127.0.0.1:18762/api/v1/auth/login' -Method Post `
    -ContentType 'application/json' -Body $loginBody -SkipCertificateCheck
  # 新实例先完成管理员设置，再写入业务资料；指定时区同时验证打包时区数据可用。
  $numberingBody = @{
    style = 'english'; timezone_mode = 'specified'; timezone = 'America/New_York'; version = 0
  } | ConvertTo-Json -Compress
  Invoke-RestMethod 'https://127.0.0.1:18762/api/v1/system/document-numbering' -Method Put `
    -ContentType 'application/json' -Body $numberingBody -Headers @{
      Authorization = "Bearer $($login.token)"
    } -SkipCertificateCheck | Out-Null
  $supplierBody = @{ name = 'CI 验收供应商' } | ConvertTo-Json -Compress
  $supplier = Invoke-RestMethod 'https://127.0.0.1:18762/api/v1/suppliers' -Method Post `
    -ContentType 'application/json' -Body $supplierBody -Headers @{
      Authorization = "Bearer $($login.token)"
    } -SkipCertificateCheck
  Assert-TestSupplier -Port 18762 -Password $adminPassword -SupplierId $supplier.id
  $certificate = Join-Path $serviceData 'server.crt'
  $originalCertificate = (Get-FileHash $certificate -Algorithm SHA256).Hash
  $beforeCrash = Get-CimInstance Win32_Service -Filter "Name='NexoraERPHost'"
  if (-not $beforeCrash -or $beforeCrash.State -ne 'Running' -or $beforeCrash.ProcessId -le 0) {
    throw '无法取得运行中的 Windows 服务进程，不能验证异常恢复。'
  }
  # 强制结束服务进程，必须由 SCM 的故障恢复策略拉起新进程；手动 start 不能替代这项检查。
  Stop-Process -Id $beforeCrash.ProcessId -Force
  $recovered = $false
  for ($attempt = 0; $attempt -lt 480; $attempt++) {
    $afterCrash = Get-CimInstance Win32_Service -Filter "Name='NexoraERPHost'" -ErrorAction SilentlyContinue
    if ($afterCrash -and $afterCrash.State -eq 'Running' -and $afterCrash.ProcessId -gt 0 -and
        $afterCrash.ProcessId -ne $beforeCrash.ProcessId) {
      $recovered = $true
      break
    }
    Start-Sleep -Milliseconds 250
  }
  if (-not $recovered) {
    & sc.exe queryex NexoraERPHost
    & sc.exe qfailure NexoraERPHost
    throw 'Windows 服务进程异常退出后，SCM 未在 120 秒内启动新进程。'
  }
  Assert-ServiceHealthy
  Assert-TestSupplier -Port 18762 -Password $adminPassword -SupplierId $supplier.id
  if ((Get-FileHash $certificate -Algorithm SHA256).Hash -ne $originalCertificate) {
    throw 'Windows 服务异常恢复后证书发生变化。'
  }
  & $service stop
  if ($LASTEXITCODE -ne 0) { throw 'Windows 系统服务停止失败。' }
  & $service start
  if ($LASTEXITCODE -ne 0) { throw 'Windows 系统服务重新启动失败。' }
  # 重新启动后再次确认数据库和 HTTPS 可用，而不是只相信 sc.exe 的退出码。
  Assert-ServiceHealthy
  Assert-TestSupplier -Port 18762 -Password $adminPassword -SupplierId $supplier.id
  # 用同一安装包演练升级和恢复，确认备份含原证书且新版程序能重新接管服务。
  & $service upgrade --source (Split-Path $service -Parent)
  if ($LASTEXITCODE -ne 0) { throw 'Windows 系统服务升级失败。' }
  Assert-ServiceHealthy
  Assert-TestSupplier -Port 18762 -Password $adminPassword -SupplierId $supplier.id
  if ((Get-FileHash $certificate -Algorithm SHA256).Hash -ne $originalCertificate) {
    throw 'Windows 升级后服务端证书发生变化。'
  }
  $backupDir = Join-Path $env:ProgramData 'Nexora ERP/backups'
  $archive = Get-ChildItem $backupDir -Filter 'upgrade-*.nexora-backup' |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
  if (-not $archive) { throw 'Windows 系统服务升级没有生成成组备份。' }
  $restoredDir = Join-Path $env:RUNNER_TEMP 'nexora-service-restored'
  & $service restore --archive $archive.FullName --data-dir $restoredDir
  if ($LASTEXITCODE -ne 0) { throw 'Windows 成组备份恢复失败。' }
  if ((Get-FileHash (Join-Path $restoredDir 'server.crt') -Algorithm SHA256).Hash -ne $originalCertificate) {
    throw 'Windows 恢复后的服务端证书发生变化。'
  }
  # 恢复目录必须能作为独立实例启动并读取原业务资料；文件存在本身不足以证明可恢复。
  & $service stop
  if ($LASTEXITCODE -ne 0) { throw '恢复实例启动前无法停止原 Windows 服务。' }
  $restoredProcess = Start-Process -FilePath $service -ArgumentList @(
    '--data-dir', "`"$restoredDir`"", '--name', '"CI 恢复服务"', '--port', '18763'
  ) -PassThru -WindowStyle Hidden
  try {
    Assert-ServiceHealthy -Port 18763
    Assert-TestSupplier -Port 18763 -Password $adminPassword -SupplierId $supplier.id
  } finally {
    if (-not $restoredProcess.HasExited) { Stop-Process -Id $restoredProcess.Id -Force }
  }
} finally {
  # 服务已自行退出时不再执行 stop，保留最初的失败信息。
  if ((Get-Service -Name NexoraERPHost -ErrorAction SilentlyContinue).Status -eq 'Running') { & $service stop }
}

# 桌面程序也必须实际渲染首次进入页，不能只检查可执行文件存在。
$env:NEXORA_USER_DATA_DIR = Join-Path $env:RUNNER_TEMP 'nexora-desktop-smoke'
$desktopProcess = Start-Process -FilePath $desktop -ArgumentList '--remote-debugging-port=18752' -PassThru
try {
  node scripts/smoke-desktop.mjs http://127.0.0.1:18752
  if ($LASTEXITCODE -ne 0) { throw '桌面首次进入页检查失败。' }
  node scripts/smoke-desktop-close.mjs http://127.0.0.1:18752
  if ($LASTEXITCODE -ne 0) { throw 'Windows 桌面窗口关闭检查失败。' }
  Start-Sleep -Seconds 2
  $desktopProcess.Refresh()
  if ($desktopProcess.HasExited) { throw '关闭窗口后 Windows 托盘进程意外退出。' }
} finally {
  if (-not $desktopProcess.HasExited) { Stop-Process -Id $desktopProcess.Id -Force }
}
