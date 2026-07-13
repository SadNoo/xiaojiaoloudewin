#define AppVersion GetEnv("XIANYUXIAN_BUILD_VERSION")

[Setup]
AppId={{8F6351EF-67D8-45C5-A2D8-7F0F3A62A496}
AppName=xianyuxian 闲鱼超级管家
AppVersion={#AppVersion}
AppPublisher=xianyuxian
AppPublisherURL=https://xianyuxian.dskjahf.xyz
AppSupportURL=https://xianyuxian.dskjahf.xyz
DefaultDirName={localappdata}\Programs\xianyuxian
DefaultGroupName=xianyuxian
OutputDir=..\..\dist\installer
OutputBaseFilename=xianyuxian-setup-{#AppVersion}-x64
Compression=lzma2/ultra64
SolidCompression=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
AppMutex=Local\xianyuxian.desktop.client.v1
UninstallDisplayIcon={app}\xianyuxian.exe
VersionInfoVersion={#AppVersion}
VersionInfoProductName=xianyuxian 闲鱼超级管家

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Files]
Source: "..\..\dist\xianyuxian\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "redist\MicrosoftEdgeWebview2Setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall

[Icons]
Name: "{autoprograms}\xianyuxian 闲鱼超级管家"; Filename: "{app}\xianyuxian.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\xianyuxian 闲鱼超级管家"; Filename: "{app}\xianyuxian.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加选项："; Flags: unchecked

[Run]
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; Parameters: "/silent /install"; StatusMsg: "正在安装 Microsoft Edge WebView2 Runtime..."; Flags: waituntilterminated runhidden; Check: not IsWebView2Installed
Filename: "{app}\xianyuxian.exe"; Description: "启动 xianyuxian 闲鱼超级管家"; Flags: nowait postinstall skipifsilent

[Code]
function IsWebView2Installed: Boolean;
var
  Version: String;
begin
  Result :=
    RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) or
    RegQueryStringValue(HKLM32, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) or
    RegQueryStringValue(HKLM64, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version);
end;
