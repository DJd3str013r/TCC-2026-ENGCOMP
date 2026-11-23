# -*- coding: utf-8 -*-
"""Equacoes do Referencial: (2) proporcao estimada, (3) intervalo de escore de Wilson, (4) tamanho da amostra,
(5) intervalo hibrido de escore de Newcombe para a diferenca, (6) precisao e (7) revocacao."""
import math

from scipy.stats import norm

Z = float(norm.ppf(0.975))   # quantil de ordem 0,975 da normal padrao (z aproximadamente 1,96)


def proporcao(k, n):
    """Equacao (2)."""
    return k / n if n else float("nan")


def wilson(k, n, z=Z):
    """Equacao (3): limites (l, u) do intervalo de escore de Wilson."""
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    centro = p + z * z / (2 * n)
    raiz = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    den = 1 + z * z / n
    return ((centro - raiz) / den, (centro + raiz) / den)


def tamanho_amostra(e=0.05, p0=0.5, z=Z):
    """Equacao (4), arredondada para cima."""
    return math.ceil(z * z * p0 * (1 - p0) / (e * e)), z * z * p0 * (1 - p0) / (e * e)


def newcombe(k1, n1, k2, n2, z=Z):
    """Equacao (5): delta = p1 - p2 e limites (L, U) do metodo hibrido de escore (metodo 10 de Newcombe)."""
    p1, p2 = k1 / n1, k2 / n2
    l1, u1 = wilson(k1, n1, z)
    l2, u2 = wilson(k2, n2, z)
    d = p1 - p2
    L = d - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)
    U = d + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)
    return d, L, U


def precisao(vp, fp):
    """Equacao (6)."""
    return vp / (vp + fp) if (vp + fp) else float("nan")


def revocacao(vp, fn):
    """Equacao (7)."""
    return vp / (vp + fn) if (vp + fn) else float("nan")


def decisao_central(l, u, limiar=0.10):
    """Regra da hipotese central (subsecao 1 e 2.7): refutada se u < limiar, sustentada se l > limiar."""
    if u < limiar:
        return "refutada"
    if l > limiar:
        return "sustentada"
    return "inconclusiva"


def decisao_secundaria(L, U):
    """Regra da hipotese secundaria (2.7): sustentada se L > 0, refutada se U < 0, inconclusiva se contem o zero."""
    if L > 0:
        return "sustentada"
    if U < 0:
        return "refutada"
    return "inconclusiva"


def quartis(valores):
    import numpy as np
    a = np.asarray(sorted(valores), dtype=float)
    if a.size == 0:
        return {}
    return {"n": int(a.size), "minimo": float(a.min()), "q1": float(np.percentile(a, 25)),
            "mediana": float(np.median(a)), "q3": float(np.percentile(a, 75)), "maximo": float(a.max())}
