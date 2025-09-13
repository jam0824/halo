import math
from time import sleep
import threading
from rpi_hardware_pwm import HardwarePWM  # ★追加

class HardwareServo:
    """
    ハードウェアPWMでサーボを駆動する薄いラッパ。
    - 周期(frame_width_s)は既定 20ms（=50Hz）
    - パルス幅(min/max)を ns に変換して duty を設定
    """
    def __init__(self, pwm_channel:int, frame_width_s:float=0.02,
                 min_pulse_s:float=0.0005, max_pulse_s:float=0.0025, chip:int=0):
        self.frame_width_s = float(frame_width_s)
        self.min_pulse_s   = float(min_pulse_s)
        self.max_pulse_s   = float(max_pulse_s)
        self._hz = max(1, int(round(1.0 / self.frame_width_s)))  # 50Hz想定
        # Pi 5 のチャネル割当:
        #  ch 0→GPIO12, ch 1→GPIO13, ch 2→GPIO18, ch 3→GPIO19  (rpi-hardware-pwmの説明に準拠)
        self._pwm = HardwarePWM(pwm_channel=int(pwm_channel), hz=self._hz, chip=int(chip))
        self._running = False

    def start(self, pulse_s:float):
        duty = max(0.0, min(100.0, (pulse_s / self.frame_width_s) * 100.0))
        if not self._running:
            self._pwm.start(duty)
            self._running = True
        else:
            self._pwm.change_duty_cycle(duty)

    def set_pulse(self, pulse_s:float):
        self.start(pulse_s)

    def stop(self):
        if self._running:
            try:
                self._pwm.stop()
            finally:
                self._running = False

    def close(self):
        self.stop()

class Motor:
    PAN_START_ANGLE = 90
    TILT_START_ANGLE = 90

    def __init__(self, pan_pin:int = 18, tilt_pin:int = 19,  # ← ★GPIO18/19に変更（BCM）
                 frequency:int = 50, invert_pan:bool=False, invert_tilt:bool=False,
                 frame_width_s: float = 0.02, hold_servo: bool = True,
                 angle_step_deg: float = 1.0, min_delta_deg: float = 0.7):
        # 角度→パルス幅
        self._min_pulse_s = 0.0005
        self._max_pulse_s = 0.0025
        self._min_angle = 0.0
        self._max_angle = 180.0
        self._invert_pan = bool(invert_pan)
        self._invert_tilt = bool(invert_tilt)
        self._frame_width_s = float(frame_width_s)  # 20ms=50Hz
        self._hold = bool(hold_servo)
        self._angle_step_deg = max(0.1, float(angle_step_deg))
        self._min_delta_deg = max(0.0, float(min_delta_deg))
        self._pan_angle = float(self.PAN_START_ANGLE)
        self._tilt_angle = float(self.TILT_START_ANGLE)
        self._cleaned = False
        self._pan_thread = None
        self._tilt_thread = None
        self._pan_stop_event = threading.Event()
        self._tilt_stop_event = threading.Event()

        # BCMピン→PWMチャネル対応（Pi 5 / rpi-hardware-pwm 準拠）
        bcm_to_channel = {12:0, 13:1, 18:2, 19:3}

        def servo_for_bcm(bcm_pin:int) -> HardwareServo:
            if bcm_pin not in bcm_to_channel:
                raise ValueError(f"GPIO{bcm_pin} はハードPWM非対応です。GPIO12/13/18/19から選んでください。")
            ch = bcm_to_channel[bcm_pin]
            return HardwareServo(pwm_channel=ch, frame_width_s=self._frame_width_s,
                                 min_pulse_s=self._min_pulse_s, max_pulse_s=self._max_pulse_s, chip=0)

        # ★AngularServo をやめ、ハードPWMラッパに置換
        self._servo_pan  = servo_for_bcm(int(pan_pin))
        self._servo_tilt = servo_for_bcm(int(tilt_pin))

        self.init_position(self.PAN_START_ANGLE, self.TILT_START_ANGLE)

    def __del__(self):
        try:
            self.clean_up()
        except Exception:
            pass

    def clean_up(self):
        if self._cleaned:
            return
        self._cleaned = True
        try:
            self._pan_stop_event.set()
            self._tilt_stop_event.set()
            if self._pan_thread and self._pan_thread.is_alive():
                self._pan_thread.join()
            if self._tilt_thread and self._tilt_thread.is_alive():
                self._tilt_thread.join()
        except Exception:
            pass
        for s in (self._servo_pan, self._servo_tilt):
            try:
                s.stop()
            except Exception:
                pass
            try:
                s.close()
            except Exception:
                pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.clean_up()
        return False

    def _angle_to_pulse(self, angle:float) -> float:
        # 0°→min_pulse, 180°→max_pulse の線形マップ
        a = max(self._min_angle, min(self._max_angle, float(angle)))
        ratio = (a - self._min_angle) / (self._max_angle - self._min_angle)
        return self._min_pulse_s + (self._max_pulse_s - self._min_pulse_s) * ratio

    def init_position(self, pan_angle:float=0, tilt_angle:float=0):
        self.change_pan_angle(pan_angle)
        self.change_tilt_angle(tilt_angle)

    def _quantize(self, angle: float) -> float:
        step = self._angle_step_deg
        return round(angle / step) * step

    def change_pan_angle(self, angle:float):
        if self._cleaned:
            return
        adj = (self._max_angle - float(angle)) if self._invert_pan else float(angle)
        adj_q = self._quantize(adj)
        if abs(adj_q - getattr(self, "_last_pan_set", self._pan_angle)) < self._min_delta_deg:
            self._pan_angle = float(angle)
            return
        self._pan_angle = float(angle)
        try:
            self._servo_pan.set_pulse(self._angle_to_pulse(adj_q))
            self._last_pan_set = adj_q
        except Exception:
            pass

    def change_tilt_angle(self, angle:float):
        if self._cleaned:
            return
        adj = (self._max_angle - float(angle)) if self._invert_tilt else float(angle)
        adj_q = self._quantize(adj)
        if abs(adj_q - getattr(self, "_last_tilt_set", self._tilt_angle)) < self._min_delta_deg:
            self._tilt_angle = float(angle)
            return
        self._tilt_angle = float(angle)
        try:
            self._servo_tilt.set_pulse(self._angle_to_pulse(adj_q))
            self._last_tilt_set = adj_q
        except Exception:
            pass

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
        if self._cleaned:
            return
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
                if self._cleaned:
                    return True
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
        # アイドル時はデタッチしてジッター抑制
        if not self._hold:
            try:
                self._servo_pan.detach()
            except Exception:
                pass

    def _tilt_worker(self, up_angle:float, down_angle:float, duration:float, count:int=1):
        if self._cleaned:
            return
        self._tilt_stop_event.clear()
        if self._tilt_stop_event.is_set():
            return
        base_interval = 0.02

        def ease_in_out_sine(t: float) -> float:
            return 0.5 * (1 - math.cos(math.pi * t))

        def move_ease(start: float, end: float, seconds: float) -> bool:
            if seconds <= 0:
                self.change_tilt_angle(end)
                return self._tilt_stop_event.is_set()
            steps = max(1, int(seconds / base_interval))
            for i in range(1, steps + 1):
                if self._tilt_stop_event.is_set():
                    return True
                t = i / steps
                p = t
                angle = start + (end - start) * p
                if self._cleaned:
                    return True
                self.change_tilt_angle(angle)
                if self._sleep_with_cancel(base_interval, self._tilt_stop_event):
                    return True
            return self._tilt_stop_event.is_set()

        current = float(self._tilt_angle)
        for _ in range(max(1, int(count))):
            if move_ease(current, float(up_angle), float(duration)):
                return
            current = float(up_angle)
            if move_ease(current, float(down_angle), float(duration)):
                return
            current = float(down_angle)
        if not self._hold:
            try:
                self._servo_tilt.detach()
            except Exception:
                pass

    def pan_kyoro_kyoro(self, left_angle:float, right_angle:float, time:float, count:int=1):
        if self._cleaned:
            return
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
        if self._cleaned:
            return
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

    def stop_motion(self):
        """
        実行中のパン/チルトの動作のみを停止する（pigpioのクローズは行わない）。
        """
        try:
            self._pan_stop_event.set()
            self._tilt_stop_event.set()
            if self._pan_thread and self._pan_thread.is_alive():
                self._pan_thread.join(timeout=0.2)
            if self._tilt_thread and self._tilt_thread.is_alive():
                self._tilt_thread.join(timeout=0.2)
        except Exception:
            pass
        finally:
            try:
                self._pan_stop_event.clear()
            except Exception:
                pass
            try:
                self._tilt_stop_event.clear()
            except Exception:
                pass
            if not self._hold:
                try:
                    self._servo_pan.detach()
                except Exception:
                    pass
                try:
                    self._servo_tilt.detach()
                except Exception:
                    pass

    def set_hold(self, hold: bool):
        self._hold = bool(hold)

    def detach(self):
        try:
            self._servo_pan.detach()
        except Exception:
            pass
        try:
            self._servo_tilt.detach()
        except Exception:
            pass

    def motor_kuchipaku(self):
        """
        口パク時に呼ぶ
        """
        if self._cleaned:
            return
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

