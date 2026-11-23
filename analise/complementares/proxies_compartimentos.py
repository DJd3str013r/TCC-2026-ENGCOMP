# -*- coding: utf-8 -*-
"""Compartimentos de outros padroes de proxy nos alvos (subsecao 4.6 do artigo). Leitura complementar, descritiva,
nao prevista nas subsecoes 3.6 e 3.8, feita depois da coleta sobre o estado do mesmo bloco de referencia: confere se
os alvos com codigo guardam implementacao em compartimento de outro padrao de proxy.

Alvos: enderecos distintos dos valores das constantes do tipo address das certidoes positivas cujo alvo tem codigo
(tamanho_codigo > 0 na certidao). Para cada alvo, no bloco 26.296.341 (parametro numerico, nunca 'latest'), le por
eth_getStorageAt, em cada no publico da lista RPCS_REDE_PRINCIPAL de atesta/config.py (a mesma de atesta/rpc.py):
  - keccak256("org.zeppelinos.proxy.implementation")  (AdminUpgradeabilityProxy da ZeppelinOS, legado);
  - keccak256("PROXIABLE")                             (EIP-1822);
  - os dois compartimentos do ERC-1967 (implementacao e beacon), como controle do que as certidoes ja registram;
  - o compartimento 0, so nos alvos cujo nome no instantaneo indica Gnosis Safe.
Quando um compartimento de implementacao vem preenchido, le tambem o compartimento de administrador do mesmo padrao e
o codigo do endereco guardado (eth_getCode), e procura esse endereco no instantaneo. Le ainda o codigo de cada alvo
(eth_getCode) para conferir o tamanho com a certidao e procurar no codigo as constantes dos compartimentos (PUSH32),
os seletores de atualizacao (PUSH4) e as instrucoes DELEGATECALL.
Nome, compilador e grau no instantaneo vem do extrato dados/complementares/proxies_extrato.csv (proxies_extrato.py);
o resumo do codigo registrado, de dados/verificados.parquet (publicado a parte).

Rede: por padrao nao acessa a rede e refaz o resultado a partir das respostas brutas da leitura de 18/11/2026 (UTC),
guardadas em dados/complementares/proxies_compartimentos_respostas.jsonl (compartimentos, bloco e identificador da
rede) e dados/complementares/proxies_compartimentos_respostas_codigo.jsonl (eth_getCode): cada tentativa recebe a
resposta gravada, na ordem da gravacao, e o programa para com erro se a sequencia de chamadas divergir dela. Com
--rede, le a rede principal (so leitura, JSON-RPC direto com urllib, sem usar nem gravar o cache de RPC do projeto) e
regrava esses dois arquivos, com data (UTC) e no de cada resposta.

Le tambem dados/certidoes/*.json, dados/sorteio_semente.json e, para dar nome as constantes,
saidas/complementares/proxies_delegacao_positivos.json (se existir). Grava
saidas/complementares/proxies_compartimentos.json.

Uso: python analise/complementares/proxies_compartimentos.py"""
import argparse
import csv
import glob
import hashlib
import json
import re
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import duckdb
from Crypto.Hash import keccak

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))
from atesta.config import RPCS_REDE_PRINCIPAL, SLOT_BEACON, SLOT_IMPLEMENTACAO  # noqa: E402

CERTIDOES = RAIZ / "dados" / "certidoes"
SEMENTE = RAIZ / "dados" / "sorteio_semente.json"
EXTRATO = RAIZ / "dados" / "complementares" / "proxies_extrato.csv"
CODIGOS_REGISTRADOS = RAIZ / "dados" / "verificados.parquet"
ARQ_BRUTAS = RAIZ / "dados" / "complementares" / "proxies_compartimentos_respostas.jsonl"
ARQ_BRUTAS_COD = RAIZ / "dados" / "complementares" / "proxies_compartimentos_respostas_codigo.jsonl"
ARQ_DELEGACAO = RAIZ / "saidas" / "complementares" / "proxies_delegacao_positivos.json"
SAIDA = RAIZ / "saidas" / "complementares"

PAUSA = 0.25          # segundos entre chamadas ao mesmo no
TENTATIVAS = 3


def k256(b):
    h = keccak.new(digest_bits=256)
    h.update(b)
    return h.digest()


def agora():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def relativo(caminho):
    """Caminho relativo a raiz do repositorio, com barras normais."""
    return Path(caminho).relative_to(RAIZ).as_posix()


def ler_extrato():
    """Linhas da tabela vigente_endereco do instantaneo gravadas por proxies_extrato.py, por endereco; campos vazios
    (None) quando o endereco nao tem verificacao vigente."""
    with open(EXTRATO, encoding="utf-8", newline="") as f:
        return {r["address"]: {k: (v or None) for k, v in r.items()} for r in csv.DictReader(f)}


class Cliente:
    """Cliente JSON-RPC minimo. Deixa de consultar (e registra em 'desativados') o no que esgota as tentativas em 3
    chamadas seguidas ou em metade ou mais das chamadas, depois de 8 chamadas. Motivo: um dos nos publicos distribui
    as chamadas entre servidores, alguns sem estado historico, e responde ora com o valor, ora com erro.
    Com rede, grava cada tentativa em arq_brutas; sem rede, cada tentativa recebe a resposta guardada em arq_brutas,
    na ordem da gravacao."""
    FALHAS_SEGUIDAS_PARA_DESATIVAR = 3
    MINIMO_DE_CHAMADAS_PARA_A_TAXA = 8

    def __init__(self, arq_brutas, rede):
        self.rede = rede
        if rede:
            self.arq = open(arq_brutas, "a", encoding="utf-8")
        else:
            self.guardadas = [json.loads(x) for x in open(arq_brutas, encoding="utf-8")]
            self.proxima = 0
        self.momento = None   # fim (UTC) da ultima tentativa
        self.ultimo = defaultdict(float)
        self.falhas_seguidas = defaultdict(int)
        self.chamadas_no = defaultdict(int)
        self.falhas_no = defaultdict(int)
        self.desativados = {}
        self.n = 0

    def chamar(self, url, metodo, params):
        if url in self.desativados:
            return None, "no desativado apos falhas"
        r, e = self._chamar(url, metodo, params)
        self.chamadas_no[url] += 1
        if e is None:
            self.falhas_seguidas[url] = 0
        else:
            self.falhas_seguidas[url] += 1
            self.falhas_no[url] += 1
            taxa = self.falhas_no[url] / self.chamadas_no[url]
            if (self.falhas_seguidas[url] >= self.FALHAS_SEGUIDAS_PARA_DESATIVAR or
                    (self.chamadas_no[url] >= self.MINIMO_DE_CHAMADAS_PARA_A_TAXA and taxa >= 0.5)):
                self.desativados[url] = {"em_utc": self.momento, "chamadas": self.chamadas_no[url],
                                         "chamadas_sem_resposta": self.falhas_no[url], "ultimo_erro": e}
        return r, e

    def _tentativa(self, url, metodo, params, t):
        """Uma tentativa, pela rede (gravada) ou pela resposta guardada. Devolve (status HTTP, resposta bruta, erro)."""
        if not self.rede:
            if self.proxima >= len(self.guardadas):
                sys.exit(f"falta resposta guardada para {metodo} {params} em {url}")
            reg = self.guardadas[self.proxima]
            self.proxima += 1
            if (reg["no"], reg["metodo"], reg["params"], reg["tentativa"]) != (url, metodo, params, t):
                sys.exit(f"chamada fora da ordem das respostas guardadas: {metodo} {params} em {url}, tentativa {t}")
            self.momento = reg["fim_utc"]
            return reg["status_http"], reg["resposta_bruta"], reg["erro"]
        espera = PAUSA - (time.time() - self.ultimo[url])
        if espera > 0:
            time.sleep(espera)
        corpo = json.dumps({"jsonrpc": "2.0", "id": self.n, "method": metodo, "params": params}).encode()
        req = urllib.request.Request(url, data=corpo, headers={"Content-Type": "application/json",
                                                               "User-Agent": "python-urllib"})
        reg = {"no": url, "metodo": metodo, "params": params, "tentativa": t, "inicio_utc": agora()}
        status, bruto, erro = None, None, None
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                status = r.status
                bruto = r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            status = e.code
            try:
                bruto = e.read().decode("utf-8", "replace")[:2000]
            except Exception:  # noqa: BLE001
                bruto = None
            erro = f"HTTP {e.code}"
        except Exception as e:  # noqa: BLE001
            erro = f"{type(e).__name__}: {e}"
        self.ultimo[url] = time.time()
        reg.update({"fim_utc": agora(), "status_http": status, "resposta_bruta": bruto, "erro": erro})
        self.arq.write(json.dumps(reg, ensure_ascii=False) + "\n")
        self.arq.flush()
        self.momento = reg["fim_utc"]
        return status, bruto, erro

    def _chamar(self, url, metodo, params):
        """Uma chamada JSON-RPC com novas tentativas. Devolve (resultado, erro)."""
        erro = None
        for t in range(1, TENTATIVAS + 1):
            self.n += 1
            _, bruto, erro = self._tentativa(url, metodo, params, t)
            if erro is None:
                try:
                    d = json.loads(bruto)
                except ValueError:
                    erro = "resposta nao e JSON"
                else:
                    if "error" in d:
                        erro = f"erro JSON-RPC: {d['error']}"
                    elif "result" in d:
                        return d["result"], None
                    else:
                        erro = "resposta sem result"
            if t < TENTATIVAS and self.rede:
                time.sleep(t)
        return None, erro


def desmontar(codigo):
    instr, pc, n = [], 0, len(codigo)
    while pc < n:
        op = codigo[pc]
        if 0x60 <= op <= 0x7F:
            k = op - 0x5F
            instr.append((pc, op, codigo[pc + 1:pc + 1 + k]))
            pc += 1 + k
        else:
            instr.append((pc, op, b""))
            pc += 1
    return instr


def fim_do_codigo(codigo):
    """Exclui o bloco CBOR de metadados do fim (comprimento nos dois ultimos bytes), quando ha um."""
    if len(codigo) < 4:
        return len(codigo)
    n = int.from_bytes(codigo[-2:], "big")
    ini = len(codigo) - 2 - n
    if 0 < n < 200 and ini > 0 and codigo[ini] in (0xA1, 0xA2, 0xA3, 0xA4, 0xA5):
        return ini
    return len(codigo)


def main():
    argumentos = argparse.ArgumentParser(description="Compartimentos de outros padroes de proxy nos alvos com codigo.")
    argumentos.add_argument("--rede", action="store_true",
                            help="le a rede principal (so leitura) e regrava as respostas guardadas; sem ele, refaz "
                                 "o resultado a partir delas")
    rede = argumentos.parse_args().rede
    for p in [CERTIDOES, SEMENTE, EXTRATO, CODIGOS_REGISTRADOS] + ([] if rede else [ARQ_BRUTAS, ARQ_BRUTAS_COD]):
        if not p.exists():
            sys.exit(f"entrada ausente: {relativo(p)}")

    # compartimentos
    s_zos_impl = k256(b"org.zeppelinos.proxy.implementation")
    s_zos_admin = k256(b"org.zeppelinos.proxy.admin")
    s_proxiable = k256(b"PROXIABLE")
    s_1967_impl = (int.from_bytes(k256(b"eip1967.proxy.implementation"), "big") - 1).to_bytes(32, "big")
    s_1967_beacon = (int.from_bytes(k256(b"eip1967.proxy.beacon"), "big") - 1).to_bytes(32, "big")
    s_1967_admin = (int.from_bytes(k256(b"eip1967.proxy.admin"), "big") - 1).to_bytes(32, "big")
    compart = {
        "zeppelinos_implementacao": s_zos_impl,
        "eip1822_proxiable": s_proxiable,
        "erc1967_implementacao": s_1967_impl,
        "erc1967_beacon": s_1967_beacon,
    }
    hexs = {k: "0x" + v.hex() for k, v in compart.items()}
    hexs.update({"zeppelinos_admin": "0x" + s_zos_admin.hex(), "erc1967_admin": "0x" + s_1967_admin.hex()})
    # conferencia com as constantes do verificador (atesta/config.py)
    cfg_impl, cfg_beacon = "0x%064x" % SLOT_IMPLEMENTACAO, "0x%064x" % SLOT_BEACON
    conf_cfg = {"erc1967_implementacao_igual_ao_do_verificador": hexs["erc1967_implementacao"] == cfg_impl,
                "erc1967_beacon_igual_ao_do_verificador": hexs["erc1967_beacon"] == cfg_beacon}
    seletores = {nome: "0x" + k256(nome.encode())[:4].hex() for nome in (
        "upgradeTo(address)", "upgradeToAndCall(address,bytes)", "implementation()", "admin()", "changeAdmin(address)",
        "updateCodeAddress(address)", "proxiableUUID()", "masterCopy()")}

    # alvos com codigo, a partir das certidoes positivas
    alvos, bloco = {}, set()
    for p in sorted(glob.glob(str(CERTIDOES / "*.json"))):
        c = json.load(open(p, encoding="utf-8"))
        if c.get("indicador_equacao_2") != 1:
            continue
        bloco.add(c["contrato"]["bloco_referencia"])
        for k in c["constantes"]:
            if not k.get("tau_address"):
                continue
            for v in k["valores"]:
                a = (k.get("alvos") or {}).get(v) or {}
                if a.get("tamanho_codigo"):
                    d = alvos.setdefault(v, {"classes": set(), "apontado_por": [], "tamanho_codigo_certidao": set(),
                                             "erc1967_certidao": set()})
                    d["classes"].add(a["classe"])
                    d["tamanho_codigo_certidao"].add(a["tamanho_codigo"])
                    d["erc1967_certidao"].add((a.get("erc1967_implementacao"), a.get("erc1967_beacon")))
                    d["apontado_por"].append({"positivo": c["contrato"]["endereco"],
                                              "contrato": c["acervo"]["contrato_compilado"],
                                              "construto": k["construto"], "tipo": k["tipo"]})
    assert len(bloco) == 1
    BLOCO = bloco.pop()
    BLOCO_HEX = hex(BLOCO)
    semente = json.load(open(SEMENTE, encoding="utf-8"))
    assert semente["bloco_referencia"] == BLOCO
    n_valores = sum(len(d["apontado_por"]) for d in alvos.values())

    # nomes das constantes (saida de proxies_delegacao.py, se existir)
    nomes_constantes = {}
    if ARQ_DELEGACAO.exists():
        for c in json.load(open(ARQ_DELEGACAO, encoding="utf-8")):
            for x in c["constantes_address"]:
                nomes_constantes[(c["endereco"], x["construto"])] = x["nome"]
    for d in alvos.values():
        for ap in d["apontado_por"]:
            ap["nome_da_constante"] = nomes_constantes.get((ap["positivo"], ap["construto"]))

    # instantaneo: vigente_endereco pelo extrato; verificados_ord pelo conjunto publicado (mesmas linhas)
    extrato = ler_extrato()
    tmp = tempfile.mkdtemp(prefix="duckdb_")
    con_ddb = duckdb.connect(":memory:", config={"temp_directory": Path(tmp).as_posix()})
    con_ddb.execute("CREATE VIEW verificados_ord AS SELECT address, runtime_code_hash FROM read_parquet('"
                    + CODIGOS_REGISTRADOS.as_posix().replace("'", "''") + "')")

    def instantaneo(endereco, codigo=None):
        if endereco not in extrato:
            sys.exit(f"endereco fora do extrato: {endereco} (rode analise/complementares/proxies_extrato.py)")
        r = extrato[endereco]
        hs = [x[0].hex() for x in con_ddb.execute("SELECT runtime_code_hash FROM verificados_ord WHERE address = from_hex(?)",
                                                  [endereco[2:]]).fetchall()]
        out = {"nome": r["fully_qualified_name"], "compilador": r["version"],
               "grau_sourcify": r["grau_sourcify"], "verificado": bool(hs)}
        if codigo is not None:
            out["codigo_igual_ao_registrado"] = hashlib.sha256(codigo).hexdigest() in hs
        return out

    if rede:
        nos = list(RPCS_REDE_PRINCIPAL)
        ARQ_BRUTAS.parent.mkdir(parents=True, exist_ok=True)
        for arq in (ARQ_BRUTAS, ARQ_BRUTAS_COD):
            if arq.exists():
                arq.unlink()  # respostas guardadas, substituidas pelas desta leitura
    cli = Cliente(ARQ_BRUTAS, rede)
    cli_cod = Cliente(ARQ_BRUTAS_COD, rede)
    if not rede:
        # nos na ordem da leitura guardada (a primeira chamada a cada no e eth_chainId)
        nos = list(dict.fromkeys(r["no"] for r in cli.guardadas if r["metodo"] == "eth_chainId"))
    inicio = agora() if rede else cli.guardadas[0]["inicio_utc"]

    # 1. identificacao da rede e do bloco em cada no
    info_nos = {}
    for u in nos:
        cid, e1 = cli.chamar(u, "eth_chainId", [])
        blk, e2 = cli.chamar(u, "eth_getBlockByNumber", [BLOCO_HEX, False])
        info_nos[u] = {"chainId": cid, "erro_chainId": e1,
                       "hash_bloco": (blk or {}).get("hash"), "erro_bloco": e2,
                       "hash_igual_ao_do_sorteio": (blk or {}).get("hash") == semente["hash_bloco"]}

    # 2. compartimentos em cada alvo, em cada no
    leituras = defaultdict(dict)   # (alvo, compartimento) -> {no: valor ou None}
    erros = defaultdict(dict)
    nomes_alvo = {v: instantaneo(v) for v in alvos}
    safe = {v: bool(nomes_alvo[v]["nome"] and re.search(r"(?i)(gnosis|^safe$|safel2|safeproxy|\bsafe\b)",
                                                          nomes_alvo[v]["nome"].split(":")[-1]))
            for v in alvos}
    for v in sorted(alvos):
        lista = list(compart.items()) + ([("compartimento_0_gnosis_safe", b"\x00" * 32)] if safe[v] else [])
        for nome_c, slot in lista:
            for u in nos:
                if not info_nos[u]["hash_igual_ao_do_sorteio"]:
                    continue
                r, e = cli.chamar(u, "eth_getStorageAt", [v, "0x" + slot.hex(), BLOCO_HEX])
                leituras[(v, nome_c)][u] = r
                erros[(v, nome_c)][u] = e

    def consolidar(chave):
        vals = {u: x for u, x in leituras[chave].items() if isinstance(x, str) and x.startswith("0x")}
        distintos = sorted({int(x, 16) for x in vals.values()})
        return {"valor": ("0x%064x" % distintos[0]) if len(distintos) == 1 else None,
                "nos_que_responderam": sorted(vals), "concordam": len(distintos) == 1,
                "valores_por_no": vals, "erros_por_no": {u: e for u, e in erros[chave].items() if e}}

    resultado_alvos = []
    for v in sorted(alvos):
        d = alvos[v]
        comp = {}
        for nome_c in list(compart) + (["compartimento_0_gnosis_safe"] if safe[v] else []):
            cons = consolidar((v, nome_c))
            val = cons["valor"]
            if val is not None and int(val, 16) != 0:
                b = bytes.fromhex(val[2:])
                cons["endereco_guardado"] = "0x" + b[12:].hex() if not any(b[:12]) else None
            comp[nome_c] = cons
        # 3. complementos para compartimento de implementacao preenchido
        extra = {}
        for nome_c, admin_slot in (("zeppelinos_implementacao", s_zos_admin), ("eip1822_proxiable", None),
                                   ("compartimento_0_gnosis_safe", None)):
            if nome_c not in comp or not comp[nome_c].get("endereco_guardado"):
                continue
            imp = comp[nome_c]["endereco_guardado"]
            cods = {}
            for u in nos:
                if not info_nos[u]["hash_igual_ao_do_sorteio"]:
                    continue
                r, e = cli_cod.chamar(u, "eth_getCode", [imp, BLOCO_HEX])
                if isinstance(r, str) and r.startswith("0x"):
                    cods[u] = r
            cod_hashes = {u: "0x" + k256(bytes.fromhex(x[2:])).hex() for u, x in cods.items()}
            cod = bytes.fromhex(next(iter(cods.values()))[2:]) if cods else None
            ex = {"implementacao": imp, "tamanho_codigo_implementacao": len(cod) if cod is not None else None,
                  "keccak_codigo_implementacao_por_no": cod_hashes,
                  "codigo_igual_entre_nos": len(set(cod_hashes.values())) == 1 if cod_hashes else None,
                  "implementacao_no_instantaneo": instantaneo(imp, cod) if cod else instantaneo(imp)}
            if admin_slot is not None:
                adm = {}
                for u in nos:
                    if not info_nos[u]["hash_igual_ao_do_sorteio"]:
                        continue
                    r, e = cli.chamar(u, "eth_getStorageAt", [v, "0x" + admin_slot.hex(), BLOCO_HEX])
                    leituras[(v, "zeppelinos_admin")][u] = r
                    erros[(v, "zeppelinos_admin")][u] = e
                ca = consolidar((v, "zeppelinos_admin"))
                if ca["valor"] and int(ca["valor"], 16):
                    b = bytes.fromhex(ca["valor"][2:])
                    ca["endereco_guardado"] = "0x" + b[12:].hex() if not any(b[:12]) else None
                ex["compartimento_admin"] = ca
            extra[nome_c] = ex
        # 4. codigo do alvo: tamanho, constantes de compartimento, seletores e DELEGATECALL
        cod_alvo, no_cod = None, None
        for u in nos:
            if not info_nos[u]["hash_igual_ao_do_sorteio"]:
                continue
            r, e = cli_cod.chamar(u, "eth_getCode", [v, BLOCO_HEX])
            if isinstance(r, str) and r.startswith("0x"):
                cod_alvo, no_cod = bytes.fromhex(r[2:]), u
                break
        analise = None
        if cod_alvo is not None:
            fim = fim_do_codigo(cod_alvo)
            ins = [x for x in desmontar(cod_alvo[:fim])]
            p32 = {"0x" + x[2].hex() for x in ins if x[1] == 0x7F}
            p4 = {"0x" + x[2].hex() for x in ins if x[1] == 0x63}
            analise = {"no": no_cod, "tamanho": len(cod_alvo),
                       "tamanho_igual_ao_da_certidao": {len(cod_alvo)} == d["tamanho_codigo_certidao"],
                       "bytes_examinados_sem_metadados_finais": fim,
                       "instrucoes_DELEGATECALL": sum(1 for x in ins if x[1] == 0xF4),
                       "instrucoes_CALLCODE": sum(1 for x in ins if x[1] == 0xF2),
                       "constantes_de_compartimento_no_codigo": sorted(k for k, h in hexs.items() if h in p32),
                       "seletores_no_codigo": sorted(k for k, h in seletores.items() if h in p4)}
        preenchidos_outro = sorted(k for k in ("zeppelinos_implementacao", "eip1822_proxiable", "compartimento_0_gnosis_safe")
                                   if k in comp and comp[k].get("endereco_guardado"))
        resultado_alvos.append({
            "alvo": v, "classes": sorted(d["classes"]), "nome_no_instantaneo": nomes_alvo[v]["nome"],
            "verificado_no_instantaneo": nomes_alvo[v]["verificado"],
            "indica_gnosis_safe": safe[v], "apontado_por": d["apontado_por"],
            "erc1967_na_certidao": sorted(str(x) for x in d["erc1967_certidao"]),
            "compartimentos": comp, "implementacao_em_compartimento_de_outro_padrao": preenchidos_outro,
            "complementos": extra, "codigo": analise})

    # 5. resumo
    def preenchido(r, k):
        c = r["compartimentos"].get(k)
        return bool(c and c["valor"] and int(c["valor"], 16) != 0)

    outros = [r for r in resultado_alvos if r["implementacao_em_compartimento_de_outro_padrao"]]
    sem_leitura = [(r["alvo"], k) for r in resultado_alvos for k, c in r["compartimentos"].items() if c["valor"] is None]
    divergentes = [(r["alvo"], k) for r in resultado_alvos for k, c in r["compartimentos"].items()
                   if len(c["valores_por_no"]) > 1 and not c["concordam"]]
    if not rede:
        for c in (cli, cli_cod):
            if c.proxima != len(c.guardadas):
                sys.exit("sobraram respostas guardadas: a sequencia de chamadas divergiu da gravada")
    fim = agora() if rede else max(x for x in (cli.momento, cli_cod.momento) if x)
    resumo = {
        "inicio_utc": inicio, "fim_utc": fim, "bloco": BLOCO, "bloco_hex": BLOCO_HEX,
        "hash_bloco_do_sorteio": semente["hash_bloco"], "nos": info_nos,
        "keccak256": hexs, "conferencia_com_atesta_config": conf_cfg, "seletores": seletores,
        "valores_address_com_alvo_com_codigo": n_valores, "alvos_distintos_com_codigo": len(resultado_alvos),
        "alvos_que_indicam_gnosis_safe": sum(safe.values()),
        "leituras_por_compartimento": {k: sum(1 for r in resultado_alvos if k in r["compartimentos"])
                                       for k in list(compart) + ["compartimento_0_gnosis_safe"]},
        "leituras_sem_valor": sem_leitura, "leituras_divergentes_entre_nos": divergentes,
        "nos_por_leitura": dict(Counter(len(c["nos_que_responderam"]) for r in resultado_alvos
                                        for c in r["compartimentos"].values())),
        "preenchidos": {k: sum(preenchido(r, k) for r in resultado_alvos)
                        for k in list(compart) + ["compartimento_0_gnosis_safe"]},
        "alvos_com_implementacao_em_compartimento_de_outro_padrao": len(outros),
        "quais": [{"alvo": r["alvo"], "nome_no_instantaneo": r["nome_no_instantaneo"],
                   "padroes": r["implementacao_em_compartimento_de_outro_padrao"],
                   "implementacao": {k: r["complementos"][k]["implementacao"] for k in r["complementos"]},
                   "implementacao_no_instantaneo": {k: r["complementos"][k]["implementacao_no_instantaneo"]
                                                    for k in r["complementos"]},
                   "admin": {k: (r["complementos"][k].get("compartimento_admin") or {}).get("endereco_guardado")
                             for k in r["complementos"]},
                   "apontado_por": r["apontado_por"],
                   "codigo": r["codigo"]} for r in outros],
        "alvos_com_erc1967_preenchido": sum(preenchido(r, "erc1967_implementacao") or preenchido(r, "erc1967_beacon")
                                            for r in resultado_alvos),
        "codigo_dos_alvos_lido": sum(1 for r in resultado_alvos if r["codigo"]),
        "codigo_dos_alvos_com_tamanho_igual_ao_da_certidao": sum(1 for r in resultado_alvos
                                                                 if r["codigo"] and r["codigo"]["tamanho_igual_ao_da_certidao"]),
        "alvos_sem_instrucao_DELEGATECALL": sum(1 for r in resultado_alvos
                                                if r["codigo"] and r["codigo"]["instrucoes_DELEGATECALL"] == 0),
        "alvos_com_instrucao_DELEGATECALL": [{"alvo": r["alvo"], "nome": r["nome_no_instantaneo"],
                                              "instrucoes": r["codigo"]["instrucoes_DELEGATECALL"],
                                              "constantes_de_compartimento": r["codigo"]["constantes_de_compartimento_no_codigo"],
                                              "seletores": r["codigo"]["seletores_no_codigo"]}
                                             for r in resultado_alvos if r["codigo"] and r["codigo"]["instrucoes_DELEGATECALL"]],
        "alvos_com_constante_de_compartimento_no_codigo": [
            {"alvo": r["alvo"], "nome": r["nome_no_instantaneo"],
             "constantes": r["codigo"]["constantes_de_compartimento_no_codigo"]}
            for r in resultado_alvos if r["codigo"] and r["codigo"]["constantes_de_compartimento_no_codigo"]],
        "chamadas": cli.n, "chamadas_codigo": cli_cod.n,
        "nos_desativados": cli.desativados, "nos_desativados_codigo": cli_cod.desativados,
        "respostas_brutas": [relativo(ARQ_BRUTAS), relativo(ARQ_BRUTAS_COD)],
        "lidas_da_rede_nesta_execucao": rede,
    }
    con_ddb.close()
    shutil.rmtree(tmp, ignore_errors=True)
    SAIDA.mkdir(parents=True, exist_ok=True)
    json.dump({"resumo": resumo, "alvos": resultado_alvos},
              open(SAIDA / "proxies_compartimentos.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(json.dumps(resumo, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
