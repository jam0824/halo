import difflib


class TextSimilarity:
    """
    テキスト間の類似度を計算するユーティリティ。
    主に、テキストAとテキストBの部分文字列の最大類似度を推定する。
    """

    def __init__(self, min_ratio_window: float = 0.6, max_ratio_window: float = 1.4, coarse_step_divisor: int = 5, fine_step_divisor: int = 6) -> None:
        self.min_ratio_window = min_ratio_window
        self.max_ratio_window = max_ratio_window
        self.coarse_step_divisor = max(1, coarse_step_divisor)
        self.fine_step_divisor = max(1, fine_step_divisor)

    def calc_max_substring_similarity(self, a: str, b: str) -> tuple[float, str]:
        """
        a と b の部分一致の最大類似度を返す。
        戻り値: (score[0..1], b内の一致抜粋)
        """
        if not a or not b:
            return 0.0, ""
        a_norm = a.strip()
        b_norm = b.strip()

        target_len = max(1, len(a_norm))
        min_len = max(1, int(target_len * self.min_ratio_window))
        max_len_w = max(min_len, int(target_len * self.max_ratio_window))

        if len(b_norm) <= max_len_w:
            return difflib.SequenceMatcher(None, a_norm, b_norm).ratio(), b_norm

        best = 0.0
        best_sub = ""
        step_len = max(1, target_len // self.coarse_step_divisor)
        for L in range(min_len, max_len_w + 1, step_len):
            step = max(1, L // self.fine_step_divisor)
            for i in range(0, len(b_norm) - L + 1, step):
                sub = b_norm[i:i + L]
                r = difflib.SequenceMatcher(None, a_norm, sub).ratio()
                if r > best:
                    best = r
                    best_sub = sub
        return best, best_sub


