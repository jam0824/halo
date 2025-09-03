import argparse
import json
import sys
from typing import Dict

import requests


def send_run(message: str, url: str = "http://192.168.1.151:50022/run") -> Dict[str, object]:
    """/run に JSON {message} をPOSTし、結果JSONを返す"""
    response = requests.post(url, json={"message": message}, timeout=120)
    response.raise_for_status()
    return response.json()


def main() -> None:
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
    args = parser.parse_args()

    try:
        data = send_run(args.message, args.url)
        print(json.dumps(data, ensure_ascii=False, indent=2))
    except requests.RequestException as exc:
        print(f"HTTPエラー: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()


