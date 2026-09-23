@REM To be used with a scheduler, run weekly, to generate and email reports.

@echo off
echo Starting weekly report emailing...
cd "C:\Users\Admin\Code\new_rota\rota-scrape"
@REM START /B "C:\Python38\pythonw.exe" "C:\Users\Admin\Code\new_rota\rota-scrape\email_other_reports.pyw"
poetry run python email_other_reports.py
echo Run complete.
timeout /t 3