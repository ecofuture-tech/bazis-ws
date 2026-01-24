import os


os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sample.settings')

from bazis.core.app import app
from bazis.contrib.ws.ws import ws_route

app.router.routes.append(ws_route)

if __name__ == "__main__":
    app.uvicorn_start()
