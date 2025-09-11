import queue
import re
import sys
import time
import threading
from typing import Optional, Callable, Iterator, Tuple

from google.cloud import speech

import pyaudio

# Audio recording parameters
RATE = 16000
CHUNK = int(RATE / 10)  # 100ms


class MicrophoneStream:
    """Opens a recording stream as a generator yielding the audio chunks."""

    # PyAudio を共有し、再生成を避ける
    _shared_audio_interface: Optional[pyaudio.PyAudio] = None
    _shared_lock = threading.Lock()

    @classmethod
    def _get_shared_interface(cls) -> pyaudio.PyAudio:
        with cls._shared_lock:
            if cls._shared_audio_interface is None:
                cls._shared_audio_interface = pyaudio.PyAudio()
            return cls._shared_audio_interface

    @classmethod
    def terminate_shared(cls) -> None:
        with cls._shared_lock:
            if cls._shared_audio_interface is not None:
                try:
                    cls._shared_audio_interface.terminate()
                except Exception:
                    pass
                cls._shared_audio_interface = None

    def __init__(self: object, rate: int = RATE, chunk: int = CHUNK) -> None:
        """The audio -- and generator -- is guaranteed to be on the main thread."""
        self._rate = rate
        self._chunk = chunk

        # Create a thread-safe buffer of audio data
        self._buff = queue.Queue()
        self.closed = True

    def __enter__(self: object) -> object:
        # 共有PyAudioインスタンスを使用
        self._audio_interface = self._get_shared_interface()
        self._audio_stream = self._audio_interface.open(
            format=pyaudio.paInt16,
            # The API currently only supports 1-channel (mono) audio
            # https://goo.gl/z757pE
            channels=1,
            rate=self._rate,
            input=True,
            frames_per_buffer=self._chunk,
            # Run the audio stream asynchronously to fill the buffer object.
            # This is necessary so that the input device's buffer doesn't
            # overflow while the calling thread makes network requests, etc.
            stream_callback=self._fill_buffer,
        )

        self.closed = False

        return self

    def __exit__(
        self: object,
        type: object,
        value: object,
        traceback: object,
    ) -> None:
        """Closes the stream, regardless of whether the connection was lost or not."""
        self._audio_stream.stop_stream()
        self._audio_stream.close()
        self.closed = True
        # Signal the generator to terminate so that the client's
        # streaming_recognize method will not block the process termination.
        self._buff.put(None)
        # 共有インスタンスはここでは終了しない

    def _fill_buffer(
        self: object,
        in_data: object,
        frame_count: int,
        time_info: object,
        status_flags: object,
    ) -> object:
        """Continuously collect data from the audio stream, into the buffer.

        Args:
            in_data: The audio data as a bytes object
            frame_count: The number of frames captured
            time_info: The time information
            status_flags: The status flags

        Returns:
            The audio data as a bytes object
        """
        self._buff.put(in_data)
        return None, pyaudio.paContinue

    def generator(self: object) -> object:
        """Generates audio chunks from the stream of audio data in chunks.

        Args:
            self: The MicrophoneStream object

        Returns:
            A generator that outputs audio chunks.
        """
        while not self.closed:
            # Use a blocking get() to ensure there's at least one chunk of
            # data, and stop iteration if the chunk is None, indicating the
            # end of the audio stream.
            chunk = self._buff.get()
            if chunk is None:
                return
            data = [chunk]

            # Now consume whatever other data's still buffered.
            while True:
                try:
                    chunk = self._buff.get(block=False)
                    if chunk is None:
                        return
                    data.append(chunk)
                except queue.Empty:
                    break

            yield b"".join(data)

class GoogleSpeechToText:
    def __init__(self,
                 language_code: str = "ja-JP",
                 rate: int = RATE,
                 chunk: int = CHUNK,
                 interim_results: bool = True,
                 debug: bool = False) -> None:
        self.language_code = language_code
        self.rate = int(rate)
        self.chunk = int(chunk)
        self.interim_results = bool(interim_results)
        self.debug = bool(debug)
        self._client = speech.SpeechClient()

        self._config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=self.rate,
            language_code=self.language_code,
            enable_word_time_offsets=True,  # 単語ごとのタイムスタンプを有効化
        )
        self._streaming_config = speech.StreamingRecognitionConfig(
            config=self._config,
            interim_results=self.interim_results,
            single_utterance=True,
        )

    def warm_up(self) -> None:
        # ほんの少しだけストリームを開閉してPyAudio/クライアントを暖気
        try:
            with MicrophoneStream(self.rate, self.chunk) as stream:
                time.sleep(0.02)
        except Exception:
            pass

    def close(self) -> None:
        # SpeechClient はGCで解放されるが、マイク資源は明示解放
        try:
            MicrophoneStream.terminate_shared()
        except Exception:
            pass
        return None

    def listen_streaming_iter(
        self,
        *,
        single_utterance: bool = False,
    ) -> Iterator[Tuple[str, bool]]:
        """
        ストリーミングで (text, is_final) を逐次 yield するジェネレータ。

        - single_utterance=True: 1発話で終了
        - single_utterance=False: 連続で待ち受け
        """
        streaming_config = speech.StreamingRecognitionConfig(
            config=self._config,
            interim_results=True,
            single_utterance=bool(single_utterance),
        )

        try:
            while True:
                with MicrophoneStream(self.rate, self.chunk) as stream:
                    audio_generator = stream.generator()
                    requests = (
                        speech.StreamingRecognizeRequest(audio_content=content)
                        for content in audio_generator
                    )
                    responses = self._client.streaming_recognize(streaming_config, requests)

                    for response in responses:
                        if not response.results:
                            continue
                        result = response.results[0]
                        if not result.alternatives:
                            continue
                        transcript = result.alternatives[0].transcript or ""
                        if not transcript:
                            continue
                        if result.is_final:
                            yield (transcript.strip(), True)
                            if single_utterance:
                                return
                            # 次の発話を待つ（外側のwhileで新規ストリーム）
                            break
                        else:
                            yield (transcript, False)
                if single_utterance:
                    break
        except KeyboardInterrupt:
            return
        except Exception as e:
            if self.debug:
                print(f"[listen_streaming_iter] error: {e}")
            return

    def listen_once(self, timeout_sec: float = 15.0) -> str:
        def _dur_to_sec(dur) -> float:
            return (getattr(dur, "seconds", 0) or 0) + (getattr(dur, "nanos", 0) or 0) / 1e9

        def _first_word_start_sec(result) -> float:
            # 最初に非ゼロの start_time を持つ単語を探す。なければ 0 とみなす。
            try:
                words = result.alternatives[0].words
                for w in words:
                    s = _dur_to_sec(getattr(w, "start_time", None) or type("X", (), {"seconds": 0, "nanos": 0})())
                    if s > 0:
                        return s
                return 0.0
            except Exception:
                return 0.0

        deadline = time.time() + float(timeout_sec)

        with MicrophoneStream(self.rate, self.chunk) as stream:
            audio_generator = stream.generator()
            requests = (
                speech.StreamingRecognizeRequest(audio_content=content)
                for content in audio_generator
            )

            # ★ストリーム開始時刻
            t_stream_start = time.time()

            responses = self._client.streaming_recognize(self._streaming_config, requests)

            num_chars_printed = 0
            final_text = ""
            t_first_partial = None

            for response in responses:
                if time.time() > deadline:
                    break
                if not response.results:
                    continue
                result = response.results[0]
                if not result.alternatives:
                    continue

                transcript = result.alternatives[0].transcript or ""

                # ★最初の暫定結果が出たタイミング
                if not result.is_final and transcript and t_first_partial is None:
                    t_first_partial = time.time()

                if not result.is_final:
                    if self.debug:
                        overwrite_chars = " " * (num_chars_printed - len(transcript))
                        sys.stdout.write(transcript + overwrite_chars + "\r")
                        sys.stdout.flush()
                        num_chars_printed = len(transcript)
                    continue

                # --- final ---
                if self.debug:
                    overwrite_chars = " " * (num_chars_printed - len(transcript))
                    print(transcript + overwrite_chars)
                final_text = transcript.strip()

                # ★メトリクス算出
                t_final = time.time()

                # 音声内のタイムスタンプ
                utter_end_sec = _dur_to_sec(getattr(result, "result_end_time", None) or type("X", (), {"seconds": 0, "nanos": 0})())
                speech_start_sec = _first_word_start_sec(result)  # 無音を推定

                # 各種指標
                e2e_final = t_final - t_stream_start  # 1) ストリーム開始→最終結果
                wait_from_speech_start = e2e_final - speech_start_sec  # 2) 発話開始→最終結果（無音除外）
                processing_overhead_final = e2e_final - utter_end_sec  # 3) システム処理（モデル+ネット）推定

                print(f"[METRIC] E2E final (stream start → final)音声認識を開けてから最終結果が返ってくるまでの時間: {e2e_final:.3f} s")
                if t_first_partial is not None:
                    e2e_first = t_first_partial - t_stream_start
                    first_token_from_speech = max(0.0, e2e_first - speech_start_sec)
                    print(f"[METRIC] First partial (stream start → first)ストリーミング開始から 最初の暫定結果が返ってくるまでの時間: {e2e_first:.3f} s")
                    print(f"[METRIC] First partial (speech start → first)実際に喋り始めてから 最初の暫定結果が出るまでの時間。: {first_token_from_speech:.3f} s")

                print(f"[METRIC] Wait from speech start → final / 発話開始から最終確定結果が返るまでの時間: {wait_from_speech_start:.3f} s")
                print(f"[METRIC] Processing overhead (≈ e2e - utterance) / 音声を全部話し終えてから結果が確定するまでにかかった時間: {processing_overhead_final:.3f} s")
                print(f"[DEBUG] result_end_time (utterance end in stream)音声ストリームの開始から数えて、発話が終了した位置: {utter_end_sec:.3f} s")
                print(f"[DEBUG] speech_start_offset (first word start)最初の単語が出現した時刻: {speech_start_sec:.3f} s")

                break

        return final_text



if __name__ == "__main__":
    """
    stt = GoogleSpeechToText(debug=True)
    stt.warm_up()
    print("--- 発話してください ---")
    text = stt.listen_once()
    print("確定:", text)
    """
    stt = GoogleSpeechToText(debug=False)
    print("--- 発話してください ---")
    for text, is_final in stt.listen_streaming_iter(single_utterance=False):
        print("final:" if is_final else "partial:", text)
