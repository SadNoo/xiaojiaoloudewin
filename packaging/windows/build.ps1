param(
    [string]$Version = "0.1.0",
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$BuildRoot = Join-Path $Root ".build\windows"
$RuntimeRoot = Join-Path $BuildRoot "runtime"
$BrowserRoot = Join-Path $RuntimeRoot "playwright"
$Venv = Join-Path $BuildRoot "venv"
$Python = Join-Path $Venv "Scripts\python.exe"
$DistApp = Join-Path $Root "dist\xianyuxian"

if (-not [Environment]::Is64BitOperatingSystem) {
    throw "首版客户端仅支持 Windows 10/11 x64。"
}

New-Item -ItemType Directory -Force -Path $BuildRoot, $RuntimeRoot | Out-Null
Set-Content -Path (Join-Path $Root "desktop_client\_generated_build.py") -Value "APP_VERSION = '$Version'" -Encoding UTF8

if (-not (Test-Path $Python)) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        py -3.12 -m venv $Venv
    }
    else {
        python -m venv $Venv
    }
}
& $Python -m pip install --upgrade pip
& $Python -m pip install -r (Join-Path $Root "desktop_client\requirements-windows.txt")

Push-Location (Join-Path $Root "frontend")
try {
    if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) { corepack enable }
    pnpm install --frozen-lockfile
    pnpm build
}
finally {
    Pop-Location
}

$env:PLAYWRIGHT_BROWSERS_PATH = $BrowserRoot
& $Python -m playwright install chromium

$NodeExe = Join-Path $RuntimeRoot "node.exe"
if (-not (Test-Path $NodeExe)) {
    Invoke-WebRequest "https://nodejs.org/dist/v22.23.1/win-x64/node.exe" -OutFile $NodeExe
}

$Redist = Join-Path $PSScriptRoot "redist"
New-Item -ItemType Directory -Force -Path $Redist | Out-Null
$WebViewBootstrapper = Join-Path $Redist "MicrosoftEdgeWebview2Setup.exe"
if (-not (Test-Path $WebViewBootstrapper)) {
    Invoke-WebRequest "https://go.microsoft.com/fwlink/p/?LinkId=2124703" -OutFile $WebViewBootstrapper
}

Push-Location $Root
try {
    & $Python -m PyInstaller --noconfirm --clean (Join-Path $PSScriptRoot "xianyuxian.spec")
}
finally {
    Pop-Location
}

Copy-Item $BrowserRoot (Join-Path $DistApp "playwright") -Recurse -Force
New-Item -ItemType Directory -Force -Path (Join-Path $DistApp "runtime") | Out-Null
Copy-Item $NodeExe (Join-Path $DistApp "runtime\node.exe") -Force

$SelfTest = Start-Process -FilePath (Join-Path $DistApp "xianyuxian.exe") -ArgumentList "--self-test" -Wait -PassThru
if ($SelfTest.ExitCode -ne 0) {
    $Report = Join-Path $env:LOCALAPPDATA "xianyuxian\logs\windows-self-test.json"
    if (Test-Path $Report) { Get-Content $Report }
    throw "Windows 自检失败，退出码 $($SelfTest.ExitCode)"
}

if (-not $SkipInstaller) {
    $Iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
    if (-not (Test-Path $Iscc)) { throw "未找到 Inno Setup 6：$Iscc" }
    $env:XIANYUXIAN_BUILD_VERSION = $Version
    & $Iscc (Join-Path $PSScriptRoot "installer.iss")
}

Write-Host "Windows 客户端构建完成：$DistApp"
