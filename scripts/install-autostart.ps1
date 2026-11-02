# Register Amy to start at user login (Windows Scheduled Task).
. "$PSScriptRoot\_env.ps1"
$task = "AmyAssistant"
$run = Join-Path $script:AmyRoot "scripts\run.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -WindowStyle Hidden -File `"$run`""
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName $task -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Host "Registered Scheduled Task '$task' at logon."
Write-Host "Remove with: .\scripts\uninstall-autostart.ps1"
