import sounddevice as sd
import time
from typing import Optional
import webrtcvad

class VAD:
    @staticmethod
    def listen_until_voice_webrtc(
        aggressiveness: int = 2,
        samplerate: int = 16000,
        frame_duration_ms: int = 30,
        device: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        min_consecutive_speech_frames: int = 3,
    ) -> bool:
        """
        py-webrtcvad を使って、音声(有声)を検出したら True を返す。
        - aggressiveness: 0(ゆるい)〜3(厳しい)
        - samplerate: 8000/16000/32000/48000 のいずれか
        - frame_duration_ms: 10/20/30 のいずれか
        - min_consecutive_speech_frames: 連続で有声になったフレーム数のしきい値
        - timeout_seconds: タイムアウト（秒）。None なら無限待機
        """
        if frame_duration_ms not in (10, 20, 30):
            raise ValueError("frame_duration_ms must be one of 10, 20, 30")
        if samplerate not in (8000, 16000, 32000, 48000):
            raise ValueError("samplerate must be one of 8000, 16000, 32000, 48000")

        vad = webrtcvad.Vad(aggressiveness)
        samples_per_frame = int(samplerate * frame_duration_ms / 1000)
        start_time = time.time()

        try:
            with sd.InputStream(
                samplerate=samplerate,
                channels=1,
                dtype="int16",
                blocksize=samples_per_frame,
                device=device,
            ) as stream:
                consecutive_speech = 0
                while True:
                    np_frames, _ = stream.read(samples_per_frame)
                    if np_frames.size == 0:
                        if timeout_seconds is not None and (time.time() - start_time) >= timeout_seconds:
                            return False
                        continue

                    frame_bytes = np_frames.reshape(-1).tobytes()
                    try:
                        is_speech = vad.is_speech(frame_bytes, samplerate)
                    except Exception:
                        is_speech = False

                    if is_speech:
                        consecutive_speech += 1
                        if consecutive_speech >= min_consecutive_speech_frames:
                            return True
                    else:
                        consecutive_speech = 0

                    if timeout_seconds is not None and (time.time() - start_time) >= timeout_seconds:
                        return False
        except Exception:
            return False

if __name__ == "__main__":
    # py-webrtcvad による検出（3フレーム連続で有声が出たら True）
    is_voice = VAD.listen_until_voice_webrtc(
        aggressiveness=3,
        samplerate=16000,
        frame_duration_ms=20,
        device=None,
        timeout_seconds=None,
        min_consecutive_speech_frames=8,
    )
    print(is_voice)