"""
Playwright を使ってブラウザ操作を行うためのユーティリティ。
結果を返したあともブラウザを閉じないよう、ブラウザをモジュール内で
シングルトンとして起動・保持する。
"""

import asyncio
from typing import Optional

from playwright.async_api import async_playwright, Browser, Playwright, Page

from langchain_openai import ChatOpenAI
from langchain_community.agent_toolkits import PlayWrightBrowserToolkit
from langgraph.prebuilt import create_react_agent


_playwright: Optional[Playwright] = None
_async_browser: Optional[Browser] = None
_keep_alive_page: Optional[Page] = None


async def ensure_browser() -> Browser:
    """ブラウザを起動して保持する。既に起動済みならそれを返す。"""
    global _playwright, _async_browser

    global _keep_alive_page

    if _async_browser is not None:
        try:
            # 接続が生きていればそのまま利用
            _async_browser.is_connected()
            # キープアライブページが閉じられていたら再作成
            if _keep_alive_page is None or _keep_alive_page.is_closed():
                _keep_alive_page = await _async_browser.new_page()
                await _keep_alive_page.goto("about:blank")
            return _async_browser
        except Exception:
            _async_browser = None

    if _playwright is None:
        _playwright = await async_playwright().start()

    _async_browser = await _playwright.chromium.launch(
        headless=False,  # ウィンドウを表示
        channel="chrome",
        args=["--disable-blink-features=AutomationControlled"],
    )
    # ウィンドウを残すためのキープアライブページを1枚開く
    _keep_alive_page = await _async_browser.new_page()
    await _keep_alive_page.goto("about:blank")
    return _async_browser


async def close_browser() -> None:
    """必要に応じて手動でブラウザ/Playwrightを終了するための関数。"""
    global _playwright, _async_browser

    if _async_browser is not None:
        try:
            await _async_browser.close()
        finally:
            _async_browser = None

    if _playwright is not None:
        try:
            await _playwright.stop()
        finally:
            _playwright = None


async def run_message(user_message: str) -> str:
    # 使い捨てではなく、常駐ブラウザを確保
    browser = await ensure_browser()

    # Toolkit を async ブラウザから作成
    toolkit = PlayWrightBrowserToolkit.from_browser(async_browser=browser)
    listTools = toolkit.get_tools()

    # LLM
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

    # Agent（LangGraph, async）
    agent = create_react_agent(model=llm, tools=listTools)

    # 実行（結果返却後もブラウザは閉じない）
    result = await agent.ainvoke({
        "messages": [("user", user_message)]
    })

    return result["messages"][-1].content

async def main():
    # デモ用の既定メッセージで実行
    content = await run_message("グーグルを開いて、ハロを検索して、上位タイトルを5つ教えて")
    print("\n--- 実行結果 ---")
    print(content)
    # デモ用途では、任意のキー入力までブラウザを開いたままにする
    print("\nブラウザを開いたままにしています。何かキーを押すと終了します...")
    try:
        # Windows でも動く簡易待機（標準入力をブロック）
        await asyncio.get_event_loop().run_in_executor(None, input)
    finally:
        await close_browser()

if __name__ == "__main__":
    asyncio.run(main())
