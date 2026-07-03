param(
    [Parameter(Mandatory = $true)]
    [string]$Root
)

$ErrorActionPreference = "SilentlyContinue"

$logDir = Join-Path $Root "logs"
$readyFile = Join-Path $logDir ".gui-ready"
$loadingFile = Join-Path $logDir ".gui-loading"

if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

Remove-Item $readyFile -Force -ErrorAction SilentlyContinue
Set-Content -Path $loadingFile -Value "1" -Encoding ASCII

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$form = New-Object System.Windows.Forms.Form
$form.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::None
$form.StartPosition = [System.Windows.Forms.FormStartPosition]::CenterScreen
$form.Size = New-Object System.Drawing.Size(380, 150)
$form.BackColor = [System.Drawing.Color]::FromArgb(15, 23, 42)
$form.TopMost = $true
$form.ShowInTaskbar = $false

$title = New-Object System.Windows.Forms.Label
$title.Text = "Telegram 购物机器人"
$title.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 13, [System.Drawing.FontStyle]::Bold)
$title.ForeColor = [System.Drawing.Color]::FromArgb(241, 245, 249)
$title.BackColor = $form.BackColor
$title.AutoSize = $true
$title.Location = New-Object System.Drawing.Point(40, 32)
$form.Controls.Add($title)

$status = New-Object System.Windows.Forms.Label
$status.Text = "正在加载控制面板"
$status.Font = New-Object System.Drawing.Font("Microsoft YaHei UI", 10)
$status.ForeColor = [System.Drawing.Color]::FromArgb(148, 163, 184)
$status.BackColor = $form.BackColor
$status.AutoSize = $true
$status.Location = New-Object System.Drawing.Point(40, 68)
$form.Controls.Add($status)

$bar = New-Object System.Windows.Forms.ProgressBar
$bar.Style = "Marquee"
$bar.MarqueeAnimationSpeed = 24
$bar.Size = New-Object System.Drawing.Size(300, 8)
$bar.Location = New-Object System.Drawing.Point(40, 104)
$form.Controls.Add($bar)

$dots = 0
$started = Get-Date
$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 350
$timer.Add_Tick({
    $script:dots = ($script:dots + 1) % 4
    $status.Text = "正在加载控制面板" + ("." * $script:dots)
    if (Test-Path $readyFile) {
        $timer.Stop()
        $form.Close()
        return
    }
    if (((Get-Date) - $started).TotalSeconds -gt 120) {
        $timer.Stop()
        $form.Close()
    }
})
$timer.Start()

[void]$form.ShowDialog()

Remove-Item $loadingFile -Force -ErrorAction SilentlyContinue
Remove-Item $readyFile -Force -ErrorAction SilentlyContinue
