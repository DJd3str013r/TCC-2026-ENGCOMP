# -*- coding: utf-8 -*-
"""Etapa 9 (subsecao 3.8): tratamento dos dados. Le as certidoes da amostra e produz saidas/resultados.json e a
figura 2 (PNG, preto e branco) da secao 4 do artigo. Tres conferencias (metadados_parciais,
conferencia_dois_ultimos_bytes e codigo_de_criacao) usam tambem as leituras da cadeia e as respostas da API
guardadas em .cache/. As conferencias descritivas citadas nas subsecoes 4.1, 4.2 e 4.6 ficam em
analise/complementares/.

Uso: python analise/analisar.py"""
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from atesta.classificacao import CLASSES, NULO  # noqa: E402
from atesta.config import CERTIDOES, DADOS, SAIDAS, TAMANHO_AMOSTRA  # noqa: E402
from atesta.estatistica import (Z, decisao_central, decisao_secundaria, newcombe, proporcao, quartis,  # noqa: E402
                                wilson)

LIMIAR = 0.10


def carregar():
    sorteio = json.loads((DADOS / "sorteio.json").read_text(encoding="utf-8"))
    with open(DADOS / "amostra.csv", encoding="utf-8") as f:
        amostra = list(csv.DictReader(f))
    eleg = [r for r in amostra if r["elegivel"] == "1"]
    certs = []
    for r in eleg:
        arq = CERTIDOES / f"{r['endereco']}.json"
        c = json.loads(arq.read_text(encoding="utf-8")) if arq.exists() else {"situacao": "ausente", "contrato": {"endereco": r["endereco"]}}
        c["_grau"] = r["grau"]
        c["_compilador"] = r["compilador"]
        certs.append(c)
    return sorteio, amostra, eleg, certs


def hipotese_central(certs):
    proc = [c for c in certs if c["situacao"] == "processado"]
    k, n = sum(c["indicador_equacao_2"] for c in proc), len(proc)
    l, u = wilson(k, n)
    perdas = len(certs) - n
    sens = {}
    if perdas:
        for nome, extra in (("perdas_com_indicador_0", 0), ("perdas_com_indicador_1", perdas)):
            ll, uu = wilson(k + extra, len(certs))
            sens[nome] = {"k": k + extra, "n": len(certs), "p": (k + extra) / len(certs), "l": ll, "u": uu,
                          "decisao": decisao_central(ll, uu, LIMIAR)}
    dec = decisao_central(l, u, LIMIAR)
    firme = all(s["decisao"] == dec for s in sens.values()) if sens else True
    return {"k": k, "n": n, "p": proporcao(k, n), "l": l, "u": u, "semiamplitude": (u - l) / 2,
            "limiar": LIMIAR, "decisao": dec, "perdas": perdas, "sensibilidade": sens, "decisao_firme": firme}


def hipotese_secundaria(certs):
    g = {"parcial": [], "exata": []}
    for c in certs:
        g[c["_grau"]].append(c)
    out = {}
    proc = {k: [c for c in v if c["situacao"] == "processado"] for k, v in g.items()}
    k1, n1 = sum(c["indicador_equacao_2"] for c in proc["parcial"]), len(proc["parcial"])
    k2, n2 = sum(c["indicador_equacao_2"] for c in proc["exata"]), len(proc["exata"])
    out["parcial"] = {"k": k1, "n": n1, "p": proporcao(k1, n1), "ic": wilson(k1, n1), "sorteados": len(g["parcial"])}
    out["exata"] = {"k": k2, "n": n2, "p": proporcao(k2, n2), "ic": wilson(k2, n2), "sorteados": len(g["exata"])}
    for gr in ("parcial", "exata"):
        out[gr]["amplitude"] = out[gr]["ic"][1] - out[gr]["ic"][0]   # precisao alcancada no grupo (3.8)
    if n1 and n2:
        d, L, U = newcombe(k1, n1, k2, n2)
        out.update({"delta": d, "L": L, "U": U, "decisao": decisao_secundaria(L, U)})
        perd1, perd2 = len(g["parcial"]) - n1, len(g["exata"]) - n2
        if perd1 or perd2:
            sens = {}
            for nome, e1, e2 in (("parcial_0_exata_1", 0, perd2), ("parcial_1_exata_0", perd1, 0)):
                dd, LL, UU = newcombe(k1 + e1, len(g["parcial"]), k2 + e2, len(g["exata"]))
                sens[nome] = {"delta": dd, "L": LL, "U": UU, "decisao": decisao_secundaria(LL, UU)}
            out["sensibilidade"] = sens
            out["decisao_firme"] = all(s["decisao"] == out["decisao"] for s in sens.values())
        else:
            out["decisao_firme"] = True
    else:
        out["decisao"] = "inconclusiva (grupo sem contrato processado)"
    return out


def regioes_e_constantes(certs):
    proc = [c for c in certs if c["situacao"] == "processado"]
    reg_motivo, contr_motivo, bytes_motivo = Counter(), Counter(), Counter()
    const_motivo_tau = Counter()
    divergentes = []
    for c in proc:
        vistos = set()
        for r in c["regioes"]:
            reg_motivo[r["motivo"]] += 1
            bytes_motivo[r["motivo"]] += r["comprimento"]
            vistos.add(r["motivo"])
        for m in vistos:
            contr_motivo[m] += 1
        for k in c["constantes"]:
            const_motivo_tau[(k["motivo"], k["tau_address"])] += 1
            if k["valores_distintos"] > 1:
                divergentes.append((c["contrato"]["endereco"], k["construto"], k["valores_distintos"]))
    sem_regiao = sum(1 for c in proc if not c["regioes"])
    combinacoes = Counter("+".join(sorted({r["motivo"] for r in c["regioes"]})) or "nenhuma" for c in proc)
    tipos_imutaveis = Counter()
    for c in proc:
        for k in c["constantes"]:
            if k["motivo"] == "immutable":
                tipos_imutaveis[("address" if k["tau_address"] else "outro")] += 1
    tipos_addr = Counter()
    so_contrato = 0
    for c in proc:
        if not c["indicador_equacao_2"]:
            continue
        tipos_c = []
        for k in c["constantes"]:
            if not k["tau_address"]:
                continue
            if k["motivo"] != "immutable":
                tipos_c.append("outro_motivo")
                continue
            t = k["tipo"]
            cat = "address" if t in ("address", "address payable") else ("contrato_ou_interface" if t.startswith("contract ") else "definido_pelo_usuario")
            tipos_addr[cat] += 1
            tipos_c.append(cat)
        if tipos_c and all(x in ("contrato_ou_interface", "definido_pelo_usuario") for x in tipos_c):
            so_contrato += 1
    return {"imutaveis_address_por_tipo": dict(tipos_addr), "positivos_so_por_tipo_nao_address": so_contrato,
            "regioes_por_motivo": dict(reg_motivo), "contratos_com_motivo": dict(contr_motivo),
            "bytes_por_motivo": dict(bytes_motivo), "contratos_sem_regiao": sem_regiao,
            "constantes_por_motivo_e_tau": {f"{m}|{'address' if t else 'outro'}": n for (m, t), n in const_motivo_tau.items()},
            "imutaveis_por_tau": dict(tipos_imutaveis), "combinacoes_de_motivos": dict(combinacoes),
            "constantes_com_valores_distintos": divergentes}


def cobertura(certs):
    proc = [c for c in certs if c["situacao"] == "processado"]
    por = {"total": quartis([c["cobertura"] for c in proc])}
    for gr in ("parcial", "exata"):
        por[gr] = quartis([c["cobertura"] for c in proc if c["_grau"] == gr])
    por["contratos_com_cobertura_1"] = sum(1 for c in proc if c["cobertura"] == 1)
    por["cobertura_1_por_grau"] = dict(Counter(c["_grau"] for c in proc if c["cobertura"] == 1))
    for gr in ("parcial", "exata"):
        m = min((c for c in proc if c["_grau"] == gr), key=lambda c: c["cobertura"], default=None)
        if m is not None:
            por[gr]["motivos_do_minimo"] = sorted({r["motivo"] for r in m["regioes"]})
    por["bytes_nao_atestados"] = quartis([c["bytes_nao_atestados"] for c in proc])
    return por


def alvos(certs):
    proc = [c for c in certs if c["situacao"] == "processado"]
    por_valor, por_contrato, subst = Counter(), Counter(), defaultdict(lambda: [0, 0])
    trivial = 0
    positivos = 0
    motivo_valor = Counter()
    for c in proc:
        classes_c = set()
        valores = []
        for k in c["constantes"]:
            if not k["tau_address"]:
                continue
            for v, a in (k.get("alvos") or {}).items():
                por_valor[a["classe"]] += 1
                motivo_valor[(k["motivo"], a["classe"])] += 1
                classes_c.add(a["classe"])
                valores.append(a["classe"])
                if a.get("substituivel") is not None:
                    subst[a["classe"]][0] += 1
                    subst[a["classe"]][1] += int(bool(a["substituivel"]))
        for cl in classes_c:
            por_contrato[cl] += 1
        if c["indicador_equacao_2"]:
            positivos += 1
            if valores and all(x in ("endereco_nulo", "proprio_contrato") for x in valores):
                trivial += 1
    distintos = {v for c in proc for k in c["constantes"] if k["tau_address"]
                 for v, a in (k.get("alvos") or {}).items() if a.get("substituivel") is not None}
    return {"por_valor": {k: por_valor.get(k, 0) for k in CLASSES}, "por_contrato": {k: por_contrato.get(k, 0) for k in CLASSES},
            "enderecos_distintos_com_codigo": len(distintos),
            "substituivel": {k: {"com_codigo": v[0], "substituiveis": v[1]} for k, v in subst.items()},
            "contratos_positivos": positivos, "positivos_so_nulo_ou_proprio": trivial,
            "classe_por_motivo": {f"{m}|{cl}": n for (m, cl), n in motivo_valor.items()}}


def autorreferencia(certs):
    """Parcela de p, p1 e p2 que decorre apenas de constantes com endereco nulo ou do proprio contrato."""
    out = {}
    for nome, grupo in (("total", certs), ("parcial", [c for c in certs if c["_grau"] == "parcial"]),
                        ("exata", [c for c in certs if c["_grau"] == "exata"])):
        proc = [c for c in grupo if c["situacao"] == "processado"]
        k_triv = 0
        for c in proc:
            if not c["indicador_equacao_2"]:
                continue
            classes = [a["classe"] for k in c["constantes"] if k["tau_address"] for a in (k.get("alvos") or {}).values()]
            if classes and all(x in ("endereco_nulo", "proprio_contrato") for x in classes):
                k_triv += 1
        k = sum(c["indicador_equacao_2"] for c in proc)
        out[nome] = {"positivos": k, "so_nulo_ou_proprio": k_triv, "n": len(proc), "positivos_sem_triviais": k - k_triv,
                     "p_sem_triviais": (k - k_triv) / len(proc) if proc else None,
                     "ic_sem_triviais": wilson(k - k_triv, len(proc)) if proc else None}
    return out


def secundaria_sem_triviais(auto):
    """Diferenca de Newcombe sem os positivos que so tem endereco nulo ou o proprio contrato (descritivo)."""
    p, e = auto["parcial"], auto["exata"]
    d, L, U = newcombe(p["positivos_sem_triviais"], p["n"], e["positivos_sem_triviais"], e["n"])
    return {"delta": d, "L": L, "U": U, "decisao": decisao_secundaria(L, U)}


def compiladores(certs):
    def faixa(v):
        try:
            p = [int(x) for x in v.split("+")[0].split("-")[0].split(".")[:3]]
        except ValueError:
            return "outra"
        if p < [0, 4, 0]:
            return "anterior a 0.4"
        if p < [0, 5, 0]:
            return "0.4.x"
        if p < [0, 6, 5]:
            return "0.5.0 a 0.6.4"
        if p < [0, 8, 0]:
            return "0.6.5 a 0.7.x"
        return "0.8.x"
    t = defaultdict(Counter)
    for c in certs:
        t[c["_grau"]][faixa(c["_compilador"] or "")] += 1
    return {g: dict(v) for g, v in t.items()}


def por_era(certs):
    """Descritivo (sem inferencia): indicador por grau entre contratos compilados antes e a partir da 0.6.5, versao
    que introduziu as variaveis imutaveis."""
    def era(v):
        try:
            p = [int(x) for x in (v or "").split("+")[0].split("-")[0].split(".")[:3]]
        except ValueError:
            return "desconhecida"
        return "a partir de 0.6.5" if p >= [0, 6, 5] else "antes de 0.6.5"
    t = defaultdict(lambda: [0, 0])
    motivos_antes = Counter()
    for c in certs:
        if c["situacao"] != "processado":
            continue
        k = f"{c['_grau']}|{era(c['_compilador'])}"
        t[k][0] += 1
        t[k][1] += c["indicador_equacao_2"]
        if c["indicador_equacao_2"] and era(c["_compilador"]) == "antes de 0.6.5":
            motivos_antes["+".join(sorted({k_["motivo"] for k_ in c["constantes"] if k_["tau_address"]}))] += 1
    out = {k: {"n": v[0], "positivos": v[1]} for k, v in sorted(t.items())}
    out["positivos_antes_de_0.6.5_por_motivo"] = dict(motivos_antes)
    p, e = out.get("parcial|a partir de 0.6.5"), out.get("exata|a partir de 0.6.5")
    if p and e and p["n"] and e["n"]:
        out["delta_a_partir_de_0.6.5"] = p["positivos"] / p["n"] - e["positivos"] / e["n"]
        # Acrescimo de 17/11: intervalos so descritivos, nao previstos na subsecao 3.8, pelas mesmas Equacoes (3) e
        # (5); nao entram em nenhuma decisao.
        k, n = p["positivos"] + e["positivos"], p["n"] + e["n"]
        out["a_partir_de_0.6.5_juntos"] = {"k": k, "n": n, "p": proporcao(k, n), "ic": list(wilson(k, n))}
        _, L, U = newcombe(p["positivos"], p["n"], e["positivos"], e["n"])
        out["newcombe_a_partir_de_0.6.5"] = [L, U]
    return out


def extremos(certs):
    proc = [c for c in certs if c["situacao"] == "processado"]
    menor = sorted(proc, key=lambda c: c["cobertura"])[:3]
    maior_bytes = sorted(proc, key=lambda c: -c["bytes_nao_atestados"])[:3]
    f = lambda c: {"endereco": c["contrato"]["endereco"], "cobertura": c["cobertura"], "tamanho": c["contrato"]["tamanho_codigo"],
                   "bytes_nao_atestados": c["bytes_nao_atestados"], "grau": c["_grau"], "compilador": c["_compilador"],
                   "motivos": sorted({r["motivo"] for r in c["regioes"]})}
    return {"menor_cobertura": [f(c) for c in menor], "mais_bytes": [f(c) for c in maior_bytes]}


def confronto(certs):
    proc = [c for c in certs if c["situacao"] == "processado"]
    coinc = sum(1 for c in proc if c["confronto_acervo"]["coincide"])
    diverg = [{"endereco": c["contrato"]["endereco"], **c["confronto_acervo"]} for c in proc if not c["confronto_acervo"]["coincide"]]
    match = Counter(str(c.get("acervo", {}).get("match_id_coincide")) for c in proc)
    metadados = Counter((c["_grau"], c["recompilacao"]["metadados_em_F"]) for c in proc)
    return {"coincide": coinc, "divergem": len(diverg), "divergencias": diverg, "match_id_coincide": dict(match),
            "metadados_em_F_por_grau": {f"{g}|{m}": n for (g, m), n in metadados.items()},
            "posicoes_metadados": dict(Counter(c["recompilacao"].get("posicoes_metadados", "nao_usadas") for c in proc))}


def bloco_de_metadados(codigo):
    """'sem_bloco', 'com_resumo' ou 'sem_resumo': o comprimento do ultimo bloco CBOR vem nos dois ultimos bytes."""
    if len(codigo) < 4:
        return "sem_bloco"
    n = int.from_bytes(codigo[-2:], "big")
    if not 0 < n <= len(codigo) - 2 or not 0xa1 <= codigo[-2 - n] <= 0xa5:
        return "sem_bloco"
    bloco = codigo[-2 - n:-2]
    return "com_resumo" if any(x in bloco for x in (b"ipfs", b"bzzr0", b"bzzr1")) else "sem_resumo"


def metadados_parciais(certs):
    """Contratos de correspondencia parcial sem bloco de metadados em F(a): o codigo da cadeia nao traz bloco, ou o
    traz sem o resumo do arquivo de metadados, identico ao recompilado (leituras do cache, sem rede)."""
    from atesta.rpc import RPC
    rpc = RPC()
    t, lista = Counter(), []
    for c in certs:
        if c["situacao"] != "processado" or c["_grau"] != "parcial" or c["recompilacao"]["metadados_em_F"]:
            continue
        cl = bloco_de_metadados(rpc.codigo(c["contrato"]["endereco"], c["contrato"]["bloco_referencia"]))
        t[cl] += 1
        lista.append({"endereco": c["contrato"]["endereco"], "compilador": c["_compilador"], "bloco": cl,
                      "blocos_removidos": c["recompilacao"].get("blocos_removidos", 0)})
    return {"por_situacao": dict(t), "contratos": lista}


def conferencia_dois_ultimos_bytes(certs):
    """Conferencia que a 3.4 preve e o verificador nao faz: nos contratos com metadados em F(a), o ultimo bloco
    CBOR indicado pelos dois ultimos bytes de c_a esta entre as regioes de metadados registradas pelo acervo."""
    from atesta.rpc import RPC
    rpc = RPC()
    coincide = diverge = 0
    for c in certs:
        if c["situacao"] != "processado" or not c["recompilacao"]["metadados_em_F"]:
            continue
        cod = rpc.codigo(c["contrato"]["endereco"], c["contrato"]["bloco_referencia"])
        n = int.from_bytes(cod[-2:], "big") + 2
        regs = {(r["inicio"], r["comprimento"]) for r in c["regioes"] if r["motivo"] == "cborAuxdata"}
        if (len(cod) - n, n) in regs:
            coincide += 1
        else:
            diverge += 1
    return {"coincide": coincide, "diverge": diverge}


def menores_coberturas(certs, limite=0.6):
    """Contratos com C(a) abaixo do limite: tamanho, motivos e fracao do codigo ocupada pelo bloco de metadados."""
    proc = [c for c in certs if c["situacao"] == "processado"]
    abaixo = sorted((c for c in proc if c["cobertura"] < limite), key=lambda c: c["cobertura"])
    meta = lambda c: sum(r["comprimento"] for r in c["regioes"] if r["motivo"] == "cborAuxdata")
    frac = [meta(c) / c["contrato"]["tamanho_codigo"] for c in abaixo]
    parciais = [c for c in proc if c["_grau"] == "parcial" and c["recompilacao"]["metadados_em_F"]]
    return {"limite": limite, "n": len(abaixo),
            "so_metadados": all(all(r["motivo"] == "cborAuxdata" for r in c["regioes"]) for c in abaixo),
            "graus": dict(Counter(c["_grau"] for c in abaixo)),
            "tamanho_min": min(c["contrato"]["tamanho_codigo"] for c in abaixo) if abaixo else None,
            "tamanho_max": max(c["contrato"]["tamanho_codigo"] for c in abaixo) if abaixo else None,
            "fracao_metadados_min": min(frac) if frac else None, "fracao_metadados_max": max(frac) if frac else None,
            "parciais_com_metadados_acima_da_metade": sum(1 for c in parciais if meta(c) > c["contrato"]["tamanho_codigo"] / 2)}


def codigo_de_criacao(certs):
    """Descritivo, nao previsto na subsecao 3.8 (P-18): correspondencia do codigo de criacao registrada pelo acervo e
    valores do tipo address que aparecem como literal no codigo de criacao recompilado, isto e, que o confronto do
    codigo de criacao alcanca. Nao altera o indicador da Equacao (2) nem as decisoes. A contagem
    positivos_com_valor_fora_dos_dois_confrontos desconta tambem o endereco nulo e o proprio contrato, como
    autorreferencia(); a busca dos literais e conferida no codigo-fonte de cada contrato positivo."""
    proc = [c for c in certs if c["situacao"] == "processado"]
    graus = Counter((c["acervo"].get("grau_codigo_criacao") or "sem", c["_grau"]) for c in proc)
    pos = [c for c in proc if c["indicador_equacao_2"]]
    valores = literais = com_literal = 0
    fora = []
    for c in pos:
        tem_criacao = bool(c["acervo"].get("grau_codigo_criacao"))
        tem_lit = resto = False
        for k in c["constantes"]:
            if not k["tau_address"]:
                continue
            lits = set(k.get("literais_no_codigo_de_criacao") or [])
            for v, a in (k.get("alvos") or {}).items():
                valores += 1
                if v in lits:
                    literais += 1
                    tem_lit = True
                if a["classe"] not in ("endereco_nulo", "proprio_contrato") and not (v in lits and tem_criacao):
                    resto = True
        com_literal += tem_lit
        if resto:
            fora.append(c["contrato"]["endereco"])
    # conferencia no codigo-fonte de cada contrato positivo: valores nao nulos escritos nele (40 digitos hexadecimais)
    from atesta.acervo import APISourcify
    api = APISourcify()
    no_fonte = []
    for c in pos:
        fontes = (api.contrato(1, c["contrato"]["endereco"]).get("stdJsonInput") or {}).get("sources") or {}
        texto = "\n".join((s or {}).get("content") or "" for s in fontes.values()).lower()
        for k in c["constantes"]:
            if k["tau_address"]:
                no_fonte += [v for v in k["valores"] if v != NULO and v[2:] in texto]
    n, k = len(proc), len(fora)
    return {"por_grau": {f"{a}|{b}": m for (a, b), m in sorted(graus.items())},
            "valores_no_codigo_fonte": sorted(no_fonte),
            "literais_lista": sorted(v for c in pos for k in c["constantes"] if k["tau_address"]
                                     for v in (k.get("literais_no_codigo_de_criacao") or [])),
            "com_correspondencia_de_criacao": sum(m for (a, b), m in graus.items() if a != "sem"),
            "mesmo_grau": sum(m for (a, b), m in graus.items() if a == b),
            "positivos": len(pos),
            "positivos_com_correspondencia_de_criacao": sum(1 for c in pos if c["acervo"].get("grau_codigo_criacao")),
            "positivos_mesmo_grau": sum(1 for c in pos if c["acervo"].get("grau_codigo_criacao") == c["_grau"]),
            "valores": valores, "literais": literais, "contratos_com_literal": com_literal,
            "positivos_com_valor_fora_dos_dois_confrontos": k, "p": k / n if n else None,
            "ic": wilson(k, n) if n else None, "enderecos_fora": fora}


def motores(certs):
    """Motor de cada recompilacao por grau e, no soljson, a causa: versao nightly ou anterior a 0.4.11, ou falta de
    binario nativo com a versao longa exata (desde a 1.5.0)."""
    from atesta.compilador import _tupla
    proc = [c for c in certs if c["situacao"] == "processado"]
    out = {f"{m}|{g}": n for (m, g), n in sorted(Counter((c["recompilacao"]["motor"], c["_grau"]) for c in proc).items())}
    causa = Counter()
    for c in proc:
        if c["recompilacao"]["motor"] != "soljson":
            continue
        v = c["acervo"]["compilador"].lstrip("v")
        antiga = "nightly" in v or _tupla(v.split("+")[0].split("-")[0]) < (0, 4, 11)
        causa["nightly_ou_anterior_a_0.4.11" if antiga else "sem_binario_da_versao_exata"] += 1
    out["soljson_por_causa"] = dict(causa)
    out["soljson_sem_binario_versoes"] = sorted({c["acervo"]["compilador"] for c in proc
                                                 if c["recompilacao"]["motor"] == "soljson"
                                                 and "nightly" not in c["acervo"]["compilador"]
                                                 and _tupla(c["acervo"]["compilador"].lstrip("v").split("+")[0].split("-")[0]) >= (0, 4, 11)})
    return out


def esperadas_por_motivo(v):
    """Regioes esperadas por motivo numa rodada de validacao (pelos rotulos dos controles)."""
    e = v["regioes_esperadas"]
    return {"immutable": e.get("imutavel+", 0) + e.get("imutavel-", 0),
            "library": e.get("biblioteca+", 0) + e.get("biblioteca-", 0),
            "callProtection": e.get("chamada+", 0) + e.get("chamada-", 0),
            "cborAuxdata": e.get("metadados+", 0) + e.get("metadados-", 0)}


def historico(certs):
    """Rodadas do ensaio (dados/piloto), das validacoes e da amostra (dados/logs), com o diagnostico de cada falha
    (dados/falhas_diagnosticadas.json)."""
    diag = json.loads((DADOS / "falhas_diagnosticadas.json").read_text(encoding="utf-8"))
    piloto = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((DADOS / "piloto").glob("0x*.json"))]
    ensaio = {}
    blocos_ensaio = {c["contrato"]["bloco_referencia"] for c in piloto}
    corrigida = [x["corrigida_em"] for x in diag["ensaio"].values()]
    versao_sorteio = "1.3.0"   # o sorteio valido foi refeito com a 1.3.0 (P-10)
    chave = lambda v: tuple(int(x) for x in v.split("."))
    sobrescritos = json.loads((DADOS / "ensaio_sobrescritos.json").read_text(encoding="utf-8"))["contratos"]
    for c in piloto:
        ensaio.setdefault(c["verificador"]["versao"], {"contratos": 0, "falhas": Counter()})["contratos"] += 1
    # a 1a rodada (1.0.0) tambem verificou os contratos cujas certidoes a 2a rodada sobrescreveu
    ensaio["1.0.0"]["contratos"] += len(sobrescritos)
    for end, x in diag["ensaio"].items():
        for rod in x.get("rodadas", [x["rodada"]]):
            ensaio[rod]["falhas"]["+".join(x["causas"])] += 1
    refeitos = {}
    for pasta in sorted((DADOS / "piloto").glob("refeitos-*")):
        r = json.loads((pasta / "resumo.json").read_text(encoding="utf-8"))
        refeitos[pasta.name.split("-", 1)[1]] = dict(Counter(x["situacao"] for x in r))
    compilador = {c["contrato"]["endereco"]: c["_compilador"] for c in certs}
    rodadas = []
    for log in sorted((DADOS / "logs").glob("execucao*.log")):
        txt = log.read_text(encoding="utf-8")
        resumo = json.loads(txt[txt.index("{"):txt.index("}") + 1])
        falhas = re.findall(r"falha (0x[0-9a-f]{40}):", txt)
        inicio = (DADOS / "logs" / log.name.replace(".log", "-inicio.txt")).read_text(encoding="utf-8").strip()
        rodadas.append({"verificador": resumo["verificador"], "processados": resumo["processados"],
                        "contratos": resumo["contratos"], "inicio": inicio,
                        "falhas": dict(Counter("+".join(diag["amostra"][f]["causas"]) for f in falhas)),
                        "falhas_por_compilador": [compilador[f] for f in falhas]})
    rodadas.sort(key=lambda r: tuple(int(x) for x in r["verificador"].split(".")))
    val = [json.loads(x) for x in (SAIDAS / "validacao_historico.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    # so contam como validacao "antes de medir" as rodadas anteriores ao inicio da ultima rodada sobre a amostra; as
    # posteriores (por exemplo, testes rodados depois da medicao) sao relatadas a parte
    instante = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))
    limite = max(instante(r["inicio"]) for r in rodadas)
    antes = [v for v in val if instante(v["quando"]) <= limite]
    return {"ensaio": {k: {"contratos": v["contratos"], "falhas": dict(v["falhas"])} for k, v in sorted(ensaio.items())},
            "ensaio_contratos": len(piloto), "ensaio_refeitos": refeitos,
            "ensaio_contratos_com_falha": len(diag["ensaio"]),
            "ensaio_com_falha_processados_na_segunda_rodada": sum(
                1 for e in diag["ensaio"] if json.loads((DADOS / "piloto" / f"{e}.json").read_text(encoding="utf-8"))
                ["situacao"] == "processado"),
            "ensaio_bloco": sorted(blocos_ensaio),
            "ensaio_falhas_corrigidas_antes_do_sorteio": sum(1 for v in corrigida if chave(v) <= chave(versao_sorteio)),
            "ensaio_falhas_corrigidas_depois_do_sorteio": sum(1 for v in corrigida if chave(v) > chave(versao_sorteio)),
            "regioes_esperadas_por_versao": {
                ver: sorted({(sum(v["regioes_esperadas"].values()),
                              v["regioes_esperadas"].get("imutavel+", 0) + v["regioes_esperadas"].get("imutavel-", 0))
                             for v in antes if v["verificador"] == ver})
                for ver in sorted({v["verificador"] for v in antes}, key=chave)},
            "vp_igual_ao_esperado_em_todas": all(
                v["por_motivo"][m]["VP"] == esperadas_por_motivo(v)[m] and v["por_motivo"][m]["FN"] == 0
                for v in antes for m in v["por_motivo"]),
            "validacoes_por_versao": dict(sorted(Counter(v["verificador"] for v in antes).items())),
            "validacoes_depois_da_ultima_rodada": len(val) - len(antes),
            "validacoes_todas_aprovadas": all(v["aprovado"] for v in val),
            "validacoes_sem_fp_fn": all(m["FP"] == 0 and m["FN"] == 0 for v in val for m in v["por_motivo"].values()),
            "rodadas_amostra": rodadas}


def figuras(certs, res):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter
    plt.rcParams.update({"font.family": "Times New Roman", "font.size": 11, "mathtext.fontset": "stix"})
    (SAIDAS / "figuras").mkdir(exist_ok=True)
    proc = [c for c in certs if c["situacao"] == "processado"]
    dados = [[c["cobertura"] for c in proc if c["_grau"] == g] for g in ("parcial", "exata")]
    fig, ax = plt.subplots(figsize=(6.3, 2.9), dpi=200)
    bp = ax.boxplot(dados, orientation="horizontal", widths=0.5, patch_artist=True, showfliers=True,
                    flierprops={"marker": "o", "markersize": 3, "markerfacecolor": "white", "markeredgecolor": "black"},
                    medianprops={"color": "black", "linewidth": 1.5}, whiskerprops={"color": "black"},
                    capprops={"color": "black"}, boxprops={"color": "black"})
    for b in bp["boxes"]:
        b.set_facecolor("white")
    ax.set_yticks([1, 2], [f"Correspondência parcial ($n={len(dados[0])}$)", f"Correspondência exata ($n={len(dados[1])}$)"])
    ax.set_xlabel("Cobertura de atestação, $C(a)$")
    ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x:.1f}".replace(".", ",")))
    lo = min(min(d) for d in dados if d)
    ax.set_xlim(max(0, lo - 0.01), 1.0005)
    ax.grid(axis="x", color="0.85", linewidth=0.6)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()
    fig.savefig(SAIDAS / "figuras" / "figura2_cobertura.png")
    plt.close(fig)


def main():
    sorteio, amostra, eleg, certs = carregar()
    base = json.loads((DADOS / "base_resumo.json").read_text(encoding="utf-8"))
    validacao = [json.loads(x) for x in (SAIDAS / "validacao_historico.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    falhas = [{"endereco": c["contrato"]["endereco"], "causa": c.get("causa")} for c in certs if c["situacao"] != "processado"]
    hist = historico(certs)
    inicio_ultima = max(datetime.fromisoformat(r["inicio"].replace("Z", "+00:00")) for r in hist["rodadas_amostra"])
    val_antes = [v for v in validacao if datetime.fromisoformat(v["quando"]) <= inicio_ultima]
    res = {
        "z": Z,
        "sorteio": sorteio, "base": base,
        "amostra": {"examinados": len(amostra), "elegiveis": len(eleg), "processados": len(eleg) - len(falhas),
                    "perdas": falhas, "tamanho_planejado": TAMANHO_AMOSTRA,
                    "por_grau": dict(Counter(c["_grau"] for c in certs))},
        "hipotese_central": hipotese_central(certs),
        "hipotese_secundaria": hipotese_secundaria(certs),
        "cobertura": cobertura(certs),
        "regioes": regioes_e_constantes(certs),
        "alvos": alvos(certs),
        "autorreferencia": autorreferencia(certs),
        "compiladores_por_grau": compiladores(certs),
        "indicador_por_grau_e_era": por_era(certs),
        "extremos": extremos(certs),
        "confronto_acervo": confronto(certs),
        "metadados_parciais": metadados_parciais(certs),
        "menores_coberturas": menores_coberturas(certs),
        "codigo_de_criacao": codigo_de_criacao(certs),
        "motores": motores(certs),
        "historico": hist,
        "conferencia_dois_ultimos_bytes": conferencia_dois_ultimos_bytes(certs),
        "validacao": {"rodadas": len(val_antes), "ultima": val_antes[-1] if val_antes else None,
                      "rodadas_depois_da_ultima_medicao": len(validacao) - len(val_antes),
                      "historico": [{"quando": v["quando"], "verificador": v["verificador"], "aprovado": v["aprovado"],
                                     "por_motivo": {m: {k: x[k] for k in ("VP", "FP", "FN", "P", "R")}
                                                    for m, x in v["por_motivo"].items()}} for v in validacao]},
    }
    res["autorreferencia"]["secundaria_sem_triviais"] = secundaria_sem_triviais(res["autorreferencia"])
    (SAIDAS / "resultados.json").write_text(json.dumps(res, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    figuras(certs, res)
    hc, hs = res["hipotese_central"], res["hipotese_secundaria"]
    print(json.dumps({"amostra": res["amostra"]["processados"], "hipotese_central": {k: hc[k] for k in ("k", "n", "p", "l", "u", "decisao", "decisao_firme")},
                      "hipotese_secundaria": {k: hs.get(k) for k in ("parcial", "exata", "delta", "L", "U", "decisao")},
                      "cobertura": res["cobertura"]["total"], "alvos": res["alvos"]["por_valor"],
                      "autorreferencia": res["autorreferencia"]["total"], "confronto": {k: res["confronto_acervo"][k] for k in ("coincide", "divergem", "match_id_coincide")}},
                     indent=1, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
