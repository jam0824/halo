import asyncio
from bleak import BleakClient

ADDRESS = "69:96:1C:04:00:58"
CHAR_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"  # Write/Notify対象

async def main():
    async with BleakClient(ADDRESS) as client:
        print("Connected:", client.is_connected)

        # 車を前進させる
        await client.write_gatt_char(CHAR_UUID, b"A#")

        # 応答やセンサデータを受け取るコールバック
        def handle_rx(_, data: bytearray):
            print("RX:", data.decode(errors="ignore"))

        await client.start_notify(CHAR_UUID, handle_rx)

        # 10秒待ってみる
        await asyncio.sleep(10)

        await client.stop_notify(CHAR_UUID)

asyncio.run(main())