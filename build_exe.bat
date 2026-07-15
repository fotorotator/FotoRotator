@echo off
echo Balim FotoRotator do .exe...
pyinstaller --onefile --windowed --noconfirm --name FotoRotator --icon assets\icon.ico --add-data "assets;assets" --collect-data customtkinter --collect-data pillow_heif --collect-data pytesseract --hidden-import pystray._win32 run.py
if errorlevel 1 goto :eof

echo.
echo Pocitam kontrolny sucet (SHA-256)...
certutil -hashfile dist\FotoRotator.exe SHA256 > dist\_hash_raw.txt
findstr /v /c:"hash" /v /c:"CertUtil" dist\_hash_raw.txt > dist\_hash_clean.txt
for /f "usebackq delims= " %%h in (dist\_hash_clean.txt) do echo %%h > dist\FotoRotator.exe.sha256
del dist\_hash_raw.txt dist\_hash_clean.txt

echo.
echo Hotovo! .exe aj kontrolny sucet su v priecinku dist\
pause
