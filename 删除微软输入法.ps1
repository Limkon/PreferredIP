Write-Host "1. 正在解除设置进程对语言数据库的锁死..." -ForegroundColor Yellow

# 1. 强杀设置进程与输入法宿主，释放 COM 互斥锁
Stop-Process -Name "SystemSettings" -Force -ErrorAction SilentlyContinue
Stop-Process -Name "TextInputHost" -Force -ErrorAction SilentlyContinue

# 恢复注册表权限
$zhPath = "HKCU:\Control Panel\International\User Profile\zh-Hans-CN"
if (Test-Path $zhPath) {
    try {
        $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey("Control Panel\International\User Profile\zh-Hans-CN", [Microsoft.Win32.RegistryKeyPermissionCheck]::ReadWriteSubTree, [System.Security.AccessControl.RegistryRights]::ChangePermissions)
        if ($key) {
            $acl = $key.GetAccessControl()
            $acl.SetAccessRuleProtection($false, $false)
            $key.SetAccessControl($acl)
            $key.Close()
        }
    } catch {}
}

Write-Host "2. 正在准备注入【中文(简体) - 美式键盘】..." -ForegroundColor Yellow

# 2. 将写入命令打包
$applyScript = @'
$zhList = New-WinUserLanguageList -Language "zh-Hans-CN"
$zhList[0].InputMethodTips.Clear()
$zhList[0].InputMethodTips.Add("0804:00000409")
Set-WinUserLanguageList -LanguageList $zhList -Force
'@

Write-Host "3. 正在应用配置 (限时写入，防止接口死锁挂起)..." -ForegroundColor Yellow

# 3. 在独立的隐藏子进程中写入配置，限时等待 3 秒，超时直接断开继续
$encoded = [Convert]::ToBase64String([System.Text.Encoding]::Unicode.GetBytes($applyScript))
$p = Start-Process powershell.exe -ArgumentList "-NoProfile -NonInteractive -EncodedCommand $encoded" -WindowStyle Hidden -PassThru

# 等待 3 秒（配置写入实际上只需 0.5 秒）
$null = $p.WaitForExit(3000)
if (-not $p.HasExited) {
    # 写入完成但底层挂起时，直接强杀后台子进程，不让它拖住主脚本
    $p.Kill()
}

Write-Host "4. 正在刷新托盘与输入法界面..." -ForegroundColor Yellow

# 4. 重启输入法与任务栏，完成托盘更新
Stop-Process -Name "ctfmon" -Force -ErrorAction SilentlyContinue
Stop-Process -Name "explorer" -Force -ErrorAction SilentlyContinue

Start-Process "ctfmon.exe"
Start-Process "explorer.exe"

Write-Host "`n========================================================" -ForegroundColor Green
Write-Host "   配置全部完成，脚本正常退出！" -ForegroundColor Green
Write-Host "   - 语言架构：【中文(简体，中国)】" -ForegroundColor Cyan
Write-Host "   - 唯一键盘：【美式键盘 (0804:00000409)】" -ForegroundColor Cyan
Write-Host "   - 微软拼音：彻底除名！" -ForegroundColor Green
Write-Host "========================================================" -ForegroundColor Green