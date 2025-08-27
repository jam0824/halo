#!/usr/bin/env python3
# mic_vu.py - PyAudioでマイク入力のレベル(ピーク/RMS)を表示する簡易VUメーター
# - 入力デバイス一覧を表示して選択
# - デバイスの defaultSampleRate / チャンネルに自動追従
# - 100msごとに Peak, RMS(dBFS), 簡易バー を表示
# - pulse/default/ALSA いずれも可

import sys, time, math, struct
import pyaudio

FRAMES_PER_BUFFER = 2048       # 48k/monoで~42.7ms。44100でもOK
PRINT_INTERVAL_SEC = 0.1       # 表示間隔 100ms
BAR_LEN = 50                   # バーの長さ

def list_input_devices(pa):
    devs = []
    for i in range(pa.get_device_count()):
        try:
            info = pa.get_device_info_by_index(i)
        except Exception:
            continue
        if int(info.get("maxInputChannels", 0)) > 0:
            devs.append(info)
    return devs

def pick_device(pa):
    try:
        default_info = pa.get_default_input_device_info()
        default_idx = int(default_info["index"])
    except Exception:
        default_info = None
        default_idx = None

    devs = list_input_devices(pa)
    if not devs:
        print("入力デバイスが見つかりません。")
        sys.exit(1)

    print("\n利用可能なマイク一覧（Enterで既定を使用）:")
    indices = []
    for n, info in enumerate(devs):
        di = int(info["index"])
        name = info.get("name", "unknown")
        rate = int(info.get("defaultSampleRate", 48000))
        ch   = int(info.get("maxInputChannels", 1))
        default_mark = " (既定)" if default_idx is not None and di == default_idx else ""
        print(f"  [{n}] index={di}, name='{name}', channels={ch}, defaultRate={rate}{default_mark}")
        indices.append(di)

    choice = input("マイク番号を選択してください（Enterで既定）: ").strip()
    if choice == "":
        if default_idx is not None:
            return default_idx
        return indices[0]
    try:
        n = int(choice)
        if not (0 <= n < len(indices)):
            raise ValueError
        return indices[n]
    except Exception:
        print("不正な入力です。既定のマイクを使用します。")
        if default_idx is not None:
            return default_idx
        return indices[0]

def dbfs_from_rms(rms):
    if rms <= 0:
        return -float('inf')
    # 16bitフルスケール=32768
    return 20.0 * math.log10(rms / 32768.0)

def main():
    pa = pyaudio.PyAudio()
    try:
        dev_index = pick_device(pa)
        info = pa.get_device_info_by_index(dev_index)

        # デバイス既定に追従
        rate = int(info.get("defaultSampleRate", 48000))
        # monoで読みたいが、どうしてもmono不可な機種なら2chに（稀）
        channels = 1 if int(info.get("maxInputChannels", 1)) >= 1 else 2

        print(f"\n=== Open device ===")
        print(f"index={dev_index}, name='{info.get('name','unknown')}', rate={rate}, channels={channels}")
        print("Ctrl-C で終了します。\n")

        stream = pa.open(format=pyaudio.paInt16,
                         channels=channels,
                         rate=rate,
                         input=True,
                         input_device_index=dev_index,
                         frames_per_buffer=FRAMES_PER_BUFFER,
                         start=True)

        last_print = 0.0
        peak_hold = 0
        peak_decay = 2000  # 表示上のピークホールド(サンプル値)の緩やか減衰

        while True:
            data = stream.read(FRAMES_PER_BUFFER, exception_on_overflow=False)
            # 16bitリトルエンディアン
            cnt = len(data) // 2
            if cnt == 0:
                continue
            samples = struct.unpack("<" + "h"*cnt, data)

            # mono計算（ステレオならLのみ見る。必要なら平均/最大に変更可）
            if channels > 1:
                mono = samples[::channels]
            else:
                mono = samples

            # ピーク & RMS
            abs_vals = [abs(x) for x in mono]
            peak = max(abs_vals)
            peak_hold = max(peak, int(peak_hold * 0.9))  # 疑似ホールド
            sq_sum = sum(v*v for v in mono)
            rms = math.sqrt(sq_sum / len(mono))

            now = time.time()
            if now - last_print >= PRINT_INTERVAL_SEC:
                last_print = now
                db = dbfs_from_rms(rms)
                # バー生成（-60dBFS～0dBFSを0～BAR_LENにマップ）
                bar_db = max(-60.0, min(0.0, db))
                fill = int((bar_db + 60.0) / 60.0 * BAR_LEN)
                bar = "#" * fill + "-" * (BAR_LEN - fill)
                clip = " CLIP!" if peak >= 32767 else ""
                # 上書き1行表示
                sys.stdout.write(f"\rPeak:{peak:5d}  RMS:{db:6.1f} dBFS  |{bar}|{clip}   ")
                sys.stdout.flush()

    except KeyboardInterrupt:
        print("\n終了します。")
    finally:
        try:
            if 'stream' in locals() and stream.is_active():
                stream.stop_stream()
        except Exception:
            pass
        try:
            if 'stream' in locals():
                stream.close()
        except Exception:
            pass
        pa.terminate()

if __name__ == "__main__":
    main()
