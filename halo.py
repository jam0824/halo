import re
import threading
import time
from typing import Optional, TYPE_CHECKING, Union

from command_selector import CommandSelector
from llm import LLM
from stt_azure import AzureSpeechToText
from stt_google import GoogleSpeechToText
from voicevox import VoiceVoxTTS

from helper.halo_helper import HaloHelper
from helper.filler import Filler
from helper.corr_gate import CorrelationGate
from helper.asr_coherence import ASRCoherenceFilter
from helper.vad import VAD
from helper.similarity import TextSimilarity
from halo_mcp.spotify_refresh import SpotifyRefresh

if TYPE_CHECKING:
    from function_led import LEDBlinker
    from function_motor import Motor

class Halo:
    def __init__(self):
        self.halo_helper = HaloHelper()
        self.config = self.halo_helper.load_config()

        self.owner_name: str = self.config["owner_name"]
        self.your_name: str = self.config["your_name"]
        self.run_timeout_sec: int = self.config["run_timeout_sec"]
        self.stt_type: str = self.config["stt"]
        self.llm_model: str = self.config["llm"]
        self.tts_config: dict = self.config["voiceVoxTTS"]
        self.change_name: dict = self.config["change_text"]
        self.isfiller: bool = self.config["filler"]["use_filler"]
        self.filler_dir: str = self.config["filler"]["filler_dir"]
        self.use_led: bool = self.config["led"]["use_led"]
        self.led_pin: int = self.config["led"]["led_pin"]
        self.use_motor: bool = self.config["motor"]["use_motor"]
        self.pan_pin: int = self.config["motor"]["pan_pin"]
        self.tilt_pin: int = self.config["motor"]["tilt_pin"]
        self.interrupt_word: str = self.config["interrupt_word"]
        self.coherence_threshold: float = self.config["coherence_threshold"]

        self.interrupt_word_pattern = re.compile(self.interrupt_word)
        self.wakeup_word: str = self.config["wakeup_word"]
        self.wakeup_word_pattern = re.compile(self.wakeup_word)
        self.similarity_threshold: float = self.config["similarity_threshold"]
        self.farewell_word: str = self.config["farewell_word"]
        self.farewell_word_pattern = re.compile(self.farewell_word)

        self.command_selector = CommandSelector()
        self.llm = LLM()
        self.stt = self.load_stt(self.stt_type)
        self.asr_coherence_filter = ASRCoherenceFilter()
        self.similarity = TextSimilarity()
        self.filler = Filler(self.isfiller, self.filler_dir)
        self.system_content = self.halo_helper.load_system_prompt_and_replace(self.owner_name, self.your_name)
        print(self.system_content)

        # 相関ゲート（TTS由来の音を抑制）をアプリ全体で共有
        cfg = self.config.get("vad", {})
        self.corr_gate = CorrelationGate(
            sample_rate=cfg.get("samplereate", 16000),
            frame_ms=cfg.get("frame_duration_ms", 20),
            buffer_sec=1.0,
            corr_threshold=cfg.get("corr_threshold", 0.60),
            max_lag_ms=cfg.get("max_lag_ms", 95),
        )

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
        self.spotify_refresh = SpotifyRefresh().refresh()

        # プリウォーム
        try:
            self.stt.warm_up()
            response_text = self.llm.generate_text(self.llm_model, "日本語で会話", self.system_content, "")
            print(response_text)
        except Exception as e:
            print(f"STT warm_up でエラー: {e}")

        # 常時STT運用用の状態
        self.history: str = ""
        self.response: str = ""
        self.command: dict = {}
        # TTSをバックグラウンドで回すためのスレッド管理
        self.tts_thread: Optional[threading.Thread] = None
        self.tts_lock = threading.Lock()
        # STT安定化用カウンタ
        self._stt_fail_count: int = 0

    def is_vad(self, config: dict, min_consecutive_speech_frames: int) -> bool:
        print("VAD detection start")
        is_vad = VAD.listen_until_voice_webrtc(
            aggressiveness=config["vad"]["aggressiveness"],
            samplerate=config["vad"]["samplereate"],
            frame_duration_ms=config["vad"]["frame_duration_ms"],
            min_consecutive_speech_frames=min_consecutive_speech_frames,
            device=None,
            timeout_seconds=None,
            corr_gate=self.corr_gate,
            stop_event=None,
        )
        if is_vad:
            print("VAD detected")
        return is_vad

    def main_loop(self) -> None:
        self.speak_async("起動したのだ")
        self.run()
        time.sleep(1)
        self.speak_async("待機モードに入るのだ")
        while True:
            if not self.is_vad(self.config, 12):
                time.sleep(0.1)
                continue
            first_text = self.stt.listen_once()
            if not self.wakeup_word_pattern.match(first_text):
                print("ウェイクアップキーワードが含まれていません")
                time.sleep(0.1)
                continue
            self.speak_async("おしゃべりするのだ")
            self.run()
            time.sleep(1)
            self.speak_async("待機モードに入るのだ")

    def run(self) -> None:
        print("========== 話しかけてください。Ctrl+Cで終了します。 ==========")
        time_out = time.time() + self.run_timeout_sec

        try:
            while True:
                try:
                    if time.time() >= time_out:
                        print(f"タイムアウト({self.run_timeout_sec}s)により終了します。")
                        break
                    # VADで発話を検出
                    if not self.is_vad(self.config, self.config["vad"]["min_consecutive_speech_frames"]):
                        time.sleep(0.1)
                        continue

                    user_text = self.stt.listen_once()
                    if not user_text or user_text == "":
                        time.sleep(0.1)
                        continue
                    self.history = self.halo_helper.append_history(self.history, self.owner_name, user_text)

                    # 終了ワードのチェック
                    if self.check_farewell(user_text):
                        break
                    # 文章のチェックして、正しいユーザー発話ではない場合はcontinue
                    if self.check_sentence(user_text, self.response):
                        continue
                    # フィラー再生
                    self.say_filler()

                    print("LLMで応答を生成中...")
                    response_text = self.llm.generate_text(self.llm_model, user_text, self.system_content, self.history)
                    self.response, self.command = self.halo_helper.get_halo_response(response_text)
                    self.history = self.halo_helper.append_history(self.history, self.your_name, self.response)
                    # コマンドがあれば実行
                    self.exec_command(self.command)
                    

                    # 応答読み上げは非同期で行う
                    self.speak_async(self.response)
                    time_out = time.time() + self.run_timeout_sec    # タイムアウト時間を更新

                except KeyboardInterrupt:
                    print("\n\n音声認識ループが中断されました")
                    break
        except Exception as e:
            print(f"音声認識ループでエラーが発生しました: {e}")
        finally:
            try:
                self.stop_tts()
                if self.tts_thread and self.tts_thread.is_alive():
                    self.tts_thread.join(timeout=0.5)
            except Exception:
                pass
            try:
                self.stt.close()
            except Exception:
                pass
            try:
                self.stop_led()
                if self.use_led and self.led:
                    self.led.off()
                self.stop_motor()
            except Exception:
                pass

    # ---------- tts control ----------
    def stop_tts(self) -> None:
        try:
            self.tts.stop()
        except Exception:
            pass

    def speak_async(self, text: str) -> None:
        # 進行中があれば停止
        with self.tts_lock:
            self.stop_tts()
            self.stop_led()
            self.stop_motor()
            # 再生停止の完了を待つ（短時間）
            try:
                # まずはスレッドの終了を待機
                if self.tts_thread and self.tts_thread.is_alive():
                    self.tts_thread.join(timeout=1.0)
            except Exception as e:
                print(f"TTSスレッド終了エラー: {e}")
            
            def _run():
                try:
                    self.move_pan_kyoro_kyoro(1, 2)
                    self.tts.speak(text, self.led, self.use_led, self.motor, self.use_motor, corr_gate=self.corr_gate)
                except Exception as e:
                    print(f"TTSエラー: {e}")

            self.tts_thread = threading.Thread(target=_run, daemon=True)
            self.tts_thread.start()
    # ---------- コマンド実行 ----------
    def exec_command(self, command: str) -> str:
        if self.command == "":
            return
        fut = self.command_selector.exec_command(command)
        if fut:
            def _on_done(f):
                try:
                    result = f.result()
                    if result:
                        self.response = result['result']
                        self.history = self.halo_helper.append_history(self.history, self.your_name, self.response)
                        print(f"[command_response] {self.response}")
                        self.speak_async(self.response)
                except Exception as e:
                    print(f"[command_error] {e}")
            fut.add_done_callback(_on_done)

    # ---------- 会話ロジック ----------

    def check_farewell(self, txt: str) -> bool:
        if self.farewell_word_pattern.match(txt):
            farewell = "バイバイ！"
            print(f"{self.your_name}: {farewell}")
            self.tts.speak(farewell, self.led, self.use_led, self.motor, self.use_motor, corr_gate=self.corr_gate)
            return True
        return False

    def check_sentence(self, user_text: str, response: str) -> bool:
        if self.is_similarity_threshold(user_text, response):
            print(f"類似度がしきい値を超えています :txt: {user_text} :response: {response}")
            return True
        if self.is_coherence_threshold(user_text, self.coherence_threshold):
            print(f"破綻がしきい値を超えています :txt: {user_text} :threshold: {self.coherence_threshold}")
            return True
        return False

    def say_filler(self) -> bool:
        if self.filler.say_filler():
            if self.use_led and self.led:
                self.led.start_blink()
            self.move_tilt_kyoro_kyoro(2)
            self.move_pan_kyoro_kyoro(1, 2)
            return True
        return False

    def is_similarity_threshold(self, user_text: str, response: str) -> bool:
        # 類似度（ユーザ確定テキスト vs 応答テキストの一部）
        score = 0.0
        try:
            # print(f"類似度計算 :user_text: {user_text} :response: {self.response}")
            score, best_sub = self.similarity.calc_max_substring_similarity(user_text, self.response)
            print(f"類似度: {score * 100:.1f}%  一致抜粋: {best_sub[:80]}")
        except Exception as e:
            print(f"類似度計算エラー: {e}")
        return score >= self.similarity_threshold

    def is_coherence_threshold(self, txt: str, threshold: float) -> bool:
        # 文章の破綻度
        try:
            is_noisy, score = self.asr_coherence_filter.is_noisy(txt, threshold)
        except Exception as e:
            print(f"破綻度計算エラー: {e}")
            return False
        # 完全に0の時は文中にハテナがあるなど
        if score == 0.0:
            is_noisy = False
        if is_noisy:
            return True
        return False

    # ---------- メカ ----------
    # LED停止
    def stop_led(self):
        if self.use_led and self.led:
            self.led.stop_blink()
        return
    # モーター停止
    def stop_motor(self):
        if self.use_motor and self.motor:
            try:
                self.motor.stop_motion()
            except Exception as e:
                print(f"モーター停止エラー: {e}")
        return
    # pan動作
    def move_pan_kyoro_kyoro(self, speed: float = 1, count: int = 1):
        if self.use_motor and self.motor:
            self.motor.pan_kyoro_kyoro(80, 100, speed, count)
    # tilt動作
    def move_tilt_kyoro_kyoro(self, count: int = 1):
        if self.use_motor and self.motor:
            self.motor.motor_kuchipaku()

    # ---------- STT ----------
    def load_stt(self,stt_type: str) -> Union[AzureSpeechToText, GoogleSpeechToText]:
        if stt_type == "azure":
            return AzureSpeechToText()
        elif stt_type == "google":
            return GoogleSpeechToText()
        else:
            raise ValueError(f"Invalid STT type: {stt_type}")

if __name__ == "__main__":
    halo = Halo()
    halo.main_loop()