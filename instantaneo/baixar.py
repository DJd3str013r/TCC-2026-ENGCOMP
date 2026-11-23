# -*- coding: utf-8 -*-
"""Etapa 5 (parte 1): baixa do instantaneo da exportacao Parquet v2 do Sourcify so as colunas necessarias, uma vez,
para dados/instantaneo/<tabela>/<arquivo>.parquet, e grava o manifesto (chave, tamanho, ETag, data de modificacao de
cada arquivo de origem, como publicados pelo servidor).

Uso: python instantaneo/baixar.py [--paralelo 6]"""
import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from atesta.config import EXPORT_BASE, INSTANTANEO  # noqa: E402

TABELAS = {
    # tabela: (colunas, filtro)
    "contract_deployments": ("id, address, contract_id, block_number", "WHERE chain_id = 1"),
    "verified_contracts": ("id, deployment_id, compilation_id, creation_match, runtime_match, "
                           "runtime_metadata_match, creation_metadata_match", ""),
    "sourcify_matches": ("id, verified_contract_id, creation_match, runtime_match, created_at, updated_at", ""),
    "compiled_contracts": ("id, compiler, version, language, name, fully_qualified_name", ""),
    "contracts": ("id, runtime_code_hash", ""),
}


def listar(tabela):
    url = f"{EXPORT_BASE}?prefix=v2/{tabela}/"
    x = requests.get(url, timeout=120).text
    if "<IsTruncated>true</IsTruncated>" in x:
        raise RuntimeError(f"listagem truncada para {tabela}")
    arquivos = []
    for bloco in re.findall(r"<Contents>(.*?)</Contents>", x, re.S):
        g = lambda tag: (re.search(f"<{tag}>(.*?)</{tag}>", bloco) or [None, None])[1]
        arquivos.append({"chave": g("Key"), "tamanho": int(g("Size")), "etag": (g("ETag") or "").strip('"'),
                         "modificado": g("LastModified")})
    return arquivos


def baixar_arquivo(tabela, arq):
    destino = INSTANTANEO / tabela / (Path(arq["chave"]).stem + ".parquet")
    if destino.exists():
        return destino, 0.0
    cols, filtro = TABELAS[tabela]
    url = EXPORT_BASE + arq["chave"]
    tmp = destino.with_suffix(".tmp")
    for tentativa in range(5):
        try:
            t0 = time.time()
            con = duckdb.connect()
            con.execute("LOAD httpfs;")
            con.execute(f"COPY (SELECT {cols} FROM read_parquet('{url}') {filtro}) TO '{tmp.as_posix()}' "
                        f"(FORMAT parquet, COMPRESSION zstd)")
            con.close()
            tmp.replace(destino)
            return destino, time.time() - t0
        except Exception as e:  # noqa: BLE001
            ultimo = e
            time.sleep(5 * (tentativa + 1))
    raise RuntimeError(f"{arq['chave']}: {ultimo}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--paralelo", type=int, default=6)
    ap.add_argument("--tabelas", nargs="*", default=list(TABELAS))
    a = ap.parse_args()
    duckdb.connect().execute("INSTALL httpfs;")
    man_arq = INSTANTANEO / "manifesto.json"
    manifesto = json.loads(man_arq.read_text(encoding="utf-8")) if man_arq.exists() else {}
    if "listado_em" not in manifesto:
        manifesto["listado_em"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        manifesto["origem"] = EXPORT_BASE + "?prefix=v2/"
        manifesto["tabelas"] = {}
    for t in a.tabelas:
        if t not in manifesto["tabelas"]:
            manifesto["tabelas"][t] = {"colunas": TABELAS[t][0], "filtro": TABELAS[t][1], "arquivos": listar(t)}
            man_arq.write_text(json.dumps(manifesto, indent=1), encoding="utf-8")
    for t in a.tabelas:
        (INSTANTANEO / t).mkdir(parents=True, exist_ok=True)
        arquivos = manifesto["tabelas"][t]["arquivos"]
        t0 = time.time()
        with ThreadPoolExecutor(a.paralelo) as ex:
            futs = [ex.submit(baixar_arquivo, t, arq) for arq in arquivos]
            for i, f in enumerate(as_completed(futs), 1):
                f.result()
                if i % 20 == 0 or i == len(arquivos):
                    print(f"{t}: {i}/{len(arquivos)} arquivos ({time.time() - t0:.0f} s)", flush=True)
    print("ok")


if __name__ == "__main__":
    main()
