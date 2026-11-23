# -*- coding: utf-8 -*-
"""Refaz, com a versao atual do verificador, os contratos do ensaio (amostra/piloto.py) cuja certidao terminou em
falha, no mesmo bloco do ensaio. As certidoes originais ficam intactas em dados/piloto/; as refeitas vao para
dados/piloto/refeitos-<versao>/, com um resumo.json. O ensaio nao entra nas estimativas.

Uso: python amostra/piloto_refazer.py"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from atesta import VERSAO  # noqa: E402
from atesta.acervo import APISourcify  # noqa: E402
from atesta.config import DADOS  # noqa: E402
from atesta.rpc import RPC  # noqa: E402
from atesta.verificador import verificar  # noqa: E402


def main():
    origem = DADOS / "piloto"
    falhas = [c for c in (json.loads(p.read_text(encoding="utf-8")) for p in sorted(origem.glob("0x*.json")))
              if c["situacao"] != "processado"]
    destino = origem / f"refeitos-{VERSAO}"
    destino.mkdir(exist_ok=True)
    rpc, api = RPC(), APISourcify()
    res = []
    for c in falhas:
        end, bloco = c["contrato"]["endereco"], c["contrato"]["bloco_referencia"]
        novo = verificar(end, bloco, rpc, api.contrato(1, end))
        (destino / f"{end}.json").write_text(json.dumps(novo, indent=1, ensure_ascii=False), encoding="utf-8")
        res.append({"endereco": end, "compilador": c["acervo"]["compilador"], "versao_original": c["verificador"]["versao"],
                    "causa_original": c.get("causa"), "situacao": novo["situacao"], "causa": novo.get("causa"),
                    "motor": (novo.get("recompilacao") or {}).get("motor"),
                    "coincide": (novo.get("confronto_acervo") or {}).get("coincide")})
        print(end, c["acervo"]["compilador"], "->", novo["situacao"], (novo.get("causa") or "")[:120], flush=True)
    (destino / "resumo.json").write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    print(Counter(r["situacao"] for r in res))


if __name__ == "__main__":
    main()
