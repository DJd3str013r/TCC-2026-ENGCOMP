# -*- coding: utf-8 -*-
"""Leitura da cadeia por JSON-RPC (eth_getCode, eth_getStorageAt, eth_getBlockByNumber), sempre em bloco fixo, com
varios nos de reserva e cache em disco. Tambem ha um provedor em memoria (py-evm) para os contratos-controle."""
import json
import time

import requests

from .cache import Cache
from .config import RPCS_REDE_PRINCIPAL


class ErroRPC(Exception):
    pass


class RPC:
    """Cliente JSON-RPC com reserva entre nos e cache por (metodo, parametros). So aceita bloco numerico: leitura
    em 'latest' nao e reproduzivel e nao entra no cache."""

    def __init__(self, urls=None, nome_cache="rpc_rede_principal"):
        self.urls = list(urls or RPCS_REDE_PRINCIPAL)
        self.cache = Cache(nome_cache)
        self.sessao = requests.Session()
        self.chamadas_rede = 0

    def _chamar(self, metodo, params):
        ultimo = None
        for tentativa in range(6):
            for url in self.urls:
                try:
                    r = self.sessao.post(url, json={"jsonrpc": "2.0", "id": 1, "method": metodo, "params": params},
                                         timeout=60)
                    self.chamadas_rede += 1
                    if r.status_code != 200:
                        ultimo = f"{url}: HTTP {r.status_code} {r.text[:120]}"
                        continue
                    d = r.json()
                    if "error" in d:
                        ultimo = f"{url}: {d['error']}"
                        continue
                    return d["result"]
                except (requests.RequestException, ValueError) as e:
                    ultimo = f"{url}: {type(e).__name__} {e}"
            time.sleep(2 * (tentativa + 1))
        raise ErroRPC(f"{metodo}{params}: {ultimo}")

    def chamar(self, metodo, params, cache=True):
        chave = metodo + json.dumps(params, separators=(",", ":"))
        if cache:
            v = self.cache.obter(chave)
            if v is not None:
                return v
        v = self._chamar(metodo, params)
        if cache and v is not None:
            self.cache.gravar(chave, v)
        return v

    @staticmethod
    def _bloco(bloco):
        if not isinstance(bloco, int):
            raise ValueError("bloco deve ser numerico (leitura ancorada)")
        return hex(bloco)

    def codigo(self, endereco, bloco):
        return bytes.fromhex(self.chamar("eth_getCode", [endereco.lower(), self._bloco(bloco)])[2:])

    def armazenamento(self, endereco, posicao, bloco):
        return int(self.chamar("eth_getStorageAt", [endereco.lower(), hex(posicao), self._bloco(bloco)]), 16)

    def bloco(self, numero):
        return self.chamar("eth_getBlockByNumber", [self._bloco(numero), False])

    def ultimo_bloco(self):
        return int(self.chamar("eth_blockNumber", [], cache=False), 16)


class ProvedorMemoria:
    """Mesma interface do RPC sobre uma cadeia py-evm em memoria (contratos-controle)."""

    def __init__(self, cadeia):
        self.cadeia = cadeia

    def _estado(self, bloco):
        cab = self.cadeia.get_canonical_block_header_by_number(bloco)
        return self.cadeia.get_vm(cab).state

    def codigo(self, endereco, bloco):
        return bytes(self._estado(bloco).get_code(bytes.fromhex(endereco[2:])))

    def armazenamento(self, endereco, posicao, bloco):
        return self._estado(bloco).get_storage(bytes.fromhex(endereco[2:]), posicao)

    def bloco(self, numero):
        cab = self.cadeia.get_canonical_block_header_by_number(numero)
        return {"number": hex(cab.block_number), "hash": "0x" + cab.hash.hex(), "timestamp": hex(cab.timestamp)}
