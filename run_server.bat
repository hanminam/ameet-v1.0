REM Run the uvicorn server with the correct directory settings
echo.
echo Starting Uvicorn server...
uvicorn app.main:app --reload --app-dir src

echo.
pause