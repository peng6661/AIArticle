@echo off
chcp 65001 >nul 2>&1
title AIArticle Frontend Dev Server
python "%~dp0start_server.py"
