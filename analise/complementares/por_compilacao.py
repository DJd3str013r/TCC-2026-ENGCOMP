# -*- coding: utf-8 -*-
"""Fracao por compilacao (subsecao 4.6 do artigo). Contagem descritiva, nao prevista na subsecao 3.8: nao altera
nenhuma estimativa nem a decisao das hipoteses, que sao por endereco (unidade da subsecao 3.2).

1) Conta, em dados/base.parquet, os enderecos, as compilacoes distintas (compilation_id do acervo), a participacao
   das dez compilacoes mais frequentes e a distribuicao das compilacoes por tamanho (numero de enderecos da
   compilacao na base). Junta as 385 certidoes a base pelo endereco (conferindo ordem, indice_base e match_id com
   dados/amostra.csv) e conta os sorteados, e os positivos, nas dez mais frequentes, nas de compilacao unica (com
   intervalo de Wilson pela funcao wilson de atesta/estatistica.py) e por faixa de tamanho (1, 2 a 10, 11 a 1.000,
   mais de 1.000 enderecos), com o esperado sob amostragem aleatoria simples.
2) Confere a premissa de que contratos da mesma compilacao tem o mesmo indicador: entre os sorteados e, a parte,
   somando os 291 contratos do ensaio de dados/piloto (fora da amostra). Calcula a fracao de compilacoes com
   indicador 1 pelo estimador de razao ponderado pelo inverso do tamanho da compilacao,
       p = soma(ind_i / c_i) / soma(1 / c_i)   (soma sobre os 385 sorteados),
   com intervalo percentil por bootstrap (10.000 reamostragens com reposicao, semente fixa registrada no JSON).
   Como conferencia, a mesma fracao pos-estratificada em compilacao unica e demais, com as participacoes conhecidas
   da base.
3) Aplica a mesma regra da hipotese central (decisao_central de atesta/estatistica.py: refutada se u < 0,10,
   sustentada se l > 0,10, inconclusiva se o intervalo contem 0,10) aos intervalos dessa unidade, so como leitura
   descritiva.
Diagnostico da composicao: qui-quadrado da distribuicao dos sorteados pelas faixas contra a da base e a fracao por
endereco pos-estratificada pelas faixas (nenhum dos dois previsto na subsecao 3.8).

Le dados/base.parquet (publicado a parte), dados/certidoes/*.json, dados/amostra.csv, dados/piloto/0x*.json (e
dados/piloto/refeitos-1.7.0/0x*.json), saidas/resultados.json e atesta/estatistica.py (importado). Grava
saidas/complementares/por_compilacao.json e saidas/complementares/sorteados_por_compilacao.csv. Nao acessa a rede.

Uso: python analise/complementares/por_compilacao.py"""
import csv
import datetime
import glob
import hashlib
import json
import math
import os
import platform
import shutil
import sys
import tempfile
from pathlib import Path

import duckdb
import numpy as np
import scipy
from scipy.stats import chisquare

RAIZ = Path(__file__).resolve().parents[2]
BASE = RAIZ / "dados" / "base.parquet"
CERT = RAIZ / "dados" / "certidoes"
PILOTO = RAIZ / "dados" / "piloto"
AMOSTRA = RAIZ / "dados" / "amostra.csv"
RESULTADOS = RAIZ / "saidas" / "resultados.json"
ESTATISTICA = RAIZ / "atesta" / "estatistica.py"
SAIDAS = RAIZ / "saidas" / "complementares"
SAIDA_JSON = SAIDAS / "por_compilacao.json"
SAIDA_CSV = SAIDAS / "sorteados_por_compilacao.csv"

for _p in (BASE, CERT, PILOTO, AMOSTRA, RESULTADOS, ESTATISTICA):
    if not _p.exists():
        sys.exit(f"entrada ausente: {_p.relative_to(RAIZ).as_posix()}")

sys.path.insert(0, str(RAIZ))
from atesta.estatistica import Z, decisao_central, wilson  # noqa: E402

SEMENTE = 20261117                     # fixada antes de rodar o bootstrap
REAMOSTRAGENS = 10_000
SEMENTES_ESTABILIDADE = (SEMENTE + 1, SEMENTE + 2, SEMENTE + 3, SEMENTE + 4)  # so para ver o erro de Monte Carlo
LIMIAR = 0.10
FAIXAS = (("1", 1, 1), ("2 a 10", 2, 10), ("11 a 1.000", 11, 1000), ("mais de 1.000", 1001, None))


def relativo(caminho):
    """Caminho relativo a raiz do repositorio, com barras normais."""
    return Path(caminho).relative_to(RAIZ).as_posix()


def sha256_arquivo(caminho, bloco=1 << 20):
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for b in iter(lambda: f.read(bloco), b""):
            h.update(b)
    return h.hexdigest()


def fmt_pct(x, casas=1):
    return f"{100 * x:.{casas}f}".replace(".", ",") + "%"


def faixa_de(c):
    for nome, lo, hi in FAIXAS:
        if c >= lo and (hi is None or c <= hi):
            return nome
    raise ValueError(c)


def assinatura(d):
    """Regioes de F(a) que nao sao de metadados, as unicas que podem ter tau = address."""
    return sorted((r["motivo"], int(r["inicio"]), int(r["comprimento"]), r["tipo"], bool(r["tau_address"]),
                   r["construto"]) for r in d.get("regioes", []) if r["motivo"] != "cborAuxdata")


def indices_bootstrap(n, semente, b=REAMOSTRAGENS):
    """b reamostragens com reposicao das n unidades (numpy Generator PCG64)."""
    rng = np.random.Generator(np.random.PCG64(semente))
    return rng.integers(0, n, size=(b, n))


def percentis(v):
    l, u = np.percentile(v, [2.5, 97.5])
    return float(l), float(u)


def main():
    inicio = datetime.datetime.now(datetime.timezone.utc)
    tmp = tempfile.mkdtemp(prefix="duckdb_")
    con = duckdb.connect(":memory:")
    con.execute(f"SET temp_directory='{Path(tmp).as_posix()}'")

    # 1) base de amostragem por compilacao
    con.execute(f"""create table b as
                    select indice, address, compilation_id as cid, match_id, fully_qualified_name as fqn, version
                    from read_parquet('{BASE.as_posix()}')""")
    N, N_dist, cid_nulos, M = con.execute(
        "select count(*), count(distinct address), count(*) - count(cid), count(distinct cid) from b").fetchone()
    con.execute("""create table kc as
                   select cid, count(*) as c, count(distinct fqn) as nomes, count(distinct version) as versoes,
                          min(fqn) as fqn, min(version) as versao
                   from b group by cid""")
    nomes_max, versoes_max = con.execute("select max(nomes), max(versoes) from kc").fetchone()
    top11 = con.execute("select cid, c, fqn, versao from kc order by c desc, cid limit 11").fetchall()
    top10 = top11[:10]
    soma10 = int(sum(r[1] for r in top10))
    empate_na_decima = top11[9][1] == top11[10][1]
    U = con.execute("select count(*) from kc where c = 1").fetchone()[0]
    maior_c = con.execute("select max(c) from kc").fetchone()[0]

    faixas_base = []
    for nome, lo, hi in FAIXAS:
        cond = f"c >= {lo}" + (f" and c <= {hi}" if hi is not None else "")
        k, e = con.execute(f"select count(*), coalesce(sum(c), 0) from kc where {cond}").fetchone()
        faixas_base.append({"faixa": nome, "compilacoes": int(k), "fracao_das_compilacoes": k / M,
                            "enderecos": int(e), "fracao_dos_enderecos": e / N})
    assert sum(f["compilacoes"] for f in faixas_base) == M and sum(f["enderecos"] for f in faixas_base) == N

    # certidoes, ensaio e amostra
    arquivos = sorted(glob.glob(os.path.join(CERT, "*.json")))
    h_cert = hashlib.sha256()
    certs = []
    for f in arquivos:
        with open(f, "rb") as fh:
            bruto = fh.read()
        h_cert.update(os.path.basename(f).encode() + b"\0" + hashlib.sha256(bruto).digest())
        d = json.loads(bruto.decode("utf-8"))
        certs.append({"endereco": d["contrato"]["endereco"].lower(), "ind": int(d["indicador_equacao_2"]),
                      "ordem": int(d["ordem"]), "situacao": d["situacao"], "grau": d["acervo"]["grau_instantaneo"],
                      "match_id": int(d["acervo"]["match_id_instantaneo"]), "versao": d["verificador"]["versao"],
                      "contrato_compilado": d["acervo"].get("contrato_compilado"), "assinatura": assinatura(d)})
    por_end = {c["endereco"]: c for c in certs}

    # ensaio (fora da amostra): certidoes da raiz de dados/piloto; as refeitas pela 1.7.0 substituem as de falha
    piloto = {}
    for pasta in (PILOTO, os.path.join(PILOTO, "refeitos-1.7.0")):
        for f in sorted(glob.glob(os.path.join(pasta, "0x*.json"))):
            with open(f, encoding="utf-8") as fh:
                d = json.load(fh)
            piloto[d["contrato"]["endereco"].lower()] = {
                "situacao": d["situacao"], "ind": d.get("indicador_equacao_2"), "versao": d["verificador"]["versao"],
                "contrato_compilado": d["acervo"].get("contrato_compilado"),
                "bloco": d["contrato"]["bloco_referencia"], "assinatura": assinatura(d) if d["situacao"] == "processado"
                else None}
    piloto = {k: v for k, v in piloto.items() if v["situacao"] == "processado" and k not in por_end}

    with open(AMOSTRA, encoding="utf-8", newline="") as fh:
        amostra = [r for r in csv.DictReader(fh)]
    am = {r["endereco"].lower(): r for r in amostra if r["elegivel"] == "1"}

    with open(RESULTADOS, encoding="utf-8") as fh:
        res = json.load(fh)
    hc = res["hipotese_central"]

    # juncao com a base (amostra e ensaio)
    con.execute("create table s (address blob, ind integer, ordem integer)")
    con.executemany("insert into s values (?, ?, ?)",
                    [(bytes.fromhex(c["endereco"][2:]), c["ind"], c["ordem"]) for c in certs])
    linhas = con.execute("""select s.ordem, s.ind, b.address, b.indice, b.match_id, b.cid, kc.c
                            from s join b using (address) join kc using (cid)
                            order by s.ordem""").fetchall()
    con.execute("create table p (address blob)")
    con.executemany("insert into p values (?)", [(bytes.fromhex(k[2:]),) for k in piloto])
    linhas_p = con.execute("select b.address, b.cid, kc.c from p join b using (address) join kc using (cid)").fetchall()
    con.close()
    shutil.rmtree(tmp, ignore_errors=True)

    unidos = []
    for ordem, ind, addr, indice, match_id, cid, c in linhas:
        end = "0x" + bytes(addr).hex()
        a = am.get(end)
        unidos.append({"ordem": int(ordem), "endereco": end, "ind": int(ind), "cid": cid, "c": int(c),
                       "indice_coincide": a is not None and int(a["indice_base"]) == int(indice),
                       "match_id_coincide": (a is not None and int(a["match_id_instantaneo"]) == int(match_id)
                                             and por_end[end]["match_id"] == int(match_id)),
                       "ordem_coincide": a is not None and int(a["ordem"]) == int(ordem),
                       "grau": por_end[end]["grau"]})
    n = len(unidos)
    k_total = sum(u["ind"] for u in unidos)
    juncao = {
        "certidoes": len(certs),
        "certidoes_processadas": sum(c["situacao"] == "processado" for c in certs),
        "versoes_do_atesta_nas_certidoes": sorted({c["versao"] for c in certs}),
        "linhas_da_amostra_csv_elegiveis": len(am),
        "enderecos_das_certidoes_na_amostra_csv": sum(e in am for e in por_end),
        "unidas_a_base": n,
        "enderecos_distintos_unidos": len({u["endereco"] for u in unidos}),
        "ordem_coincide": sum(u["ordem_coincide"] for u in unidos),
        "indice_base_coincide": sum(u["indice_coincide"] for u in unidos),
        "match_id_coincide_base_certidao_amostra": sum(u["match_id_coincide"] for u in unidos),
        "positivos": k_total,
        "resultados_json_k_n": [hc["k"], hc["n"]],
    }
    juncao["cobre_os_385"] = (len(certs) == 385 and n == 385 and juncao["enderecos_distintos_unidos"] == 385
                              and juncao["enderecos_das_certidoes_na_amostra_csv"] == 385
                              and juncao["indice_base_coincide"] == 385
                              and juncao["match_id_coincide_base_certidao_amostra"] == 385
                              and juncao["ordem_coincide"] == 385)
    juncao["confere_com_resultados_json"] = (k_total == hc["k"] and n == hc["n"])
    if not (juncao["cobre_os_385"] and juncao["confere_com_resultados_json"]):
        sys.exit("a juncao nao cobre os 385 ou nao confere com resultados.json: " + json.dumps(juncao))

    # 1) sorteados por compilacao
    ind = np.array([u["ind"] for u in unidos], dtype=float)   # na ordem do sorteio (campo ordem)
    c = np.array([u["c"] for u in unidos], dtype=float)
    cids10 = {r[0] for r in top10}
    na10 = np.array([u["cid"] in cids10 for u in unidos])
    unica = c == 1
    faixa = np.array([faixa_de(int(x)) for x in c])

    lista10 = []
    for cid, cc, fqn, versao in top10:
        sel = [u for u in unidos if u["cid"] == cid]
        lista10.append({"compilation_id": cid, "enderecos": int(cc), "fracao_dos_enderecos": cc / N,
                        "contrato_compilado": fqn, "compilador": versao, "sorteados": len(sel),
                        "positivos": sum(u["ind"] for u in sel)})

    pos10 = int(ind[na10].sum())
    k_u, n_u = int(ind[unica].sum()), int(unica.sum())
    l_u, u_u = wilson(k_u, n_u)
    k_f, n_f = int(ind[~na10].sum()), int((~na10).sum())
    l_f, u_f = wilson(k_f, n_f)

    faixas_amostra = []
    for fb in faixas_base:
        sel = faixa == fb["faixa"]
        faixas_amostra.append({"faixa": fb["faixa"], "sorteados": int(sel.sum()), "positivos": int(ind[sel].sum()),
                               "esperado_sob_aas": n * fb["fracao_dos_enderecos"]})

    # diagnostico da composicao (nao previsto)
    obs = [f["sorteados"] for f in faixas_amostra]
    esp = [f["esperado_sob_aas"] for f in faixas_amostra]
    qui = chisquare(obs, esp)
    W = np.array([fb["fracao_dos_enderecos"] for fb in faixas_base])
    masc = [faixa == fb["faixa"] for fb in faixas_base]
    p_ps_end = float(sum(W[h] * ind[masc[h]].mean() for h in range(len(FAIXAS))))

    # 2) premissa: mesmo indicador na compilacao
    grupos = {}
    for u in unidos:
        grupos.setdefault(u["cid"], []).append(u)
    multi = {k: v for k, v in grupos.items() if len(v) >= 2}
    lista_multi = []
    for cid, us in sorted(multi.items(), key=lambda kv: (-kv[1][0]["c"], kv[0])):
        inds = sorted({u["ind"] for u in us})
        assin = {json.dumps(por_end[u["endereco"]]["assinatura"]) for u in us}
        lista_multi.append({"compilation_id": cid, "enderecos_na_base": us[0]["c"], "sorteados": len(us),
                            "indicadores": inds, "positivos": sum(u["ind"] for u in us),
                            "regioes_sem_metadados_identicas": len(assin) == 1,
                            "regioes_sem_metadados": json.loads(next(iter(assin))) if len(assin) == 1 else None})

    # mesma conferencia somando o ensaio (fora da amostra; versoes 1.0.0 a 1.2.0 e 1.7.0; bloco 26.290.000)
    g2 = {cid: [("amostra", u["endereco"], u["ind"], por_end[u["endereco"]]["assinatura"],
                 por_end[u["endereco"]]["versao"], por_end[u["endereco"]]["contrato_compilado"]) for u in us]
          for cid, us in grupos.items()}
    piloto_na_base = 0
    for addr, cid, cc in linhas_p:
        end = "0x" + bytes(addr).hex()
        pv = piloto[end]
        piloto_na_base += 1
        g2.setdefault(cid, []).append(("ensaio", end, int(pv["ind"]), pv["assinatura"], pv["versao"],
                                       pv["contrato_compilado"]))
    multi2 = {k: v for k, v in g2.items() if len(v) >= 2}
    com_pos2 = []
    for cid, v in sorted(multi2.items()):
        if any(x[2] == 1 for x in v):
            com_pos2.append({"compilation_id": cid,
                             "contratos": [{"origem": x[0], "endereco": x[1], "indicador": x[2], "versao": x[4],
                                            "contrato_compilado": x[5]} for x in v],
                             "regioes_sem_metadados_identicas": len({json.dumps(x[3]) for x in v}) == 1,
                             "regioes_sem_metadados": v[0][3]})
    premissa = {
        "por_construcao": ("Em atesta/regioes.py (delimitar), as regioes que podem ter tau = address (variavel "
                           "imutavel, biblioteca, protecao de chamada) e o tipo declarado vem da saida do compilador "
                           "para a entrada de compilacao guardada pelo acervo; o codigo lido da cadeia so acrescenta "
                           "os blocos de metadados (tau diferente de address). Enderecos da mesma compilacao recebem, "
                           "assim, o mesmo indicador, salvo se a entrada servida pelo acervo variar entre eles."),
        "amostra": {
            "compilacoes_distintas_na_amostra": len(grupos),
            "compilacoes_com_2_ou_mais_sorteados": len(multi),
            "sorteados_nessas_compilacoes": sum(len(v) for v in multi.values()),
            "compilacoes_com_indicador_misto": sum(len(x["indicadores"]) > 1 for x in lista_multi),
            "compilacoes_com_algum_positivo": sum(x["positivos"] > 0 for x in lista_multi),
            "compilacoes_com_regioes_sem_metadados_diferentes": sum(not x["regioes_sem_metadados_identicas"]
                                                                    for x in lista_multi),
            "lista": lista_multi,
        },
        "amostra_e_ensaio": {
            "nota": ("O ensaio (dados/piloto) tem contratos fora da amostra, lidos no bloco 26.290.000 e processados "
                     "pelas versoes 1.0.0 a 1.2.0 (as falhas, refeitas pela 1.7.0); entra so nesta conferencia."),
            "contratos_do_ensaio_processados": len(piloto),
            "versoes_no_ensaio": sorted({v["versao"] for v in piloto.values()}),
            "blocos_no_ensaio": sorted({v["bloco"] for v in piloto.values()}),
            "contratos_do_ensaio_na_base": piloto_na_base,
            "compilacoes_com_2_ou_mais_contratos": len(multi2),
            "contratos_nessas_compilacoes": sum(len(v) for v in multi2.values()),
            "compilacoes_com_indicador_misto": sum(len({x[2] for x in v}) > 1 for v in multi2.values()),
            "compilacoes_com_algum_positivo": len(com_pos2),
            "compilacoes_com_positivo": com_pos2,
        },
        "como_se_confere": ("Agrupam-se os contratos por compilation_id. Em cada compilacao com dois ou mais "
                            "contratos, confere-se se o indicador e o mesmo e se as regioes de F(a) que nao sao de "
                            "metadados (motivo, inicio, comprimento, tipo, tau_address, construto) sao identicas nas "
                            "certidoes."),
    }

    # 2) estimador de razao e bootstrap
    y = ind / c
    x = 1.0 / c
    p_r = float(y.sum() / x.sum())
    kish = float(x.sum() ** 2 / (x ** 2).sum())
    m_est = float(N / n * x.sum())
    idx = indices_bootstrap(n, SEMENTE)
    rb = y[idx].sum(axis=1) / x[idx].sum(axis=1)
    l_b, u_b = percentis(rb)
    estab = []
    for s in SEMENTES_ESTABILIDADE:
        i2 = indices_bootstrap(n, s)
        l2, u2 = percentis(y[i2].sum(axis=1) / x[i2].sum(axis=1))
        estab.append({"semente": s, "intervalo": [l2, u2], "decisao_descritiva": decisao_central(l2, u2, LIMIAR)})
    # erro-padrao linearizado da razao (so conferencia; com correcao de populacao finita sobre enderecos)
    xbar = float(x.mean())
    e = y - p_r * x
    ep_lin = math.sqrt((1 - n / N) * float((e ** 2).sum() / (n - 1)) / (n * xbar ** 2))

    # conferencia: pos-estratificacao em compilacao unica (c = 1) e demais (c >= 2), participacoes conhecidas
    Q1 = U / M
    dois = ~unica
    p_pc = Q1 * (k_u / n_u) + (1 - Q1) * float(y[dois].sum() / x[dois].sum())
    U_b = unica[idx]
    n1_b = U_b.sum(axis=1)
    k1_b = (ind[idx] * U_b).sum(axis=1)
    y2_b = (y[idx] * ~U_b).sum(axis=1)
    x2_b = (x[idx] * ~U_b).sum(axis=1)
    ok_pc = (n1_b > 0) & (x2_b > 0)
    pc_b = Q1 * k1_b[ok_pc] / n1_b[ok_pc] + (1 - Q1) * y2_b[ok_pc] / x2_b[ok_pc]
    l_pc, u_pc = percentis(pc_b)

    # diagnostico: fracao por endereco pos-estratificada pelas quatro faixas (mesmas reamostragens)
    ind_b = ind[idx]                                                  # (B, n)
    nh_b = np.stack([m[idx].sum(axis=1) for m in masc])               # (faixas, B)
    kh_b = np.stack([(ind_b * m[idx]).sum(axis=1) for m in masc])     # (faixas, B)
    ok_pe = (nh_b > 0).all(axis=0)
    pe_b = (W[:, None] * kh_b[:, ok_pe] / nh_b[:, ok_pe]).sum(axis=0)
    l_pe, u_pe = percentis(pe_b)

    estimador = {
        "aviso": ("Descritivo e nao previsto na subsecao 3.8: a regra de decisao do artigo usa o intervalo de "
                  "Wilson da fracao por endereco. Este intervalo e de bootstrap, sobre outra unidade."),
        "formula": "p = soma(ind_i / c_i) / soma(1 / c_i), soma sobre os 385 sorteados; c_i = enderecos da compilacao "
                   "do contrato i na base",
        "alvo": ("fracao de compilacoes da base com indicador 1, se o indicador for constante dentro da compilacao; "
                 "sem essa premissa, a media, entre as compilacoes, da fracao de seus enderecos com indicador 1"),
        "numerador_soma_ind_sobre_c": float(y.sum()),
        "denominador_soma_1_sobre_c": float(x.sum()),
        "p": p_r,
        "n_efetivo_kish": kish,
        "compilacoes_estimadas_N_sobre_n_vezes_soma_1_sobre_c": m_est,
        "compilacoes_na_base": int(M),
        "bootstrap": {
            "reamostragens": REAMOSTRAGENS,
            "semente": SEMENTE,
            "gerador": f"numpy {np.__version__} Generator(PCG64(semente)).integers(0, n, size=(B, n))",
            "unidades": "os 385 sorteados, na ordem do campo ordem das certidoes (ordem da permutacao do sorteio)",
            "metodo": "percentil (numpy.percentile, interpolacao linear) nos quantis 2,5% e 97,5%",
            "intervalo": [l_b, u_b],
            "media_das_reamostragens": float(rb.mean()),
            "erro_padrao": float(rb.std(ddof=1)),
            "estabilidade_outras_sementes": estab,
        },
        "linearizacao_conferencia": {
            "erro_padrao": ep_lin,
            "intervalo_p_mais_menos_z_ep": [p_r - Z * ep_lin, p_r + Z * ep_lin],
        },
        "decisao_descritiva": decisao_central(l_b, u_b, LIMIAR),
        "pos_estratificado_conferencia": {
            "formula": ("Q1 * k_u / n_u + (1 - Q1) * soma_{c>=2}(ind/c) / soma_{c>=2}(1/c), com Q1 = compilacoes "
                        "unicas / compilacoes da base (conhecido)"),
            "Q1": Q1,
            "p": p_pc,
            "intervalo_bootstrap_mesmas_reamostragens": [l_pc, u_pc],
            "reamostragens_validas": int(ok_pc.sum()),
            "decisao_descritiva": decisao_central(l_pc, u_pc, LIMIAR),
        },
    }

    composicao = {
        "aviso": "Diagnostico descritivo, nao previsto na subsecao 3.8; nao altera a estimativa do artigo.",
        "qui_quadrado_faixas": {"observado": obs, "esperado_sob_aas": esp, "estatistica": float(qui.statistic),
                                "graus_de_liberdade": len(obs) - 1, "p_valor": float(qui.pvalue)},
        "fracao_por_endereco_pos_estratificada_pelas_faixas": {
            "p": p_ps_end,
            "intervalo_bootstrap_mesmas_reamostragens": [l_pe, u_pe],
            "reamostragens_validas": int(ok_pe.sum()),
            "decisao_descritiva": decisao_central(l_pe, u_pe, LIMIAR),
            "fracao_do_artigo": hc["p"],
        },
    }

    # 3) leitura descritiva da decisao
    p_end, l_end, u_end = hc["p"], hc["l"], hc["u"]
    leitura = {
        "regra": "decisao_central de atesta/estatistica.py: refutada se u < 0,10; sustentada se l > 0,10; senao, "
                 "inconclusiva",
        "por_endereco_resultados_json": {"k": hc["k"], "n": hc["n"], "p": p_end, "wilson": [l_end, u_end],
                                         "decisao": hc["decisao"]},
        "por_compilacao_estimador_de_razao": {"p": p_r, "intervalo_bootstrap": [l_b, u_b],
                                              "decisao_descritiva": estimador["decisao_descritiva"]},
        "por_compilacao_pos_estratificado": {"p": p_pc, "intervalo_bootstrap": [l_pc, u_pc],
                                             "decisao_descritiva": decisao_central(l_pc, u_pc, LIMIAR)},
        "so_compilacoes_unicas_wilson": {"k": k_u, "n": n_u, "p": k_u / n_u, "wilson": [l_u, u_u],
                                         "decisao_descritiva": decisao_central(l_u, u_u, LIMIAR)},
        "mudaria": estimador["decisao_descritiva"] != hc["decisao"],
        "aviso": ("Leitura so descritiva: a hipotese central foi decidida por endereco, pela regra fixada antes da "
                  "coleta; nenhuma decisao por compilacao foi prevista."),
    }

    saida = {
        "aviso": ("Contagem descritiva, nao prevista na subsecao 3.8 do artigo. Nao altera as estimativas nem a "
                  "decisao das hipoteses, que sao por endereco (unidade de analise da subsecao 3.2)."),
        "gerado_em_utc": inicio.isoformat(timespec="seconds"),
        "programa": relativo(Path(__file__).resolve()),
        "ambiente": {"python": platform.python_version(), "numpy": np.__version__, "duckdb": duckdb.__version__,
                     "scipy": scipy.__version__, "z": Z},
        "entradas": {
            "base": {"caminho": relativo(BASE), "bytes": os.path.getsize(BASE), "sha256": sha256_arquivo(BASE)},
            "certidoes": {"pasta": relativo(CERT), "arquivos": len(arquivos),
                          "sha256_do_conjunto": h_cert.hexdigest(),
                          "como": "sha256 da concatenacao, em ordem de nome, de nome + NUL + sha256(arquivo)"},
            "piloto": {"pasta": relativo(PILOTO), "contratos_processados_fora_da_amostra": len(piloto)},
            "amostra": {"caminho": relativo(AMOSTRA), "sha256": sha256_arquivo(AMOSTRA)},
            "resultados": {"caminho": relativo(RESULTADOS), "sha256": sha256_arquivo(RESULTADOS)},
            "estatistica": {"caminho": relativo(ESTATISTICA), "sha256": sha256_arquivo(ESTATISTICA),
                            "funcoes_importadas": ["wilson", "decisao_central", "Z"]},
        },
        "base": {
            "enderecos": int(N),
            "enderecos_distintos": int(N_dist),
            "compilation_id_nulos": int(cid_nulos),
            "compilacoes_distintas": int(M),
            "maximo_de_nomes_de_contrato_por_compilacao": int(nomes_max),
            "maximo_de_versoes_do_compilador_por_compilacao": int(versoes_max),
            "maior_compilacao_enderecos": int(maior_c),
            "dez_mais_frequentes": {
                "enderecos": soma10,
                "fracao_dos_enderecos": soma10 / N,
                "tamanho_da_decima": int(top11[9][1]),
                "tamanho_da_decima_primeira": int(top11[10][1]),
                "empate_na_decima": bool(empate_na_decima),
                "criterio_de_desempate": "compilation_id crescente (nao houve empate se empate_na_decima = false)",
                "lista": lista10,
            },
            "compilacao_unica": {"compilacoes": int(U), "fracao_das_compilacoes": U / M,
                                 "enderecos": int(U), "fracao_dos_enderecos": U / N},
            "faixas_de_tamanho": faixas_base,
        },
        "juncao": juncao,
        "sorteados": {
            "n": n,
            "positivos": k_total,
            "nas_dez_mais_frequentes": {"sorteados": int(na10.sum()), "positivos": pos10},
            "fora_das_dez_mais_frequentes": {"sorteados": n_f, "positivos": k_f, "p": k_f / n_f,
                                             "wilson": [l_f, u_f],
                                             "nota": "dominio por endereco (enderecos fora das dez compilacoes)"},
            "compilacao_unica": {"sorteados": n_u, "positivos": k_u, "p": k_u / n_u, "wilson": [l_u, u_u],
                                 "nota": ("sob amostragem aleatoria simples de enderecos, estes sorteados formam "
                                          "amostra aleatoria simples das compilacoes unicas da base")},
            "faixas_de_tamanho": faixas_amostra,
        },
        "diagnostico_da_composicao": composicao,
        "premissa_indicador_constante_na_compilacao": premissa,
        "estimador_de_razao": estimador,
        "decisao_nessa_unidade": leitura,
    }
    SAIDAS.mkdir(parents=True, exist_ok=True)
    with open(SAIDA_JSON, "w", encoding="utf-8") as fh:
        json.dump(saida, fh, ensure_ascii=False, indent=1)

    with open(SAIDA_CSV, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["ordem", "endereco", "grau", "indicador_equacao_2", "compilation_id", "enderecos_da_compilacao",
                    "faixa", "nas_dez_mais_frequentes", "sorteados_na_mesma_compilacao"])
        for u in unidos:
            w.writerow([u["ordem"], u["endereco"], u["grau"], u["ind"], u["cid"], u["c"], faixa_de(u["c"]),
                        int(u["cid"] in cids10), len(grupos[u["cid"]])])

    pa, pe = premissa["amostra"], premissa["amostra_e_ensaio"]
    print(f"base: {N} enderecos, {M} compilacoes; dez mais frequentes: {soma10} ({fmt_pct(soma10 / N)})")
    print(f"juncao: {n} de 385, cobre_os_385={juncao['cobre_os_385']}, k={k_total}")
    print(f"nas dez: {int(na10.sum())} sorteados, {pos10} positivos; fora: {k_f}/{n_f}")
    print(f"compilacao unica: {k_u}/{n_u} = {k_u / n_u:.4f} [{l_u:.4f}; {u_u:.4f}] -> {decisao_central(l_u, u_u)}")
    for fa in faixas_amostra:
        print(f"  faixa {fa['faixa']}: {fa['sorteados']} sorteados, {fa['positivos']} positivos, "
              f"esperado {fa['esperado_sob_aas']:.1f}")
    print(f"qui-quadrado {qui.statistic:.2f}, p {qui.pvalue:.4f}; por endereco pos-estratificada {p_ps_end:.4f} "
          f"[{l_pe:.4f}; {u_pe:.4f}]")
    print(f"premissa amostra: {pa['compilacoes_com_2_ou_mais_sorteados']} compilacoes com 2+, "
          f"{pa['compilacoes_com_indicador_misto']} mistas, {pa['compilacoes_com_algum_positivo']} com positivo")
    print(f"premissa amostra+ensaio: {pe['compilacoes_com_2_ou_mais_contratos']} compilacoes com 2+, "
          f"{pe['compilacoes_com_indicador_misto']} mistas, {pe['compilacoes_com_algum_positivo']} com positivo")
    print(f"razao: {p_r:.4f} bootstrap [{l_b:.4f}; {u_b:.4f}] -> {estimador['decisao_descritiva']}; "
          f"Kish {kish:.1f}; M estimado {m_est:.0f} (base {M})")
    print(f"pos-estratificado: {p_pc:.4f} [{l_pc:.4f}; {u_pc:.4f}]")


if __name__ == "__main__":
    main()
