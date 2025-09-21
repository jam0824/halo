from helper.wav_player import WavPlayer

class Filler:
    player = None
    isfiller = False
    def __init__(self, is_filler: bool, filler_dir: str):
        self.isfiller = is_filler
        if is_filler:
            self.player = WavPlayer()
            self.player.preload_dir(filler_dir)

    def say_filler(self) -> bool:
        if self.player is None or not self.isfiller:
            return False
        self.player.random_play(block=False)
        print("filler再生中")
        return True
    
    def stop_filler(self) -> bool:
        if self.player is None or not self.isfiller:
            return False
        self.player.stop()
        print("filler再生停止")
        return True
            