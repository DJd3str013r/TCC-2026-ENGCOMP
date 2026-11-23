# -*- coding: utf-8 -*-
"""Etapa 6 (subsecao 3.5): sorteio. A base, ordenada pelo valor numerico do endereco, recebe uma permutacao
aleatoria uniforme (gerador PCG64 do numpy) cuja semente e o resumo (hash) do bloco de referencia, valor publico,
fixado e registrado antes do sorteio. Os contratos sao examinados na ordem da permutacao, com a leitura do
codigo no bloco de referencia: o que nao satisfaz o criterio da cadeia (codigo existe e coincide com o implantado
registrado no acervo) e excluido e substituido pelo seguinte, ate reunir 385 elegiveis.

Uso: python amostra/sortear.py --bloco <altura>"""
import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from atesta.config import DADOS, TAMANHO_AMOSTRA  # noqa: E402
from atesta.rpc import RPC  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bloco", type=int, required=True)
    a = ap.parse_args()
    rpc = RPC()
    bloco = rpc.bloco(a.bloco)
    semente = int(bloco["hash"], 16)
    registro = {"bloco_referencia": a.bloco, "hash_bloco": bloco["hash"],
                "data_bloco_utc": datetime.fromtimestamp(int(bloco["timestamp"], 16), timezone.utc).isoformat(),
                "semente": str(semente), "gerador": f"numpy {np.__version__} PCG64, permutation(N)",
                "registrado_em": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    arq_semente = DADOS / "sorteio_semente.json"
    if arq_semente.exists():   # o registro feito antes do primeiro sorteio prevalece
        anterior = json.loads(arq_semente.read_text(encoding="utf-8"))
        assert anterior["bloco_referencia"] == a.bloco and anterior["semente"] == registro["semente"]
        registro = anterior
    else:
        arq_semente.write_text(json.dumps(registro, indent=1), encoding="utf-8")

    con = duckdb.connect()
    base = con.execute(f"SELECT indice, address, runtime_code_hash, runtime_metadata_match, version, match_id "
                       f"FROM read_parquet('{(DADOS / 'base.parquet').as_posix()}') ORDER BY indice").fetchall()
    N = len(base)
    perm = np.random.Generator(np.random.PCG64(semente)).permutation(N)
    examinados, elegiveis = [], 0
    for ordem, idx in enumerate(perm):
        indice, endereco, resumo, meta, versao, match_id = base[int(idx)]
        end = "0x" + bytes(endereco).hex()
        codigo = rpc.codigo(end, a.bloco)
        if not codigo:
            motivo = "sem codigo no bloco de referencia"
        elif hashlib.sha256(codigo).digest() != bytes(resumo):   # o acervo guarda SHA-256 do codigo
            motivo = "codigo no bloco de referencia difere do registrado no acervo"
        else:
            motivo = ""
        if not motivo:
            elegiveis += 1
        examinados.append({"ordem": ordem, "indice_base": int(indice), "endereco": end, "elegivel": int(not motivo),
                           "motivo_exclusao": motivo, "grau": "exata" if meta else "parcial", "compilador": versao,
                           "match_id_instantaneo": int(match_id)})
        if elegiveis == TAMANHO_AMOSTRA:
            break
    with open(DADOS / "amostra.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(examinados[0]))
        w.writeheader()
        w.writerows(examinados)
    registro.update({"N_base": N, "examinados": len(examinados), "elegiveis": elegiveis,
                     "excluidos": len(examinados) - elegiveis,
                     "exclusoes_por_motivo": {m: sum(1 for e in examinados if e["motivo_exclusao"] == m)
                                              for m in {e["motivo_exclusao"] for e in examinados} if m}})
    (DADOS / "sorteio.json").write_text(json.dumps(registro, indent=1), encoding="utf-8")
    print(json.dumps(registro, indent=1))


if __name__ == "__main__":
    main()
