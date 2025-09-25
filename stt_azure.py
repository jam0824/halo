import os
import threading
from typing import Optional, Callable
import azure.cognitiveservices.speech as speechsdk
from motor_controller import MotorController

class AzureSpeechToText:
    def __init__(self, language: str = "ja-JP", subscription: Optional[str] = None,
                 region: Optional[str] = None, device_id: Optional[str] = None):
        self.is_motion = False    # LEDやモーターが作動中か
        self.language = language
        self.subscription = subscription or os.environ.get("SPEECH_KEY")
        self.region = region or os.environ.get("SPEECH_REGION")
        if not self.subscription or not self.region:
            raise RuntimeError("Azure Speech の認証情報(SPEECH_KEY / SPEECH_REGION)が未設定です。")

        self.speech_config = speechsdk.SpeechConfig(
            subscription=self.subscription,
            region=self.region,
        )
        self.speech_config.speech_recognition_language = self.language

        # 終了サイレンスを短めに（確定を早く出す）
        # 300〜700ms 程度で調整してみてください
        self.speech_config.set_property(
            speechsdk.PropertyId.SpeechServiceConnection_EndSilenceTimeoutMs, "300"
        )
        # 先頭無音の許容（長すぎると開始が遅く見える）
        self.speech_config.set_property(
            speechsdk.PropertyId.SpeechServiceConnection_InitialSilenceTimeoutMs, "3000"
        )

        # マイク設定
        if device_id is None:
            self.audio_config = speechsdk.audio.AudioConfig(use_default_microphone=True)
        else:
            self.audio_config = speechsdk.audio.AudioConfig(device_id=device_id)

        # recognizer は使い回す
        self.recognizer = speechsdk.SpeechRecognizer(
            speech_config=self.speech_config,
            audio_config=self.audio_config,
        )

        # 事前に接続を開いておく（初回の遅延対策）
        self.connection = speechsdk.Connection.from_recognizer(self.recognizer)

    def listen_once_fast(
        self,
        print_interim: bool = True,
        session_timeout_sec: float = 15.0,
        motor_controller = None,
        on_interim: Optional[Callable[[str], None]] = None,
        on_final: Optional[Callable[[str], None]] = None,
    ) -> str:
        """
        連続認識で最初の確定が来たら即停止して返す。
        """
        self.motor_controller = motor_controller
        result_text = {"text": ""}  # クロージャで書き換えたいのでdictで包む
        done = threading.Event()

        def on_recognizing(evt):
            #if print_interim:
            #   print("中間:", evt.result.text)
            try:
                if on_interim is not None:
                    on_interim(evt.result.text)
            except Exception:
                pass
            self.start_motion()

        def on_recognized(evt):
            # 最初の確定を受けたら即停止して返す
            if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
                print("確定:", evt.result.text)
                self.stop_motion()
                result_text["text"] = evt.result.text or ""
                try:
                    if on_final is not None:
                        on_final(result_text["text"])
                except Exception:
                    pass
                done.set()

        def on_canceled(evt):
            print("キャンセル:", evt.reason, evt.error_details or "")
            self.stop_motion()
            done.set()
            

        def on_session_stopped(evt):
            print("=== 認識終了 ===")
            self.stop_motion()

        # ハンドラ登録
        self.recognizer.recognizing.connect(on_recognizing)
        self.recognizer.recognized.connect(on_recognized)
        self.recognizer.canceled.connect(on_canceled)
        self.recognizer.session_started.connect(lambda evt: print("=== 認識開始 ==="))
        self.recognizer.session_stopped.connect(on_session_stopped)

        try:
            # 事前に接続オープン（true: 自動再接続あり）
            self.connection.open(True)

            # 連続認識スタート
            self.recognizer.start_continuous_recognition_async().get()

            done.wait(timeout=session_timeout_sec)
            return result_text["text"]
        finally:
            try:
                self.recognizer.stop_continuous_recognition_async().get()
            except Exception:
                pass
            # ハンドラを外しておく（重複防止）
            try:
                self.recognizer.recognizing.disconnect_all()
                self.recognizer.recognized.disconnect_all()
                self.recognizer.canceled.disconnect_all()
                self.recognizer.session_started.disconnect_all()
                self.recognizer.session_stopped.disconnect_all()
            except Exception:
                pass

    # 既存APIを残したい場合は中で fast を呼ぶ
    def listen_once(self, timeout_sec: float = 15.0) -> str:
        return self.listen_once_fast(print_interim=True, session_timeout_sec=timeout_sec)

    def warm_up(self):
        """コネクションだけ先に開いておくと初回の待ちが軽くなる"""
        try:
            self.connection.open(True)
        except Exception as e:
            print("warm_up error:", e)

    def close(self):
        try:
            self.connection.close()
        except Exception:
            pass
    def start_motion(self):
        if not self.is_motion:
            self.is_motion = True
            self.motor_controller.led_on()
            self.motor_controller.motor_tilt_change_angle(110)

    def stop_motion(self):
        if self.is_motion:
            self.is_motion = False
            self.motor_controller.led_off()
            self.motor_controller.motor_tilt_start_angle()

if __name__ == "__main__":
    stt = AzureSpeechToText()
    try:
        stt.warm_up()
        print("--- 発話してください ---")
        text = stt.listen_once()
        print("確定:", text)
    finally:
        stt.close()
