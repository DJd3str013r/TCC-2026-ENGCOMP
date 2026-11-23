# -*- coding: utf-8 -*-
"""Classificacao do alvo de cada valor de constante do tipo address (etapa 8, subsecao 3.6), automatica, na ordem:
endereco nulo; proprio contrato; conta sem codigo; conta externa com delegacao (EIP-7702); contrato verificado no
acervo (rede principal, com codigo implantado igual ao lido no bloco de referencia); contrato sem verificacao no
acervo. Alvos com codigo, inclusive o proprio contrato (desde a 1.7.0, P-15), recebem o indicador de
substituibilidade (compartimentos de implementacao e de beacon do ERC-1967 nao nulos)."""
import hashlib

from Crypto.Hash import keccak

from .config import PREFIXO_DELEGACAO, SLOT_BEACON, SLOT_IMPLEMENTACAO

NULO = "0x" + "00" * 20
CLASSES = ["endereco_nulo", "proprio_contrato", "conta_sem_codigo", "conta_externa_com_delegacao",
           "contrato_verificado_no_acervo", "contrato_sem_verificacao_no_acervo"]


def keccak256(b):
    k = keccak.new(digest_bits=256)
    k.update(b)
    return k.digest()


def substituibilidade(v, codigo, bloco, provedor):
    impl = provedor.armazenamento(v, SLOT_IMPLEMENTACAO, bloco)
    beacon = provedor.armazenamento(v, SLOT_BEACON, bloco)
    return {"substituivel": bool(impl or beacon), "erc1967_implementacao": hex(impl) if impl else None,
            "erc1967_beacon": hex(beacon) if beacon else None, "tamanho_codigo": len(codigo)}


def classificar(v, endereco, bloco, provedor, verificados):
    """v e endereco: '0x' + 40 hex minusculos. verificados(endereco) -> conjunto de resumos SHA-256 (hex) do codigo
    implantado registrado no instantaneo para esse endereco na rede principal (vazio se nao verificado)."""
    v = v.lower()
    if v == NULO:
        return {"classe": "endereco_nulo", "substituivel": None}
    codigo = provedor.codigo(v, bloco)
    if v == endereco.lower():
        return {"classe": "proprio_contrato", **substituibilidade(v, codigo, bloco, provedor)}
    if not codigo:
        return {"classe": "conta_sem_codigo", "substituivel": None}
    extra = substituibilidade(v, codigo, bloco, provedor)
    if len(codigo) == 23 and codigo[:3] == PREFIXO_DELEGACAO:
        return {"classe": "conta_externa_com_delegacao", "delegado": "0x" + codigo[3:].hex(), **extra}
    resumos = verificados(v)
    if resumos and hashlib.sha256(codigo).hexdigest() in resumos:   # o acervo guarda SHA-256 do codigo
        return {"classe": "contrato_verificado_no_acervo", **extra}
    return {"classe": "contrato_sem_verificacao_no_acervo", "verificado_com_outro_codigo": bool(resumos), **extra}
