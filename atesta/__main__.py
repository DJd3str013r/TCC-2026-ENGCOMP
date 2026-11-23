# -*- coding: utf-8 -*-
"""python -m atesta <endereco> --bloco <altura>: certidao de um contrato da rede principal na saida padrao."""
import argparse
import json
import sys

from .acervo import APISourcify
from .rpc import RPC
from .verificador import classificar_certidao, verificar


def main():
    ap = argparse.ArgumentParser(prog="atesta")
    ap.add_argument("endereco")
    ap.add_argument("--bloco", type=int, required=True)
    ap.add_argument("--rede", type=int, default=1)
    a = ap.parse_args()
    rpc = RPC()
    reg = APISourcify().contrato(a.rede, a.endereco)
    c = verificar(a.endereco, a.bloco, rpc, reg, rede=a.rede)
    c = classificar_certidao(c, rpc, lambda v: set())   # sem o instantaneo: 'verificado no acervo' fica indisponivel
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(c, indent=1, ensure_ascii=False))
    return 0 if c["situacao"] == "processado" else 2


if __name__ == "__main__":
    sys.exit(main())
