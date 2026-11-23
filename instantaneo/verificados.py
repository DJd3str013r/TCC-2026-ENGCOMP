# -*- coding: utf-8 -*-
"""Monta dados/instantaneo.duckdb so com a tabela verificados_ord, que amostra/executar.py consulta, a partir de
dados/verificados.parquet (o mesmo conteudo que instantaneo/base.py grava nas duas). Serve a quem tem os arquivos
publicados e nao o instantaneo projetado; nao roda se dados/instantaneo.duckdb ja existir.

Uso: python instantaneo/verificados.py"""
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from atesta.config import DADOS  # noqa: E402


def main():
    destino = DADOS / "instantaneo.duckdb"
    if destino.exists():
        sys.exit("dados/instantaneo.duckdb ja existe")
    con = duckdb.connect(str(destino))
    con.execute(f"CREATE TABLE verificados_ord AS SELECT address, runtime_code_hash FROM "
                f"read_parquet('{(DADOS / 'verificados.parquet').as_posix()}') ORDER BY address")
    print(con.execute("SELECT count(*) FROM verificados_ord").fetchone()[0], "enderecos em verificados_ord")
    con.close()


if __name__ == "__main__":
    main()
