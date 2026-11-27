@echo off
rem Run from source without building an exe.
if not exist .venv ( py -3 -m venv .venv & call .venv\Scripts\activate.bat & pip install -r requirements.txt ) else ( call .venv\Scripts\activate.bat )
python run_txbridge.py %*
