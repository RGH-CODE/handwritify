# Windows installer build

Install Python dependencies and Inno Setup, then run this from PowerShell
in `handwritify`:

```powershell
python -m pip install -r requirements.txt -r requirements-desktop-build.txt
.\packaging\windows\build-installer.ps1
```

Install Inno Setup from https://jrsoftware.org/isinfo.php. Its command-line
compiler (`ISCC.exe`) must be available on `PATH`.

The script builds the app, downloads the official UB Mannheim Tesseract OCR
Windows installer, and packages both into `dist\installer\Handwritify.exe`.
Internet access is needed while building the installer; the person installing
Handwritify does not need to download Tesseract separately.

During setup, Tesseract is installed silently alongside Handwritify, so it
does not require a separate PATH change.

Before launching the installed app, configure `HANDWRITIFY_USERNAME` and
`HANDWRITIFY_PASSWORD` as Windows environment variables for the account that
will run it. Choose your own values; no default login is shipped.
