; KouboAgent API Keys - Inno Setup Installer
; 使用 Inno Setup 6 编译

#define MyAppName "KouboAgent"
#define MyAppVersion "9.0"
#define MyAppPublisher "KouboAgent"
#define MyAppURL "https://github.com/your-repo/kouboagent"
#define MyAppExeName "KouboAgent_api_keys_v9.exe"

[Setup]
AppId={{B4F3C1A2-8D7E-4F6B-9A0C-3E2D1F5A8B7C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer_output
OutputBaseFilename=KouboAgent_v{#MyAppVersion}_Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
AllowNoIcons=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName} {#MyAppVersion}

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："; Flags: checkedonce

[Files]
; 主程序
Source: "KouboAgent_api_keys_v9.exe"; DestDir: "{app}"; Flags: ignoreversion
; 模板配置文件（安装后重命名为 api_config.json）
Source: "api_config.template.json"; DestDir: "{app}"; DestName: "api_config.json"; Flags: ignoreversion onlyifdoesntexist
; 运行时依赖
Source: "_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; 安装完成后可选启动
Filename: "{app}\{#MyAppExeName}"; Description: "运行 {#MyAppName}"; Flags: postinstall nowait skipifsilent unchecked

[UninstallRun]
; 清理运行时生成的 output 目录
Filename: "{cmd}"; Parameters: "/c rmdir /s /q ""{app}\output"""; Flags: runhidden

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  ConfigPath: string;
begin
  if CurStep = ssPostInstall then
  begin
    ConfigPath := ExpandConstant('{app}\api_config.json');
    if not FileExists(ConfigPath) then
    begin
      SaveStringToFile(ConfigPath,
        '{' + #13#10 +
        '  "deepseek_api_key": "YOUR_DEEPSEEK_API_KEY",' + #13#10 +
        '  "minimax_api_key": "YOUR_MINIMAX_API_KEY",' + #13#10 +
        '  "chanjing_app_id": "YOUR_CHANJING_APP_ID",' + #13#10 +
        '  "chanjing_secret_key": "YOUR_CHANJING_SECRET_KEY",' + #13#10 +
        '  "chanjing_person_id": "",' + #13#10 +
        '  "zhiling_key": "YOUR_ZHILING_KEY"' + #13#10 +
        '}' + #13#10, False);
    end;
  end;
end;
