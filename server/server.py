import asyncio
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from langchain_playwright import run_message, close_browser


app = FastAPI(title="LLM Playwright Server")


class RunRequest(BaseModel):
    message: str


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/run")
async def run(req: RunRequest) -> dict:
    try:
        content = await run_message(req.message)
        return {"result": content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/close")
async def close() -> dict:
    try:
        await close_browser()
        return {"status": "closed"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=50022)


