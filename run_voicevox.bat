start "" D:\download\tools\VOICEVOX\vv-engine\run.exe --host 0.0.0.0 --port 50021
cd /d D:\codes\halo\playwright
python -m uvicorn server:app --host 0.0.0.0 --port 50022
