# Windows installation

SHG Series Analyzer v0.1.0 is distributed as an unsigned x64 Windows installer and as a portable ZIP. End users do not need Python, Git, PySide6, NumPy, SciPy, Matplotlib, Pillow, tifffile, or any build tools.

## Standard installation

1. Download `SHG-Series-Analyzer-Setup-0.1.0.exe` and `SHA256SUMS.txt` from the release.
2. Verify the SHA-256 checksum before running the installer.
3. Run the installer and select English or Russian.
4. Optionally enable the desktop shortcut. A Start menu shortcut is always created.
5. Launch **SHG Series Analyzer** from the Start menu.

The application is installed for the current user in `%LOCALAPPDATA%\Programs\SHG Series Analyzer` and does not require administrator rights. Uninstall it from Windows **Installed apps**. The uninstaller removes application files and shortcuts only; analysis results saved elsewhere are not removed.

## Portable installation

1. Download `SHG-Series-Analyzer-Portable-0.1.0.zip` and `SHA256SUMS.txt`.
2. Verify the SHA-256 checksum.
3. Extract the complete archive to a writable folder.
4. Run `SHGSeriesAnalyzer.exe` from the extracted folder.

Do not move the EXE out of its extracted directory: the adjacent runtime files are required.

## Check SHA-256 on Windows

From PowerShell in the download directory:

```powershell
Get-FileHash .\SHG-Series-Analyzer-Setup-0.1.0.exe -Algorithm SHA256
Get-FileHash .\SHG-Series-Analyzer-Portable-0.1.0.zip -Algorithm SHA256
Get-Content .\SHA256SUMS.txt
```

Compare the reported hashes exactly with `SHA256SUMS.txt`.

## Security and scientific status

- Version 0.1.0 is not digitally signed, so Windows SmartScreen may display a warning. Verify the SHA-256 checksum and download only from the project release page.
- The packaged demo resources are synthetic. No real experimental data are included.
- The detector's scientific accuracy requires independent validation. `OK` is an internal structural status, not an accuracy guarantee.

## Developer build

Python commands are for developers only. From the repository root, using an existing `.venv`:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[test,build]"
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\smoke_test_windows.ps1
```

The build uses PyInstaller `--onedir` followed by Inno Setup. Generated `build`, `dist`, and `release` directories are excluded from Git.
