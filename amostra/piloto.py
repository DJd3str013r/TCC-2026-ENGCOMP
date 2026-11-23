# -*- coding: utf-8 -*-
"""Ensaio do verificador antes do sorteio oficial (nao entra nas estimativas): sorteia, com semente propria e
diferente da oficial, enderecos verificados da rede principal com correspondencia do codigo de execucao e roda o
verificador, para achar falhas do instrumento antes da medicao. Grava dados/piloto/.

Uso: python amostra/piloto.py --n 40 --bloco <altura> [--semente 2026]"""
import argparse
import json
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import duckdb
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from atesta.acervo import APISourcify, ErroAcervo  # noqa: E402
from atesta.config import DADOS, INSTANTANEO  # noqa: E402
from atesta.rpc import RPC  # noqa: E402
from atesta.verificador import verificar  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--bloco", type=int, required=True)
    ap.add_argument("--semente", type=int, default=2026)
    ap.add_argument("--paralelo", type=int, default=6)
    a = ap.parse_args()
    con = duckdb.connect()
    con.execute("SET threads TO 1")   # REPEATABLE so e deterministico com uma thread (P-19)
    linhas = con.execute(f"""
        SELECT d.address FROM read_parquet('{(INSTANTANEO / 'contract_deployments').as_posix()}/*.parquet') d
        JOIN read_parquet('{(INSTANTANEO / 'verified_contracts').as_posix()}/*.parquet') v ON v.deployment_id = d.id
        WHERE v.runtime_match USING SAMPLE reservoir(4000 ROWS) REPEATABLE ({a.semente})""").fetchall()
    ends = sorted({"0x" + bytes(x[0]).hex() for x in linhas})
    rng = np.random.default_rng(a.semente)
    escolhidos = [ends[i] for i in rng.permutation(len(ends))[: a.n * 2]]
    rpc, api = RPC(), APISourcify()
    saida = DADOS / "piloto"
    saida.mkdir(exist_ok=True)

    def um(end):
        try:
            reg = api.contrato(1, end)
        except ErroAcervo as e:
            return {"endereco": end, "situacao": "sem_api", "causa": str(e)}
        if (reg.get("compilation") or {}).get("language", "").lower() != "solidity" or not reg.get("runtimeMatch"):
            return {"endereco": end, "situacao": "fora_da_base"}
        if not rpc.codigo(end, a.bloco):
            return {"endereco": end, "situacao": "sem_codigo"}
        c = verificar(end, a.bloco, rpc, reg)
        (saida / f"{end}.json").write_text(json.dumps(c, indent=1, ensure_ascii=False), encoding="utf-8")
        return {"endereco": end, "situacao": c["situacao"], "causa": c.get("causa"),
                "compilador": c["acervo"]["compilador"], "coincide": (c.get("confronto_acervo") or {}).get("coincide")}

    res = []
    with ThreadPoolExecutor(a.paralelo) as ex:
        for f in as_completed([ex.submit(um, e) for e in escolhidos]):
            r = f.result()
            res.append(r)
            if r["situacao"] == "falha":
                print("FALHA", r["endereco"], r.get("compilador"), (r.get("causa") or "")[:200], flush=True)
    # todos os 2n candidatos sao verificados e relatados (antes, o laco parava em n e as falhas dos demais, ja
    # gravadas em dados/piloto/, nao apareciam no resumo; P-19)
    print(Counter(r["situacao"] for r in res))
    print("confronto com o acervo:", Counter(r.get("coincide") for r in res if r["situacao"] == "processado"))
    (saida / "resumo.json").write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
