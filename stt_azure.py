import os
from typing import Optional
import azure.cognitiveservices.speech as speechsdk


class AzureSpeechToText:
    def __init__(self, language: str = "ja-JP", subscription: Optional[str] = None,
                 region: Optional[str] = None, device_id: Optional[str] = None):
        self.language = language
        self.subscription = subscription or os.environ.get("SPEECH_KEY")
        self.region = region or os.environ.get("SPEECH_REGION")
        if not self.subscription or not self.region:
            raise RuntimeError("Azure Speech の認証情報(SPEECH_KEY / SPEECH_REGION)が未設定です。")

        # 設定
        self.speech_config = speechsdk.SpeechConfig(
            subscription=self.subscription,
            region=self.region,
        )
        self.speech_config.speech_recognition_language = self.language

        # マイク設定（デフォルトまたは指定デバイス）
        if device_id is None:
            self.audio_config = speechsdk.audio.AudioConfig(use_default_microphone=True)
        else:
            self.audio_config = speechsdk.audio.AudioConfig(device_id=device_id)

    def listen_once(self, timeout_sec: float = 15.0) -> str:
        """
        1回の発話を認識し、確定テキストを返す（ブロッキング）。
        """
        # 無音タイムアウト（先頭無音）
        try:
            self.speech_config.set_property(
                speechsdk.PropertyId.SpeechServiceConnection_InitialSilenceTimeoutMs,
                str(int(timeout_sec * 1000)),
            )
        except Exception:
            pass

        recognizer = speechsdk.SpeechRecognizer(
            speech_config=self.speech_config,
            audio_config=self.audio_config,
        )
        try:
            # 中間結果（逐次）
            recognizer.recognizing.connect(lambda evt: print("中間:", evt.result.text))
            # 確定結果（分節ごと）
            recognizer.recognized.connect(lambda evt: print("確定:", evt.result.text))
            # セッション開始/終了・エラー
            recognizer.session_started.connect(lambda evt: print("=== 認識開始 ==="))
            recognizer.session_stopped.connect(lambda evt: print("=== 認識終了 ==="))
            recognizer.canceled.connect(lambda evt: print("キャンセル:", evt.reason, evt.error_details or ""))
            
            result = recognizer.recognize_once_async().get()
        except Exception as e:
            print(f"Azure STT エラー: {e}")
            return ""

        reason = getattr(result, "reason", None)
        if reason == speechsdk.ResultReason.RecognizedSpeech:
            return result.text or ""
        elif reason == speechsdk.ResultReason.NoMatch:
            return ""
        elif reason == speechsdk.ResultReason.Canceled:
            details = speechsdk.CancellationDetails.from_result(result)
            print(f"Azure STT キャンセル: {details.reason}, {details.error_details or ''}")
            return ""
        return ""

    def warm_up(self):
        """初期化の肩慣らし（任意）。"""
        return None

    def close(self):
        """Azure SDK はGCで解放されるため、ここでは特に何もしない。"""
        return None


if __name__ == "__main__":
    stt = AzureSpeechToText()
    try:
        print("--- 発話してください ---")
        text = stt.listen_once()
        print("確定:", text)
    finally:
        stt.close()
