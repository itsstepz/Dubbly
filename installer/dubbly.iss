; Inno Setup script for Dubbly. Keep this file ASCII-only.
#ifndef AppVersion
  #define AppVersion "1.1.0"
#endif
#define AppName "Dubbly"
#define AppExe "Dubbly.exe"

[Setup]
; Fixed ID: a new installer upgrades the previous installation in place
AppId={{F3E1F404-3E08-43FC-B778-55F730AD2A61}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppName}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\installer_out
OutputBaseFilename=Dubbly-Setup
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
; Program Files by default (ASCII path); the dialog also offers a per-user install
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
WizardStyle=modern

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl,messages_ru.isl"
Name: "english"; MessagesFile: "compiler:Default.isl,messages_en.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\Dubbly\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
{ On uninstall: ask whether to delete the downloaded data. Dubbly writes the data folders to
  HKCU\Software\Dubbly\DataDirs (separated by ";"). Only Dubbly's own subfolders and files are
  deleted, never a whole chosen folder, so a folder like F:\ stays safe. }

procedure DeleteDubblyData(Dir: String);
var
  FindRec: TFindRec;
begin
  if Length(Dir) < 4 then
    exit;
  DelTree(Dir + '\models', True, True, True);
  DelTree(Dir + '\bin', True, True, True);
  DelTree(Dir + '\cuda', True, True, True);
  DelTree(Dir + '\voices', True, True, True);
  DelTree(Dir + '\work', True, True, True);
  DelTree(Dir + '\preview', True, True, True);
  DelTree(Dir + '\fonts', True, True, True);
  DeleteFile(Dir + '\settings.json');
  if FindFirst(Dir + '\my_terms_*.txt', FindRec) then
  begin
    try
      repeat
        DeleteFile(Dir + '\' + FindRec.Name);
      until not FindNext(FindRec);
    finally
      FindClose(FindRec);
    end;
  end;
  RemoveDir(Dir);  { only if it is empty now }
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Dirs, D: String;
  P: Integer;
begin
  if CurUninstallStep <> usPostUninstall then
    exit;
  if not RegQueryStringValue(HKCU, 'Software\Dubbly', 'DataDirs', Dirs) then
    exit;
  if UninstallSilent or (Trim(Dirs) = '') then
    exit;
  if MsgBox(CustomMessage('AskDeleteData'), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) <> IDYES then
    exit;
  while Dirs <> '' do
  begin
    P := Pos(';', Dirs);
    if P = 0 then
    begin
      D := Dirs;
      Dirs := '';
    end
    else
    begin
      D := Copy(Dirs, 1, P - 1);
      Delete(Dirs, 1, P);
    end;
    DeleteDubblyData(Trim(D));
  end;
  RegDeleteKeyIncludingSubkeys(HKCU, 'Software\Dubbly');
end;
