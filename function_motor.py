import RPi.GPIO as GPIO
from time import sleep
import threading


class Motor:
    PAN_START_ANGLE = 90
    TILT_START_ANGLE = 90
    def __init__(self, pan_pin:int = 4, tilt_pin:int = 17, frequency:int = 50):
        self.pan_pin = pan_pin
        self.tilt_pin = tilt_pin
        self.frequency = frequency
        self.cycle = 1000/frequency
        self._cleaned = False
        self._pan_thread: threading.Thread | None = None
        self._tilt_thread: threading.Thread | None = None
        self._pan_stop_event = threading.Event()
        self._tilt_stop_event = threading.Event()
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.pan_pin, GPIO.OUT)
        GPIO.setup(self.tilt_pin, GPIO.OUT)
        self.pan_pwm = GPIO.PWM(self.pan_pin, self.frequency)
        self.tilt_pwm = GPIO.PWM(self.tilt_pin, self.frequency)
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
            self.pan_pwm.stop()
        except Exception:
            pass
        try:
            self.tilt_pwm.stop()
        except Exception:
            pass
        try:
            GPIO.cleanup()
        except Exception:
            pass
        self._cleaned = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.clean_up()
        return False
        
    def init_position(self, pan_angle:float=0, tilt_angle:float=0):
        self.pan_pwm.start(self.get_motor_duty(pan_angle))
        self.tilt_pwm.start(self.get_motor_duty(pan_angle))

    def get_motor_ms(self, angle:float) -> float:
        x = (360 - angle) / 180
        return x

    def get_motor_duty(self, angle:float) -> float:
        duty_per = self.get_motor_ms(angle) / self.cycle * 100
        return duty_per
    
    def change_pan_angle(self, angle:float):
        self.pan_pwm.ChangeDutyCycle(self.get_motor_duty(angle))
    
    def change_tilt_angle(self, angle:float):
        self.tilt_pwm.ChangeDutyCycle(self.get_motor_duty(angle))

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

    def _pan_worker(self, left_angle:float, right_angle:float, duration:float):
        self._pan_stop_event.clear()
        if self._pan_stop_event.is_set():
            return
        self.change_pan_angle(left_angle)
        if self._sleep_with_cancel(duration, self._pan_stop_event):
            return
        self.change_pan_angle(right_angle)
        if self._sleep_with_cancel(duration, self._pan_stop_event):
            return

    def _tilt_worker(self, up_angle:float, down_angle:float, duration:float):
        self._tilt_stop_event.clear()
        if self._tilt_stop_event.is_set():
            return
        self.change_tilt_angle(up_angle)
        if self._sleep_with_cancel(duration, self._tilt_stop_event):
            return
        self.change_tilt_angle(down_angle)
        if self._sleep_with_cancel(duration, self._tilt_stop_event):
            return

    def pan_kyoro_kyoro(self, left_angle:float, right_angle:float, time:float):
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
            args=(left_angle, right_angle, time),
            daemon=True,
        )
        self._pan_thread.start()
    
    def tilt_kyoro_kyoro(self, up_angle:float, down_angle:float, time:float):
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
            args=(up_angle, down_angle, time),
            daemon=True,
        )
        self._tilt_thread.start()


if __name__ == "__main__":
    with Motor() as motor:
        print("start position")
        sleep(5)
        print("pan_kyoro_kyoro")
        motor.pan_kyoro_kyoro(60, 120, 1)
        print("tilt_kyoro_kyoro")
        motor.tilt_kyoro_kyoro(45, 90, 1)
        sleep(5)
        print("tilt0")
        motor.change_tilt_angle(0)
        sleep(5)
        print("tilt90")
        motor.change_tilt_angle(90)
        sleep(5)
        print("スタートポジションに戻します")
        motor.pan_to_start_position()
        motor.tilt_to_start_position()
        

