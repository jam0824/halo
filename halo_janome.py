# 使う前に必要ならインストールしてください:
# pip install janome
# （SudachiPyも使う場合）pip install sudachipy sudachidict-core

from typing import List, Iterable, Literal, Optional
import os
import json
import asyncio
import random

class JapaneseNounExtractor:
    """
    日本語の形態素解析を行い、一般名詞 or 固有名詞のみを返すユーティリティ。
    engine='janome'（既定）または 'sudachi' を選べます。

    Parameters
    ----------
    engine : Literal['janome', 'sudachi']
        使用する形態素解析エンジン。既定は 'janome'。
    normalize : bool
        見出し語（基本形）で返すかどうか。既定 True（表記ゆれを抑えたいときに便利）。
    unique : bool
        重複を削除して返すか。既定 False（出現順を保持）。
    """

    def __init__(
        self,
        engine: Literal['janome', 'sudachi'] = 'janome',
        normalize: bool = True,
        unique: bool = False,
    ):
        self.engine = engine
        self.normalize = normalize
        self.unique = unique
        self.count = 0
        self.is_speak_filler = False
        self.list_keyword_templates = self.load_keyword_templates()

        if engine == 'janome':
            from janome.tokenizer import Tokenizer
            self._tokenizer = Tokenizer()
        elif engine == 'sudachi':
            # SudachiPy は辞書が必要です。標準辞書: sudachidict-core
            from sudachipy import dictionary, tokenizer
            self._tokenizer = dictionary.Dictionary().create()
            self._mode = tokenizer.Tokenizer.SplitMode.C  # C=最長単位、A=細かく
        else:
            raise ValueError("engine must be 'janome' or 'sudachi'")

    def load_keyword_templates(self, path: Optional[str] = None) -> List[str]:
        try:
            base_dir = os.path.dirname(__file__)
            json_path = path or os.path.join(base_dir, "keyword_filler.json")
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            list_templates = data.get("keyword_filler", [])
            if not isinstance(list_templates, list):
                list_templates = []
            self.list_keyword_templates = list_templates
            return list_templates
        except Exception as e:
            try:
                print(f"keyword_filler.json 読み込みエラー: {e}")
            except Exception:
                pass
            return []

    def extract(self, text: str) -> List[str]:
        """テキストから一般名詞・固有名詞のみを抽出して返します。"""
        if not text:
            return []

        if self.engine == 'janome':
            nouns = self._extract_janome(text)
        else:
            nouns = self._extract_sudachi(text)

        if self.unique:
            seen = set()
            deduped = []
            for n in nouns:
                if n not in seen:
                    seen.add(n)
                    deduped.append(n)
            return deduped
        return nouns

    # 関数呼び出し風に使えるように
    __call__ = extract

    # --- 内部実装: Janome ---
    def _extract_janome(self, text: str) -> List[str]:
        """
        Janome の品詞体系（例）:
          名詞,一般 / 名詞,固有名詞,人名,... / 名詞,サ変接続 など
        """
        results: List[str] = []
        for t in self._tokenizer.tokenize(text):
            pos = t.part_of_speech.split(',')  # e.g. ['名詞', '固有名詞', '一般', '*']
            if pos[0] != '名詞':
                continue
            # 一般名詞または固有名詞だけ採用
            is_common = len(pos) > 1 and pos[1] == '一般'
            is_proper = len(pos) > 1 and pos[1] == '固有名詞'
            if not (is_common or is_proper):
                continue

            surface = t.base_form if self.normalize and t.base_form != '*' else t.surface
            # 空文字/記号除去の簡易チェック
            if surface and surface.isascii() is False or surface:
                results.append(surface)
        return results

    # --- 内部実装: SudachiPy ---
    def _extract_sudachi(self, text: str) -> List[str]:
        """
        Sudachi の品詞体系（例）:
          ['名詞','普通名詞','一般',...], ['名詞','固有名詞','人名',...]
        '普通名詞' or '固有名詞' を対象にします。
        """
        results: List[str] = []
        for m in self._tokenizer.tokenize(text, self._mode):
            pos = m.part_of_speech()  # tuple
            if len(pos) < 2 or pos[0] != '名詞':
                continue
            is_common = pos[1] in ('普通名詞', '一般')  # dictにより末端の語が'一般'になる場合がある
            is_proper = pos[1] == '固有名詞'
            if not (is_common or is_proper):
                continue

            surface = m.normalized_form() if self.normalize else m.surface()
            if surface:
                results.append(surface)
        return results
        
    async def make_keyword_filler_async(self, text: str) -> str:
        nouns = await asyncio.to_thread(self.extract, text)
        print(nouns)
        if nouns != [] and not self.is_speak_filler:
            self.count += 1
            if self.count >= 2:
                self.is_speak_filler = True
                return random.choice(self.list_keyword_templates).format(keyword=nouns[0])
        return ""
    def reset_keyword_filler(self) -> None:
        self.count = 0
        self.is_speak_filler = False
        return

    


# ========== 使用例 ==========
if __name__ == "__main__":
    text = "昨日、東京スカイツリーでイベントがあり、任天堂の新作ゲームが話題になりました。"

    # Janome（既定）
    extractor = JapaneseNounExtractor(engine="janome", normalize=True, unique=True)
    print(extractor.extract(text))
    # 例）['昨日', '東京', 'スカイツリー', 'イベント', '任天堂', '新作', 'ゲーム', '話題']

    # SudachiPy を使う場合
    # extractor2 = JapaneseNounExtractor(engine="sudachi", normalize=True, unique=False)
    # print(extractor2(text))
