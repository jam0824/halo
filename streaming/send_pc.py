# send_pc_loopback.py
import socket, sounddevice as sd, struct, threading, time

PI_IP = "192.168.1.248"   # ← Raspberry Pi のIPに変更
PORT  = 5004
SR    = 48000
CH    = 2
FRAME = 1440
DEVICE_NAME = "ステレオ ミキサー (Realtek HD Audio Stereo input)"  # ←list_devicesで見つけた名前

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
seq  = 0
running = True

def callback(indata, frames, t, status):
    global seq
    if status:
        print("SD Status:", status)
    # 先頭に 4バイトのシーケンス番号（ネットワークバイトオーダー）
    header = struct.pack("!I", seq & 0xFFFFFFFF)
    sock.sendto(header + indata.tobytes(), (PI_IP, PORT))
    seq += 1

def main():
    global running
    print("Using device:", DEVICE_NAME)
    # WASAPI loopback を使うには device に "(loopback)" の付く出力デバイスを指定
    with sd.InputStream(samplerate=SR, channels=CH, dtype='int16',
                        blocksize=FRAME, device=DEVICE_NAME, callback=callback):
        print(f"Streaming system sound to {PI_IP}:{PORT} @ {SR}Hz, CH={CH}, frame={FRAME}")
        try:
            while running:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    print("Stopped.")

if __name__ == "__main__":
    main()
