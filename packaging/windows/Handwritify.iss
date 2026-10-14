[Setup]
AppName=Handwritify
AppVerName=Handwritify 1.0.0
DefaultGroupName=Handwritify
DefaultDirName={localappdata}\Handwritify
OutputBaseFilename=Handwritify
OutputDir=..\..\dist\installer
Compression=9
PrivilegesRequired=lowest

[Files]
Source: "..\..\dist\Handwritify\Handwritify.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\dist\Handwritify\_internal\*"; DestDir: "{app}\_internal"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#TesseractSetup}"; DestDir: "{tmp}"; DestName: "tesseract-setup.exe"

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
  TesseractPath: String;
  InstallerParams: String;
begin
  if CurStep = ssPostInstall then
  begin
    TesseractPath := ExpandConstant('{app}\_internal\Tesseract-OCR\tesseract.exe');
    InstallerParams :=
      '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /DIR="' +
      ExpandConstant('{app}\_internal\Tesseract-OCR') + '"';

    if not Exec(
      ExpandConstant('{tmp}\tesseract-setup.exe'),
      InstallerParams,
      '',
      SW_HIDE,
      ewWaitUntilTerminated,
      ResultCode
    ) then
      RaiseException('Could not start the Tesseract OCR installer.');

    if ResultCode <> 0 then
      RaiseException(Format('The Tesseract OCR installer failed with exit code %d.', [ResultCode]));

    if not FileExists(TesseractPath) then
      RaiseException('Tesseract OCR was not installed. Please run setup again.');
  end;
end;

[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal\Tesseract-OCR"
