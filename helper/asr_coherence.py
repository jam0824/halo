# -*- coding: utf-8 -*-
from typing import List, Optional, Tuple
from collections import Counter
import re, math

class ASRCoherenceFilter:
    """
    音声認識テキストの破綻検知＆クレンジング
    - coherence_score(text): 0.0~1.0（高いほど一貫）
    - is_noisy(text): 破綻（ノイズ）かどうか
    - clean_text(text): 主要トピックに沿う文のみ抽出
    """
    # ====== クラス共通（正規表現・デフォ値） ======
    JP_SENT_SPLIT = re.compile(r'(?<=[。！？!?\n])')
    DEFAULT_FILLERS = {
        "えー","えっと","えーっと","あの","あのー","その","まー","まあ","なんか","みたいな",
        "うーん","え","えと","そのー"
    }

    def __init__(self, noisy_threshold: float = 0.45, min_fragment_chars: int = 8):
        self.noisy_threshold = noisy_threshold
        self.min_fragment_chars = min_fragment_chars
        self.fillers = set(self.DEFAULT_FILLERS)
        self._embedder = None  # lazy load

    # ====== 公開API ======
    def coherence_score(self, text: str) -> float:
        sents = self._split_sentences(text)
        if not sents:
            return 0.0
        # 単一文の扱いを優遇：十分な長さなら高スコアを初期付与し、繰り返しに軽いペナルティ
        if len(sents) == 1:
            s = sents[0]
            base = 1.0 if len(s) >= self.min_fragment_chars else 0.5
            toks = list(s)
            rep = self._repetition_ratio(toks, 2)
            penalty = 0.15 * min(1.0, rep * 3)
            return self._clip01(base - penalty)

        emb_coh = self._embedding_coherence(sents)  # Optional[float]

        # --- ヒューリスティック ---
        grams = [self._char_ngrams(s, 2) for s in sents]
        jac_sims = [self._jaccard(grams[i], grams[i+1]) for i in range(len(grams)-1)] or [0.0]
        jac_mean = sum(jac_sims) / len(jac_sims)

        frag = self._fragment_ratio(sents, self.min_fragment_chars)
        toks = list("".join(sents))
        rep = self._repetition_ratio(toks, 2)

        # --- 合成（埋め込みがあれば主、なければJaccard重視） ---
        if emb_coh is not None:
            score = 0.65 * self._clip01(emb_coh) + 0.25 * self._clip01(jac_mean)
        else:
            score = 0.90 * self._clip01(jac_mean)

        penalty = 0.10 * (0.6*frag + 0.4*min(1.0, rep*3))
        return self._clip01(score - penalty)

    def is_noisy(self, text: str, threshold: Optional[float] = None) -> Tuple[bool, float]:
        th = self.noisy_threshold if threshold is None else threshold
        score = self.coherence_score(text)
        print(f"破綻度: {score} :threshold: {th}")
        return score < th, score

    def clean_text(self, text: str, min_keep: int = 2) -> str:
        sents = self._split_sentences(text)
        if len(sents) <= 1:
            return text.strip()

        if self._ensure_embedder():
            import numpy as np
            V = self._embedder.encode(sents)
            sims_mat = self._cosine_mat(V)
            np.fill_diagonal(sims_mat, 0.0)
            center = int(sims_mat.sum(axis=1).argmax())
            order = sims_mat[center].argsort()[::-1]  # 近い順
            picked = [i for i in order if sims_mat[center, i] >= 0.35]
            if center not in picked:
                picked = [center] + picked
            picked = picked[:max(min_keep, math.ceil(len(sents)*0.5))]
            picked = sorted(set(picked))
            return " ".join([sents[i] for i in picked]).strip()
        else:
            grams = [self._char_ngrams(s, 2) for s in sents]
            neigh = []
            for i, gi in enumerate(grams):
                sims = [self._jaccard(gi, gj) for j, gj in enumerate(grams) if j != i]
                neigh.append(sum(sims) / max(1, len(sims)))
            center = int(max(range(len(neigh)), key=lambda i: neigh[i]))
            sims_to_center = [(self._jaccard(grams[center], g), idx) for idx, g in enumerate(grams)]
            sims_to_center.sort(reverse=True)
            picked = [idx for sim, idx in sims_to_center if sim >= 0.25]
            picked = picked[:max(min_keep, math.ceil(len(sents)*0.5))]
            picked = sorted(set(picked))
            return " ".join([sents[i] for i in picked]).strip()

    # ====== オプション設定 ======
    def add_fillers(self, *words: str):
        """フィラー（無意味語）を追加"""
        for w in words:
            if w:
                self.fillers.add(w)

    def set_noisy_threshold(self, value: float):
        self.noisy_threshold = float(value)

    # ====== 内部：前処理 ======
    def _normalize(self, text: str) -> str:
        t = re.sub(r'\s+', ' ', text.strip())
        # 句読点が無い長い塊に軽い区切りを入れる
        t = re.sub(r'([^\n]{80,}?)(\s+)', r'\1。 ', t)
        return t

    def _split_sentences(self, text: str) -> List[str]:
        text = self._normalize(text)
        sents = [s.strip() for s in self.JP_SENT_SPLIT.split(text) if s.strip()]
        cleaned = []
        for s in sents:
            s2 = re.sub(r'([、。,．，…]+)$', '', s)
            if s2 in self.fillers:
                continue
            cleaned.append(s)
        return cleaned

    # ====== 内部：ヒューリスティック ======
    @staticmethod
    def _char_ngrams(s: str, n: int = 2) -> Counter:
        s = re.sub(r'\s+', '', s)
        if len(s) < n:
            return Counter()
        return Counter([s[i:i+n] for i in range(len(s)-n+1)])

    @staticmethod
    def _jaccard(a: Counter, b: Counter) -> float:
        A, B = set(a), set(b)
        if not A and not B:
            return 1.0
        inter = len(A & B)
        union = len(A | B)
        return inter / union if union else 0.0

    @staticmethod
    def _repetition_ratio(tokens: List[str], k: int = 2) -> float:
        if len(tokens) < k:
            return 0.0
        grams = [tuple(tokens[i:i+k]) for i in range(len(tokens)-k+1)]
        from collections import Counter as C
        c = C(grams)
        repeats = sum(v for v in c.values() if v > 1)
        return repeats / max(1, len(grams))

    @staticmethod
    def _fragment_ratio(sents: List[str], min_chars: int) -> float:
        frags = sum(1 for s in sents if len(s) < min_chars)
        return frags / max(1, len(sents))

    @staticmethod
    def _clip01(x: float) -> float:
        return 0.0 if x < 0 else 1.0 if x > 1 else x

    # ====== 内部：埋め込み ======
    def _ensure_embedder(self) -> bool:
        if self._embedder is not None:
            return self._embedder is not False
        try:
            from sentence_transformers import SentenceTransformer
            self._embedder = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
            return True
        except Exception:
            self._embedder = False  # 明示的に無効
            return False

    def _embedding_coherence(self, sents: List[str]) -> Optional[float]:
        if not self._ensure_embedder() or len(sents) < 2:
            return None
        import numpy as np
        vecs = self._embedder.encode(sents)
        sims = [self._cosine(vecs[i], vecs[i+1]) for i in range(len(sents)-1)]
        return float(sum(sims)/len(sims)) if sims else None

    @staticmethod
    def _cosine(a, b) -> float:
        import numpy as np
        na = np.linalg.norm(a); nb = np.linalg.norm(b)
        if na == 0 or nb == 0:
            return 0.0
        return float((a @ b) / (na * nb))

    @staticmethod
    def _cosine_mat(V):
        import numpy as np
        n = np.linalg.norm(V, axis=1, keepdims=True)
        n[n == 0] = 1.0
        return (V @ V.T) / (n @ n.T)


# ====== 使用例 ======
if __name__ == "__main__":
    f = ASRCoherenceFilter(noisy_threshold=0.45)

    noisy = "えっと その 今日は売上の話を… えーっと… 明日の天気はどうかな ところで冷蔵庫が まあ みたいな 予算案は未確定です。"
    clean = "本件の売上は前年同期比で15%増加しました。要因は広告費の最適化と新規顧客の流入です。次四半期も同様の施策を継続します。"

    for t in [noisy, clean]:
        s = f.coherence_score(t)
        print("TEXT:", t)
        print("COHERENCE:", round(s, 3), "NOISY?", f.is_noisy(t))
        print("CLEANED:", f.clean_text(t))
        print("---")
