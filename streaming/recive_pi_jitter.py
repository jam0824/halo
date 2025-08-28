# recive_pi_jitter.py
import socket, sounddevice as sd, numpy as np, struct, threading, collections

SR    = 48000
CH    = 2
PORT  = 5004
FRAME = 1440
BYTES_PER_FRAME = FRAME * CH * 2   # int16=2bytes
PKT_PAYLOAD_LEN = BYTES_PER_FRAME  # ヘッダ4B + 音声ペイロード
GAIN_DB = 6.0  # 受信側の音量を+6 dB（約2倍）に
GAIN = 10 ** (GAIN_DB / 20)

# 受信スレッドが詰めるリングバッファ（パケット単位）
packet_buffer = collections.deque(maxlen=512)  # 過剰なら古いものが落ちる
buffer_lock   = threading.Lock()

expected_seq  = None
running       = True

def udp_receiver():
    global expected_seq, running
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1<<20)  # 1MB
    sock.bind(("0.0.0.0", PORT))
    print(f"Listening on UDP :{PORT}")

    while running:
        data, _ = sock.recvfrom(4 + PKT_PAYLOAD_LEN + 512)  # 多少大きめに
        if len(data) < 4:
            continue
        seq = struct.unpack("!I", data[:4])[0]
        payload = data[4:]

        if len(payload) != PKT_PAYLOAD_LEN:
            # 予期しないサイズは捨てる
            continue

        with buffer_lock:
            if expected_seq is None:
                expected_seq = seq
            # 欠落検出（seq が飛んでいたら、その分の無音フレームを挿入）
            while expected_seq < seq:
                packet_buffer.append(np.zeros((FRAME, CH), dtype=np.int16))
                expected_seq += 1
            # 現在のパケットを追加
            frame = np.frombuffer(payload, dtype=np.int16).reshape(-1, CH)
            packet_buffer.append(frame)
            expected_seq = seq + 1

def audio_callback(outdata, frames, time, status):
    # frames は通常 FRAME（=960）で来る想定
    # 足りなければ無音で埋める。多すぎてもここでは1フレーム分しか消費しない。
    if status:
        print("Out Status:", status)
    need = frames
    written = 0
    with buffer_lock:
        while need > 0:
            if packet_buffer:
                frm = packet_buffer.popleft()
            else:
                frm = np.zeros((FRAME, CH), dtype=np.int16)

            if GAIN != 1.0:
                # float化 → 乗算 → クリップ → int16に戻す
                frm = (frm.astype(np.float32) * GAIN)
                np.clip(frm, -32768, 32767, out=frm)
                frm = frm.astype(np.int16)
            take = min(need, len(frm))
            outdata[written:written+take, :] = frm[:take, :]
            # 余った分を次回のため先頭から削って戻す
            if take < len(frm):
                packet_buffer.appendleft(frm[take:, :].copy())
            written += take
            need    -= take
    if written < frames:
        # 念のため残りを無音で埋める
        outdata[written:frames, :] = 0

def main():
    global running
    # UDP受信スレッド開始
    t = threading.Thread(target=udp_receiver, daemon=True)
    t.start()

    # まずは少し貯めてから再生開始（初期ジッタバッファ）
    import time as _t
    _t.sleep(0.4)  # 200ms ほど貯める

    with sd.OutputStream(samplerate=SR, channels=CH, dtype='int16',
                         blocksize=FRAME, callback=audio_callback):
        print("Playing...")
        try:
            while True:
                _t.sleep(1)
        except KeyboardInterrupt:
            running = False
    print("Stopped.")

if __name__ == "__main__":
    main()
