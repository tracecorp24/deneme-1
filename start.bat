@echo off
chcp 65001 > nul
title VFS Global Bulgaristan Vize Botu - Kontrol Paneli
color 0B

echo ======================================================================
echo    VFS GLOBAL BULGARİSTAN VİZE BOTU - YÖNETİM VE TEST PANELİ
echo ======================================================================
echo.
echo [1/3] Python ortamı denetleniyor...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    color 0C
    echo [HATA] Python bulunamadı! Lütfen Python'un kurulu ve PATH'e ekli olduğundan emin olun.
    pause
    exit /b 1
)

echo [2/3] Web sunucusu başlatılıyor (http://localhost:5000)...
start "" http://localhost:5000

echo [3/3] Bot arayüzü aktif! Tarayıcınız açılıyor...
echo.
echo ======================================================================
echo   Arayüz Adresi: http://localhost:5000
echo   Kapatmak için bu pencereyi kapatabilir veya Ctrl+C yapabilirsiniz.
echo ======================================================================
echo.

python web_app.py
pause
