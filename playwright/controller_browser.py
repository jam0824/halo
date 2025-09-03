from concurrent.futures import ThreadPoolExecutor, Future
from typing import Optional, Dict
import atexit

from send_run import SendRunClient


class BrowserController:
    """
    非ブロッキングで /run にメッセージを送るコントローラ。
    内部でスレッド実行し、Future を返す。
    """

    def __init__(self, url: str = "http://192.168.1.151:50022/run", timeout: int = 120, max_workers: int = 2) -> None:
        self.client = SendRunClient(url=url, timeout=timeout)
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="browser-send")
        atexit.register(self.close)

    def send_async(self, message: str) -> Future:
        """非ブロッキングで送信を実行し、Future[Dict] を返す。"""
        return self.executor.submit(self.client.send, message)

    def close(self) -> None:
        try:
            self.client.close()
        except Exception:
            pass
        try:
            self.executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass


if __name__ == "__main__":
    bc = BrowserController()
    fut = bc.send_async("グーグルを開いて、ハロを検索して、上位タイトルを5つ教えて")
    print(fut.result())
