import pigpio
import math
from time import sleep
import threading


class Motor:
    PAN_START_ANGLE = 90
    TILT_START_ANGLE = 90
    def __init__(self, pan_pin:int = 12, tilt_pin:int = 25, frequency:int = 50, invert_pan:bool=False, invert_tilt:bool=False):
        self.pan_pin = pan_pin
        self.tilt_pin = tilt_pin
        self.frequency = frequency  # pigpioのset_servo_pulsewidthは周波数指定不要
        # サーボ用パルス幅(us)
        self._min_pulse_us = 500
        self._max_pulse_us = 2500
        self._min_angle = 0.0
        self._max_angle = 180.0
        self._invert_pan = bool(invert_pan)
        self._invert_tilt = bool(invert_tilt)
        # 直近に指示した角度を保持（イージングの始点に利用）
        self._pan_angle: float = float(self.PAN_START_ANGLE)
        self._tilt_angle: float = float(self.TILT_START_ANGLE)
        self._cleaned = False
        self._pan_thread: threading.Thread | None = None
        self._tilt_thread: threading.Thread | None = None
        self._pan_stop_event = threading.Event()
        self._tilt_stop_event = threading.Event()
        self.pi = pigpio.pi()
        if not self.pi.connected:
            raise RuntimeError("pigpio daemon (pigpiod) に接続できませんでした。pigpiod を起動してください。")
        self.init_position(self.PAN_START_ANGLE, self.TILT_START_ANGLE)
    
    def __del__(self):
        try:
            self.clean_up()
        except Exception:
            pass

    def clean_up(self):
        if self._cleaned:
            return
        # 要求停止を出して実行中のスレッドを終了させる
        try:
            self._pan_stop_event.set()
            self._tilt_stop_event.set()
            if self._pan_thread and self._pan_thread.is_alive():
                self._pan_thread.join()
            if self._tilt_thread and self._tilt_thread.is_alive():
                self._tilt_thread.join()
        except Exception:
            pass
        try:
            # サーボ信号を停止
            self.pi.set_servo_pulsewidth(self.pan_pin, 0)
        except Exception:
            pass
        try:
            self.pi.set_servo_pulsewidth(self.tilt_pin, 0)
        except Exception:
            pass
        try:
            self.pi.stop()
        except Exception:
            pass
        self._cleaned = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.clean_up()
        return False
        
    def init_position(self, pan_angle:float=0, tilt_angle:float=0):
        self.change_pan_angle(pan_angle)
        self.change_tilt_angle(tilt_angle)
    def _angle_to_pulsewidth(self, angle:float) -> int:
        # 角度を安全にクリップ
        a = max(self._min_angle, min(self._max_angle, float(angle)))
        span_us = self._max_pulse_us - self._min_pulse_us
        span_deg = self._max_angle - self._min_angle
        pw = self._min_pulse_us + (a - self._min_angle) * span_us / span_deg
        return int(round(pw))
    
    def change_pan_angle(self, angle:float):
        adj = (self._max_angle - float(angle)) if self._invert_pan else float(angle)
        self._pan_angle = float(angle)
        self.pi.set_servo_pulsewidth(self.pan_pin, self._angle_to_pulsewidth(adj))
    
    def change_tilt_angle(self, angle:float):
        adj = (self._max_angle - float(angle)) if self._invert_tilt else float(angle)
        self._tilt_angle = float(angle)
        self.pi.set_servo_pulsewidth(self.tilt_pin, self._angle_to_pulsewidth(adj))

    def pan_to_start_position(self):
        self.change_pan_angle(self.PAN_START_ANGLE)
    
    def tilt_to_start_position(self):
        self.change_tilt_angle(self.TILT_START_ANGLE)


    def _sleep_with_cancel(self, seconds:float, stop_event:threading.Event) -> bool:
        remaining = max(0.0, float(seconds))
        interval = 0.05
        while remaining > 0:
            if stop_event.is_set():
                return True
            chunk = interval if remaining > interval else remaining
            sleep(chunk)
            remaining -= chunk
        return stop_event.is_set()

    def _pan_worker(self, left_angle:float, right_angle:float, duration:float, count:int=1):
        """パンのみイージングで左右へ往復する。
        duration は各移動(左->右, 右->左 など)の所要時間[s]。
        """
        self._pan_stop_event.clear()
        if self._pan_stop_event.is_set():
            return
        # 1ステップのスリープ間隔(秒)
        base_interval = 0.02  # 50Hz程度

        def ease_in_out_sine(t: float) -> float:
            return 0.5 * (1 - math.cos(math.pi * t))

        def move_ease(start: float, end: float, seconds: float) -> bool:
            if seconds <= 0:
                self.change_pan_angle(end)
                return self._pan_stop_event.is_set()
            steps = max(1, int(seconds / base_interval))
            for i in range(1, steps + 1):
                if self._pan_stop_event.is_set():
                    return True
                t = i / steps
                p = t
                angle = start + (end - start) * p
                self.change_pan_angle(angle)
                if self._sleep_with_cancel(base_interval, self._pan_stop_event):
                    return True
            return self._pan_stop_event.is_set()

        current = float(self._pan_angle)
        for _ in range(max(1, int(count))):
            if move_ease(current, float(left_angle), float(duration)):
                return
            current = float(left_angle)
            if move_ease(current, float(self.PAN_START_ANGLE), float(duration)):
                return
            current = float(self.PAN_START_ANGLE)
            if move_ease(current, float(right_angle), float(duration)):
                return
            current = float(right_angle)
        # 最後にスタート角へ戻す
        move_ease(current, float(self.PAN_START_ANGLE), float(duration))

    def _tilt_worker(self, up_angle:float, down_angle:float, duration:float, count:int=1):
        self._tilt_stop_event.clear()
        if self._tilt_stop_event.is_set():
            return
        for _ in range(max(1, int(count))):
            self.change_tilt_angle(up_angle)
            if self._sleep_with_cancel(duration, self._tilt_stop_event):
                return
            self.change_tilt_angle(down_angle)
            if self._sleep_with_cancel(duration, self._tilt_stop_event):
                return

    def pan_kyoro_kyoro(self, left_angle:float, right_angle:float, time:float, count:int=1):
        # 既存の動作があれば停止を指示
        try:
            self._pan_stop_event.set()
            if self._pan_thread and self._pan_thread.is_alive():
                self._pan_thread.join(timeout=0.1)
        except Exception:
            pass
        # 非ブロッキング開始
        self._pan_thread = threading.Thread(
            target=self._pan_worker,
            args=(left_angle, right_angle, time, count),
            daemon=True,
        )
        self._pan_thread.start()
    
    def tilt_kyoro_kyoro(self, up_angle:float, down_angle:float, time:float, count:int=1):
        # 既存の動作があれば停止を指示
        try:
            self._tilt_stop_event.set()
            if self._tilt_thread and self._tilt_thread.is_alive():
                self._tilt_thread.join(timeout=0.1)
        except Exception:
            pass
        # 非ブロッキング開始
        self._tilt_thread = threading.Thread(
            target=self._tilt_worker,
            args=(up_angle, down_angle, time, count),
            daemon=True,
        )
        self._tilt_thread.start()

    def motor_kuchipaku(self):
        """
        口パク時に呼ぶ
        """
        self.tilt_kyoro_kyoro(120, self.TILT_START_ANGLE, 0.5, 2)


if __name__ == "__main__":
    with Motor() as motor:
        print("start position")
        sleep(5)
        print("pan_kyoro_kyoro")
        motor.pan_kyoro_kyoro(60, 120, 1, 1)
        print("tilt_kyoro_kyoro")
        motor.tilt_kyoro_kyoro(135, 90, 0.5, 5)
        sleep(5)
        print("tilt90")
        motor.change_tilt_angle(90)
        sleep(5)
        print("tilt135")
        motor.change_tilt_angle(135)
        sleep(5)

        print("スタートポジションに戻します")
        motor.pan_to_start_position()
        motor.tilt_to_start_position()
        sleep(2)

