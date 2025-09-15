start "" D:\download\tools\VOICEVOX\vv-engine\run.exe --host 0.0.0.0 --port 50021
cd /d D:\codes\halo
start npx -y @playwright/mcp@latest --host 0.0.0.0 --port 8931
start ngrok http --domain=prevalid-unacrimoniously-leigh.ngrok-free.app 8931
cd /d D:\codes\halo\server
start python -m uvicorn server:app --host 0.0.0.0 --port 50022
