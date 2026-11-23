# -*- coding: utf-8 -*-
"""Complementacao da entrada de compilacao pelos metadados do contrato (subsecao 4.1 do artigo; P-13). Conferencia
descritiva, nao prevista na subsecao 3.8: nao altera nenhuma certidao nem nenhuma estimativa.

A versao 1.4.0 do verificador passou a completar a entrada armazenada pelo acervo com as configuracoes que o arquivo
de metadados do proprio contrato registra e que ela omite (atesta.verificador.entrada_completa). Para cada certidao
da amostra que registra configuracoes vindas dos metadados (recompilacao.ajustes_dos_metadados), o programa recompila
o contrato duas vezes, com a entrada armazenada e com a entrada completada, refaz nas duas a delimitacao de F(a)
(atesta.regioes.delimitar) e compara regioes, valores, tipos e metadados_em_F com os da certidao. Em todas as
certidoes, confere que a complementacao, recalculada sobre o mesmo registro do acervo, acrescenta as configuracoes
que a certidao registra; nas que nao registram nenhuma, a entrada completada coincide com a armazenada.

Le dados/certidoes/*.json, o registro de cada contrato no cache da API do Sourcify (.cache/sourcify_api.sqlite) e o
codigo lido da cadeia no bloco de referencia (.cache/rpc_rede_principal.sqlite), os dois caches publicados a parte e
abertos so para leitura, e usa a lista oficial dos binarios (.cache/solc/list.json) e os compiladores que o
verificador baixa para .cache/solc/: o binario nativo da versao exata ou o soljson, por js/solcjs.js (Node.js),
conforme o motor registrado na certidao. Se faltar algum, para e diz qual; nao baixa nada. Nao acessa a rede. Grava
saidas/complementares/complementacao_entrada.json, com o sha256 dos dois caches e o compilador usado em cada versao.

Uso: python analise/complementares/complementacao_entrada.py"""
import copy
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))
from atesta.compilador import _tupla, mesma_versao  # noqa: E402
from atesta.regioes import FalhaInstrumento, delimitar  # noqa: E402
from atesta.verificador import entrada_completa  # noqa: E402

CERTIDOES = RAIZ / "dados" / "certidoes"
CACHE = RAIZ / ".cache"
SOLC = CACHE / "solc"
JS = RAIZ / "js" / "solcjs.js"
SAIDA = RAIZ / "saidas" / "complementares" / "complementacao_entrada.json"


def abrir(nome):
    """Cache do verificador, so para leitura."""
    arq = CACHE / f"{nome}.sqlite"
    if not arq.exists():
        sys.exit(f"falta .cache/{nome}.sqlite")
    return sqlite3.connect(arq.as_uri() + "?mode=ro&immutable=1", uri=True)


def sha256_arquivo(arq):
    h = hashlib.sha256()
    with open(arq, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def registro(api, endereco, rede=1):
    r = api.execute("SELECT v FROM kv WHERE k = ?", (f"{rede}:{endereco.lower()}",)).fetchone()
    return None if r is None else json.loads(r[0])


def codigo(rpc, endereco, bloco):
    k = "eth_getCode" + json.dumps([endereco.lower(), hex(bloco)], separators=(",", ":"))
    r = rpc.execute("SELECT v FROM kv WHERE k = ?", (k,)).fetchone()
    return None if r is None else bytes.fromhex(json.loads(r[0])[2:])


def exe_nativo(lista, versao_longa):
    """solc.exe da versao longa exata, como em atesta.compilador.executavel, mas sem baixar nem renomear: na pasta da
    versao longa ou na da versao curta (baixador 1.x), se o sha256.txt dela for do mesmo build."""
    b = next((x for x in lista["builds"] if mesma_versao(x["longVersion"], versao_longa)), None)
    if b is None:
        return None
    for pasta in (SOLC / f"solc-v{b['longVersion']}", SOLC / f"solc-v{b['version']}"):
        sha = pasta / "sha256.txt"
        if (pasta / "solc.exe").exists() and (not sha.exists() or b["path"] in sha.read_text(encoding="utf-8")):
            return pasta / "solc.exe"
    return None


def soljson(versao_longa):
    """soljson da versao exata, como em atesta.compilador.soljson, mas sem baixar."""
    v = versao_longa.lstrip("v")
    arq = SOLC / "soljson" / f"soljson-v{v}.js"
    if arq.exists():
        return arq
    return next((f for f in sorted((SOLC / "soljson").glob("soljson-v*.js")) if mesma_versao(f.name[9:-3], v)), None)


def comando(lista, versao_longa, motor):
    """(arquivo do compilador, linha de comando), ou None se o compilador nao estiver em .cache/solc."""
    if motor == "solc nativo":
        exe = exe_nativo(lista, versao_longa)
        return None if exe is None else (exe, [str(exe), "--standard-json"])
    js = soljson(versao_longa)
    return None if js is None else (js, ["node", str(JS), str(js)])


def compilar(std_input, versao_longa, arquivo, contrato, cmd):
    """Mesma entrada, mesma selecao de saida e mesma busca do contrato de atesta.compilador.compilar."""
    v = versao_longa.lstrip("v").split("+")[0].split("-")[0]
    entrada = copy.deepcopy(std_input)
    entrada["language"] = entrada.get("language", "Solidity")
    aj = entrada.setdefault("settings", {})
    saidas = ["evm.bytecode.object", "evm.deployedBytecode.object", "evm.deployedBytecode.linkReferences"]
    if _tupla(v) >= (0, 6, 5):
        saidas.append("evm.deployedBytecode.immutableReferences")
    sel = {arquivo: {contrato: saidas}}
    if _tupla(v) >= (0, 4, 12):
        sel.setdefault("*", {})[""] = ["ast"]
    aj["outputSelection"] = sel
    r = subprocess.run(cmd, input=json.dumps(entrada).encode("utf-8"), capture_output=True, timeout=1800)
    s = json.loads(r.stdout.decode("utf-8", "replace"))
    erros = [e for e in s.get("errors", []) if e.get("severity") == "error"]
    if erros:
        return {"erro": erros[0].get("message", "")[:150]}
    cs = s.get("contracts", {})
    c = (cs.get(arquivo) or {}).get(contrato)
    if c is None and contrato in (cs.get("") or {}):
        c = cs[""][contrato]
    if c is None:
        ach = [x[contrato] for x in cs.values() if contrato in x]
        c = ach[0] if len(ach) == 1 else None
    if c is None:
        return {"erro": "ausente da saida"}
    dep = c.get("evm", {}).get("deployedBytecode", {})
    return {"objeto": dep.get("object", ""), "imutaveis": dep.get("immutableReferences") or {},
            "ligacoes": dep.get("linkReferences") or {},
            "ast": {k: x.get("ast") or x.get("legacyAST") for k, x in s.get("sources", {}).items()}}


def resumo(regs):
    return sorted((r.inicio, r.comprimento, r.motivo, r.construto, r.valor, r.tipo, r.tau_address) for r in regs)


def resumo_certidao(c):
    return sorted((r["inicio"], r["comprimento"], r["motivo"], r["construto"], r["valor"], r["tipo"], r["tau_address"])
                  for r in c["regioes"])


def confrontar(c, reg, c_a, std, cmd):
    """Recompila com a entrada dada, refaz a delimitacao e compara com a certidao."""
    arq, nome = reg["compilation"]["fullyQualifiedName"].rsplit(":", 1)
    rt = reg.get("runtimeBytecode") or {}
    comp = compilar(std, reg["compilation"]["compilerVersion"], arq, nome, cmd)
    if "erro" in comp:
        return "erro de compilacao: " + comp["erro"]
    try:
        regs, info = delimitar(c_a, comp, arq, nome, rt.get("cborAuxdata"), rt.get("transformations"))
    except FalhaInstrumento as e:
        return "falha do instrumento: " + str(e)
    iguais = resumo(regs) == resumo_certidao(c) and info["metadados_em_F"] == c["recompilacao"]["metadados_em_F"]
    return "igual a certidao" if iguais else "difere da certidao"


def ajustes(c):
    return (c.get("recompilacao") or {}).get("ajustes_dos_metadados") or []


def main():
    api, rpc = abrir("sourcify_api"), abrir("rpc_rede_principal")
    if not (SOLC / "list.json").exists():
        sys.exit("falta .cache/solc/list.json")
    lista = json.loads((SOLC / "list.json").read_text(encoding="utf-8"))
    certs = [json.loads(f.read_text(encoding="utf-8")) for f in sorted(CERTIDOES.glob("0x*.json"))]
    com_ajustes = [c for c in certs if ajustes(c)]

    recalculo_igual, cmds, compiladores, faltam = 0, {}, {}, set()
    for c in certs:
        end = c["contrato"]["endereco"]
        reg = registro(api, end)
        if entrada_completa(reg)[1] == ajustes(c):
            recalculo_igual += 1
        if ajustes(c):
            versao, motor = reg["compilation"]["compilerVersion"], c["recompilacao"]["motor"]
            achado = comando(lista, versao, motor)
            if achado is None:
                faltam.add(f"{motor} {versao}")
                continue
            arq_compilador, cmds[end] = achado
            compiladores[f"{motor} {versao}"] = arq_compilador.relative_to(RAIZ).as_posix()
    if faltam:
        sys.exit("faltam em .cache/solc (o verificador os baixa): " + ", ".join(sorted(faltam)))
    precisa_node = any(x[0] == "node" for x in cmds.values())
    if precisa_node and (shutil.which("node") is None or not (RAIZ / "js" / "node_modules" / "solc").exists()):
        sys.exit("o soljson precisa do Node.js e de js/node_modules (cd js && npm ci)")

    contratos = []
    for c in com_ajustes:
        end = c["contrato"]["endereco"]
        reg = registro(api, end)
        c_a = codigo(rpc, end, c["contrato"]["bloco_referencia"])
        linha = {"endereco": end, "ajustes_dos_metadados": ajustes(c), "grau": c["acervo"]["grau_codigo_execucao"],
                 "motor": c["recompilacao"]["motor"], "compilador": c["acervo"]["compilador"]}
        casos = (("entrada_armazenada", reg["stdJsonInput"]), ("entrada_completada", entrada_completa(reg)[0]))
        for rotulo, std in casos:
            linha[rotulo] = confrontar(c, reg, c_a, std, cmds[end])
        contratos.append(linha)
        print(json.dumps(linha, ensure_ascii=False), flush=True)

    # par de resultados: com a entrada armazenada | com a entrada completada
    pares = Counter(f"{x['entrada_armazenada'].split(':')[0]} | {x['entrada_completada'].split(':')[0]}"
                    for x in contratos)
    res = {
        "aviso": "Conferencia descritiva, nao prevista na subsecao 3.8 do artigo. Nao altera nenhuma certidao nem "
                 "nenhuma estimativa.",
        "programa": Path(__file__).resolve().relative_to(RAIZ).as_posix(),
        "entradas": {
            "certidoes": "dados/certidoes/*.json",
            "cache_api": {"arquivo": ".cache/sourcify_api.sqlite", "modo": "somente leitura",
                          "sha256": sha256_arquivo(CACHE / "sourcify_api.sqlite")},
            "cache_rpc": {"arquivo": ".cache/rpc_rede_principal.sqlite", "modo": "somente leitura",
                          "sha256": sha256_arquivo(CACHE / "rpc_rede_principal.sqlite")},
            "compiladores": dict(sorted(compiladores.items())),
        },
        "certidoes": len(certs),
        "versao_das_certidoes": dict(Counter(c["verificador"]["versao"] for c in certs)),
        "com_ajustes_dos_metadados": len(com_ajustes),
        "por_ajustes": {"+".join(k): n for k, n in sorted(Counter(tuple(ajustes(c)) for c in com_ajustes).items())},
        "sem_ajustes_dos_metadados": len(certs) - len(com_ajustes),
        "ajustes_recalculados_iguais_aos_da_certidao": recalculo_igual,
        "resultados_armazenada_completada": dict(sorted(pares.items())),
        "iguais_a_certidao_nos_dois_casos": pares["igual a certidao | igual a certidao"],
        "contratos": contratos,
    }
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k not in ("entradas", "contratos")}, indent=1,
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
