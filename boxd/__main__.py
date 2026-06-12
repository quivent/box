import uvicorn

from . import config

if __name__ == "__main__":
    uvicorn.run("boxd.main:app", host=config.HOST, port=config.PORT, log_level="info")
