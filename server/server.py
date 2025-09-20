import asyncio
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from pathlib import Path
from fastapi.responses import JSONResponse


app = FastAPI(title="Halo Server")


class RunRequest(BaseModel):
    message: str


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse(content={"status": "ok"}, media_type="application/json; charset=utf-8")


# ヘルパー: 指定日のダイアリーファイルを読み込む（ファイルオープン処理を分離）
async def read_diary_content(date_str: str) -> str:
    base_dir = Path(__file__).resolve().parent.parent
    file_path = base_dir / "fake_memory/diary" / f"{date_str}_diary.txt"
    if not file_path.exists():
        raise FileNotFoundError(f"Diary file not found: {file_path}")
    # 同期ファイルI/Oをスレッドに逃がして非同期対応
    return await asyncio.to_thread(file_path.read_text, encoding="utf-8")


# エンドポイント: 文字列パラメータ（例: "20250920"）で指定し、内容を返す
@app.get("/diary/{date_str}")
async def get_diary(date_str: str) -> JSONResponse:
    try:
        content = await read_diary_content(date_str)
        return JSONResponse(content={"date": date_str, "content": content}, media_type="application/json; charset=utf-8")
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=50022)


