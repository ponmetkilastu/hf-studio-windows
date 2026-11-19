"""Kisayol: gercek API core/local_api.py icinde."""
from core.local_api import app, HOST, PORT
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
