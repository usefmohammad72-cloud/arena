; installer.iss  — با Inno Setup 6 کامپایل کن
#define MyAppName "سامانه تحلیلی مقاطعه"
#define MyAppShort "STM"
#define MyAppVersion "1.0.0"
#define MyAppExe "STM.exe"

[Setup]
AppId={{8A6B2F1C-9D4E-4B7A-A3F2-STM000000001}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=STM
DefaultDirName={autopf}\{#MyAppShort}
DefaultGroupName={#MyAppShort}
DisableProgramGroupPage=yes
OutputDir=dist_installer
OutputBaseFilename=STM_Setup_v{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExe}

[Languages]
Name: "farsi"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "ساخت آیکون روی دسکتاپ"; GroupDescription: "آیکون:"

[Files]
Source: "dist\STM\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppShort}"; Filename: "{app}\{#MyAppExe}"
Name: "{autodesktop}\{#MyAppShort}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "اجرای سامانه"; Flags: nowait postinstall skipifsilent

; داده‌های کاربر در %LOCALAPPDATA%\STM دست‌نخورده باقی می‌مونه