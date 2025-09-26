# example.py
import time
from motor_controller import MotorController
from voicevox_pipelined import VoiceVoxTTSPipelined
from helper.halo_helper import HaloHelper

tts = VoiceVoxTTSPipelined(base_url="http://192.168.1.151:50021", speaker=89, max_len=80)
tts.set_params(speedScale=1.0, pitchScale=0.0, intonationScale=1.0)

halo_helper = HaloHelper()
config = halo_helper.load_config()
motor = MotorController(config)
tts.start_stream(motor_controller=motor, synth_workers=2, autoplay=False)  # 合成2並列
time.sleep(1)
print("start")
tts.talk_resume()
tts.push_text("こんにちは。")
time.sleep(0.2)
tts.push_text("今はパイプライン実装で、")
time.sleep(0.2)
tts.push_text("再生しながら同時に次の文を合成しています。")
tts.push_text("疑問文は上がり調子になりますか？")
time.sleep(1)
tts.push_text("しばらく待ってから話しています。")
tts.push_text("ちょっと長めの文章を話しています。少し長いかもしれません。")
time.sleep(1)

tts.close_stream()
tts.wait_until_idle()
tts.shutdown()
