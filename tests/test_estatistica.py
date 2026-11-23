# -*- coding: utf-8 -*-
"""Equacoes (2) a (7) conferidas contra referencias independentes."""
import math

import pytest
from scipy.stats import binomtest

from atesta.estatistica import (Z, decisao_central, decisao_secundaria, newcombe, precisao, revocacao,
                                tamanho_amostra, wilson)


@pytest.mark.parametrize("k,n", [(0, 10), (1, 10), (5, 40), (37, 385), (100, 385), (385, 385)])
def test_wilson_igual_ao_scipy(k, n):
    l, u = wilson(k, n)
    ref = binomtest(k, n).proportion_ci(confidence_level=0.95, method="wilson")
    assert l == pytest.approx(ref.low, abs=1e-12)
    assert u == pytest.approx(ref.high, abs=1e-12)


def test_newcombe_exemplo_do_artigo_original():
    # Newcombe (1998), exemplo 56/70 x 48/80: metodo 10 (hibrido de escore) = 0,0524 a 0,3339
    d, L, U = newcombe(56, 70, 48, 80)
    assert d == pytest.approx(0.2)
    assert L == pytest.approx(0.0524, abs=5e-5)
    assert U == pytest.approx(0.3339, abs=5e-5)


def test_tamanho_da_amostra_385():
    n, bruto = tamanho_amostra(z=1.96)
    assert bruto == pytest.approx(384.16)
    assert n == 385
    assert tamanho_amostra()[0] == 385


def test_semiamplitude_de_wilson_nao_excede_e_com_385():
    pior = max((wilson(k, 385)[1] - wilson(k, 385)[0]) / 2 for k in range(386))
    assert pior <= 0.05
    # com mais de quatro perdas a garantia deixa de valer (subsecao 3.8)
    assert max((wilson(k, 381)[1] - wilson(k, 381)[0]) / 2 for k in range(382)) <= 0.05
    assert max((wilson(k, 380)[1] - wilson(k, 380)[0]) / 2 for k in range(381)) > 0.05


def test_regras_de_decisao():
    assert decisao_central(0.02, 0.08) == "refutada"
    assert decisao_central(0.12, 0.20) == "sustentada"
    assert decisao_central(0.08, 0.13) == "inconclusiva"
    assert decisao_secundaria(0.01, 0.2) == "sustentada"
    assert decisao_secundaria(-0.2, -0.01) == "refutada"
    assert decisao_secundaria(-0.1, 0.1) == "inconclusiva"


def test_precisao_revocacao():
    assert precisao(3, 0) == 1 and revocacao(3, 0) == 1
    assert precisao(1, 1) == 0.5 and revocacao(1, 3) == 0.25
    assert math.isnan(precisao(0, 0))
    assert Z == pytest.approx(1.959963984540054)
