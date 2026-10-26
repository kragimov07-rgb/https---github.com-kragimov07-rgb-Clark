"""ML-матчинг товаров к видам работ (multi-label) и к классу материала (multi-class).

baseline: TF-IDF (слова) + логистическая регрессия one-vs-rest.
hybrid:   1) логрегрессия OvR на TF-IDF (слова + символьные n-граммы) + эмбеддинги e5
             + zero-shot сходства со справочником;
          2) kNN по эмбеддингам (голосование похожих размеченных товаров);
          3) zero-shot вероятность: калибратор, общий для всех видов работ, переводит сходство
             товара с типовыми материалами вида работ в вероятность — работает и для видов товаров,
             которых не было в обучении.
          Итог — взвешенная смесь; пороги подбираются по каждому виду работ на out-of-fold.
"""
import os
import warnings

import joblib
import numpy as np
from scipy import sparse
from sklearn.exceptions import ConvergenceWarning
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold, KFold
from sklearn.multiclass import OneVsRestClassifier

warnings.filterwarnings("ignore", category=UserWarning, module="sklearn.multiclass")
warnings.filterwarnings("ignore", category=ConvergenceWarning)

N_JOBS = int(os.getenv("RC_NJOBS", "4"))  # процессов для one-vs-rest: больше -> риск свопа на 16 ГБ
THRESH_GRID = np.round(np.arange(0.15, 0.81, 0.05), 2)
WORD_TOKENS = r"(?u)\b[^\W\d_]{2,}\b"  # только слова, без артикулов и чисел


def f1_binary(y, p):
    tp = float((y & p).sum())
    fp = float((~y & p).sum())
    fn = float((y & ~p).sum())
    return 2 * tp / (2 * tp + fp + fn) if tp else 0.0


def zs_features(Z):
    """Признаки zero-shot калибратора для каждой пары (товар, вид работ)."""
    top = Z.max(1, keepdims=True)
    rank = (-Z).argsort(1).argsort(1)
    return np.stack([Z, Z - top, (rank == 0).astype(float), (rank < 3).astype(float)], axis=-1)


class WorkTypeMatcher:
    def __init__(self, classes, mode="hybrid", knn_k=10, w_knn=0.25, w_zs=0.35, fallback=0.3,
                 tune_thresholds=True, group_tuning=False):
        assert mode in ("baseline", "hybrid")
        self.classes = list(classes)
        self.mode = mode
        self.knn_k, self.w_knn, self.w_zs = knn_k, w_knn, w_zs
        self.fallback = fallback  # если ни один вид работ не прошёл порог — берём лучший при P >= fallback
        self.tune_thresholds = tune_thresholds
        self.group_tuning = group_tuning
        self.thresholds = np.full(len(classes), 0.5)

    def _params(self):
        return dict(knn_k=self.knn_k, w_knn=self.w_knn, w_zs=self.w_zs, fallback=self.fallback)

    # ---------- признаки ----------
    def _features(self, texts, E, Z):
        X = [self.v_word.transform(texts)]
        if self.mode == "hybrid":
            X.append(self.v_char.transform(texts))
            if E is not None:
                X.append(sparse.csr_matrix(E * 1.5))
                X.append(sparse.csr_matrix(Z * 3.0))
        return sparse.hstack(X).tocsr()

    # ---------- обучение ----------
    def _fit_core(self, texts, Y, E, Z):
        self.v_word = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, max_features=30000,
                                      token_pattern=WORD_TOKENS)
        self.v_word.fit(texts)
        if self.mode == "hybrid":
            self.v_char = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=2, sublinear_tf=True,
                                          max_features=30000)
            self.v_char.fit(texts)
        X = self._features(texts, E, Z)
        self.clf = OneVsRestClassifier(LogisticRegression(C=8.0 if self.mode == "hybrid" else 10.0, max_iter=1000,
                                                          class_weight="balanced", solver="liblinear"), n_jobs=N_JOBS)
        self.clf.fit(X, Y)
        self.use_emb = self.mode == "hybrid" and E is not None
        self.E_train, self.Y_train = (E, Y) if self.use_emb else (None, None)
        if self.use_emb:
            F = zs_features(Z).reshape(-1, 4)
            self.zs = LogisticRegression(C=1.0, max_iter=1000).fit(F, Y.reshape(-1))
            # шлюз «товар относится к ремонту»: отсекает сад, быт и т.п. до назначения видов работ
            in_scope = (Y.sum(1) > 0).astype(int)
            G = self._gate_features(E, Z)
            self.gate = LogisticRegression(C=2.0, max_iter=2000, class_weight="balanced").fit(G, in_scope) \
                if 0 < in_scope.sum() < len(in_scope) else None

    @staticmethod
    def _gate_features(E, Z):
        zs = np.sort(Z, 1)[:, ::-1]
        return np.hstack([E, zs[:, :3] * 5])

    def _proba_core(self, texts, E, Z):
        P = self.clf.predict_proba(self._features(texts, E, Z))
        if self.use_emb and E is not None:
            Pk = self._knn(E)
            Pz = self.zs.predict_proba(zs_features(Z).reshape(-1, 4))[:, 1].reshape(Z.shape)
            P = (1 - self.w_knn - self.w_zs) * P + self.w_knn * Pk + self.w_zs * Pz
            if self.gate is not None:
                g = self.gate.predict_proba(self._gate_features(E, Z))[:, 1]
                P = P * np.clip(g / 0.5, 0, 1)[:, None]  # при g < 0.5 вероятности пропорционально гасятся
        return P

    def _knn(self, E, batch=2048):
        out = np.zeros((len(E), self.Y_train.shape[1]))
        k = min(self.knn_k, len(self.E_train))
        for s in range(0, len(E), batch):  # батчами: для 80k товаров полная матрица сходства не помещается в память
            S = E[s:s + batch] @ self.E_train.T
            idx = np.argpartition(-S, k - 1, axis=1)[:, :k]
            w = np.take_along_axis(S, idx, axis=1).clip(min=0) ** 3
            votes = (w[:, :, None] * self.Y_train[idx]).sum(1)
            out[s:s + batch] = votes / np.maximum(w.sum(1, keepdims=True), 1e-9)
        return out

    def fit(self, texts, Y, E=None, Z=None, kinds=None, max_negatives=20000, seed=0, groups=None):
        """groups (например, категории каталога): пороги подбираются на out-of-fold по группам —
        настроены на обобщение на новые категории, а не на запоминание знакомых."""
        Y = np.asarray(Y, dtype=int)
        if self.mode == "baseline":
            E = Z = None
        # большой каталог: товары вне ремонта прореживаются (все ремонтные товары остаются)
        neg = np.where(Y.sum(1) == 0)[0]
        if len(neg) > max_negatives:
            keep = np.sort(np.concatenate([np.where(Y.sum(1) > 0)[0],
                                           np.random.default_rng(seed).choice(neg, max_negatives, replace=False)]))
            texts = [texts[i] for i in keep]
            Y = Y[keep]
            E = None if E is None else E[keep]
            Z = None if Z is None else Z[keep]
            kinds = None if kinds is None else [kinds[i] for i in keep]
            groups = None if groups is None else [groups[i] for i in keep]
        if self.tune_thresholds:
            self._tune(texts, Y, E, Z, groups if self.group_tuning else None)
        self._fit_core(texts, Y, E, Z)
        if kinds is not None:
            pos = np.where(Y.sum(1) > 0)[0]  # класс материала нужен только ремонтным товарам
            Xk = self._features([texts[i] for i in pos], None if E is None else E[pos], None if Z is None else Z[pos])
            # one-vs-rest liblinear параллельно по классам: в разы быстрее мультиклассового lbfgs на 30k+ товаров
            self.kind_clf = OneVsRestClassifier(LogisticRegression(C=10.0, solver="liblinear", max_iter=1000),
                                                n_jobs=N_JOBS).fit(Xk, [kinds[i] for i in pos])
        return self

    def _tune(self, texts, Y, E, Z, groups=None):
        """Подбор порога по каждому виду работ на out-of-fold предсказаниях (3 фолда; по группам, если заданы)."""
        sub = lambda A, idx: None if A is None else A[idx]  # noqa: E731
        if len(texts) > 30000:  # подбор порогов на подвыборке — быстрее и достаточно для 26 порогов
            s = np.sort(np.random.default_rng(1).choice(len(texts), 30000, replace=False))
            texts, Y, E, Z = [texts[i] for i in s], Y[s], sub(E, s), sub(Z, s)
            groups = None if groups is None else [groups[i] for i in s]
        oof = np.zeros(Y.shape, dtype=float)
        splitter = GroupKFold(3).split(texts, groups=groups) if groups is not None else \
            KFold(3, shuffle=True, random_state=0).split(texts)
        for tr, va in splitter:
            m = WorkTypeMatcher(self.classes, self.mode, tune_thresholds=False, **self._params())
            m._fit_core([texts[i] for i in tr], Y[tr], sub(E, tr), sub(Z, tr))
            oof[va] = m._proba_core([texts[i] for i in va], sub(E, va), sub(Z, va))
        Yb = Y.astype(bool)
        glob = max(THRESH_GRID, key=lambda t: f1_binary(Yb.ravel(), (oof >= t).ravel()))
        th = np.full(Y.shape[1], glob)
        for c in range(Y.shape[1]):
            if Y[:, c].sum() >= 8:
                th[c] = max(THRESH_GRID, key=lambda t: (f1_binary(Yb[:, c], oof[:, c] >= t), -abs(t - glob)))
        self.thresholds = th
        if self.fallback:
            # порог fallback подбираем так, чтобы не ломать распознавание товаров вне ремонта
            def score(fb):
                self.fallback = fb
                return f1_binary(Yb.ravel(), self.decide(oof).astype(bool).ravel())
            self.fallback = max([0.0, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5], key=score)

    # ---------- предсказание ----------
    def predict_proba(self, texts, E=None, Z=None):
        if self.mode == "baseline":
            E = Z = None
        return self._proba_core(texts, E, Z)

    def decide(self, P):
        Yp = (P >= self.thresholds).astype(int)
        if self.fallback:
            empty = Yp.sum(1) == 0
            best = P.argmax(1)
            ok = empty & (P[np.arange(len(P)), best] >= self.fallback)
            Yp[np.where(ok)[0], best[ok]] = 1
        return Yp

    def predict(self, texts, E=None, Z=None):
        P = self.predict_proba(texts, E, Z)
        return self.decide(P), P

    def predict_kind(self, texts, E=None, Z=None):
        if not hasattr(self, "kind_clf"):
            return [None] * len(texts), np.zeros(len(texts))
        if self.mode == "baseline":
            E = Z = None
        Pk = self.kind_clf.predict_proba(self._features(texts, E, Z))
        return [self.kind_clf.classes_[i] for i in Pk.argmax(1)], Pk.max(1)

    def predict_all(self, texts, E=None, Z=None):
        """Виды работ + класс материала; товарам без видов работ класс «other»."""
        Yp, P = self.predict(texts, E, Z)
        kinds, kconf = self.predict_kind(texts, E, Z)
        kinds = [k if Yp[i].any() else "other" for i, k in enumerate(kinds)]
        return Yp, P, kinds, kconf

    def neighbors(self, e_row, k=5):
        if self.E_train is None:
            return [], []
        s = self.E_train @ e_row
        idx = np.argsort(-s)[:k]
        return idx.tolist(), s[idx].tolist()

    def save(self, path):
        joblib.dump(self, path, compress=3)

    @staticmethod
    def load(path) -> "WorkTypeMatcher":
        return joblib.load(path)
