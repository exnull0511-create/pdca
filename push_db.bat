@echo off
chcp 65001 > nul
echo ===================================
echo  DB を GitHub に Push します
echo ===================================

:: バッチファイルのあるフォルダに移動（どこから起動しても確実に動くよう）
cd /d "%~dp0"

:: 日本語ファイル名の問題を回避するため git の quotepath を無効化
git config core.quotepath false

:: dataフォルダ内のDBファイルをすべてステージング
git add data/S*DB*.xlsx

:: ステージングされたファイルを確認
for /f %%i in ('git diff --cached --name-only') do set STAGED=%%i

if not defined STAGED (
    echo.
    echo [変更なし] DB ファイルに更新はありませんでした
    echo.
    echo ヒント: ファイルを上書き保存したか確認してください
    pause
    exit /b
)

:: 日付取得 (YYYYMMDD形式)
for /f "tokens=2 delims==" %%a in ('wmic os get localdatetime /value') do set DT=%%a
set DATE_STR=%DT:~0,8%

git commit -m "DB更新 %DATE_STR%"
git push

if %errorlevel%==0 (
    echo.
    echo Push 完了！ GitHub Actions が次回実行時から反映されます
) else (
    echo.
    echo Push 失敗。git の設定やネットワークを確認してください
)
pause
