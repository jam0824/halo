# halo.py
import json
import threading
import time
import re
from typing import Optional, TYPE_CHECKING, Union

from llm import LLM
from voicevox import VoiceVoxTTS
from wav_player import WavPlayer
from stt_azure import AzureSpeechToText
from stt_google import GoogleSpeechToText
from vad import VAD
from command_selector import CommandSelector
from corr_gate import CorrelationGate

if TYPE_CHECKING:
    from function_led import LEDBlinker
    from function_motor import Motor


class HaloApp:
    def __init__(self) -> None:
        self.config = self.load_config()
        self.system_content_template = self.load_system_prompt()

        self.owner_name: str = self.config["owner_name"]
        self.your_name: str = self.config["your_name"]
        self.stt_type: str = self.config["stt"]
        self.llm_model: str = self.config["llm"]
        self.tts_config: dict = self.config["voiceVoxTTS"]
        self.change_name: dict = self.config["change_text"]
        self.isfiller: bool = self.config.get("use_filler", False)
        self.use_led: bool = self.config["led"]["use_led"]
        self.led_pin: int = self.config["led"]["led_pin"]
        self.use_motor: bool = self.config["motor"]["use_motor"]
        self.pan_pin: int = self.config["motor"]["pan_pin"]
        self.tilt_pin: int = self.config["motor"]["tilt_pin"]
        self.interrupt_word: str = self.config["interrupt_word"]
        self.interrupt_word_pattern = re.compile(self.interrupt_word)
        self.command_selector = CommandSelector()
        self.llm = LLM()
        self.stt = self.load_stt(self.stt_type)

        self.led: Optional["LEDBlinker"] = None
        if self.use_led:
            try:
                from function_led import LEDBlinker  # 遅延インポート
                self.led = LEDBlinker(self.led_pin)
            except Exception as e:
                print(f"LED機能を無効化します: {e}")
                self.use_led = False
                self.led = None

        self.motor: Optional["Motor"] = None
        if self.use_motor:
            try:
                from function_motor import Motor
                self.motor = Motor(self.pan_pin, self.tilt_pin)
            except Exception as e:
                print(f"モーター機能を無効化します: {e}")
                self.use_motor = False
                self.motor = None

        self.tts = VoiceVoxTTS(
            base_url=self.tts_config["base_url"],
            speaker=self.tts_config["speaker"],
            max_len=self.tts_config["max_len"],
            queue_size=self.tts_config["queue_size"],
        )
        self.tts.set_params(
            speedScale=self.tts_config["speedScale"],
            pitchScale=self.tts_config["pitchScale"],
            intonationScale=self.tts_config["intonationScale"],
        )

        if self.isfiller:
            self.player = WavPlayer()
            self.player.preload_dir("./filler")
        else:
            self.player = None

        # プリウォーム
        try:
            self.stt.warm_up()
        except Exception as e:
            print(f"STT warm_up でエラー: {e}")

        self.system_content = self.replace_placeholders(
            self.system_content_template, self.owner_name, self.your_name
        )
        
        self.is_my_stt_turn = False    # 自分のSTTのターンかどうか
        print(self.system_content)

    # ----------------- ライフサイクル -----------------
    def run(self) -> None:
        history = ""
        try:
            loop_count = 0
            while True:
                loop_count += 1
                print(f"\n=== ループ {loop_count} 開始 ===")

                try:
                    stt_start_time = time.perf_counter()
                    self.is_my_stt_turn = True
                    user_text = self.exec_stt(self.stt)
                    self.is_my_stt_turn = False
                    stt_end_time = time.perf_counter()
                    print(f"[STT latency] {stt_end_time - stt_start_time:.1f} ms")
                except KeyboardInterrupt:
                    print("\n\n音声認識中に中断されました。")
                    break
                if not user_text:
                    print("音声が認識されませんでした。もう一度話してください")
                    continue

                user_text = self.apply_text_changes(user_text, self.change_name)
                history = self.make_history(history, self.owner_name, user_text)

                if self.is_ferewell(user_text):
                    break

                self.say_filler()
                self.command_selector.select(user_text)

                print("LLMで応答を生成中...")
                llm_start_time = time.perf_counter()
                try:
                    response = self.llm.generate_text(self.llm_model, user_text, self.system_content, history)
                    response = self.get_halo_response(response)
                    history = self.make_history(history, self.your_name, response)
                except Exception as e:
                    print(f"LLMでエラーが発生しました: {e}")
                    continue
                llm_end_time = time.perf_counter()
                print(f"[LLM latency] {llm_end_time - llm_start_time:.1f} ms")

                self.move_pan_kyoro_kyoro(2, 1)
                self.move_tilt_kyoro_kyoro(2)
                is_vad = self.config["vad"]["use_vad"]
                self.exec_tts_with_live_stt(response)
                """
                if is_vad:
                    self.exec_tts_with_vad(response)
                else:
                    self.exec_tts_no_vad(response)
                """

                print(f"=== ループ {loop_count} 完了 ===")

        except KeyboardInterrupt:
            print("\n\n会話を終了します。")
            with self._suppress_ex():
                self.tts.stop()
        except Exception as e:
            print(f"\nエラーが発生しました: {e}")
            import traceback
            traceback.print_exc()
            with self._suppress_ex():
                self.tts.stop()
        finally:
            with self._suppress_ex():
                self.stt.close()
            with self._suppress_ex():
                if self.use_motor and self.motor:
                    self.motor.clean_up()

    # ----------------- 補助メソッド -----------------
    @staticmethod
    def load_system_prompt(system_prompt_path: str = "system_prompt.md") -> str:
        with open(system_prompt_path, 'r', encoding='utf-8') as file:
            system_prompt = file.read()
        return system_prompt

    @staticmethod
    def load_config(config_path: str = "config.json") -> dict:
        try:
            with open(config_path, 'r', encoding='utf-8') as file:
                config = json.load(file)
            return config
        except FileNotFoundError:
            print(f"設定ファイル {config_path} が見つかりません。デフォルト設定を使用します。")
            return HaloApp.get_default_config()
        except json.JSONDecodeError as e:
            print(f"設定ファイルの読み込みエラー: {e}。デフォルト設定を使用します。")
            return HaloApp.get_default_config()

    @staticmethod
    def get_default_config() -> dict:
        return {
            "owner_name": "まつ",
            "your_name": "ハロ",
            "change_text": {"春": "ハロ"},
            "llm": "gpt-4o-mini",
            "voiceVoxTTS": {
                "base_url": "http://127.0.0.1:50021",
                "speaker": 89,
                "max_len": 80,
                "queue_size": 4,
                "speedScale": 1.0,
                "pitchScale": 0.0,
                "intonationScale": 1.0,
            },
            "led": {"use_led": True, "led_pin": 17},
            "motor": {"use_motor": True, "pan_pin": 4, "tilt_pin": 17},
            "vad": {
                "use_vad": True,
                "samplereate": 16000,
                "frame_duration_ms": 20,
                "min_consecutive_speech_frames": 12,
                "corr_threshold": 0.60,
                "max_lag_ms": 95,
            },
        }

    @staticmethod
    def load_stt(stt_type: str) -> Union[AzureSpeechToText, GoogleSpeechToText]:
        if stt_type == "azure":
            return AzureSpeechToText()
        elif stt_type == "google":
            return GoogleSpeechToText()
        else:
            raise ValueError(f"Invalid STT type: {stt_type}")

    @staticmethod
    def replace_placeholders(text: str, owner_name: str, your_name: str) -> str:
        text = text.replace("{owner_name}", owner_name)
        text = text.replace("{your_name}", your_name)
        return text

    @staticmethod
    def replace_dont_need_word(text: str, your_name: str) -> str:
        text = text.replace(f"{your_name}:", "")
        text = text.replace(f"{your_name}：", "")
        return text

    @staticmethod
    def apply_text_changes(text: str, change_text_config: dict) -> str:
        if not change_text_config:
            return text
        result = text
        for key, value in change_text_config.items():
            if key in result:
                result = result.replace(key, value)
        return result

    @staticmethod
    def _suppress_ex():
        class _Ctx:
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc, tb):
                return True
        return _Ctx()

    # ----------------- 会話ロジック -----------------
    def exec_stt(self, stt: Union[AzureSpeechToText, GoogleSpeechToText]) -> str:
        print("--- 音声入力待ち ---")
        try:
            user_text = stt.listen_once()
            return user_text
        except KeyboardInterrupt:
            print("\n音声認識を中断しました。")
            raise

    def is_ferewell(self, user_text: str) -> bool:
        if not self.check_end_command(user_text):
            return False
        farewell = "バイバイ！"
        print(f"{self.your_name}: {farewell}")
        try:
            self.tts.speak(farewell, self.led, self.use_led, self.motor, self.use_motor, corr_gate=None)
        except Exception as e:
            print(f"TTSでエラーが発生しました: {e}")
        return True

    @staticmethod
    def check_end_command(user_text: str) -> bool:
        return any(k in user_text for k in ("終了", "バイバイ", "さようなら"))

    def make_history(self, history: str, name: str, message: str) -> str:
        line_text = f"{name}: {message}"
        history += line_text + "\n"
        print(line_text)
        return history

    def move_pan_kyoro_kyoro(self, speed: float = 1, count: int = 1):
        if self.use_motor and self.motor:
            self.motor.pan_kyoro_kyoro(80, 100, speed, count)

    def move_tilt_kyoro_kyoro(self, count: int = 1):
        if self.use_motor and self.motor:
            self.motor.motor_kuchipaku()

    def say_filler(self):
        if self.isfiller:
            if self.use_led and self.led:
                self.led.start_blink()
            self.move_tilt_kyoro_kyoro(2)
            self.move_pan_kyoro_kyoro(1, 2)
            if self.player:
                self.player.random_play(block=False)
            print("filler再生中")

    def exec_tts_with_vad(self, text: str):
        print(f"exec_tts_with_vad: {text}")
        cfg = self.config["vad"]
        corr_gate = CorrelationGate(
            sample_rate=cfg["samplereate"],
            frame_ms=cfg["frame_duration_ms"],
            buffer_sec=1.0,
            corr_threshold=cfg["corr_threshold"],
            max_lag_ms=cfg["max_lag_ms"],
        )
        stop_event = threading.Event()
        def _vad_watcher():
            VAD_FINISH_COUNT = 3
            detect_count = 0
            while not stop_event.is_set() and detect_count < VAD_FINISH_COUNT:
                ok = VAD.listen_until_voice_webrtc(
                    aggressiveness=3,
                    samplerate=cfg["samplereate"],
                    frame_duration_ms=cfg["frame_duration_ms"],
                    device=None,
                    timeout_seconds=None,
                    min_consecutive_speech_frames=cfg["min_consecutive_speech_frames"],
                    corr_gate=corr_gate,
                    stop_event=stop_event,
                )
                if stop_event.is_set():
                    break
                if ok:
                    print(f"割り込み : VADで音声が検出されました。{detect_count}")
                    detect_count += 1
            if detect_count >= VAD_FINISH_COUNT:
                print(f"割り込み : 音声を{VAD_FINISH_COUNT}回検知したため停止します。")
                self.tts.stop()

        watcher = threading.Thread(target=_vad_watcher, daemon=True)
        watcher.start()
        try:
            self.tts.speak(text, self.led, self.use_led, self.motor, self.use_motor, corr_gate=corr_gate)
        except KeyboardInterrupt:
            self.tts.stop()
            print("\n読み上げを中断しました。")
        except Exception as e:
            print(f"TTSでエラーが発生しました: {e}")
        finally:
            stop_event.set()
            watcher.join(timeout=1.0)
    
    def exec_tts_no_vad(self, text: str):
        self.tts.speak(text, self.led, self.use_led, self.motor, self.use_motor, corr_gate=None)

    def exec_tts_with_live_stt(self, text: str, interrupt_word: str = "待"):
        """
        音声合成中に同時に音声認識（中間結果を取得）。
        中間結果に interrupt_word が含まれたら TTS を停止する。
        （Azure Speech の連続認識を利用）
        """
        # Azure以外のSTTの場合はフォールバック
        if not hasattr(self.stt, "recognizer"):
            print("live STTはAzureのみ対応のためフォールバックします。")
            return self.exec_tts_no_vad(text)

        # 相関ゲート（TTS由来の音を抑制）
        cfg = self.config["vad"]
        corr_gate = CorrelationGate(
            sample_rate=cfg["samplereate"],
            frame_ms=cfg["frame_duration_ms"],
            buffer_sec=1.0,
            corr_threshold=cfg["corr_threshold"],
            max_lag_ms=cfg["max_lag_ms"],
        )

        recognizing_cb = None
        recognized_cb = None
        canceled_cb = None
        session_started_cb = None
        session_stopped_cb = None

        try:
            # 連続認識のイベントハンドラ登録（中間結果で割り込み）
            def on_recognizing(evt):
                if self.is_my_stt_turn:
                    return
                try:
                    txt = evt.result.text or ""
                    if txt:
                        print("tts中間:", txt)
                    if self.interrupt_word_pattern.match(txt):
                        print(f"tts中間結果に『{self.interrupt_word}』を検出")
                        self.tts.stop()
                except Exception:
                    pass

            def on_recognized(evt):
                pass  # 確定はログのみでも良い

            def on_canceled(evt):
                print("STTキャンセル:", getattr(evt, "reason", None))

            def on_session_started(evt):
                print("=== 連続認識開始 ===")

            def on_session_stopped(evt):
                print("=== 連続認識終了 ===")

            rec = self.stt.recognizer
            recognizing_cb = rec.recognizing.connect(on_recognizing)
            recognized_cb = rec.recognized.connect(on_recognized)
            canceled_cb = rec.canceled.connect(on_canceled)
            session_started_cb = rec.session_started.connect(on_session_started)
            session_stopped_cb = rec.session_stopped.connect(on_session_stopped)

            # 接続開始 → 連続認識開始
            if hasattr(self.stt, "connection") and self.stt.connection is not None:
                with self._suppress_ex():
                    self.stt.connection.open(True)
            rec.start_continuous_recognition_async().get()

            # TTS 実行
            self.tts.speak(text, self.led, self.use_led, self.motor, self.use_motor, corr_gate=corr_gate)

        except KeyboardInterrupt:
            self.tts.stop()
            print("\n読み上げを中断しました。")
        except Exception as e:
            print(f"TTS/Live STTでエラーが発生しました: {e}")
        finally:
            # 認識を止め、ハンドラ解除
            with self._suppress_ex():
                rec = getattr(self.stt, "recognizer", None)
                if rec is not None:
                    try:
                        rec.stop_continuous_recognition_async().get()
                    except Exception:
                        pass
                    try:
                        rec.recognizing.disconnect(recognizing_cb) if recognizing_cb else None
                        rec.recognized.disconnect(recognized_cb) if recognized_cb else None
                        rec.canceled.disconnect(canceled_cb) if canceled_cb else None
                        rec.session_started.disconnect(session_started_cb) if session_started_cb else None
                        rec.session_stopped.disconnect(session_stopped_cb) if session_stopped_cb else None
                    except Exception:
                        pass

    def get_halo_response(self, text: str) -> str:
        print(f"text: {text}")
        response_json = json.loads(text)
        response = self.replace_dont_need_word(response_json['message'], self.your_name)

        command = response_json['command']
        if command:
            for key, value in command.items():
                # 利用側の実装に合わせてここでディスパッチ
                try:
                    self.command_selector.exec_command(key, value)  # 型があればそちらに合わせる
                except AttributeError:
                    self.command_selector.select(str(value))
        return response


if __name__ == "__main__":
    app = HaloApp()
    app.run()
