"""`python -m insightai` starts the service with the host and port from config.toml."""
import uvicorn

from .config import get_settings

if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run("insightai.main:app", host=settings.host, port=settings.port, log_level="info")
