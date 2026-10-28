; Mouthpiece installer (Inno Setup 6). Build: iscc install\windows\mouthpiece.iss  (or install/build-windows.sh
; on Linux, through Wine). Installs per user (no admin), copies the app, then runs setup.ps1 to fetch
; Python, the PyTorch build for the GPU and the voice model (several GB, so they aren't bundled).

#define AppName "Mouthpiece"
#define AppVersion "1.0.0"
#define Root "..\.."

[Setup]
AppId={{A2A1C89B-B757-4F95-AA66-0AA8E8557FDD}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Dude, We Late
AppComments=your voice, typed.
DefaultDirName={localappdata}\Programs\Mouthpiece
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#Root}\dist
OutputBaseFilename=Mouthpiece-Setup-{#AppVersion}
SetupIconFile={#Root}\brand\icon\mouthpiece.ico
UninstallDisplayIcon={app}\mouthpiece.ico
UninstallDisplayName={#AppName}
WizardStyle=modern
WizardImageFile=wizard-1.bmp,wizard-2.bmp
WizardSmallImageFile=wizard-small-1.bmp,wizard-small-2.bmp
Compression=lzma2/max
SolidCompression=yes
CloseApplications=no

[Languages]
Name: "pt"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
pt.Desktop=Criar um atalho na Área de Trabalho
en.Desktop=Create a desktop shortcut
pt.Setup=Baixando o Python, o PyTorch e o modelo de voz (alguns GB). Acompanhe na janela que abriu; pode levar vários minutos.
en.Setup=Downloading Python, PyTorch and the voice model (a few GB). Follow along in the window that opened; this can take several minutes.
pt.SetupFailed=A instalação dos componentes falhou. Veja o arquivo de log:%n%1%n%nVocê pode tentar de novo depois rodando setup.ps1 na pasta do app.
en.SetupFailed=Installing the components failed. See the log:%n%1%n%nYou can retry later by running setup.ps1 in the app folder.
pt.Open=Abrir o Mouthpiece
en.Open=Open Mouthpiece

[Tasks]
Name: "desktop"; Description: "{cm:Desktop}"

[Files]
Source: "{#Root}\server.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Root}\server_model.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Root}\audio.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Root}\cli.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Root}\launcher.pyw"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Root}\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Root}\pronuncia.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Root}\static\*"; DestDir: "{app}\static"; Flags: ignoreversion recursesubdirs
Source: "{#Root}\brand\icon\mouthpiece.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "setup.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "uninstall.ps1"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Mouthpiece"; Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: """{app}\launcher.pyw"""; WorkingDir: "{app}"; IconFilename: "{app}\mouthpiece.ico"; Comment: "your voice, typed."
Name: "{autodesktop}\Mouthpiece"; Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: """{app}\launcher.pyw"""; WorkingDir: "{app}"; IconFilename: "{app}\mouthpiece.ico"; Tasks: desktop

[Run]
Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: """{app}\launcher.pyw"""; WorkingDir: "{app}"; Description: "{cm:Open}"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\uninstall.ps1"""; Flags: runhidden waituntilterminated; RunOnceId: "StopAndUnpath"

[UninstallDelete]
; Only what setup.ps1 created inside the app folder. User data in %APPDATA%\Mouthpiece stays.
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\bin"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: files; Name: "{app}\setup.log"

[Code]
// Runs setup.ps1 in a visible console (so the long download shows progress) and stops with a clear
// message if it fails, instead of leaving shortcuts that point at a missing Python.
procedure CurStepChanged(CurStep: TSetupStep);
var
  Code: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    WizardForm.StatusLabel.Caption := CustomMessage('Setup');
    if not Exec('powershell.exe', '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\setup.ps1') + '"',
                ExpandConstant('{app}'), SW_SHOW, ewWaitUntilTerminated, Code) or (Code <> 0) then
    begin
      MsgBox(FmtMessage(CustomMessage('SetupFailed'), [ExpandConstant('{app}\setup.log')]), mbError, MB_OK);
      Abort;
    end;
  end;
end;
