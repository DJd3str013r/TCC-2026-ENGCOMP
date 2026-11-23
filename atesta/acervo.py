# -*- coding: utf-8 -*-
"""Acervo do Sourcify.

- Instantaneo: colunas necessarias das tabelas da exportacao Parquet v2 (contract_deployments, verified_contracts,
  compiled_contracts, sourcify_matches, contracts), baixadas uma vez para dados/instantaneo/ (ver instantaneo/).
- Dados de cada contrato sorteado (entrada de compilacao, codigo registrado, posicoes dos blocos de metadados,
  transformacoes): API v2 do Sourcify, com cache em disco e conferencia do identificador da verificacao (matchId)
  contra o vigente no instantaneo."""
import time

import requests

from .cache import Cache
from .config import SOURCIFY_API


class ErroAcervo(Exception):
    pass


class APISourcify:
    def __init__(self):
        self.cache = Cache("sourcify_api")
        self.sessao = requests.Session()

    def contrato(self, rede, endereco):
        chave = f"{rede}:{endereco.lower()}"
        v = self.cache.obter(chave)
        if v is not None:
            return v
        url = f"{SOURCIFY_API}/v2/contract/{rede}/{endereco}?fields=all"
        ultimo = None
        for tentativa in range(6):
            try:
                r = self.sessao.get(url, timeout=120)
                if r.status_code == 200:
                    v = r.json()
                    self.cache.gravar(chave, v)
                    return v
                if r.status_code == 404:
                    raise ErroAcervo(f"{chave}: nao encontrado na API")
                ultimo = f"HTTP {r.status_code} {r.text[:150]}"
            except requests.RequestException as e:
                ultimo = f"{type(e).__name__} {e}"
            time.sleep(3 * (tentativa + 1))
        raise ErroAcervo(f"{chave}: {ultimo}")


def bytes_hex(s):
    if s is None:
        return None
    return bytes.fromhex(s[2:] if s.startswith("0x") else s)
