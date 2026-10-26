"""Воспроизводимая оценка ML-матчинга «товар -> виды работ».

Протоколы:
  random  — 5-fold CV по товарам (товары одного подтипа встречаются и в train, и в test);
  group   — 5-fold GroupKFold по подтипам товара: в тесте только подтипы, которых модель не видела
            (проверка обобщения на новые виды товаров, а не запоминания шаблонов);
  new     — обучение на всём каталоге, тест на отдельной выгрузке новых товаров (new_products.json).

Метрики: micro-F1 (основная, цель >= 0.8), macro-F1, samples-F1, точность пустого ответа для товаров
вне ремонта, nDCG@10 и MAP ранжирования товаров внутри вида работ, accuracy класса материала.

Запуск: python -m eval.evaluate   -> reports/metrics.json, reports/metrics.md
"""
import json
import resource
import sys
import time
from pathlib import Path

import numpy as np
from sklearn.metrics import average_precision_score, f1_score
from sklearn.model_selection import GroupKFold, KFold

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.ml.dataset import build, default_sets  # noqa: E402
from app.ml.embed import Embedder  # noqa: E402
from app.ml.features import Featurizer  # noqa: E402
from app.ml.matcher import WorkTypeMatcher  # noqa: E402
from app.config import DATASET  # noqa: E402
from app.taxonomy import work_type_name  # noqa: E402

REPORTS = ROOT / "reports"


def ndcg_at_k(y, s, k=10):
    order = np.argsort(-s)[:k]
    gains = y[order] / np.log2(np.arange(2, len(order) + 2))
    ideal = np.sort(y)[::-1][:k] / np.log2(np.arange(2, min(k, len(y)) + 2))
    return float(gains.sum() / ideal.sum()) if ideal.sum() else None


def metrics(Y, Yp, P, kinds=None, kinds_pred=None):
    out = {
        "micro_f1": f1_score(Y, Yp, average="micro", zero_division=0),
        "macro_f1": f1_score(Y, Yp, average="macro", zero_division=0),
        "samples_f1": f1_score(Y, Yp, average="samples", zero_division=1),
        "exact_match": float((Y == Yp).all(1).mean()),
    }
    none_mask = Y.sum(1) == 0
    if none_mask.any():
        out["out_of_scope_correct"] = float((Yp[none_mask].sum(1) == 0).mean())
    multi = Y.sum(1) >= 2
    if multi.any():
        out["multi_label_micro_f1"] = f1_score(Y[multi], Yp[multi], average="micro", zero_division=0)
    nd, ap = [], []
    for c in range(Y.shape[1]):
        if Y[:, c].sum():
            nd.append(ndcg_at_k(Y[:, c], P[:, c], 10))
            ap.append(average_precision_score(Y[:, c], P[:, c]))
    out["ndcg@10"] = float(np.mean(nd))
    out["map"] = float(np.mean(ap))
    if kinds is not None:  # класс материала важен только для ремонтных товаров
        ins = np.where(Y.sum(1) > 0)[0]
        out["kind_accuracy"] = float(np.mean([kinds[i] == kinds_pred[i] for i in ins]))
    out["per_class_f1"] = f1_score(Y, Yp, average=None, zero_division=0).round(3).tolist()
    out["support"] = Y.sum(0).tolist()
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in out.items()}


def sub(A, idx):
    return None if A is None else A[idx]


def cross_val(mode, F, d, splitter, groups=None, **kw):
    T, E, Z = F
    n = len(T)
    Yp = np.zeros_like(d["Y"])
    P = np.zeros(d["Y"].shape)
    kinds_pred = [None] * n
    for tr, te in splitter.split(np.zeros(n), groups=groups):
        m = WorkTypeMatcher(d["classes"], mode, **kw)
        m.fit([T[i] for i in tr], d["Y"][tr], sub(E, tr), sub(Z, tr), kinds=[d["kinds"][i] for i in tr])
        tt = [T[i] for i in te]
        Yp[te], P[te], kp, _ = m.predict_all(tt, sub(E, te), sub(Z, te))
        for j, i in enumerate(te):
            kinds_pred[i] = kp[j]
    return Yp, P, kinds_pred


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--no-ablation", action="store_true")
    args = ap.parse_args()
    t_start = time.perf_counter()
    cat_path, gold_path, new_path, new_gold_path = default_sets()
    d = build(cat_path, gold_path)
    dn = build(new_path, new_gold_path)
    emb = Embedder()

    t0 = time.perf_counter()
    feat = Featurizer(emb)
    F = feat(d["products"])
    Fn = feat(dn["products"])
    emb.save()
    t_embed = time.perf_counter() - t0

    report = {"dataset": {"products": len(d["texts"]), "new_products": len(dn["texts"]),
                          "work_types": len(d["classes"]), "subtypes": len(set(d["groups"])),
                          "multi_label_products": int((d["Y"].sum(1) >= 2).sum()),
                          "out_of_scope_products": int((d["Y"].sum(1) == 0).sum()),
                          "avg_labels": round(float(d["Y"].sum(1).mean()), 3)},
              "classes": d["classes"], "results": {}, "errors": {}}

    for mode in ("baseline", "hybrid"):
        res = {}
        Yp, P, kp = cross_val(mode, F, d, KFold(args.folds, shuffle=True, random_state=42))
        res["random_5fold"] = metrics(d["Y"], Yp, P, d["kinds"], kp)
        Yp, P, kp = cross_val(mode, F, d, GroupKFold(args.folds), groups=d["groups"])
        res["group_5fold_unseen_subtypes"] = metrics(d["Y"], Yp, P, d["kinds"], kp)
        if mode == "hybrid":
            report["errors"]["group"] = error_examples(d, Yp, P)

        t0 = time.perf_counter()
        m = WorkTypeMatcher(d["classes"], mode)
        m.fit(F[0], d["Y"], F[1], F[2], kinds=d["kinds"])
        t_train = time.perf_counter() - t0
        t0 = time.perf_counter()
        yp, p, kp, _ = m.predict_all(*Fn)
        t_pred = time.perf_counter() - t0
        res["new_products"] = metrics(dn["Y"], yp, p, dn["kinds"], kp)
        res["timing"] = {"train_s": round(t_train, 2), "predict_ms_per_product": round(1000 * t_pred / len(dn["texts"]), 3)}
        report["results"][mode] = res
        print(mode, {k: (v["micro_f1"], v["macro_f1"]) for k, v in res.items() if isinstance(v, dict) and "micro_f1" in v}, flush=True)

    # абляция гибрида на протоколе «новые подтипы»: вклад каждого компонента
    abl = {}
    ablations = () if args.no_ablation else (("без kNN", {"w_knn": 0.0}), ("без zero-shot вероятности", {"w_zs": 0.0}),
                                            ("без fallback top-1", {"fallback": 0.0}),
                                            ("только zero-shot+kNN, без логрегрессии", {"w_knn": 0.4, "w_zs": 0.6}))
    for name, kw in ablations:
        Yp, P, _ = cross_val("hybrid", F, d, GroupKFold(args.folds), groups=d["groups"], **kw)
        r = metrics(d["Y"], Yp, P)
        abl[name] = {k: r[k] for k in ("micro_f1", "macro_f1", "ndcg@10", "map")}
        print(name, abl[name], flush=True)
    report["ablation_group"] = abl

    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    report["resources"] = {
        "embedding_model": emb.model_name,
        "embed_time_s_all_products": round(t_embed, 2),
        "peak_rss_mb": round(rss / (1024 * 1024 if sys.platform == "darwin" else 1024), 1),
        "total_eval_time_s": round(time.perf_counter() - t_start, 1),
        "hardware": "Apple M1 Pro, 16 GB RAM (MPS)" if sys.platform == "darwin" else "see host",
    }
    REPORTS.mkdir(exist_ok=True)
    report["dataset"]["name"] = DATASET
    report["dataset"]["folds"] = args.folds
    (REPORTS / f"metrics_{DATASET}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))
    (REPORTS / f"metrics_{DATASET}.md").write_text(to_markdown(report))
    print(json.dumps({k: report[k] for k in ("ablation_group", "resources")}, ensure_ascii=False, indent=1))


def error_examples(d, Yp, P, n=20):
    rows = []
    for i in np.where((d["Y"] != Yp).any(1))[0]:
        name = d["catalog"].get(d["ids"][i])["name"]
        gold = [d["classes"][c] for c in np.where(d["Y"][i])[0]]
        pred = [d["classes"][c] for c in np.where(Yp[i])[0]]
        rows.append({"id": d["ids"][i], "subtype": d["groups"][i], "name": name, "gold": gold, "pred": pred})
    rng = np.random.default_rng(0)
    return [rows[i] for i in rng.permutation(len(rows))[:n]] if rows else []


def to_markdown(r):
    L = ["# Метрики ML-матчинга RepairCalc", "",
         f"Каталог: **{r['dataset']['products']}** товаров, {r['dataset']['subtypes']} подтипов, "
         f"{r['dataset']['work_types']} видов работ; товаров с несколькими видами работ — "
         f"{r['dataset']['multi_label_products']}, вне ремонта — {r['dataset']['out_of_scope_products']}. "
         f"Новые товары для проверки: {r['dataset']['new_products']}.", "",
         "| Модель | Протокол | micro-F1 | macro-F1 | samples-F1 | nDCG@10 | MAP | вне ремонта | multi-label F1 | класс материала |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    names = {"random_5fold": "5-fold, случайное", "group_5fold_unseen_subtypes": "5-fold, новые подтипы",
             "new_products": "новые товары"}
    for mode, res in r["results"].items():
        for proto, m in res.items():
            if proto == "timing":
                continue
            L.append(f"| {mode} | {names[proto]} | **{m['micro_f1']:.3f}** | {m['macro_f1']:.3f} | {m['samples_f1']:.3f} | "
                     f"{m['ndcg@10']:.3f} | {m['map']:.3f} | {m.get('out_of_scope_correct', 0):.3f} | "
                     f"{m.get('multi_label_micro_f1', 0):.3f} | {m.get('kind_accuracy', 0):.3f} |")
    if not r["ablation_group"]:
        L += ["", "_Абляция не запускалась (--no-ablation)._"]
    L += ["", "## Абляция гибридной модели (новые подтипы)", "", "| Вариант | micro-F1 | macro-F1 | nDCG@10 | MAP |", "|---|---|---|---|---|"]
    g = r["results"]["hybrid"]["group_5fold_unseen_subtypes"]
    L.append(f"| hybrid (полная) | {g['micro_f1']:.3f} | {g['macro_f1']:.3f} | {g['ndcg@10']:.3f} | {g['map']:.3f} |")
    for k, v in r["ablation_group"].items():
        L.append(f"| {k} | {v['micro_f1']:.3f} | {v['macro_f1']:.3f} | {v['ndcg@10']:.3f} | {v['map']:.3f} |")
    L += ["", "## F1 по видам работ (hybrid)", "", "| Вид работ | support | F1 случайное | F1 новые подтипы | F1 новые товары |", "|---|---|---|---|---|"]
    h = r["results"]["hybrid"]
    for i, c in enumerate(r["classes"]):
        L.append(f"| {work_type_name(c)} | {h['random_5fold']['support'][i]} | {h['random_5fold']['per_class_f1'][i]:.2f} | "
                 f"{h['group_5fold_unseen_subtypes']['per_class_f1'][i]:.2f} | {h['new_products']['per_class_f1'][i]:.2f} |")
    L += ["", "## Производительность", ""]
    for mode, res in r["results"].items():
        L.append(f"- {mode}: обучение {res['timing']['train_s']} с, инференс {res['timing']['predict_ms_per_product']} мс/товар")
    rs = r["resources"]
    L += [f"- эмбеддинги ({rs['embedding_model']}) для всего каталога: {rs['embed_time_s_all_products']} с (с кэшем — мгновенно)",
          f"- пиковая память процесса оценки: {rs['peak_rss_mb']} МБ; железо: {rs['hardware']}",
          f"- полное время оценки: {rs['total_eval_time_s']} с", "",
          "## Примеры ошибок (новые подтипы)", "", "| Товар | Эталон | Предсказание |", "|---|---|---|"]
    for e in r["errors"].get("group", []):
        L.append(f"| {e['name']} | {', '.join(e['gold']) or '—'} | {', '.join(e['pred']) or '—'} |")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    main()
