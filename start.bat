@echo off
chcp 65001 >nul 2>&1
title AIArticle - Frontend + Backend
python "%~dp0start_all.py"
if %errorlevel% neq 0 pause
