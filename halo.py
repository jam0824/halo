# halo.py
import json
import threading
import time
import re
import queue
from typing import Optional, TYPE_CHECKING, Union
from similarity import TextSimilarity

from llm import LLM
from voicevox import VoiceVoxTTS
from wav_player import WavPlayer
from stt_azure import AzureSpeechToText
from stt_google import GoogleSpeechToText
from command_selector import CommandSelector
from corr_gate import CorrelationGate
from asr_coherence import ASRCoherenceFilter
from vad import VAD

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
        self.wakeup_word: str = self.config["wakeup_word"]
        self.wakeup_word_pattern = re.compile(self.wakeup_word)
        self.similarity_threshold: float = self.config["similarity_threshold"]
        self.coherence_threshold: float = self.config["coherence_threshold"]
        self.command_selector = CommandSelector()
        self.llm = LLM()
        self.stt = self.load_stt(self.stt_type)
        self.asr_coherence_filter = ASRCoherenceFilter()

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

        # フィラー時のボイス
        if self.isfiller:
            self.player = WavPlayer()
            self.player.preload_dir("./filler")
        else:
            self.player = None
        # 割り込み時のボイス
        if self.config["warikomi_voice"]["use_warikomi_voice"]:
            self.warikomi_player = WavPlayer()
            self.warikomi_player.preload_dir(self.config["warikomi_voice"]["warikomi_dir"])
        else:
            self.warikomi_player = None

        # プリウォーム
        try:
            self.stt.warm_up()
        except Exception as e:
            print(f"STT warm_up でエラー: {e}")

        self.system_content = self.replace_placeholders(
            self.system_content_template, self.owner_name, self.your_name
        )
        
        self.is_warikomi = False    # 割り込み中かどうか
        print(self.system_content)

        # 常時STT運用用の状態
        self.history: str = ""
        self.is_running: bool = True
        self.recognized_queue: "queue.Queue[str]" = queue.Queue()
        self.processor_thread: Optional[threading.Thread] = None
        self.similarity = TextSimilarity()

    # ----------------- メインループ -----------------
    def main_loop(self) -> None:
        # 1回のみ実行
        if self.config["one_time_run"]:
            self.run()
            return
        halo_text = "ハロ、起動した"
        self.tts.speak(halo_text, self.led, self.use_led, self.motor, self.use_motor, corr_gate=None)
        # 常時実行
        while True:
            if not self.is_vad():
                time.sleep(0.1)
                continue
            first_text = self.first_stt()
            if not self.wakeup_word_pattern.match(first_text):
                print("keyword not in user_text")
                time.sleep(0.1)
                continue
            halo_text = "ハロ、おしゃべりする！"
            self.tts.speak(halo_text, self.led, self.use_led, self.motor, self.use_motor, corr_gate=None)
            self.run()
            # 実行後のクールダウン
            time.sleep(1)
            halo_text = "ハロ、待機モード"
            self.tts.speak(halo_text, self.led, self.use_led, self.motor, self.use_motor, corr_gate=None)
    def is_vad(self) -> bool:
        print("VAD detection start")
        is_vad = VAD.listen_until_voice_webrtc(
            aggressiveness=3,
            samplerate=16000,
            frame_duration_ms=20,
            min_consecutive_speech_frames=12,
            device=None,
            timeout_seconds=None,
            corr_gate=None,
            stop_event=None,
        )
        if is_vad:
            print("VAD detected")
        return is_vad
    def first_stt(self) -> str:
        print("STT start")
        text = self.exec_stt(self.stt)
        user_text = self.apply_text_changes(text, self.change_name)
        return user_text

    # ----------------- ライフサイクル -----------------
    def run(self) -> None:
        print("=== 常時STTモードを開始します（Ctrl+Cで終了）===")
        # 2周目以降では前回終了時に False になっているため、毎回リセット
        self.is_running = True
        # タイムアウト（秒）。設定があれば使用、なければ120秒。
        run_timeout_sec = float(self.config.get("run_timeout_sec", 120))
        self.run_deadline = time.perf_counter() + run_timeout_sec

        recognizing_cb = None
        recognized_cb = None
        canceled_cb = None
        session_started_cb = None
        session_stopped_cb = None
        rec = None
        self.response = ""

        # 相関ゲート（TTS由来の音を抑制）
        cfg = self.config.get("vad", {})
        corr_gate = CorrelationGate(
            sample_rate=cfg.get("samplereate", 16000),
            frame_ms=cfg.get("frame_duration_ms", 20),
            buffer_sec=1.0,
            corr_threshold=cfg.get("corr_threshold", 0.60),
            max_lag_ms=cfg.get("max_lag_ms", 95),
        )

        def _clear_queue(q: "queue.Queue[str]") -> None:
            try:
                while True:
                    q.get_nowait()
            except Exception:
                pass

        def _processor_loop():
            while self.is_running:
                try:
                    text = self.recognized_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                try:
                    user_text = self.apply_text_changes(text, self.change_name)
                    self.history = self.make_history(self.history, self.owner_name, user_text)

                    if self.check_farewell(user_text):
                        break

                    print("LLMで応答を生成中...")
                    response_text = self.llm.generate_text(self.llm_model, user_text, self.system_content, self.history)
                    self.response = self.get_halo_response(response_text)
                    self.history = self.make_history(self.history, self.your_name, self.response)

                    
                    # 応答読み上げ（割り込みで self.tts.stop() される想定）
                    self.tts.speak(self.response, self.led, self.use_led, self.motor, self.use_motor, corr_gate=corr_gate)

                    # タイムアウト時間を更新
                    self.run_deadline = time.perf_counter() + float(self.config.get("run_timeout_sec", 120))
                    print(f"タイムアウト時間: {self.run_deadline}")

                except KeyboardInterrupt:
                    with self._suppress_ex():
                        self.tts.stop()
                    self.is_running = False
                    break
                except Exception as e:
                    print(f"LLM/TTSでエラーが発生しました: {e}")

        try:
            # 認識イベントの登録（Azureの連続認識がある場合）
            if hasattr(self.stt, "recognizer"):
                #音声認識中のイベントハンドラ
                def on_recognizing(evt):
                    try:
                        txt = getattr(evt.result, "text", "") or ""
                        if txt:
                            print(f"中間: {txt}")
                            check_warikomi(txt)    # 割り込みチェック
                        
                    except Exception:
                        pass
                
                #音声認識確定時のイベントハンドラ
                def on_recognized(evt):
                    try:
                        txt = getattr(evt.result, "text", "") or ""
                        if not txt:
                            return
                        print(f"確定: {txt}")
                        self.is_warikomi = False

                        # ハロが言った話と似ているか(true : 似てる)
                        if is_similarity_threshold(txt, self.response):
                            return
                        # 文章が破綻していないか(true : 破綻)
                        if is_coherence_threshold(txt, self.coherence_threshold):
                            return
                        # 新規の確定が来たら現在のTTSを停止し、最新のもののみ処理
                        with self._suppress_ex():
                            self.tts.stop()
                        stop_led(); stop_motor()
                        # フィラー再生（確定直後に再生開始）
                        self.say_filler(txt)
                        _clear_queue(self.recognized_queue)
                        self.recognized_queue.put(txt)
                    except Exception:
                        pass
                def on_canceled(evt):
                    try:
                        reason = getattr(evt, "reason", None)
                        result = getattr(evt, "result", None)
                        result_reason = getattr(result, "reason", None)
                        error_details = getattr(evt, "error_details", None)
                        cancel_details = None
                        if result is not None and hasattr(result, "cancellation_details"):
                            cd = result.cancellation_details
                            try:
                                cancel_details = f"reason={getattr(cd,'reason',None)} error_details={getattr(cd,'error_details',None)} error_code={getattr(cd,'error_code',None)}"
                            except Exception:
                                cancel_details = str(cd)
                        print(f"STTキャンセル: reason={reason} result_reason={result_reason} error_details={error_details} cancel_details={cancel_details}")
                    except Exception as e:
                        print(f"STTキャンセル: 詳細取得失敗: {e}")
                def on_session_started(evt):
                    print("=== 連続認識開始 ===")
                def on_session_stopped(evt):
                    print("=== 連続認識終了 ===")
                    
                # 割り込みのチェック
                def check_warikomi(txt: str):
                    if self.interrupt_word_pattern.match(txt) and self.tts.is_playing() and not self.is_warikomi:
                        self.is_warikomi = True
                        print(f"tts中間結果に『{self.interrupt_word}』を検出")
                        with self._suppress_ex():
                            self.tts.stop()
                        stop_motor()
                        if getattr(self, "warikomi_player", None):
                            try:
                                self.warikomi_player.random_play(block=False)
                                print("割り込み時のボイス再生中")
                            except Exception:
                                pass
                
                # 確定テキストが前回のハロの発言と似ていた場合ループバックと捉え無視
                def is_similarity_threshold(txt: str, response: str) -> bool:
                    if self.is_similarity_threshold(txt, response):
                        print(f"類似度がしきい値を超えています :txt: {txt} :response: {response}")
                        return True
                    return False
                def is_coherence_threshold(txt: str, threshold: float) -> bool:
                    is_noisy, score = self.asr_coherence_filter.is_noisy(txt, threshold)
                    # 完全に0の時は文中にハテナがあるなど
                    if score == 0.0:
                        is_noisy = False
                    if is_noisy:
                        print(f"破綻がしきい値を超えています :txt: {txt} :threshold: {threshold}")
                        return True
                    return False
                
                # LED停止
                def stop_led():
                    if self.use_led and self.led:
                        with self._suppress_ex():
                            self.led.stop_blink()
                    return
                # モーター停止
                def stop_motor():
                    if self.use_motor and self.motor:
                        with self._suppress_ex():
                            try:
                                self.motor.stop_motion()
                            except Exception:
                                pass
                    

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
            else:
                # フォールバック（中間は出せないため注意）
                print("連続認識はAzureのみ対応。フォールバックで逐次認識します。")
                def _fallback_listener():
                    while self.is_running:
                        try:
                            print("STTフォールバック中...")
                            text = self.exec_stt(self.stt)
                            if self.check_farewell(text):
                                break
                            if text:
                                print(f"確定: {text}")
                                with self._suppress_ex():
                                    self.tts.stop()
                                print("LLMで応答を生成中...")
                                response_text = self.llm.generate_text(self.llm_model, text, self.system_content, self.history)
                                self.response = self.get_halo_response(response_text)
                                self.history = self.make_history(self.history, self.your_name, self.response)
                                # 応答読み上げ（割り込みで self.tts.stop() される想定）
                                self.tts.speak(self.response, self.led, self.use_led, self.motor, self.use_motor, corr_gate=corr_gate)
                        except KeyboardInterrupt:
                            self.is_running = False
                            break
                        except Exception as e:
                            print(f"STTフォールバック中にエラー: {e}")
                            time.sleep(0.2)
                threading.Thread(target=_fallback_listener, daemon=True).start()

            # 応答処理スレッド開始
            self.processor_thread = threading.Thread(target=_processor_loop, daemon=True)
            self.processor_thread.start()

            # メインスレッドは待機（タイムアウト監視）
            while self.is_running:
                if time.perf_counter() >= self.run_deadline:
                    print(f"タイムアウト({run_timeout_sec:.0f}s)により終了します。")
                    self.is_running = False
                    break
                time.sleep(0.2)

        except KeyboardInterrupt:
            print("\n\n会話を終了します。")
        except Exception as e:
            print(f"\nエラーが発生しました: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.is_running = False
            with self._suppress_ex():
                if self.processor_thread is not None:
                    self.processor_thread.join(timeout=1.0)
            # 認識停止とハンドラ解除
            with self._suppress_ex():
                if hasattr(self.stt, "recognizer") and rec is not None:
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
            with self._suppress_ex():
                self.tts.stop()
            with self._suppress_ex():
                self.stt.close()
            with self._suppress_ex():
                if self.use_motor and self.motor:
                    self.motor.clean_up()
                if self.use_led and self.led:
                    # 確実にLEDを停止・消灯・解放
                    self.led.stop_blink(wait=True)
                    self.led.off()
                    try:
                        self.led.cleanup()
                    except Exception:
                        pass

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
    # 終了コマンドチェック
    def check_farewell(self, txt: str) -> bool:
        if self.check_end_command(txt):
            farewell = "バイバイ！"
            print(f"{self.your_name}: {farewell}")
            with self._suppress_ex():
                self.tts.speak(farewell, self.led, self.use_led, self.motor, self.use_motor, corr_gate=None)
            self.is_running = False
            return True
        return False

    def exec_stt(self, stt: Union[AzureSpeechToText, GoogleSpeechToText]) -> str:
        print("--- 音声入力待ち ---")
        try:
            user_text = stt.listen_once()
            return user_text
        except KeyboardInterrupt:
            print("\n音声認識を中断しました。")
            raise

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

    def say_filler(self, user_text: str):
        if "終了" in user_text:
            return
        if self.isfiller:
            if self.use_led and self.led:
                self.led.start_blink()
            self.move_tilt_kyoro_kyoro(2)
            self.move_pan_kyoro_kyoro(1, 2)
            if self.player:
                self.player.random_play(block=False)
            print("filler再生中")

    def is_similarity_threshold(self, user_text: str, response: str) -> bool:
        # 類似度（ユーザ確定テキスト vs 応答テキストの一部）
        score = 0.0
        try:
            # print(f"類似度計算 :user_text: {user_text} :response: {self.response}")
            score, best_sub = self.similarity.calc_max_substring_similarity(user_text, self.response)
            print(f"類似度: {score * 100:.1f}%  一致抜粋: {best_sub[:80]}")
        except Exception:
            pass
        return score >= self.similarity_threshold

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
    app.main_loop()
    #app.run()
