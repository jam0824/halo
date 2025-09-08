import queue
import sys
import time
import wave
from dataclasses import dataclass

import numpy as np
import sounddevice as sd
import webrtcvad
from faster_whisper import WhisperModel


@dataclass
class Config:
    samplerate: int = 16000      # webrtcvad は 8/16/32/48k のみ対応
    channels: int = 1            # モノラル
    frame_ms: int = 30           # 10/20/30ms のいずれか
    vad_aggressiveness: int = 2  # 0(甘い) - 3(厳しい)
    start_trigger_ms: int = 200  # 連続発話とみなすまで（開始）: 200ms
    end_trigger_ms: int = 500    # 無音が続いたら停止（終了）: 800ms
    max_record_sec: int = 60     # 安全のための上限
    output_wav: str = "capture.wav"
    model_name: str = "tiny"     # Pi なら tiny 推奨（必要なら base へ）
    language: str | None = "ja"  # 自動検出に任せるなら None


def write_wave(path: str, audio_bytes: bytes, cfg: Config):
    with wave.open(path, "wb") as wf:
        wf.setnchannels(cfg.channels)
        wf.setsampwidth(2)  # int16
        wf.setframerate(cfg.samplerate)
        wf.writeframes(audio_bytes)


def main():
    cfg = Config()
    vad = webrtcvad.Vad(cfg.vad_aggressiveness)

    # フレームあたりのサンプル数・バイト数
    samples_per_frame = int(cfg.samplerate * cfg.frame_ms / 1000)  # 16000 * 0.03 = 480
    bytes_per_frame = samples_per_frame * 2  # int16

    q_in = queue.Queue()

    def audio_callback(indata, frames, time_info, status):
        if status:
            # XRuns などの警告は標準エラーへ
            print(status, file=sys.stderr)
        # float32 -> int16 へ変換（クリッピング注意）
        pcm16 = np.clip(indata[:, 0], -1.0, 1.0)
        pcm16 = (pcm16 * 32767.0).astype(np.int16).tobytes()
        # 30ms のフレームに切る（余りは次回に回す）
        audio_buffer = audio_callback.buffer + pcm16
        # フレーム単位でキューへ
        offset = 0
        while offset + bytes_per_frame <= len(audio_buffer):
            q_in.put(audio_buffer[offset: offset + bytes_per_frame])
            offset += bytes_per_frame
        # 余りをバッファに戻す
        audio_callback.buffer = audio_buffer[offset:]

    audio_callback.buffer = b""

    # 録音開始
    print("🎙️ 話し始めてください（無音が続くと自動停止します）...")
    stream = sd.InputStream(
        samplerate=cfg.samplerate,
        channels=cfg.channels,
        dtype="float32",
        blocksize=samples_per_frame,  # 1フレーム単位でコールバック
        callback=audio_callback,
        device=None,  # 既定デバイス。必要なら index や name で指定
    )

    started = False
    voiced_ms = 0
    silence_ms = 0
    collected = []

    t0 = time.time()
    with stream:
        while True:
            try:
                frame = q_in.get(timeout=0.5)
            except queue.Empty:
                # 入力が来ていない。最大録音秒数で打ち切り
                if time.time() - t0 > cfg.max_record_sec:
                    break
                continue

            is_speech = vad.is_speech(frame, cfg.samplerate)

            if is_speech:
                voiced_ms += cfg.frame_ms
                silence_ms = 0
            else:
                silence_ms += cfg.frame_ms

            # 開始判定：一定以上の発話が続いたら「録音開始状態」へ
            if not started and voiced_ms >= cfg.start_trigger_ms:
                started = True
                # 直前に溜めた分も含めて収集開始
                # （簡易化のため、ここではフレーム到着以降だけを保存）
                # より厳密にしたければリングバッファで遡って保存する
            if started:
                collected.append(frame)

            # 終了判定：開始後に無音が一定時間続いたら停止
            if started and silence_ms >= cfg.end_trigger_ms:
                break

            # フォールバック：長すぎる録音は強制停止
            if time.time() - t0 > cfg.max_record_sec:
                break

    if not collected:
        print("音声を検出できませんでした。もう一度お試しください。")
        return

    audio_bytes = b"".join(collected)
    write_wave(cfg.output_wav, audio_bytes, cfg)
    print(f"💾 保存: {cfg.output_wav} ({len(collected)} frames)")

    # すぐに文字起こし
    print("📝 文字起こし中...")
    start_time = time.perf_counter()
    model = WhisperModel(cfg.model_name, device="cpu", compute_type="int8")
    segments, info = model.transcribe(cfg.output_wav, language=cfg.language, beam_size=1)
    print(f"Detected: {info.language} ({info.language_probability:.2f})")
    for seg in segments:
        print(f"[{seg.start:.2f} -> {seg.end:.2f}] {seg.text}")
    end_time = time.perf_counter()
    print(f"[ASR latency] {end_time - start_time:.1f} s")


if __name__ == "__main__":
    main()
