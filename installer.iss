; ======================================================
;  Chrome Profile Manager - Inno Setup Installer Script
; ======================================================

[Setup]
AppName=ZOEE DARLING
AppVersion=1.0
AppPublisher=ZOEE IT SOLUTIONS
AppPublisherURL=https://yourwebsite.com
AppSupportURL=https://yourwebsite.com/support
AppUpdatesURL=https://yourwebsite.com/updates
DefaultDirName={autopf}\ChromeProfileManager
DefaultGroupName=Chrome Profile Manager
UninstallDisplayIcon={app}\ChromeProfileManager.exe
Compression=lzma
SolidCompression=yes
OutputDir=dist
OutputBaseFilename=ChromeProfileManager_Installer
;SetupIconFile=icon.ico
PrivilegesRequired=lowest

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; === Main Application EXE built by PyInstaller ===
Source: "dist\server.exe"; DestDir: "{app}"; Flags: ignoreversion

; === ChromeDriver (ensure this file exists in the same folder) ===
Source: "dist\chromedriver.exe"; DestDir: "{app}"; Flags: ignoreversion

; === Optional icon or config files ===
;Source: "icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Chrome Profile Manager"; Filename: "{app}\server.exe"
Name: "{autodesktop}\Chrome Profile Manager"; Filename: "{app}\server.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Run]
Filename: "{app}\server.exe"; Description: "Launch Chrome Profile Manager"; Flags: nowait postinstall skipifsilent
