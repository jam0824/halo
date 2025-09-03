import argparse
import json
import sys
from typing import Dict, Optional
from urllib.parse import urlparse, urlunparse

import requests


class SendRunClient:
    """/run エンドポイントに message を送るクライアント。

    他コードからの再利用を想定し、セッション再利用やタイムアウト設定を提供。
    """

    def __init__(self, url: str = "http://192.168.1.151:50022/run", timeout: int = 120, session: Optional[requests.Session] = None) -> None:
        self.url: str = url
        self.timeout: int = timeout
        self.session: requests.Session = session or requests.Session()
        self._last_message: Optional[str] = None

    def send(self, message: str) -> Dict[str, object]:
        """message をPOSTし、結果JSONを返す"""
        self._last_message = message
        print(f"Sending message: {message} to {self.url}")
        response = self.session.post(self.url, json={"message": message}, timeout=self.timeout)
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            # サーバからの詳細なエラー本文を表示
            body = exc.response.text if exc.response is not None else ""
            print(f"サーバエラー本文: {body}", file=sys.stderr)
            raise
        return response.json()

    def close(self) -> Optional[str]:
        """最後に送ったメッセージを表示して返し、セッションを閉じる"""
        if self._last_message is not None:
            print(f"Close時のメッセージ: {self._last_message}")
        try:
            self.session.close()
        except Exception:
            pass
        return self._last_message

    def _build_close_url(self) -> str:
        """self.url から /close エンドポイントURLを生成する"""
        parsed = urlparse(self.url)
        path = parsed.path or "/run"
        if path.endswith("/run"):
            close_path = path[:-4] + "close"
        else:
            base = path.rsplit("/", 1)[0]
            close_path = (base + "/close") if base else "/close"
        return urlunparse((parsed.scheme, parsed.netloc, close_path, "", "", ""))

    def close_remote(self) -> Dict[str, object]:
        """サーバの /close を呼び出し、ステータスJSONを返す"""
        close_url = self._build_close_url()
        print(f"POST {close_url}")
        response = self.session.post(close_url, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    @classmethod
    def from_host_port(
        cls,
        host: str = "127.0.0.1",
        port: int = 50022,
        path: str = "/run",
        scheme: str = "http",
        timeout: int = 120,
        session: Optional[requests.Session] = None,
    ) -> "SendRunClient":
        url = f"{scheme}://{host}:{port}{path}"
        return cls(url=url, timeout=timeout, session=session)


def send_run(message: str, url: str = "http://192.168.1.151:50022/run") -> Dict[str, object]:
    """後方互換のための薄い関数。内部で SendRunClient を使う。"""
    client = SendRunClient(url=url)
    try:
        return client.send(message)
    finally:
        client.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="POST /run に message を送信するクライアント")
    parser.add_argument(
        "-m",
        "--message",
        default="グーグルを開いて、ハロを検索して、上位タイトルを5つ教えて",
        help="送信する message テキスト",
    )
    parser.add_argument(
        "--url",
        default="http://192.168.1.151:50022/run",
        help="エンドポイントURL",
    )
    parser.add_argument(
        "--close",
        action="store_true",
        help="/close を呼んでサーバを終了する",
    )
    args = parser.parse_args()

    try:
        client = SendRunClient(url=args.url)
        if args.close:
            data = client.close_remote()
        else:
            data = client.send(args.message)
        print(json.dumps(data, ensure_ascii=False, indent=2))
    except requests.RequestException as exc:
        print(f"HTTPエラー: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        try:
            client.close()
        except Exception:
            pass


