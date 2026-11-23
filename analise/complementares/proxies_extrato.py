# -*- coding: utf-8 -*-
"""Extrato do instantaneo para as leituras complementares de proxies (subsecao 4.6 do artigo; leituras descritivas,
nao previstas nas subsecoes 3.6 e 3.8). O instantaneo (dados/instantaneo.duckdb) nao e publicado, e
dados/base.parquet, que tem as mesmas colunas, so traz contratos em Solidity com correspondencia do codigo de
execucao: faltariam cinco dos alvos, em Vyper. Este programa grava uma vez, da tabela vigente_endereco, as colunas
fully_qualified_name, version e grau_sourcify dos enderecos que proxies_delegacao.py e proxies_compartimentos.py
consultam: os valores com codigo das constantes do tipo address dos 13 positivos (dados/certidoes/*.json) e os
enderecos cujo codigo proxies_compartimentos.py leu (respostas eth_getCode guardadas em
dados/complementares/proxies_compartimentos_respostas_codigo.jsonl). Endereco sem verificacao vigente fica com os tres
campos vazios. O resumo do codigo registrado (runtime_code_hash), que proxies_compartimentos.py e
proxies_administrador.py consultam, vem de dados/verificados.parquet, que tem as linhas da tabela verificados_ord do
instantaneo.

Le dados/instantaneo.duckdb (so leitura). Grava dados/complementares/proxies_extrato.csv. Nao acessa a rede.

Uso: python analise/complementares/proxies_extrato.py"""
import csv
import glob
import json
import shutil
import sys
import tempfile
from pathlib import Path

import duckdb

RAIZ = Path(__file__).resolve().parents[2]
CERTIDOES = RAIZ / "dados" / "certidoes"
INSTANTANEO = RAIZ / "dados" / "instantaneo.duckdb"
RESPOSTAS_CODIGO = RAIZ / "dados" / "complementares" / "proxies_compartimentos_respostas_codigo.jsonl"
EXTRATO = RAIZ / "dados" / "complementares" / "proxies_extrato.csv"
COLUNAS = ["address", "fully_qualified_name", "version", "grau_sourcify"]


def enderecos_consultados():
    """Valores com codigo das constantes do tipo address dos positivos e enderecos lidos por eth_getCode em
    proxies_compartimentos.py."""
    ends = set()
    for p in sorted(glob.glob(str(CERTIDOES / "*.json"))):
        c = json.load(open(p, encoding="utf-8"))
        if c.get("indicador_equacao_2") != 1:
            continue
        for k in c["constantes"]:
            if not k.get("tau_address"):
                continue
            for v in k["valores"]:
                if ((k.get("alvos") or {}).get(v) or {}).get("tamanho_codigo"):
                    ends.add(v.lower())
    for linha in open(RESPOSTAS_CODIGO, encoding="utf-8"):
        d = json.loads(linha)
        if d["metodo"] == "eth_getCode":
            ends.add(d["params"][0].lower())
    return sorted(ends)


def main():
    for p in (CERTIDOES, INSTANTANEO, RESPOSTAS_CODIGO):
        if not p.exists():
            sys.exit(f"entrada ausente: {p.relative_to(RAIZ).as_posix()}")
    tmp = tempfile.mkdtemp(prefix="duckdb_")
    con = duckdb.connect(str(INSTANTANEO), read_only=True, config={"temp_directory": Path(tmp).as_posix()})
    linhas = []
    for e in enderecos_consultados():
        r = con.execute("SELECT fully_qualified_name, version, grau_sourcify FROM vigente_endereco "
                        "WHERE address = from_hex(?)", [e[2:]]).fetchall()
        assert len(r) <= 1, e   # vigente_endereco tem uma linha por endereco
        linhas.append([e, *(("" if x is None else x) for x in (r[0] if r else (None, None, None)))])
    con.close()
    shutil.rmtree(tmp, ignore_errors=True)
    EXTRATO.parent.mkdir(parents=True, exist_ok=True)
    with open(EXTRATO, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLUNAS)
        w.writerows(linhas)
    print(json.dumps({"enderecos": len(linhas), "com_verificacao_vigente": sum(1 for x in linhas if x[1]),
                      "extrato": EXTRATO.relative_to(RAIZ).as_posix()}, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
