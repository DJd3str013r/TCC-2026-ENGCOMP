# -*- coding: utf-8 -*-
"""Etapa 5 (parte 2): delimitacao da populacao e enumeracao da base de amostragem (subsecao 3.5).

Base = enderecos da rede principal cuja verificacao vigente no instantaneo e de contrato declarado em Solidity e com
correspondencia registrada para o codigo de execucao (exata ou parcial); uma verificacao por endereco (a vigente:
linha de sourcify_matches com updated_at mais recente). Ordem: valor numerico do endereco.
Tambem grava, para a classificacao do alvo, o conjunto dos enderecos verificados na rede principal com o resumo do
codigo implantado registrado (qualquer linguagem e grau).

Uso: python instantaneo/base.py"""
import json
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from atesta.config import DADOS, INSTANTANEO  # noqa: E402


def main():
    con = duckdb.connect(str(DADOS / "instantaneo.duckdb"))
    for t in ("contract_deployments", "verified_contracts", "sourcify_matches", "compiled_contracts", "contracts"):
        con.execute(f"CREATE OR REPLACE VIEW {t} AS SELECT * FROM read_parquet('{(INSTANTANEO / t).as_posix()}/*.parquet')")
    con.execute("""
        CREATE OR REPLACE TABLE sm_vigente AS
        SELECT * EXCLUDE (rn) FROM (
          SELECT *, row_number() OVER (PARTITION BY id ORDER BY updated_at DESC) AS rn FROM sourcify_matches) WHERE rn = 1""")
    con.execute("""
        CREATE OR REPLACE TABLE vigente AS
        SELECT d.address, d.id AS deployment_id, d.contract_id, d.block_number,
               v.id AS verified_contract_id, v.compilation_id, v.runtime_match, v.runtime_metadata_match,
               v.creation_match, v.creation_metadata_match, s.id AS match_id, s.runtime_match AS grau_sourcify,
               s.updated_at, c.language, c.version, c.fully_qualified_name, k.runtime_code_hash
        FROM sm_vigente s
        JOIN verified_contracts v ON v.id = s.verified_contract_id
        JOIN contract_deployments d ON d.id = v.deployment_id
        JOIN compiled_contracts c ON c.id = v.compilation_id
        JOIN contracts k ON k.id = d.contract_id""")
    con.execute("""
        CREATE OR REPLACE TABLE vigente_endereco AS
        SELECT * EXCLUDE (rn) FROM (
          SELECT *, row_number() OVER (PARTITION BY address ORDER BY updated_at DESC, match_id DESC) AS rn
          FROM vigente) WHERE rn = 1""")
    con.execute("""
        CREATE OR REPLACE TABLE base AS
        SELECT row_number() OVER (ORDER BY address) - 1 AS indice, *
        FROM vigente_endereco WHERE lower(language) = 'solidity' AND runtime_match ORDER BY address""")
    con.execute("""
        CREATE OR REPLACE TABLE verificados AS
        SELECT DISTINCT d.address, k.runtime_code_hash
        FROM verified_contracts v JOIN contract_deployments d ON d.id = v.deployment_id
        JOIN contracts k ON k.id = d.contract_id""")
    con.execute("CREATE OR REPLACE TABLE verificados_ord AS SELECT address, runtime_code_hash FROM verificados ORDER BY address")
    con.execute(f"COPY base TO '{(DADOS / 'base.parquet').as_posix()}' (FORMAT parquet)")
    con.execute(f"COPY verificados TO '{(DADOS / 'verificados.parquet').as_posix()}' (FORMAT parquet)")
    r = {
        "mainnet_implantacoes": con.execute("SELECT count(*) FROM contract_deployments").fetchone()[0],
        "verificacoes_vigentes_mainnet": con.execute("SELECT count(*) FROM vigente").fetchone()[0],
        "enderecos_com_verificacao_vigente": con.execute("SELECT count(*) FROM vigente_endereco").fetchone()[0],
        "por_linguagem": con.execute("SELECT language, count(*) FROM vigente_endereco GROUP BY 1 ORDER BY 2 DESC").fetchall(),
        "solidity_sem_correspondencia_execucao": con.execute(
            "SELECT count(*) FROM vigente_endereco WHERE lower(language)='solidity' AND NOT runtime_match").fetchone()[0],
        "base": con.execute("SELECT count(*) FROM base").fetchone()[0],
        "base_por_grau": con.execute(
            "SELECT runtime_metadata_match, count(*) FROM base GROUP BY 1 ORDER BY 1").fetchall(),
        "base_grau_sourcify": con.execute("SELECT grau_sourcify, runtime_metadata_match, count(*) FROM base GROUP BY 1,2").fetchall(),
        "enderecos_verificados_qualquer": con.execute("SELECT count(DISTINCT address) FROM verificados").fetchone()[0],
    }
    (DADOS / "base_resumo.json").write_text(json.dumps(r, indent=1, default=str), encoding="utf-8")
    print(json.dumps(r, indent=1, default=str))


if __name__ == "__main__":
    main()
