#!/usr/bin/env python3
import time
from rpi_hardware_pwm import HardwarePWM

def angle_to_duty(angle, min_angle=0, max_angle=180,
                  min_pulse=0.5e-3, max_pulse=2.5e-3, frame_width=20e-3):
    """角度を duty[%] に変換"""
    angle = max(min_angle, min(max_angle, angle))
    ratio = (angle - min_angle) / (max_angle - min_angle)
    pulse = min_pulse + (max_pulse - min_pulse) * ratio
    duty = (pulse / frame_width) * 100
    return duty

if __name__ == "__main__":
    # Pi 5 の場合: ch2=GPIO18, ch3=GPIO19
    pan = HardwarePWM(pwm_channel=2, hz=50)
    tilt = HardwarePWM(pwm_channel=3, hz=50)

    try:
        print("中央へ")
        pan.start(angle_to_duty(90))
        tilt.start(angle_to_duty(90))
        time.sleep(2)

        print("左/上へ")
        pan.change_duty_cycle(angle_to_duty(45))
        tilt.change_duty_cycle(angle_to_duty(45))
        time.sleep(2)

        print("右/下へ")
        pan.change_duty_cycle(angle_to_duty(135))
        tilt.change_duty_cycle(angle_to_duty(135))
        time.sleep(2)

        print("中央に戻す")
        pan.change_duty_cycle(angle_to_duty(90))
        tilt.change_duty_cycle(angle_to_duty(90))
        time.sleep(2)

    finally:
        pan.stop()
        tilt.stop()
