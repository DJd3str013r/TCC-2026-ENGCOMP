# -*- coding: utf-8 -*-
"""Administrador do proxy de outro padrao (subsecao 4.6 do artigo). Leitura complementar, descritiva, nao prevista nas
subsecoes 3.6 e 3.8, feita depois da coleta sobre o estado do mesmo bloco de referencia: no USDC (0xa0b86991...,
FiatTokenProxy), unico alvo com implementacao em compartimento de outro padrao, le de novo os compartimentos e le o
codigo dos enderecos de administrador e de implementacao guardados neles.

Por JSON-RPC direto (urllib), nos nos publicos da lista RPCS_REDE_PRINCIPAL de atesta/config.py (a mesma de
atesta/rpc.py), sempre no bloco 26.296.341 (parametro numerico 0x1914015, nunca 'latest'), sem usar nem gravar o
cache de RPC do projeto:
  - eth_chainId e eth_getBlockByNumber (hash do bloco contra dados/sorteio_semente.json);
  - eth_getStorageAt no USDC nos compartimentos keccak256("org.zeppelinos.proxy.implementation"),
    keccak256("org.zeppelinos.proxy.admin"), keccak256("PROXIABLE") e ERC-1967 de implementacao;
  - eth_getStorageAt nos compartimentos da ZeppelinOS e do EIP-1822 em dois outros alvos: 0x67e05247... (cujo nome no
    instantaneo, FjordLbpProxyV6, contem "Proxy") e 0x3b508054... (token apontado pelo NttManager);
  - eth_getCode do endereco de administrador e do endereco de implementacao lidos no USDC.
O resumo do codigo registrado no instantaneo vem de dados/verificados.parquet (publicado a parte). As leituras sao
comparadas com as de proxies_compartimentos.py (saidas/complementares/proxies_compartimentos.json).

Rede: por padrao nao acessa a rede e refaz o resultado a partir das respostas brutas da leitura de 18/11/2026 (UTC),
guardadas em dados/complementares/proxies_administrador_respostas.jsonl: cada chamada recebe a resposta gravada, na
ordem da gravacao, e o programa para com erro se a sequencia de chamadas divergir dela. Com --rede, le a rede
principal (so leitura) e regrava esse arquivo, com data (UTC) e no de cada resposta.
Le tambem dados/sorteio_semente.json. Grava saidas/complementares/proxies_administrador.json.

Uso: python analise/complementares/proxies_administrador.py"""
import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import duckdb
from Crypto.Hash import keccak

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))
from atesta.config import RPCS_REDE_PRINCIPAL  # noqa: E402

SEMENTE = RAIZ / "dados" / "sorteio_semente.json"
CODIGOS_REGISTRADOS = RAIZ / "dados" / "verificados.parquet"
COMPARTIMENTOS = RAIZ / "saidas" / "complementares" / "proxies_compartimentos.json"
BRUTAS = RAIZ / "dados" / "complementares" / "proxies_administrador_respostas.jsonl"
SAIDA = RAIZ / "saidas" / "complementares"
BLOCO = 26296341
BLOCO_HEX = hex(BLOCO)

USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
FJORD = "0x67e0524739e59ca57ac27e520ea05d14cdb6015e"
RENZO = "0x3b50805453023a91a8bf641e279401a0b23fa6f9"


def k256(b):
    h = keccak.new(digest_bits=256)
    h.update(b)
    return h.digest()


def agora():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def relativo(caminho):
    """Caminho relativo a raiz do repositorio, com barras normais."""
    return Path(caminho).relative_to(RAIZ).as_posix()


class Cliente:
    """Cliente JSON-RPC sem novas tentativas. Com rede, grava cada chamada em BRUTAS; sem rede, cada chamada recebe a
    resposta guardada em BRUTAS, na ordem da gravacao."""

    def __init__(self, rede):
        self.rede = rede
        if rede:
            BRUTAS.parent.mkdir(parents=True, exist_ok=True)
            self.arq = open(BRUTAS, "w", encoding="utf-8")
        else:
            self.guardadas = [json.loads(x) for x in open(BRUTAS, encoding="utf-8")]
            self.proxima = 0
        self.n = 0
        self.ultimo = {}
        self.momento = None   # fim (UTC) da ultima chamada

    def guardada(self, url, metodo, params):
        """Resposta guardada da chamada: (resultado, erro), como a chamada pela rede devolveu."""
        if self.proxima >= len(self.guardadas):
            sys.exit(f"falta resposta guardada para {metodo} {params} em {url}")
        reg = self.guardadas[self.proxima]
        self.proxima += 1
        if (reg["no"], reg["metodo"], reg["params"]) != (url, metodo, params):
            sys.exit(f"chamada fora da ordem das respostas guardadas: {metodo} {params} em {url}")
        self.momento = reg["fim_utc"]
        if reg["erro"] is not None:
            return None, reg["erro"]
        return json.loads(reg["resposta_bruta"])["result"], None

    def chamar(self, url, metodo, params):
        if not self.rede:
            self.n += 1
            return self.guardada(url, metodo, params)
        espera = 0.4 - (time.time() - self.ultimo.get(url, 0))
        if espera > 0:
            time.sleep(espera)
        self.n += 1
        corpo = json.dumps({"jsonrpc": "2.0", "id": self.n, "method": metodo, "params": params}).encode()
        req = urllib.request.Request(url, data=corpo, headers={"Content-Type": "application/json",
                                                               "User-Agent": "python-urllib"})
        reg = {"no": url, "metodo": metodo, "params": params, "inicio_utc": agora()}
        status, bruto, erro, res = None, None, None, None
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                status, bruto = r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            status, erro = e.code, f"HTTP {e.code}"
            try:
                bruto = e.read().decode("utf-8", "replace")[:2000]
            except Exception:  # noqa: BLE001
                pass
        except Exception as e:  # noqa: BLE001
            erro = f"{type(e).__name__}: {e}"
        self.ultimo[url] = time.time()
        if erro is None:
            try:
                d = json.loads(bruto)
                if "result" in d:
                    res = d["result"]
                else:
                    erro = f"erro JSON-RPC: {d.get('error')}"
            except ValueError:
                erro = "resposta nao e JSON"
        reg.update({"fim_utc": agora(), "status_http": status, "resposta_bruta": bruto, "erro": erro})
        self.arq.write(json.dumps(reg, ensure_ascii=False) + "\n")
        self.arq.flush()
        self.momento = reg["fim_utc"]
        return res, erro


def main():
    argumentos = argparse.ArgumentParser(description="Administrador e implementacao do proxy de outro padrao.")
    argumentos.add_argument("--rede", action="store_true",
                            help="le a rede principal (so leitura) e regrava as respostas guardadas; sem ele, refaz "
                                 "o resultado a partir delas")
    rede = argumentos.parse_args().rede
    for p in [SEMENTE, CODIGOS_REGISTRADOS, COMPARTIMENTOS] + ([] if rede else [BRUTAS]):
        if not p.exists():
            sys.exit(f"entrada ausente: {relativo(p)}")
    semente = json.load(open(SEMENTE, encoding="utf-8"))
    assert semente["bloco_referencia"] == BLOCO
    s = {"zeppelinos_implementacao": k256(b"org.zeppelinos.proxy.implementation"),
         "zeppelinos_admin": k256(b"org.zeppelinos.proxy.admin"),
         "eip1822_proxiable": k256(b"PROXIABLE"),
         "erc1967_implementacao": (int.from_bytes(k256(b"eip1967.proxy.implementation"), "big") - 1).to_bytes(32, "big")}
    leituras = [(USDC, "zeppelinos_implementacao"), (USDC, "zeppelinos_admin"), (USDC, "eip1822_proxiable"),
                (USDC, "erc1967_implementacao"), (FJORD, "zeppelinos_implementacao"), (FJORD, "eip1822_proxiable"),
                (RENZO, "zeppelinos_implementacao"), (RENZO, "eip1822_proxiable")]
    cli = Cliente(rede)
    out = {"inicio_utc": agora() if rede else cli.guardadas[0]["inicio_utc"], "bloco": BLOCO, "bloco_hex": BLOCO_HEX,
           "keccak256": {k: "0x" + v.hex() for k, v in s.items()}, "nos": {}, "leituras": {}, "codigo": {}}
    # nos: a lista do projeto, com rede; sem rede, a ordem da leitura guardada (a primeira chamada a cada no e
    # eth_chainId)
    nos = list(RPCS_REDE_PRINCIPAL) if rede else list(dict.fromkeys(
        r["no"] for r in cli.guardadas if r["metodo"] == "eth_chainId"))
    validos = []
    for u in nos:
        cid, e1 = cli.chamar(u, "eth_chainId", [])
        blk, e2 = cli.chamar(u, "eth_getBlockByNumber", [BLOCO_HEX, False])
        h = (blk or {}).get("hash")
        out["nos"][u] = {"chainId": cid, "hash_bloco": h, "hash_igual_ao_sorteio": h == semente["hash_bloco"],
                         "erros": [e for e in (e1, e2) if e]}
        if cid == "0x1" and h == semente["hash_bloco"]:
            validos.append(u)
    for alvo, nome in leituras:
        por_no = {}
        for u in validos:
            r, e = cli.chamar(u, "eth_getStorageAt", [alvo, "0x" + s[nome].hex(), BLOCO_HEX])
            por_no[u] = r if r is not None else {"erro": e}
        vals = {x for x in por_no.values() if isinstance(x, str)}
        out["leituras"][f"{alvo}|{nome}"] = {"por_no": por_no, "nos_com_valor": sum(isinstance(x, str) for x in por_no.values()),
                                            "concordam": len({int(x, 16) for x in vals}) == 1 if vals else None,
                                            "valor": vals.pop() if len(vals) == 1 else None}
    imp = out["leituras"][f"{USDC}|zeppelinos_implementacao"]["valor"]
    adm = out["leituras"][f"{USDC}|zeppelinos_admin"]["valor"]
    # instantaneo: verificados_ord pelo conjunto publicado (mesmas linhas)
    tmp = tempfile.mkdtemp(prefix="duckdb_")
    ddb = duckdb.connect(":memory:", config={"temp_directory": Path(tmp).as_posix()})
    ddb.execute("CREATE VIEW verificados_ord AS SELECT address, runtime_code_hash FROM read_parquet('"
                + CODIGOS_REGISTRADOS.as_posix().replace("'", "''") + "')")
    for papel, val in (("implementacao", imp), ("admin", adm)):
        if not val:
            continue
        end = "0x" + val[-40:]
        cods = {}
        for u in validos:
            r, e = cli.chamar(u, "eth_getCode", [end, BLOCO_HEX])
            if isinstance(r, str):
                cods[u] = r
        cod = bytes.fromhex(next(iter(cods.values()))[2:]) if cods else None
        hs = [x[0].hex() for x in ddb.execute("SELECT runtime_code_hash FROM verificados_ord WHERE address = from_hex(?)",
                                              [end[2:]]).fetchall()]
        out["codigo"][papel] = {"endereco": end, "nos_com_valor": len(cods),
                                "codigo_igual_entre_nos": len(set(cods.values())) == 1 if cods else None,
                                "tamanho": len(cod) if cod is not None else None,
                                "designador_7702": bool(cod) and cod[:3] == b"\xef\x01\x00",
                                "sha256_igual_ao_registrado_no_instantaneo": (hashlib.sha256(cod).hexdigest() in hs)
                                if cod else None,
                                "verificado_no_instantaneo": bool(hs)}
    ddb.close()
    shutil.rmtree(tmp, ignore_errors=True)
    # comparacao com as leituras de proxies_compartimentos.py
    b = json.load(open(COMPARTIMENTOS, encoding="utf-8"))
    comp = {}
    for a in b["alvos"]:
        for nome, c in a["compartimentos"].items():
            chave = f"{a['alvo']}|{nome}"
            if chave in out["leituras"]:
                lido = out["leituras"][chave]["valor"]
                comp[chave] = {"este_programa": lido, "proxies_compartimentos": c["valor"],
                               "iguais": lido is not None and c["valor"] is not None
                               and int(lido, 16) == int(c["valor"], 16)}
    q = b["resumo"]["quais"][0]
    comp[f"{USDC}|zeppelinos_admin"] = {"este_programa": adm,
                                        "proxies_compartimentos_admin": q["admin"]["zeppelinos_implementacao"],
                                        "iguais": adm is not None and adm[-40:] == q["admin"]["zeppelinos_implementacao"][-40:]}
    out["comparacao_com_proxies_compartimentos"] = comp
    out["leituras_iguais_as_de_proxies_compartimentos"] = sum(1 for x in comp.values() if x["iguais"])
    out["leituras_comparadas"] = len(comp)
    out["chamadas"] = cli.n
    if not rede and cli.proxima != len(cli.guardadas):
        sys.exit("sobraram respostas guardadas: a sequencia de chamadas divergiu da gravada")
    out["fim_utc"] = agora() if rede else cli.momento
    out["respostas_brutas"] = relativo(BRUTAS)
    out["lidas_da_rede_nesta_execucao"] = rede
    SAIDA.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(SAIDA / "proxies_administrador.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
