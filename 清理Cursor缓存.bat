@echo off
setlocal EnableExtensions
chcp 65001 >nul

title 清理 Cursor 缓存

echo.
echo ========================================
echo   Cursor 缓存清理（仅删除缓存类目录）
echo ========================================
echo.
echo 说明：
echo   - 会清理 Chromium/Electron 缓存、编译缓存、日志等
echo   - 不会删除：用户设置、扩展、快捷键、工作区记录
echo.
echo 请先保存工作并完全退出 Cursor，否则部分目录可能被占用而无法删除。
echo.
pause

set "ERR=0"

call :TryRemove "%APPDATA%\Cursor\Cache"
call :TryRemove "%APPDATA%\Cursor\CachedData"
call :TryRemove "%APPDATA%\Cursor\CachedExtensions"
call :TryRemove "%APPDATA%\Cursor\CachedExtensionVSIXs"
call :TryRemove "%APPDATA%\Cursor\Code Cache"
call :TryRemove "%APPDATA%\Cursor\GPUCache"
call :TryRemove "%APPDATA%\Cursor\DawnWebGPUCache"
call :TryRemove "%APPDATA%\Cursor\DawnGraphiteCache"
call :TryRemove "%APPDATA%\Cursor\Service Worker"
call :TryRemove "%APPDATA%\Cursor\Network"
call :TryRemove "%APPDATA%\Cursor\logs"

call :TryRemove "%LOCALAPPDATA%\Cursor\Cache"
call :TryRemove "%LOCALAPPDATA%\Cursor\CachedData"
call :TryRemove "%LOCALAPPDATA%\Cursor\Code Cache"
call :TryRemove "%LOCALAPPDATA%\Cursor\GPUCache"
call :TryRemove "%LOCALAPPDATA%\Cursor\DawnWebGPUCache"
call :TryRemove "%LOCALAPPDATA%\Cursor\DawnGraphiteCache"

echo.
if "%ERR%"=="0" (
  echo 清理流程已执行完毕。若仍有目录删不掉，请确认 Cursor 已关闭后重试。
) else (
  echo 部分目录删除失败（可能正在占用）。请关闭 Cursor 后再次运行本脚本。
)
echo.
pause
endlocal
exit /b 0

:TryRemove
set "TARGET=%~1"
if not exist "%TARGET%" (
  echo [跳过] 不存在: %TARGET%
  exit /b 0
)
echo [清理] %TARGET%
rd /s /q "%TARGET%" 2>nul
if exist "%TARGET%" (
  echo [失败] 无法删除（可能被占用）: %TARGET%
  set "ERR=1"
) else (
  echo [完成] %TARGET%
)
exit /b 0
