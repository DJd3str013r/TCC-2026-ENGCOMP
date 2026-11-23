# -*- coding: utf-8 -*-
"""Etapa 7 (subsecao 3.6): para um contrato, le c_a no bloco de referencia, recompila com a entrada do acervo,
delimita F(a), atribui construto e valor a cada regiao, calcula C(a) (Equacao 1) e o indicador da Equacao (2), e
emite a certidao. A classificacao do alvo (etapa 8) e acrescentada a certidao por classificar_certidao()."""
import re
import time

from . import VERSAO
from .classificacao import NULO, classificar, keccak256
from .compilador import ErroCompilacao, compilar
from .regioes import FalhaInstrumento, cobertura, confronto_acervo, constantes, delimitar, para_dict

ESQUEMA = "certidao-atesta/1"
GRAUS = {"exact_match": "exata", "perfect": "exata", "match": "parcial", "partial": "parcial"}


def grau(registro_api, campo="runtimeMatch"):
    """Grau de correspondencia do codigo de execucao (ou, com campo='creationMatch', do de criacao): 'exata'
    (exact_match) ou 'parcial' (match); None se o acervo nao registra correspondencia."""
    m = registro_api.get(campo)
    return GRAUS.get(m, m)


def literais_no_codigo_de_criacao(objeto_criacao, valores):
    """Valores de 20 bytes (exceto o endereco nulo) que aparecem no codigo de criacao recompilado, isto e, que
    constam do proprio codigo compilado; marcadores de biblioteca ('__...__', 40 caracteres) viram zeros."""
    h = re.sub(r"__.{36}__", "0" * 40, (objeto_criacao or "")[2:] if (objeto_criacao or "").startswith("0x")
               else (objeto_criacao or ""))
    try:
        criacao = bytes.fromhex(h)
    except ValueError:
        return None
    return [v for v in valores if v != NULO and bytes.fromhex(v[2:]) in criacao]


CHAVES_METADADOS = ("evmVersion", "metadata", "viaIR", "optimizer", "remappings")


def entrada_completa(registro_api):
    """Entrada de compilacao do acervo, completada com as configuracoes que o arquivo de metadados do proprio contrato
    registra e que a entrada armazenada omite (por exemplo, evmVersion), sem sobrescrever o que ja existe. As
    bibliotecas, no formato 'arquivo:Nome' dos metadados, sao convertidas para o formato da entrada padrao."""
    import copy
    std = copy.deepcopy(registro_api["stdJsonInput"])
    ajustes = std.setdefault("settings", {})
    meta = ((registro_api.get("metadata") or {}).get("settings") or {})
    acrescidas = []
    for k in CHAVES_METADADOS:
        if k in meta and k not in ajustes:
            ajustes[k] = copy.deepcopy(meta[k])
            acrescidas.append(k)
    libs_meta = meta.get("libraries") or {}
    if libs_meta and not ajustes.get("libraries"):
        conv = {}
        for chave, end in libs_meta.items():
            arq, _, nome = chave.rpartition(":")
            conv.setdefault(arq, {})[nome] = end
        ajustes["libraries"] = conv
        acrescidas.append("libraries")
    return std, acrescidas


def verificar(endereco, bloco, provedor, registro_api, rede=1):
    """Devolve a certidao (dict). Em falha do instrumento, a certidao sai com situacao 'falha' e a causa."""
    t0 = time.time()
    rt = registro_api.get("runtimeBytecode") or {}
    comp_info = registro_api.get("compilation") or {}
    cert = {
        "esquema": ESQUEMA,
        "verificador": {"nome": "atesta", "versao": VERSAO},
        "contrato": {"rede": rede, "endereco": endereco.lower(), "bloco_referencia": bloco},
        "acervo": {"match_id": registro_api.get("matchId"), "grau_codigo_execucao": grau(registro_api),
                   "grau_codigo_criacao": grau(registro_api, "creationMatch"),
                   "compilador": comp_info.get("compilerVersion"), "linguagem": comp_info.get("language"),
                   "contrato_compilado": comp_info.get("fullyQualifiedName"),
                   "verificado_em": registro_api.get("verifiedAt")},
    }
    c_a = provedor.codigo(endereco, bloco)
    cert["contrato"]["tamanho_codigo"] = len(c_a)
    cert["contrato"]["resumo_codigo"] = "0x" + keccak256(c_a).hex()
    try:
        fqn = comp_info["fullyQualifiedName"]
        arquivo, nome = fqn.rsplit(":", 1)
        std, acrescidas = entrada_completa(registro_api)
        comp = compilar(std, comp_info["compilerVersion"], arquivo, nome)
        regioes, info = delimitar(c_a, comp, arquivo, nome, rt.get("cborAuxdata"), rt.get("transformations"))
        info["ajustes_dos_metadados"] = acrescidas
        info["motor"] = comp.get("motor")
    except (ErroCompilacao, FalhaInstrumento, KeyError, ValueError) as e:
        cert.update({"situacao": "falha", "causa": f"{type(e).__name__}: {e}", "segundos": round(time.time() - t0, 1)})
        return cert
    consts = para_dict(constantes(regioes, endereco))
    for c in consts:
        if c["tau_address"]:
            c["literais_no_codigo_de_criacao"] = literais_no_codigo_de_criacao(comp.get("objeto_criacao"), c["valores"])
    cert.update({
        "situacao": "processado",
        "recompilacao": info,
        "regioes": para_dict(regioes),
        "constantes": consts,
        "cobertura": cobertura(regioes, len(c_a)),
        "bytes_nao_atestados": sum(r.comprimento for r in regioes),
        "indicador_equacao_2": int(any(c["tau_address"] for c in consts)),
        "confronto_acervo": confronto_acervo(regioes, rt.get("transformations")),
        "segundos": round(time.time() - t0, 1),
    })
    return cert


def classificar_certidao(cert, provedor, verificados):
    """Etapa 8: classe do alvo de cada valor de constante do tipo address e substituibilidade."""
    if cert.get("situacao") != "processado":
        return cert
    end, bloco = cert["contrato"]["endereco"], cert["contrato"]["bloco_referencia"]
    for c in cert["constantes"]:
        if c["tau_address"]:
            c["alvos"] = {v: classificar(v, end, bloco, provedor, verificados) for v in c["valores"]}
    return cert
