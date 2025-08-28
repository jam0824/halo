import wave
import re
import queue
import threading
from io import BytesIO
from typing import Dict, Optional

import requests
import simpleaudio as sa


class VoiceVoxTTS:
    """
    VOICEVOXエンジンに文単位で合成→できた順に即時再生するTTSクラス。
    - speak(text): 同期。再生完了まで戻らない
    - stop(): 再生・生成を中断
    - set_params(...): 話速/ピッチ/抑揚/音量/無音長/語尾上げなどを動的変更
    """

    _SENT_SPLIT = re.compile(r"(.*?[。！？\?\!]|[^。！？\?\!]+$)")

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:50021",
        speaker: int = 89,
        max_len: int = 80,
        queue_size: int = 4,
        request_timeout_query: int = 15,
        request_timeout_synth: int = 60,
        default_params: Optional[Dict] = None,
    ):
        self.base_url = base_url
        self.speaker = speaker
        self.max_len = max_len
        self.queue_size = queue_size
        self.request_timeout_query = request_timeout_query
        self.request_timeout_synth = request_timeout_synth

        # VOICEVOXのデフォルト調整値
        self.params = {
            "speedScale": 1.0,
            "pitchScale": 0.0,
            "intonationScale": 1.0,
            "volumeScale": 1.0,
            "prePhonemeLength": 0.1,
            "postPhonemeLength": 0.1,
            "enableInterrogativeUpspeak": True,
        }
        if default_params:
            self.params.update(default_params)

        # 実行時制御
        self._stop_event = threading.Event()
        self._play_obj: Optional[sa.PlayObject] = None

    # --------- 公開API ---------
    def set_speaker(self, speaker: int):
        self.speaker = speaker

    def set_params(self, **kwargs):
        """例: set_params(speedScale=1.1, pitchScale=-0.2)"""
        self.params.update(kwargs)

    def speak(self, text: str):
        """
        同期実行：合成＆再生を行い、完了（または stop()）まで戻らない。
        """
        self._stop_event.clear()
        chunks = self._split_into_chunks(text, self.max_len)
        q: "queue.Queue" = queue.Queue(maxsize=self.queue_size)
        STOP = object()

        def producer():
            try:
                for sent in chunks:
                    if self._stop_event.is_set():
                        break
                    q.put(("log", f"gen:{sent}"))
                    query = self._audio_query(sent, self.speaker)
                    # パラメータを上書き
                    query.update(self.params)
                    wav_bytes = self._synth(query, self.speaker)
                    q.put(("wav", wav_bytes))
            finally:
                q.put(STOP)

        def consumer():
            while True:
                item = q.get()
                if item is STOP:
                    break
                tag, payload = item
                if self._stop_event.is_set():
                    break
                if tag == "wav":
                    self._play(payload)
                    # 合成は並行で進むため、ここは再生終了まで待つ
                    if self._play_obj:
                        self._play_obj.wait_done()

            # 停止時の後片付け
            with self._suppress_ex():
                if self._play_obj:
                    self._play_obj.stop()
            self._drain_queue(q)

        t_p = threading.Thread(target=producer, daemon=True)
        t_c = threading.Thread(target=consumer, daemon=True)
        t_p.start()
        t_c.start()
        t_p.join()
        t_c.join()

    def stop(self):
        """進行中の合成・再生を停止（割込み）。"""
        self._stop_event.set()
        with self._suppress_ex():
            if self._play_obj:
                self._play_obj.stop()

    # --------- 内部ユーティリティ ---------
    def _split_into_chunks(self, text: str, max_len: int):
        rough = [s.strip() for s in self._SENT_SPLIT.findall(text) if s.strip()]
        out = []
        for s in rough:
            if len(s) <= max_len:
                out.append(s)
            else:
                parts = re.split(r"(、|，)", s)
                buf = ""
                for p in parts:
                    if p in ("、", "，"):
                        buf += p
                        continue
                    if len(buf) + len(p) > max_len and buf:
                        out.append(buf)
                        buf = p
                    else:
                        buf += p
                if buf:
                    out.append(buf)
        return out

    def _audio_query(self, text: str, speaker: int) -> Dict:
        r = requests.post(
            f"{self.base_url}/audio_query",
            params={"text": text, "speaker": speaker},
            timeout=self.request_timeout_query,
        )
        r.raise_for_status()
        return r.json()

    def _synth(self, query: Dict, speaker: int) -> bytes:
        r = requests.post(
            f"{self.base_url}/synthesis",
            params={"speaker": speaker},
            json=query,
            timeout=self.request_timeout_synth,
        )
        r.raise_for_status()
        return r.content

    def _play(self, wav_bytes: bytes):
        with wave.open(BytesIO(wav_bytes), "rb") as wf:
            wav = sa.WaveObject.from_wave_read(wf)
            print("音声再生中")
        self._play_obj = wav.play()

    @staticmethod
    def _drain_queue(q: "queue.Queue"):
        with VoiceVoxTTS._suppress_ex():
            while not q.empty():
                q.get_nowait()

    @staticmethod
    def _suppress_ex():
        class _Ctx:
            def __enter__(self):  # noqa: D401
                return self
            def __exit__(self, exc_type, exc, tb):
                return True  # すべて無視
        return _Ctx()


# --------- 使い方例 ---------
if __name__ == "__main__":
    tts = VoiceVoxTTS(
        base_url="http://127.0.0.1:50021",
        speaker=89,        # お好みのspeakerに変更
        max_len=80,        # 文の最大長（短いほど初回発話が早い）
        queue_size=4,
    )
    # 読み上げパラメータの調整例（任意）
    tts.set_params(speedScale=1.0, pitchScale=0.0, intonationScale=1.0)

    try:
        tts.speak(
            "これはクラス版のリアルタイム再生デモです。"
            "文ごとに合成し、できた順に再生します。"
            "途中で止めたいときは、stopメソッドを呼び出せます。"
            "疑問文は上がり調子で読み上げますか？"
        )
    except KeyboardInterrupt:
        tts.stop()
