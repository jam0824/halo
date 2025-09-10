import time
import threading
import RPi.GPIO as GPIO


class LEDBlinker:
  def __init__(self, pin: int = 17, use_bcm: bool = True):
    self.pin = int(pin)
    self._stop_event = threading.Event()
    self._thread = None
    self._lock = threading.RLock()
    self._cleaned = False

    if use_bcm:
      GPIO.setmode(GPIO.BCM)
    else:
      GPIO.setmode(GPIO.BOARD)
    GPIO.setup(self.pin, GPIO.OUT, initial=GPIO.LOW)

  # コンテキスト管理
  def __enter__(self):
    return self

  def __exit__(self, exc_type, exc, tb):
    self.cleanup()
    return False

  # 制御API
  def on(self):
    if self._cleaned:
      return
    self.stop_blink()
    self._safe_output(GPIO.HIGH)

  def off(self):
    if self._cleaned:
      return
    self.stop_blink()
    self._safe_output(GPIO.LOW)

  def start_blink(self, on_sec: float = 0.3, off_sec: float = 0.3):
    with self._lock:
      if self._cleaned:
        return
      self.stop_blink()
      self._stop_event.clear()

      def _run():
        try:
          while not self._stop_event.is_set():
            self._safe_output(GPIO.HIGH)
            if self._stop_event.wait(on_sec):
              break
            self._safe_output(GPIO.LOW)
            if self._stop_event.wait(off_sec):
              break
        finally:
          self._safe_output(GPIO.LOW)

      self._thread = threading.Thread(target=_run, daemon=True)
      self._thread.start()

  def stop_blink(self, wait: bool = False):
    with self._lock:
      if self._thread and self._thread.is_alive():
        self._stop_event.set()
        if wait:
          self._thread.join(timeout=1.0)
        self._thread = None
        self._stop_event.clear()

  def cleanup(self):
    # ブリンク停止とGPIO解放
    self.stop_blink(wait=True)
    self._cleaned = True
    try:
      self._safe_output(GPIO.LOW)
    except Exception:
      pass
    try:
      # ピン単体のクリーンアップ（環境によっては全体cleanup()でもOK）
      GPIO.cleanup(self.pin)
    except Exception:
      pass

  def _safe_output(self, level):
    try:
      GPIO.output(self.pin, level)
    except Exception:
      pass


if __name__ == "__main__":
  # 簡易デモ（非ブロッキングで点滅しつつ、他処理を継続）
  try:
    with LEDBlinker(pin=17) as led:
      print("boot", flush=True)
      led.start_blink(0.3, 0.3)
      print("非ブロッキング点滅中。3秒後に点灯→2秒後に消灯→終了")
      time.sleep(3)
      led.on()
      time.sleep(2)
      led.off()
      time.sleep(1)
  except KeyboardInterrupt:
    pass