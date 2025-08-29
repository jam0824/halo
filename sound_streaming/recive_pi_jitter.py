# recive_pi_jitter.py  安定優先プロファイル
import socket, sounddevice as sd, numpy as np, struct, threading, collections, time as _t

# ===== パラメータ（安定寄り）=====
SR    = 48000
CH    = 2
PORT  = 5004

FRAME = 1440                    # 30ms @ 48kHz（安定）
BYTES_PER_FRAME = FRAME * CH * 2
PKT_PAYLOAD_LEN = BYTES_PER_FRAME

GAIN_DB = 6.0                   # 受信側ゲイン
GAIN = 10 ** (GAIN_DB / 20)

MIN_FRAMES   = 8                # 再生開始前の最低貯蓄（≈240ms）
TARGET_DEPTH = 8                # 再生中に維持したい深さ
DROP_MARGIN  = 2                # TARGET_DEPTH+2 超で1フレーム破棄
RING_MAXLEN  = 4096             # リングの最大深さ（余裕大きめ）

ADAPTIVE_DROP_ENABLED = True    # 適応ドロップON/OFF切替
PRINT_STATS_EVERY_SEC = 1.0     # 1秒ごとに統計表示

VOICE_THRESHOLD = 50

# ===== 共有状態 =====
packet_buffer = collections.deque(maxlen=RING_MAXLEN)
buffer_lock   = threading.Lock()
expected_seq  = None
running       = True

# 統計系
stats_lock    = threading.Lock()
stat_drops    = 0    # 適応ドロップ回数
stat_underrun = 0    # 無音挿入で埋めた回数
stat_last_ts  = _t.time()

def udp_receiver():
    global expected_seq, running
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1<<20)  # 1MB
    sock.bind(("0.0.0.0", PORT))
    print(f"Listening on UDP :{PORT}")

    while running:
        data, _ = sock.recvfrom(4 + PKT_PAYLOAD_LEN + 1024)
        if len(data) < 4:
            continue
        seq = struct.unpack("!I", data[:4])[0]
        payload = data[4:]
        if len(payload) != PKT_PAYLOAD_LEN:
            continue

        with buffer_lock:
            if expected_seq is None:
                expected_seq = seq
            while expected_seq < seq:
                packet_buffer.append(np.zeros((FRAME, CH), dtype=np.int16))
                expected_seq += 1
                with stats_lock:
                    # 欠落穴埋めはここではカウントしない（任意）
                    pass
            frame = np.frombuffer(payload, dtype=np.int16).reshape(-1, CH)
            packet_buffer.append(frame)
            expected_seq = seq + 1

def maybe_print_stats():
    global stat_last_ts
    now = _t.time()
    if now - stat_last_ts >= PRINT_STATS_EVERY_SEC:
        with buffer_lock:
            depth = len(packet_buffer)
        with stats_lock:
            print(f"[stats] depth={depth} frames, drop={stat_drops}, underrun={stat_underrun}")
            # 毎秒でリセットしても良いし、積算でもOK。ここでは積算のまま。
        stat_last_ts = now

def audio_callback(outdata, frames, t, status):
    global stat_drops, stat_underrun
    if status:
        print("Out Status:", status)

    # 適応ジッタ制御：厚すぎるとき古い1フレーム破棄して遅延を詰める
    if ADAPTIVE_DROP_ENABLED:
        with buffer_lock:
            depth = len(packet_buffer)
            if depth > (TARGET_DEPTH + DROP_MARGIN):
                packet_buffer.popleft()
                with stats_lock:
                    stat_drops += 1

    need = frames
    written = 0

    with buffer_lock:
        while need > 0:
            if packet_buffer:
                frm = packet_buffer.popleft()
            else:
                frm = np.zeros((FRAME, CH), dtype=np.int16)
                with stats_lock:
                    stat_underrun += 1
            # ゲイン
            if GAIN != 1.0:
                x = frm.astype(np.float32) * GAIN
                np.clip(x, -32768, 32767, out=x)
                frm = x.astype(np.int16)

            take = min(need, len(frm))
            outdata[written:written+take, :] = frm[:take, :]
            if isSounded(frm):
                print(f"frm: {frm[0][0]}")
                print("音が鳴っている")

            if take < len(frm):
                packet_buffer.appendleft(frm[take:, :].copy())

            written += take
            need    -= take

    if written < frames:
        outdata[written:frames, :] = 0

    maybe_print_stats()

def isSounded(frm):
    """
    音が鳴っているか判定する
    """
    return np.any(np.abs(frm[0][0]) > VOICE_THRESHOLD)

def main():
    global running
    t = threading.Thread(target=udp_receiver, daemon=True)
    t.start()

    # 最低貯蓄に達するまで待機
    while True:
        with buffer_lock:
            depth = len(packet_buffer)
        if depth >= MIN_FRAMES:
            break
        _t.sleep(0.005)

    with sd.OutputStream(samplerate=SR, channels=CH, dtype='int16',
                         blocksize=FRAME, latency='high', callback=audio_callback):
        print("Playing...")
        try:
            while True:
                _t.sleep(1)
        except KeyboardInterrupt:
            running = False
    print("Stopped.")

if __name__ == "__main__":
    main()
