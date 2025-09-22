from typing import Optional, TYPE_CHECKING
from helper.halo_helper import HaloHelper
import time

if TYPE_CHECKING:
    from function_led import LEDBlinker
    from function_motor import Motor

class MotorController:
    def __init__(self, config: dict):
        self.config = config
        self.use_led = self.config["led"]["use_led"]
        self.led_pin = self.config["led"]["led_pin"]
        self.use_motor = self.config["motor"]["use_motor"]
        self.pan_pin = self.config["motor"]["pan_pin"]
        self.tilt_pin = self.config["motor"]["tilt_pin"]

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

    # ---------- LED ----------
    def led_on(self):
        if self.use_led and self.led:
            self.led.on()
        return
    def led_off(self):
        if self.use_led and self.led:
            self.led.off()
        return

    def led_start_blink(self):
        if self.use_led and self.led:
            self.led.start_blink()
        return
    def led_stop_blink(self):
        if self.use_led and self.led:
            self.led.stop_blink()
        return
    # LED停止
    def led_stop_blink(self):
        if self.use_led and self.led:
            self.led.stop_blink()
        return

    # ---------- モーター ----------
    def motor_tilt_change_angle(self, angle: float):
        if self.use_motor and self.motor:
            self.motor.tilt_change_angle(angle)
        return
    def motor_pan_change_angle(self, angle: float):
        if self.use_motor and self.motor:
            self.motor.pan_change_angle(angle)
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
    def motor_pan_kyoro_kyoro(self, speed: float = 1, count: int = 1):
        if self.use_motor and self.motor:
            self.motor.pan_kyoro_kyoro(80, 100, speed, count)

    # tilt動作
    def motor_tilt_kyoro_kyoro(self, count: int = 1):
        if self.use_motor and self.motor:
            self.motor.motor_kuchipaku()


if __name__ == "__main__":
    config = HaloHelper().load_config()
    motor_controller = MotorController(config)
    print("led_on")
    motor_controller.led_on()
    time.sleep(1)
    print("led_off")
    motor_controller.led_off()
    time.sleep(1)
    print("led_start_blink")
    motor_controller.led_start_blink()
    time.sleep(1)
    print("led_stop_blink")
    motor_controller.led_stop_blink()
    time.sleep(1)
    print("motor_pan_kyoro_kyoro")
    motor_controller.motor_pan_kyoro_kyoro(1,5)
    time.sleep(5)
    print("motor_tilt_kyoro_kyoro")
    motor_controller.motor_tilt_kyoro_kyoro(2)
    time.sleep(5)
    