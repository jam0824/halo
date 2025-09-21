import json
import threading
import time
from typing import Optional, TYPE_CHECKING

from stt_google import GoogleSpeechToText
from voicevox import VoiceVoxTTS
from corr_gate import CorrelationGate
from llm import LLM
from command_selector import CommandSelector
from halo_helper import HaloHelper

if TYPE_CHECKING:
    from function_led import LEDBlinker
    from function_motor import Motor


class HaloStreamingGoogle:
    def __init__(self, config_path: str = "config.json") -> None:
        self.halo_helper = HaloHelper()
        self.cfg = self.halo_helper.load_config(config_path)

        tts_cfg = self.cfg["voiceVoxTTS"]
        self.owner_name: str = self.cfg.get("owner_name", "ユーザー")
        self.your_name: str = self.cfg.get("your_name", "ハロ")
        self.llm_model: str = self.cfg.get("llm", "gpt-4o-mini")
        self.change_text_map: dict = self.cfg.get("change_text", {})

        # --- Devices / TTS ---
        self.tts = VoiceVoxTTS(
            base_url=tts_cfg["base_url"],
            speaker=tts_cfg.get("speaker", 89),
            max_len=tts_cfg.get("max_len", 80),
            queue_size=tts_cfg.get("queue_size", 4),
        )
        self.tts.set_params(
            speedScale=tts_cfg.get("speedScale", 1.0),
            pitchScale=tts_cfg.get("pitchScale", 0.0),
            intonationScale=tts_cfg.get("intonationScale", 1.0),
        )

        self.use_led: bool = self.cfg["led"]["use_led"]
        self.led: Optional["LEDBlinker"] = None
        if self.use_led:
            try:
                from function_led import LEDBlinker

                self.led = LEDBlinker(int(self.cfg["led"]["led_pin"]))
            except Exception as e:
                print(f"LED機能を無効化します: {e}")
                self.use_led = False
                self.led = None

        self.use_motor: bool = self.cfg["motor"]["use_motor"]
        self.motor: Optional["Motor"] = None
        if self.use_motor:
            try:
                from function_motor import Motor

                self.motor = Motor(int(self.cfg["motor"]["pan_pin"]), int(self.cfg["motor"]["tilt_pin"]))
            except Exception as e:
                print(f"モーター機能を無効化します: {e}")
                self.use_motor = False
                self.motor = None

        # 相関ゲート（TTSエコー抑制用参照）
        vad_cfg = self.cfg.get("vad", {})
        self.corr_gate = CorrelationGate(
            sample_rate=vad_cfg.get("samplereate", 16000),
            frame_ms=vad_cfg.get("frame_duration_ms", 20),
            buffer_sec=1.0,
            corr_threshold=vad_cfg.get("corr_threshold", 0.60),
            max_lag_ms=vad_cfg.get("max_lag_ms", 95),
        )

        # --- Google STT / LLM / 会話状態 ---
        # デバッグを有効化してエラー要因を可視化
        self.stt = GoogleSpeechToText(debug=False)
        # マイク/クライアントの簡易ウォームアップ
        try:
            self.stt.warm_up()
        except Exception:
            pass
        self.llm = LLM()
        self.history: str = ""
        self.system_content = self.halo_helper.load_system_prompt_and_replace(self.owner_name, self.your_name)
        self.command_selector = CommandSelector()

        # TTSをバックグラウンドで回すためのスレッド管理
        self.tts_thread: Optional[threading.Thread] = None
        self.tts_lock = threading.Lock()
        # STT安定化用カウンタ
        self._stt_fail_count: int = 0

    # ---------- public ----------
    def run(self) -> None:
        print("=== Google Streaming STT × VOICEVOX (corr_gate) ===")
        print("話しかけてください。Ctrl+Cで終了します。")

        try:
            while True:
                print("[STT] 開始")
                had_any_result = False
                did_barge_in_stop = False
                try:
                    transcript = self.stt.listen_once(timeout_sec=12.0, rpc_timeout_sec=45.0)
                    if transcript:
                        had_any_result = True
                        self._stt_fail_count = 0
                    else:
                        print("[STT] 結果なし（タイムアウト/無音）")
                        self._stt_fail_count += 1
                        time.sleep(0.1)
                        continue

                    print(f"\n確定: {transcript}")
                    # 置換（名前など）
                    user_text = self.halo_helper.apply_text_changes(transcript, self.change_text_map)
                    # 履歴にユーザー発話を追加
                    self.history = self.halo_helper.append_history(self.history, self.owner_name, user_text)
                    # LLMで応答
                    try:
                        print("LLMで応答を生成中...")
                        response_text = self.llm.generate_text(self.llm_model, user_text, self.system_content, self.history)
                    except Exception as e:
                        print(f"LLMエラー: {e}")
                        continue
                    response = self.halo_helper.replace_dont_need_word(response_text, self.your_name)
                    self.history = self.halo_helper.append_history(self.history, self.your_name, response)
                    # 新規確定が来たら現TTSを停止し、最新のみ再生
                    self.speak_async(response)
                    #self._reset_stt()

                except KeyboardInterrupt:
                    break
                except Exception as e:
                    print(f"[STT] ループ内エラー: {e}")
                    self._stt_fail_count += 1
                    time.sleep(0.2)
                    if self._stt_fail_count >= 3:
                        print("[STT] エラーが続いたためクライアントを再生成します")
                        self._reset_stt()
                finally:
                    print("[STT] ストリーム終了")
                    # 何も結果が得られずに終了した場合、短い待機を挟んで再試行
                    if not had_any_result:
                        time.sleep(0.3)
                    # single_utterance=False でも外側ループで回し直す
                    continue
        except KeyboardInterrupt:
            print("\n終了します...")
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
                if self.use_led and self.led:
                    self.led.stop_blink(wait=True)
                    self.led.off()
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
            # 再生停止の完了を待つ（短時間）
            try:
                # まずはスレッドの終了を待機
                if self.tts_thread and self.tts_thread.is_alive():
                    self.tts_thread.join(timeout=1.0)
            except Exception as e:
                print(f"TTSスレッド終了エラー: {e}")
            # それでも再生が残っている場合はポーリングで確認
            try:
                deadline = time.time() + 3.0
                while (
                    (self.tts_thread and self.tts_thread.is_alive())
                    or self.tts.is_playing()
                ) and time.time() < deadline:
                    time.sleep(0.02)
                if self.tts_thread and not self.tts_thread.is_alive():
                    self.tts_thread = None
            except Exception:
                pass
            
            def _run():
                try:
                    self.tts.speak(text, self.led, self.use_led, self.motor, self.use_motor, corr_gate=self.corr_gate)
                except Exception as e:
                    print(f"TTSエラー: {e}")

            self.tts_thread = threading.Thread(target=_run, daemon=True)
            self.tts_thread.start()

    def _reset_stt(self) -> None:
        try:
            self.stt.close()
        except Exception as e:
            print(f"STTクローズエラー: {e}")
            pass
        try:
            print("STT再生成")
            self.stt = GoogleSpeechToText(debug=False)
            self.stt.warm_up()
            self._stt_fail_count = 0
        except Exception as e:
            print(f"[STT] 再生成失敗: {e}")


if __name__ == "__main__":
    app = HaloStreamingGoogle()
    app.run()
