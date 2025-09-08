import queue
import re
import sys
import time
import threading
from typing import Optional

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

    def listen_once(self, timeout_sec: float = 15.0) -> str:
        """
        1回の発話を認識して確定テキストを返す。
        single_utterance=True のストリーミングを使い、終話で自動終了。
        """
        deadline = time.time() + float(timeout_sec)

        with MicrophoneStream(self.rate, self.chunk) as stream:
            audio_generator = stream.generator()
            requests = (
                speech.StreamingRecognizeRequest(audio_content=content)
                for content in audio_generator
            )
            responses = self._client.streaming_recognize(self._streaming_config, requests)

            num_chars_printed = 0
            final_text = ""
            for response in responses:
                if time.time() > deadline:
                    break
                if not response.results:
                    continue
                result = response.results[0]
                if not result.alternatives:
                    continue
                transcript = result.alternatives[0].transcript

                if not result.is_final:
                    if self.debug:
                        overwrite_chars = " " * (num_chars_printed - len(transcript))
                        sys.stdout.write(transcript + overwrite_chars + "\r")
                        sys.stdout.flush()
                        num_chars_printed = len(transcript)
                    continue

                # final
                if self.debug:
                    overwrite_chars = " " * (num_chars_printed - len(transcript))
                    print(transcript + overwrite_chars)
                final_text = transcript.strip()
                break

        return final_text


if __name__ == "__main__":
    stt = GoogleSpeechToText(debug=True)
    stt.warm_up()
    print("--- 発話してください ---")
    text = stt.listen_once()
    print("確定:", text)