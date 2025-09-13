import sys
import os
import time
import threading
import wave
from typing import Optional, List, Dict, Union
import random

import pyaudio


class WavPlayer:
    def __init__(self, output_device_index: Optional[int] = None, frames_per_buffer: int = 1024):
        self._pa: Optional[pyaudio.PyAudio] = None
        self._stream: Optional[pyaudio.Stream] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._closed = False

        self._output_device_index: Optional[int] = output_device_index
        self._frames_per_buffer = int(frames_per_buffer)

        # 事前読み込みキャッシュ: key -> {data, channels, sample_width, rate, num_frames}
        self._preloaded: Dict[str, Dict] = {}
        self._list_keys: List[str] = []

        # 現在の出力ストリームのフォーマット
        self._current_channels: Optional[int] = None
        self._current_sample_width: Optional[int] = None
        self._current_rate: Optional[int] = None

        self._ensure_pyaudio()

    # ---- lifecycle ----
    def close(self):
        if self._closed:
            return
        try:
            self.stop()
        except Exception:
            pass
        try:
            if self._stream is not None:
                try:
                    if self._stream.is_active():
                        self._stream.stop_stream()
                except Exception:
                    pass
                try:
                    self._stream.close()
                except Exception:
                    pass
        finally:
            self._stream = None
            if self._pa is not None:
                try:
                    self._pa.terminate()
                except Exception:
                    pass
                self._pa = None
            self._closed = True

    # ---- devices ----
    def list_output_devices(self) -> List[Dict]:
        self._ensure_pyaudio()
        devices: List[Dict] = []
        try:
            count = self._pa.get_device_count()
        except Exception:
            return devices
        for i in range(count):
            try:
                info = self._pa.get_device_info_by_index(i)
            except Exception:
                continue
            if int(info.get("maxOutputChannels", 0)) > 0:
                devices.append(info)
        return devices

    def set_output_device(self, device_index: int) -> None:
        self._output_device_index = int(device_index)

    # ---- play ----
    def play(self, wav_path_or_index: Union[str, int], block: bool = True, start_frame: int = 0) -> None:
        """
        WAV を再生する。block=False でバックグラウンド再生。stop() で中断可能。
        start_frame で先頭からのフレーム位置を指定可能。
        wav_path_or_index が int の場合は事前読み込みしたリストのインデックスで再生。
        """
        # インデックス再生（事前読み込み済みが必要）
        if isinstance(wav_path_or_index, int):
            idx = int(wav_path_or_index)
            if idx < 0 or idx >= len(self._list_keys):
                raise IndexError("preload 済みリストの範囲外です")
            key = self._list_keys[idx]
            return self.play_preloaded(key=key, block=block, start_frame=start_frame)

        wav_path = wav_path_or_index
        self.stop()  # 既存再生があれば止める
        self._stop_event.clear()

        wf = wave.open(wav_path, 'rb')
        channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        rate = wf.getframerate()
        total_frames = wf.getnframes()
        if start_frame > 0:
            try:
                wf.setpos(min(start_frame, total_frames))
            except Exception:
                pass

        self._ensure_output_format(channels=channels, sample_width=sample_width, rate=rate)

        def _run():
            try:
                while not self._stop_event.is_set():
                    data = wf.readframes(self._frames_per_buffer)
                    if not data:
                        break
                    try:
                        self._stream.write(data)
                    except Exception:
                        break
            finally:
                try:
                    wf.close()
                except Exception:
                    pass
                try:
                    if self._stream is not None and self._stream.is_active():
                        self._stream.stop_stream()
                except Exception:
                    pass

        if block:
            _run()
        else:
            self._thread = threading.Thread(target=_run, daemon=True)
            self._thread.start()

    def play_and_wait(self, wav_path: str) -> None:
        self.play(wav_path, block=True)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.5)
        self._thread = None

    def is_playing(self) -> bool:
        if self._thread is None:
            return False
        return self._thread.is_alive()

    # ---- preload / play from memory ----
    def preload(self, list_paths: List[str], list_keys: Optional[List[str]] = None) -> Dict[str, bool]:
        """
        WAVを事前に読み込み、メモリに保持する。戻り値は key -> 成否。
        list_keys を省略時は各ファイルのベース名を key にする。
        """
        results: Dict[str, bool] = {}
        if list_keys is not None and len(list_keys) != len(list_paths):
            raise ValueError("list_keys の長さは list_paths と一致させてください")

        for idx, path in enumerate(list_paths):
            key = list_keys[idx] if list_keys is not None else self._basename_no_ext(path)
            try:
                wf = wave.open(path, 'rb')
                channels = wf.getnchannels()
                sample_width = wf.getsampwidth()
                rate = wf.getframerate()
                num_frames = wf.getnframes()
                data = wf.readframes(num_frames)
                wf.close()

                self._preloaded[key] = {
                    'data': data,
                    'channels': channels,
                    'sample_width': sample_width,
                    'rate': rate,
                    'num_frames': num_frames,
                }
                if key not in self._list_keys:
                    self._list_keys.append(key)
                results[key] = True
            except Exception:
                results[key] = False
        return results

    def get_preloaded_keys(self) -> List[str]:
        return list(self._list_keys)

    def play_preloaded(self, key: str, block: bool = True, start_frame: int = 0) -> None:
        """
        preload 済みのキーを低遅延で再生する。
        """
        if key not in self._preloaded:
            raise KeyError(f"key '{key}' は事前読み込みされていません")

        self.stop()
        self._stop_event.clear()

        entry = self._preloaded[key]
        data: bytes = entry['data']
        channels: int = entry['channels']
        sample_width: int = entry['sample_width']
        rate: int = entry['rate']
        num_frames: int = entry['num_frames']

        if start_frame > 0 and start_frame < num_frames:
            frame_size = channels * sample_width
            start_byte = start_frame * frame_size
            data = data[start_byte:]

        self._ensure_output_format(channels=channels, sample_width=sample_width, rate=rate)

        def _run_mem():
            try:
                frame_size = channels * sample_width
                chunk_bytes = self._frames_per_buffer * frame_size
                pos = 0
                n = len(data)
                while not self._stop_event.is_set() and pos < n:
                    end = min(pos + chunk_bytes, n)
                    try:
                        self._stream.write(data[pos:end])
                    except Exception:
                        break
                    pos = end
            finally:
                try:
                    if self._stream is not None and self._stream.is_active():
                        self._stream.stop_stream()
                except Exception:
                    pass

        if block:
            _run_mem()
        else:
            self._thread = threading.Thread(target=_run_mem, daemon=True)
            self._thread.start()

    def random_play(self, block: bool = True, start_frame: int = 0) -> str:
        """
        事前読み込み済みリストからランダムに1つ再生する。戻り値は再生したキー。
        """
        if not self._list_keys:
            raise RuntimeError("preload が未実行、または読み込み済みデータがありません")
        key = random.choice(self._list_keys)
        self.play_preloaded(key=key, block=block, start_frame=start_frame)
        return key

    def preload_dir(self, dir_path: str, recursive: bool = False) -> Dict[str, bool]:
        """
        指定ディレクトリ配下の .wav を事前読み込みする。戻り値は key -> 成否。
        - recursive=True でサブディレクトリも走査
        - キーはベース名。重複時は "name_2", "name_3" と連番付与
        """
        if not os.path.isdir(dir_path):
            raise NotADirectoryError(dir_path)

        def _is_wav(p: str) -> bool:
            lower = p.lower()
            return lower.endswith('.wav')

        listPaths: List[str] = []
        if recursive:
            for root, _dirs, files in os.walk(dir_path):
                for fn in files:
                    if _is_wav(fn):
                        listPaths.append(os.path.join(root, fn))
        else:
            try:
                for fn in os.listdir(dir_path):
                    p = os.path.join(dir_path, fn)
                    if os.path.isfile(p) and _is_wav(fn):
                        listPaths.append(p)
            except FileNotFoundError:
                raise

        listPaths.sort()
        if not listPaths:
            return {}

        # 重複ベース名をユニーク化
        seen: Dict[str, int] = {}
        listKeys: List[str] = []
        for p in listPaths:
            base = self._basename_no_ext(p)
            if base in seen:
                seen[base] += 1
                key = f"{base}_{seen[base]}"
            else:
                seen[base] = 1
                key = base
            listKeys.append(key)

        return self.preload(listPaths, list_keys=listKeys)

    # ---- internals ----
    def _ensure_pyaudio(self):
        if self._pa is None:
            self._pa = pyaudio.PyAudio()

    def _ensure_output_format(self, channels: int, sample_width: int, rate: int) -> None:
        if (
            self._stream is not None and
            self._current_channels == channels and
            self._current_sample_width == sample_width and
            self._current_rate == rate
        ):
            # 既存ストリームを再利用
            try:
                if not self._stream.is_active():
                    self._stream.start_stream()
            except Exception:
                pass
            return
        self._open_stream(channels=channels, sample_width=sample_width, rate=rate)

    def _open_stream(self, channels: int, sample_width: int, rate: int) -> None:
        self._ensure_pyaudio()
        fmt = self._pa.get_format_from_width(sample_width)
        # 既存ストリームを閉じる
        if self._stream is not None:
            try:
                if self._stream.is_active():
                    self._stream.stop_stream()
            except Exception:
                pass
            try:
                self._stream.close()
            except Exception:
                pass
            self._stream = None

        self._stream = self._pa.open(
            format=fmt,
            channels=channels,
            rate=rate,
            output=True,
            output_device_index=self._output_device_index,
            frames_per_buffer=self._frames_per_buffer,
        )
        self._current_channels = channels
        self._current_sample_width = sample_width
        self._current_rate = rate

    def _basename_no_ext(self, path: str) -> str:
        # 遅延importを避けるために標準操作だけでベース名を取り出す
        # Windows/Unix混在パスにもある程度対応
        sep_idx = max(path.rfind('/'), path.rfind('\\'))
        base = path[sep_idx + 1:] if sep_idx >= 0 else path
        dot = base.rfind('.')
        return base[:dot] if dot > 0 else base


if __name__ == "__main__":
    # 簡単な手動テスト: python wav_player.py path/to/file.wav
    player = WavPlayer()
    result = player.preload_dir("./filler")
    print(result)
    try:
        player.random_play(block=True)
    finally:
        player.close()


