# corr_gate.py
import numpy as np
from collections import deque
import threading

class CorrelationGate:
    """
    TTSの再生PCM（far-end）をためておき、マイクのフレーム（near-end）と
    正規化相関の最大値を簡易に評価するユーティリティ。
    - publish_farend(int16配列) で参照を追加
    - is_tts_like(frame_int16) で「TTSっぽいか？」を返す（Trueなら捨てる）
    """
    def __init__(self, sample_rate=16000, frame_ms=20, buffer_sec=2.0,
                 corr_threshold=0.40, max_lag_ms=60):
        self.sr = sample_rate
        self.frame = int(sample_rate * frame_ms / 1000)
        self.maxlen = int(sample_rate * buffer_sec)
        self.buf = deque(maxlen=self.maxlen)  # int16
        self.lock = threading.Lock()
        self.th = corr_threshold
        self.max_lag = int(sample_rate * max_lag_ms / 1000)

    def publish_farend(self, pcm_int16: np.ndarray):
        if pcm_int16 is None or len(pcm_int16) == 0:
            return
        if pcm_int16.ndim > 1:
            pcm_int16 = pcm_int16.reshape(-1)
        with self.lock:
            self.buf.extend(pcm_int16.tolist())

    def _normalized_dot(self, a: np.ndarray, b: np.ndarray) -> float:
        # 平均除去 → 正規化内積（-1..1）
        a = a.astype(np.float32)
        b = b.astype(np.float32)
        a -= a.mean()
        b -= b.mean()
        na = np.linalg.norm(a)
        nb = np.linalg.norm(b)
        if na == 0 or nb == 0:
            return 0.0
        return float(np.dot(a, b) / (na * nb))

    def is_tts_like(self, frame_int16: np.ndarray) -> bool:
        """TrueならTTS由来と判断して無視してよい"""
        if frame_int16 is None or len(frame_int16) == 0:
            return False
        with self.lock:
            ref = np.array(self.buf, dtype=np.int16)
        L = len(frame_int16)
        if len(ref) < L:
            return False

        # 末尾のLサンプルを中心に、±max_lagの範囲で簡易ラグ探索（ステップ=10ms/2）
        step = max(1, self.frame // 2)
        start = max(0, len(ref) - L - self.max_lag)
        end = len(ref) - L + self.max_lag + 1
        if start >= end:
            start = max(0, len(ref) - L)
            end = len(ref) - L + 1

        x = frame_int16.astype(np.int16)
        best = 0.0
        for s in range(start, end, step):
            seg = ref[s:s+L]
            if len(seg) != L:
                continue
            r = self._normalized_dot(x, seg)
            if r > best:
                best = r
                if best >= self.th:
                    return True
        return False
