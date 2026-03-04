@echo off
chcp 65001 > nul
echo ===================================
echo  DB を GitHub に Push します
echo ===================================

:: 日付取得 (YYYYMMDD形式)
for /f "tokens=1-3 delims=/" %%a in ("%date%") do (
    set Y=%%a
    set M=%%b
    set D=%%c
)
set DATE_STR=%Y%%M%%D%

:: push 実行
git add data/S級DB_slim.xlsx
git diff --cached --quiet
if %errorlevel%==0 (
    echo [変更なし] S級DB_slim.xlsx に更新はありませんでした
    pause
    exit /b
)

git commit -m "DB更新 %DATE_STR%"
git push

if %errorlevel%==0 (
    echo.
    echo ✅ Push 完了！ GitHub Actions が次回実行時から反映されます
) else (
    echo.
    echo ❌ Push 失敗。git の設定やネットワークを確認してください
)
pause
