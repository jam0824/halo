import time
import threading
from gpiozero import LED


class LEDBlinker:
  def __init__(self, pin: int = 27):
    self.pin = int(pin)
    self._lock = threading.RLock()
    self._cleaned = False
    self._led = LED(self.pin)
    self._last_on = 0.3
    self._last_off = 0.3

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
    with self._lock:
      self._safe_off()
      self._safe_on()

  def off(self):
    if self._cleaned:
      return
    with self._lock:
      self._safe_off()

  def start_blink(self, on_sec: float = 0.3, off_sec: float = 0.3):
    if self._cleaned:
      return
    with self._lock:
      self._last_on = float(on_sec)
      self._last_off = float(off_sec)
      try:
        self._led.blink(on_time=self._last_on, off_time=self._last_off, background=True)
      except Exception:
        pass

  def stop_blink(self, wait: bool = False):
    if self._cleaned:
      return
    with self._lock:
      try:
        # blinkスレッドは off() で停止する
        self._led.off()
        if wait:
          # 簡易的に直前の周期分だけ待機
          time.sleep(min(1.0, self._last_on + self._last_off))
      except Exception:
        pass

  def cleanup(self):
    # ブリンク停止とGPIO解放
    if self._cleaned:
      return
    try:
      self.stop_blink(wait=True)
    except Exception:
      pass
    self._cleaned = True
    try:
      self._led.close()
    except Exception:
      pass

  # 内部安全呼び出し
  def _safe_on(self):
    try:
      self._led.on()
    except Exception:
      pass

  def _safe_off(self):
    try:
      self._led.off()
    except Exception:
      pass


if __name__ == "__main__":
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