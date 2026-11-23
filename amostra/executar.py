# -*- coding: utf-8 -*-
"""Etapas 7 e 8 (subsecao 3.6): executa o verificador sobre cada um dos 385 contratos elegiveis da amostra, na ordem
da permutacao, e acrescenta a classificacao do alvo. Grava uma certidao por contrato em dados/certidoes/ e o resumo
em dados/execucao.json. A falha do instrumento nao exclui o contrato: fica registrada para diagnostico; corrigido o
verificador, ele e revalidado nos controles e a amostra inteira e reprocessada (--refazer).

Uso: python amostra/executar.py [--paralelo 6] [--refazer]"""
import argparse
import csv
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from atesta import VERSAO  # noqa: E402
from atesta.acervo import APISourcify, ErroAcervo  # noqa: E402
from atesta.config import CERTIDOES, DADOS  # noqa: E402
from atesta.rpc import RPC  # noqa: E402
from atesta.verificador import classificar_certidao, verificar  # noqa: E402


class Verificados:
    """endereco -> conjunto dos resumos SHA-256 do codigo implantado registrados no instantaneo (rede principal).
    Consulta sob demanda na tabela ordenada por endereco (instantaneo.duckdb, tabela verificados_ord)."""

    def __init__(self):
        import threading
        self.con = duckdb.connect(str(DADOS / "instantaneo.duckdb"), read_only=True)
        self.trava = threading.Lock()

    def __call__(self, endereco):
        with self.trava:
            r = self.con.execute("SELECT runtime_code_hash FROM verificados_ord WHERE address = from_hex(?)",
                                 [endereco.lower()[2:]]).fetchall()
        return {bytes(x[0]).hex() for x in r}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--paralelo", type=int, default=6)
    ap.add_argument("--refazer", action="store_true")
    ap.add_argument("--limite", type=int, default=0)
    a = ap.parse_args()
    sorteio = json.loads((DADOS / "sorteio.json").read_text(encoding="utf-8"))
    bloco = sorteio["bloco_referencia"]
    with open(DADOS / "amostra.csv", encoding="utf-8") as f:
        amostra = [r for r in csv.DictReader(f) if r["elegivel"] == "1"]
    if a.limite:
        amostra = amostra[:a.limite]
    rpc, api = RPC(), APISourcify()
    print("carregando verificados do instantaneo...", flush=True)
    verificados = Verificados()

    def um(r):
        destino = CERTIDOES / f"{r['endereco']}.json"
        if destino.exists() and not a.refazer:
            c = json.loads(destino.read_text(encoding="utf-8"))
            if c["verificador"]["versao"] == VERSAO:
                return c
        try:
            reg = api.contrato(1, r["endereco"])
        except ErroAcervo as e:
            c = {"esquema": "certidao-atesta/1", "verificador": {"nome": "atesta", "versao": VERSAO},
                 "contrato": {"rede": 1, "endereco": r["endereco"], "bloco_referencia": bloco},
                 "situacao": "falha", "causa": f"ErroAcervo: {e}"}
        else:
            c = verificar(r["endereco"], bloco, rpc, reg)
            c["acervo"]["match_id_instantaneo"] = int(r["match_id_instantaneo"])
            c["acervo"]["grau_instantaneo"] = r["grau"]
            c["acervo"]["match_id_coincide"] = str(reg.get("matchId")) == str(r["match_id_instantaneo"])
            c = classificar_certidao(c, rpc, verificados)
        c["ordem"] = int(r["ordem"])
        destino.write_text(json.dumps(c, indent=1, ensure_ascii=False), encoding="utf-8")
        return c

    t0 = time.time()
    certs = []
    with ThreadPoolExecutor(a.paralelo) as ex:
        futs = {ex.submit(um, r): r for r in amostra}
        for i, f in enumerate(as_completed(futs), 1):
            c = f.result()
            certs.append(c)
            if c["situacao"] != "processado":
                print(f"  falha {c['contrato']['endereco']}: {c.get('causa', '')[:160]}", flush=True)
            if i % 25 == 0 or i == len(amostra):
                print(f"{i}/{len(amostra)} ({time.time() - t0:.0f} s); falhas ate aqui: "
                      f"{sum(1 for x in certs if x['situacao'] != 'processado')}", flush=True)
    resumo = {"verificador": VERSAO, "bloco_referencia": bloco, "contratos": len(certs),
              "processados": sum(1 for c in certs if c["situacao"] == "processado"),
              "falhas": [{"endereco": c["contrato"]["endereco"], "causa": c.get("causa")} for c in certs
                         if c["situacao"] != "processado"],
              "chamadas_rpc_rede": rpc.chamadas_rede, "segundos": round(time.time() - t0)}
    (DADOS / "execucao.json").write_text(json.dumps(resumo, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in resumo.items() if k != "falhas"}, indent=1), "\nfalhas:", len(resumo["falhas"]))


if __name__ == "__main__":
    main()
