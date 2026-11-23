# -*- coding: utf-8 -*-
"""Recompilacao local com o compilador Solidity na versao exata declarada pelo acervo.

Os binarios oficiais (windows-amd64) vem de binaries.soliditylang.org, conferidos pelo sha256 da lista oficial, e
ficam em .cache/solc/. A compilacao usa a interface JSON padrao (--standard-json) com a entrada completa que o
acervo guarda (fontes e configuracoes, inclusive bibliotecas, otimizacao, versao-alvo da EVM, metadados e viaIR);
so a selecao de saida e trocada, o que nao altera o codigo gerado."""
import copy
import hashlib
import io
import json
import subprocess
import threading
import zipfile

import requests

from .config import SOLC_BASE, SOLC_DIR, SOLC_LISTA


class ErroCompilacao(Exception):
    pass


_trava = threading.Lock()
_lista = None


def _lista_oficial():
    global _lista
    if _lista is None:
        arq = SOLC_DIR / "list.json"
        if not arq.exists():
            arq.write_bytes(requests.get(SOLC_LISTA, timeout=120).content)
        _lista = json.loads(arq.read_text(encoding="utf-8"))
    return _lista


def versao_curta(versao_longa):
    """'0.8.19+commit.7dd6d404' -> '0.8.19' (so para o binario nativo; nightly usa o soljson)."""
    return versao_longa.lstrip("v").split("+")[0]


def _chave_versao(longa):
    """(versao com pre-lancamento, commit sem zeros a esquerda): o acervo as vezes registra o commit sem o zero
    inicial (0.5.14+commit.1f1aaa4 para 0.5.14+commit.01f1aaa4, P-14)."""
    v = longa.lstrip("v")
    base, _, resto = v.partition("+commit.")
    return (base, resto.split(".")[0].lstrip("0").lower())


def mesma_versao(a, b):
    """Mesma versao longa: base igual e commit igual, ou um prefixo do outro com ao menos 7 digitos, porque o acervo
    tambem registra o commit abreviado (0.3.5+commit.5f97274 para 0.3.5+commit.5f97274a, P-16)."""
    (ba, ca), (bb, cb) = _chave_versao(a), _chave_versao(b)
    if ba != bb:
        return False
    if ca == cb:
        return True
    curto, longo = sorted((ca, cb), key=len)
    return len(curto) >= 7 and longo.startswith(curto)


def _build_nativo(versao_longa):
    """Build windows-amd64 com a versao LONGA exata (com o commit): a lista tem pre-lancamentos com a mesma versao
    curta (0.8.31-pre.1, 0.8.35-pre.1), que geram metadados diferentes (P-12)."""
    return next((b for b in _lista_oficial()["builds"] if mesma_versao(b["longVersion"], versao_longa)), None)


def executavel(versao_longa):
    build = _build_nativo(versao_longa)
    if build is None:
        raise ErroCompilacao(f"versao {versao_longa} ausente da lista oficial windows-amd64")
    pasta = SOLC_DIR / f"solc-v{build['longVersion']}"
    exe = pasta / "solc.exe"
    if exe.exists():
        return exe
    with _trava:
        if exe.exists():
            return exe
        antiga = SOLC_DIR / f"solc-v{build['version']}"      # pasta da versao 1.x do baixador (so a versao curta)
        reg = antiga / "sha256.txt"
        if reg.exists() and build["path"] in reg.read_text(encoding="utf-8"):
            antiga.rename(pasta)
            return exe
        dados = requests.get(SOLC_BASE + build["path"], timeout=300).content
        sha = hashlib.sha256(dados).hexdigest()
        if "0x" + sha != build["sha256"]:
            raise ErroCompilacao(f"sha256 divergente para {build['path']}")
        pasta.mkdir(parents=True, exist_ok=True)
        if build["path"].endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(dados)) as z:
                z.extractall(pasta)
        else:
            exe.write_bytes(dados)
        (pasta / "sha256.txt").write_text(f"{sha}  {build['path']}\n", encoding="utf-8")
        if not exe.exists():
            achado = next(pasta.rglob("solc*.exe"), None)
            if achado is None:
                raise ErroCompilacao(f"solc.exe nao encontrado em {build['path']}")
            achado.rename(exe)
        return exe


def _tupla(v):
    return tuple(int(x) for x in v.split("."))


# ---------------------------------------------------------------- reserva: compilador oficial em JavaScript (soljson)
SOLJSON_LISTA = "https://binaries.soliditylang.org/bin/list.json"
SOLJSON_BASE = "https://binaries.soliditylang.org/bin/"
JS = SOLC_DIR.parent.parent / "js" / "solcjs.js"
_lista_js = None


def soljson(versao_longa):
    """Baixa (uma vez) o soljson da versao exata, inclusive nightly, conferido pelo sha256 da lista oficial."""
    global _lista_js
    v = versao_longa.lstrip("v")
    destino = SOLC_DIR / "soljson" / f"soljson-v{v}.js"
    if destino.exists():
        return destino
    with _trava:
        if destino.exists():
            return destino
        if _lista_js is None:
            arq = SOLC_DIR / "soljson-list.json"
            if not arq.exists():
                arq.write_bytes(requests.get(SOLJSON_LISTA, timeout=120).content)
            _lista_js = json.loads(arq.read_text(encoding="utf-8"))
        build = next((b for b in _lista_js["builds"] if b.get("longVersion") == v or b["path"] == f"soljson-v{v}.js"
                      or mesma_versao(b.get("longVersion", ""), v)), None)
        if build is None:
            raise ErroCompilacao(f"versao {v} ausente das listas oficiais (windows e soljson)")
        dados = requests.get(SOLJSON_BASE + build["path"], timeout=300).content
        sha = hashlib.sha256(dados).hexdigest()
        if "0x" + sha != build["sha256"]:
            raise ErroCompilacao(f"sha256 divergente para {build['path']}")
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(dados)
        (destino.parent / (destino.name + ".sha256")).write_text(f"{sha}  {build['path']}\n", encoding="utf-8")
        return destino


def _usar_binario(versao_longa):
    v = versao_longa.lstrip("v")
    if "nightly" in v:
        return False
    curta = v.split("+")[0]
    if _tupla(curta.split("-")[0]) < (0, 4, 11):      # binario sem --standard-json; o soljson traduz a entrada padrao
        return False
    return _build_nativo(v) is not None


def _rodar(versao_longa, entrada):
    if _usar_binario(versao_longa):
        cmd, motor = [str(executavel(versao_longa)), "--standard-json"], "solc nativo"
    else:
        cmd, motor = ["node", str(JS), str(soljson(versao_longa))], "soljson"
    try:
        r = subprocess.run(cmd, input=json.dumps(entrada).encode("utf-8"), capture_output=True, timeout=1800)
    except subprocess.TimeoutExpired:
        raise ErroCompilacao("tempo de compilacao esgotado (30 min)")
    if r.returncode != 0 and not r.stdout:
        raise ErroCompilacao(f"{motor} saiu com {r.returncode}: {r.stderr.decode('utf-8', 'replace')[:400]}")
    try:
        return json.loads(r.stdout.decode("utf-8", "replace")), motor
    except ValueError:
        raise ErroCompilacao(f"saida nao JSON ({motor}): {r.stdout[:300]!r} {r.stderr[:300]!r}")


def compilar(std_input, versao_longa, arquivo, contrato, com_ast=True):
    """Recompila e devolve dict com: objeto (hex do codigo de execucao, com marcadores de biblioteca, se houver),
    objeto_criacao (hex do codigo de criacao, idem), imutaveis {id: [{start,length}]}, ligacoes {arquivo: {lib:
    [{start,length}]}}, ast {arquivo: ast} (se pedido e suportado) e o motor usado (binario nativo ou soljson)."""
    v = versao_longa.lstrip("v").split("+")[0].split("-")[0]
    entrada = copy.deepcopy(std_input)
    entrada["language"] = entrada.get("language", "Solidity")
    ajustes = entrada.setdefault("settings", {})
    saidas = ["evm.bytecode.object", "evm.deployedBytecode.object", "evm.deployedBytecode.linkReferences"]
    if _tupla(v) >= (0, 6, 5):
        saidas.append("evm.deployedBytecode.immutableReferences")
    selecao = {arquivo: {contrato: saidas}}
    if com_ast and _tupla(v) >= (0, 4, 12):
        selecao.setdefault("*", {})[""] = ["ast"]
    ajustes["outputSelection"] = selecao
    saida, motor = _rodar(versao_longa, entrada)
    erros = [e for e in saida.get("errors", []) if e.get("severity") == "error"]
    if erros:
        raise ErroCompilacao("; ".join(e.get("formattedMessage", e.get("message", ""))[:300] for e in erros[:3]))
    contratos = saida.get("contracts", {})
    c = (contratos.get(arquivo) or {}).get(contrato)
    if c is None and contrato in (contratos.get("") or {}):
        c = contratos[""][contrato]          # compiladores antigos (fonte unica): chave de arquivo vazia
    if c is None:
        achados = [v[contrato] for v in contratos.values() if contrato in v]
        if len(achados) == 1:
            c = achados[0]
    if c is None:
        raise ErroCompilacao(f"contrato {arquivo}:{contrato} ausente da saida")
    dep = c.get("evm", {}).get("deployedBytecode", {})
    return {
        "versao": v,
        "motor": motor,
        "objeto": dep.get("object", ""),
        "objeto_criacao": c.get("evm", {}).get("bytecode", {}).get("object", ""),
        "imutaveis": dep.get("immutableReferences") or {},
        "ligacoes": dep.get("linkReferences") or {},
        "ast": {k: s.get("ast") or s.get("legacyAST") for k, s in saida.get("sources", {}).items()},
    }
