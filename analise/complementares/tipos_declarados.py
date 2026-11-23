# -*- coding: utf-8 -*-
"""Conferencia descritiva, nao prevista na subsecao 3.8, do tipo declarado e de tau(r) das constantes de variavel
imutavel das certidoes e do id da declaracao de cada uma (subsecoes 4.2 e 4.6 do artigo).

Nao importa o pacote atesta e nao acessa a rede. Le as certidoes (dados/certidoes), o cache da API do acervo
(.cache/sourcify_api.sqlite, aberto somente para leitura), .cache/solc/list.json e o sha256.txt de cada pasta de
compilador, e executa os binarios do compilador para Windows ja baixados em .cache/solc (solc-v<versao>/solc.exe, os
que o verificador baixa ao processar a amostra), sem alterar nem baixar nada; se faltar algum binario, o programa
para sem gravar nada. Para cada constante de variavel imutavel (construto imutavel:<id>), tres vias, cada uma
comparada com o tipo e com tau_address da certidao:

  A. AST da recompilacao. Recompila o contrato com o binario da versao registrada pelo acervo e com a entrada guardada
     pelo acervo, completada com as configuracoes do arquivo de metadados (a mesma regra da subsecao 3.3, para obter a
     mesma AST que o verificador leu). Localiza a declaracao pelo id do construto e, em separado, pelas posicoes
     (immutableReferences da recompilacao x regioes da certidao). Le typeString e typeName e aplica a regra de tau da
     subsecao 3.4 com implementacao propria: a categoria vem da declaracao referenciada (ContractDefinition com
     contractKind, UserDefinedValueTypeDefinition com o tipo subjacente, EnumDefinition), e nao do prefixo do texto.
     Confere tambem que a recompilacao reproduz o codigo da cadeia fora de F(a).
  B. Texto do codigo-fonte, sem compilador. Das posicoes das regioes da certidao chega ao id do acervo (transformacoes
     do codigo de execucao) e, pelo mapa de fontes (sourceMap) e pelos indices de fonte (sourceIds) guardados pelo
     acervo, ao trecho do codigo-fonte de cada leitura da variavel, de onde sai o nome. A declaracao e achada no texto
     (comentarios e conteudo de cadeias apagados) e o tipo escrito e resolvido pelas definicoes do proprio texto
     (contract, interface, library, enum, struct, type X is Y). Nada nesta via usa a AST.
  C. ABI guardada pelo acervo (so imutaveis publicas). Getter sem argumentos com o mesmo nome: internalType comparado
     com o tipo, e type == "address" comparado com tau.

O id da certidao, que e o da recompilacao local, e comparado com o que o acervo registra para as mesmas posicoes. Nos
ids divergentes, o vinculo certidao -> acervo e feito pela posicao (inicio das regioes),
o nome vem do mapa de fontes do acervo (via B) e e comparado com o da AST (via A); para os contratos com id divergente
cuja entrada guardada traz fontes alem das listadas nos metadados, recompila-se tambem so com estas, para testar a
causa. Grava saidas/complementares/tipos_declarados.json.

Uso: python analise/complementares/tipos_declarados.py"""
import copy
import datetime
import hashlib
import json
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from Crypto.Hash import keccak

RAIZ = Path(__file__).resolve().parents[2]
CERTIDOES = RAIZ / "dados" / "certidoes"
CACHE_API = RAIZ / ".cache" / "sourcify_api.sqlite"
SOLC_DIR = RAIZ / ".cache" / "solc"
SAIDA = RAIZ / "saidas" / "complementares" / "tipos_declarados.json"
ENDERECO = ("address", "address payable")
IDENT = r"[A-Za-z_$][\w$]*"


# ------------------------------------------------------------------------------------------------ utilidades
def abrir_ro(caminho):
    return sqlite3.connect(Path(caminho).as_uri() + "?mode=ro&immutable=1", uri=True)


def registro_api(con, end):
    linha = con.execute("SELECT v FROM kv WHERE k = ?", (f"1:{end}",)).fetchone()
    return None if linha is None else json.loads(linha[0])


def k256(b):
    h = keccak.new(digest_bits=256)
    h.update(b)
    return "0x" + h.hexdigest()


def sha256_arquivo(caminho):
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def hex_para_bytes(s):
    s = s or ""
    s = s[2:] if s.startswith("0x") else s
    s = re.sub(r"__.{36}__", "0" * 40, s)          # marcadores de biblioteca, se houver
    return bytes.fromhex(s)


def sem_sobre(tipo):
    """'ShortString (sobre bytes32)' -> 'ShortString'."""
    return re.sub(r" \(sobre [^)]*\)$", "", tipo or "")


# ------------------------------------------------------------------------------------------------ via A: recompilacao
CHAVES_METADADOS = ("evmVersion", "metadata", "viaIR", "optimizer", "remappings")


def entrada_de_compilacao(reg):
    """Entrada guardada pelo acervo, completada com as configuracoes que o arquivo de metadados registra e que a entrada
    omite, sem sobrescrever (regra da subsecao 3.3; bibliotecas no formato 'arquivo:Nome' convertidas)."""
    std = copy.deepcopy(reg["stdJsonInput"])
    st = std.setdefault("settings", {})
    meta = ((reg.get("metadata") or {}).get("settings") or {})
    acrescidas = []
    for k in CHAVES_METADADOS:
        if k in meta and k not in st:
            st[k] = copy.deepcopy(meta[k])
            acrescidas.append(k)
    libs = meta.get("libraries") or {}
    if libs and not st.get("libraries"):
        conv = {}
        for chave, end in libs.items():
            arq, _, nome = chave.rpartition(":")
            conv.setdefault(arq, {})[nome] = end
        st["libraries"] = conv
        acrescidas.append("libraries")
    return std, acrescidas


def localizar_solc(versao_longa):
    lista = json.loads((SOLC_DIR / "list.json").read_text(encoding="utf-8"))
    v = versao_longa.lstrip("v")
    build = next((b for b in lista["builds"] if b["longVersion"] == v), None)
    candidatos = [SOLC_DIR / f"solc-v{v}"]
    if build:
        candidatos.append(SOLC_DIR / f"solc-v{build['version']}")
    dirpasta = next((c for c in candidatos if (c / "solc.exe").exists()), None)
    info = {"versao": v, "build_na_lista_oficial": build["path"] if build else None}
    if dirpasta is None:
        info["executavel"] = None
        return info
    exe = dirpasta / "solc.exe"
    info["executavel"] = exe.relative_to(RAIZ).as_posix()
    info["sha256_executavel"] = sha256_arquivo(exe)
    reg = dirpasta / "sha256.txt"
    reg_txt = reg.read_text(encoding="utf-8").split() if reg.exists() else []
    if build:
        if build["path"].endswith(".zip"):
            # a lista oficial traz o sha256 do zip; o executavel foi extraido dele pelo baixador do verificador
            info["sha256_conferido"] = "zip: sha256 registrado em sha256.txt = lista oficial" if (
                len(reg_txt) >= 2 and "0x" + reg_txt[0] == build["sha256"] and reg_txt[1] == build["path"]) else \
                "zip: sha256.txt nao confere com a lista"
            info["sha256_igual_lista_oficial"] = info["sha256_conferido"].startswith("zip: sha256 registrado")
        else:
            info["sha256_igual_lista_oficial"] = "0x" + info["sha256_executavel"] == build["sha256"]
            info["sha256_conferido"] = "executavel = lista oficial" if info["sha256_igual_lista_oficial"] else \
                "executavel difere da lista oficial"
    return {"_exe": exe, **info}


def rodar_solc(exe, entrada, cwd):
    t0 = time.time()
    p = subprocess.run([str(exe), "--standard-json"], input=json.dumps(entrada).encode("utf-8"), capture_output=True,
                       timeout=1800, cwd=cwd)
    saida = json.loads(p.stdout.decode("utf-8", "replace"))
    return saida, round(time.time() - t0, 1)


def compilar(exe, entrada, arquivo, contrato, cwd):
    e = copy.deepcopy(entrada)
    e["settings"]["outputSelection"] = {
        "*": {"": ["ast"]},
        arquivo: {contrato: ["evm.deployedBytecode.object", "evm.deployedBytecode.immutableReferences",
                             "evm.deployedBytecode.linkReferences"]}}
    saida, seg = rodar_solc(exe, e, cwd)
    erros = [x.get("formattedMessage", x.get("message", ""))[:300] for x in saida.get("errors", [])
             if x.get("severity") == "error"]
    c = ((saida.get("contracts") or {}).get(arquivo) or {}).get(contrato)
    dep = ((c or {}).get("evm") or {}).get("deployedBytecode") or {}
    asts = {k: s.get("ast") for k, s in (saida.get("sources") or {}).items()}
    ids_fonte = {k: s.get("id") for k, s in (saida.get("sources") or {}).items()}
    return {"erros": erros, "segundos": seg, "objeto": dep.get("object", ""),
            "imutaveis": dep.get("immutableReferences") or {}, "ligacoes": dep.get("linkReferences") or {},
            "asts": asts, "ids_fonte": ids_fonte}


def indexar_ast(asts):
    ind, repetidos = {}, 0

    def andar(no):
        nonlocal repetidos
        if isinstance(no, dict):
            if "nodeType" in no and "id" in no:
                if no["id"] in ind and ind[no["id"]] is not no:
                    repetidos += 1
                ind.setdefault(no["id"], no)
            for v in no.values():
                andar(v)
        elif isinstance(no, list):
            for v in no:
                andar(v)

    for a in (asts or {}).values():
        andar(a)
    return ind, repetidos


def tipo_tau_ast(no, ind):
    """Tipo (no formato da certidao) e tau pela regra da 3.4: address, address payable, contrato, interface e tipo de
    valor definido pelo usuario sobre address ou address payable. A categoria vem da declaracao referenciada."""
    ts = (no.get("typeDescriptions") or {}).get("typeString")
    tn = no.get("typeName") or {}
    nt = tn.get("nodeType")
    info = {"typeString": ts, "typeName": nt}
    base = None
    if nt == "ElementaryTypeName":
        categoria = "address" if ts in ENDERECO else "elementar"
        tipo = ts
    elif nt == "UserDefinedTypeName":
        ref = tn.get("referencedDeclaration")
        alvo = ind.get(ref) or {}
        k = alvo.get("nodeType")
        info["declaracao_referenciada"] = {"id": ref, "nodeType": k, "nome": alvo.get("name"),
                                           "contractKind": alvo.get("contractKind")}
        tipo = ts
        if k == "ContractDefinition":
            categoria = alvo.get("contractKind")            # contract | interface | library
        elif k == "UserDefinedValueTypeDefinition":
            categoria = "tipo_de_valor"
            base = ((alvo.get("underlyingType") or {}).get("typeDescriptions") or {}).get("typeString")
            info["tipo_subjacente"] = base
            tipo = f"{ts} (sobre {base})"
        elif k == "EnumDefinition":
            categoria = "enum"
        elif k == "StructDefinition":
            categoria = "struct"
        else:
            categoria = "desconhecida"
    else:
        categoria, tipo = "outra", ts
    tau = categoria in ("address", "contract", "interface") or (categoria == "tipo_de_valor" and base in ENDERECO)
    # leitura literal alternativa (so o texto do tipo), para conferir que as duas formulacoes coincidem
    tau_texto_do_tipo = (ts in ENDERECO or (ts or "").startswith("contract ")
                         or (categoria == "tipo_de_valor" and base in ENDERECO))
    return {"tipo": tipo, "tau": tau, "categoria": categoria, "tau_pelo_typeString": tau_texto_do_tipo, **info}


def reproduz_codigo(objeto_hex, ligacoes, regioes, c_a):
    """Recompilado, com os bytes de F(a) copiados da cadeia, igual ao codigo da cadeia (nenhum dos 15 contratos tem
    bloco de metadados removido)."""
    h = list(objeto_hex[2:] if objeto_hex.startswith("0x") else objeto_hex)
    for libs in (ligacoes or {}).values():
        for refs in libs.values():
            for ref in refs:
                h[2 * ref["start"]:2 * (ref["start"] + ref["length"])] = list("00" * ref["length"])
    R = bytes.fromhex("".join(h))
    if len(R) != len(c_a):
        return False, f"comprimentos {len(R)} x {len(c_a)}"
    R2 = bytearray(R)
    for r in regioes:
        R2[r["inicio"]:r["inicio"] + r["comprimento"]] = c_a[r["inicio"]:r["inicio"] + r["comprimento"]]
    fora = sum(1 for x, y in zip(R2, c_a) if x != y)
    return fora == 0, f"{fora} bytes diferem fora de F(a)"


# ------------------------------------------------------------------------------------------------ via B: texto
def apagar_comentarios_e_cadeias(t):
    """t: texto em latin-1 (1 caractere = 1 byte, para manter as posicoes do mapa de fontes). Troca por espacos os
    comentarios e o conteudo das cadeias (as aspas ficam), preservando quebras de linha e comprimento."""
    out = list(t)
    i, n = 0, len(t)
    while i < n:
        c = t[i]
        if c == "/" and i + 1 < n and t[i + 1] == "/":
            j = t.find("\n", i)
            j = n if j < 0 else j
            for k in range(i, j):
                out[k] = " "
            i = j
        elif c == "/" and i + 1 < n and t[i + 1] == "*":
            j = t.find("*/", i + 2)
            j = n if j < 0 else j + 2
            for k in range(i, j):
                if out[k] != "\n":
                    out[k] = " "
            i = j
        elif c in "\"'":
            j = i + 1
            while j < n and t[j] != c and t[j] != "\n":
                j += 2 if t[j] == "\\" else 1
            for k in range(i + 1, min(j, n)):
                if out[k] != "\n":
                    out[k] = " "
            i = j + 1
        else:
            i += 1
    return "".join(out)


RE_CONTRATO = re.compile(r"(?<![\w$.])(abstract\s+contract|contract|interface|library)\s+(" + IDENT + r")")
RE_ENUM = re.compile(r"(?<![\w$.])enum\s+(" + IDENT + r")\s*\{")
RE_STRUCT = re.compile(r"(?<![\w$.])struct\s+(" + IDENT + r")\s*\{")
RE_UDVT = re.compile(r"(?<![\w$.])type\s+(" + IDENT + r")\s+is\s+(address\s+payable|" + IDENT + r")\s*;")
RE_DECL = re.compile(
    r"(?<![\w$.])(?P<tipo>address\s+payable|" + IDENT + r"(?:\s*\.\s*" + IDENT + r")*)"
    r"(?P<mods>(?:\s+(?:public|private|internal|immutable|constant|transient|override(?:\s*\([^()]*\))?))+)"
    r"\s+(?P<nome>" + IDENT + r")(?=\s*[;=])")
RE_IMPORT_SIMBOLOS = re.compile(r"(?<![\w$.])import\s*\{([^}]*)\}\s*from")
RE_IMPORT_MODULO = re.compile(r"(?<![\w$.])import\s+(?:\*\s+as\s+(" + IDENT + r")\s+from\s*[\"'][^\"']*[\"']|"
                              r"[\"'][^\"']*[\"']\s+as\s+(" + IDENT + r"))")


def normalizar_tipo(t):
    return re.sub(r"\s*\.\s*", ".", " ".join(t.split()))


class Fontes:
    """Textos das fontes guardadas pelo acervo, com comentarios e cadeias apagados, e indice das definicoes."""

    def __init__(self, sources):
        self.bruto = {k: (v.get("content") or "").encode("utf-8") for k, v in sources.items()}
        self.limpo = {k: apagar_comentarios_e_cadeias(b.decode("latin-1")) for k, b in self.bruto.items()}
        self.contratos, self.defs, self.alias_simbolo, self.alias_modulo = [], [], {}, set()
        for arq, t in self.limpo.items():
            for m in RE_CONTRATO.finditer(t):
                ab = t.find("{", m.end())
                if ab < 0:
                    continue
                prof, j = 0, ab
                while j < len(t):
                    if t[j] == "{":
                        prof += 1
                    elif t[j] == "}":
                        prof -= 1
                        if prof == 0:
                            break
                    j += 1
                tipo = " ".join(m.group(1).split())
                self.contratos.append({"arquivo": arq, "nome": m.group(2), "tipo": tipo, "ini": ab, "fim": j,
                                       "cabecalho": " ".join(t[m.start():ab].split())})
                self.defs.append({"arquivo": arq, "nome": m.group(2), "classe": "library" if tipo == "library"
                                  else "contrato", "detalhe": tipo, "dentro_de": None, "pos": m.start()})
            for rx, classe in ((RE_ENUM, "enum"), (RE_STRUCT, "struct")):
                for m in rx.finditer(t):
                    self.defs.append({"arquivo": arq, "nome": m.group(1), "classe": classe, "detalhe": None,
                                      "dentro_de": None, "pos": m.start()})
            for m in RE_UDVT.finditer(t):
                self.defs.append({"arquivo": arq, "nome": m.group(1), "classe": "tipo_de_valor",
                                  "detalhe": " ".join(m.group(2).split()), "dentro_de": None, "pos": m.start()})
            for m in RE_IMPORT_SIMBOLOS.finditer(t):
                for item in m.group(1).split(","):
                    p = item.split()
                    if len(p) == 3 and p[1] == "as":
                        self.alias_simbolo.setdefault(p[2], set()).add(p[0])
            for m in RE_IMPORT_MODULO.finditer(t):
                self.alias_modulo.add(m.group(1) or m.group(2))
        for d in self.defs:
            if d["classe"] in ("contrato", "library"):
                continue
            c = self.contrato_em(d["arquivo"], d["pos"])
            d["dentro_de"] = c["nome"] if c else None

    def contrato_em(self, arq, pos):
        return next((c for c in self.contratos if c["arquivo"] == arq and c["ini"] <= pos <= c["fim"]), None)

    def trecho(self, arq, ini, n):
        return self.bruto[arq][ini:ini + n].decode("utf-8", "replace")

    def declaracoes_imutaveis(self, nome):
        out = []
        for arq, t in self.limpo.items():
            for m in RE_DECL.finditer(t):
                if m.group("nome") == nome and re.search(r"\bimmutable\b", m.group("mods")):
                    out.append(self._decl(arq, m))
        return out

    def declaracao_em(self, arq, pos):
        m = RE_DECL.match(self.limpo[arq], pos)
        if m and re.search(r"\bimmutable\b", m.group("mods")):
            return self._decl(arq, m)
        return None

    def _decl(self, arq, m):
        mods = m.group("mods").split()
        vis = next((x for x in mods if x in ("public", "private", "internal")), "internal")
        c = self.contrato_em(arq, m.start())
        return {"arquivo": arq, "inicio": m.start(), "nome": m.group("nome"), "tipo_escrito":
                normalizar_tipo(m.group("tipo")), "visibilidade": vis, "contrato": c["nome"] if c else None,
                "texto": " ".join(self.trecho(arq, m.start(), m.end() - m.start()).split())}

    def resolver(self, tipo_escrito):
        """Tipo escrito -> (tipo no formato da certidao, categoria, tau, observacao), so pelas definicoes do texto."""
        t = normalizar_tipo(tipo_escrito)
        if t in ENDERECO:
            return t, "address", True, None
        if t == "bool":
            return t, "elementar", False, None
        m = re.fullmatch(r"(u?int)(\d*)", t)
        if m:
            return m.group(1) + (m.group(2) or "256"), "elementar", False, None
        if re.fullmatch(r"bytes([1-9]|[12]\d|3[0-2])", t):
            return t, "elementar", False, None
        if t == "byte":
            return "bytes1", "elementar", False, None
        partes = t.split(".")
        obs = []
        if partes[0] in self.alias_simbolo:
            orig = self.alias_simbolo[partes[0]]
            if len(orig) == 1:
                obs.append(f"alias de importacao {partes[0]} -> {next(iter(orig))}")
                partes[0] = next(iter(orig))
        if len(partes) == 2 and partes[0] in self.alias_modulo:
            obs.append(f"prefixo de modulo {partes[0]}")
            partes = partes[1:]
        nome = partes[-1]
        cands = [d for d in self.defs if d["nome"] == nome]
        if len(partes) == 2:
            cands = [d for d in cands if d["dentro_de"] == partes[0]]
        classes = {(d["classe"], d["detalhe"] if d["classe"] == "tipo_de_valor" else None,
                    d["dentro_de"] if d["classe"] in ("enum", "tipo_de_valor", "struct") else None) for d in cands}
        if not cands:
            return None, "nao_resolvido", None, "; ".join(obs + ["sem definicao no texto"])
        if len(classes) > 1:
            return None, "ambiguo", None, "; ".join(obs + [f"definicoes conflitantes: {sorted(map(str, classes))}"])
        classe, base, dentro = classes.pop()
        if len(cands) > 1:
            obs.append(f"{len(cands)} definicoes de mesma classe")
        if classe == "contrato":
            kinds = sorted({d["detalhe"] for d in cands})
            return f"contract {nome}", "/".join(kinds), True, "; ".join(obs) or None
        if classe == "enum":
            return f"enum {dentro + '.' if dentro else ''}{nome}", "enum", False, "; ".join(obs) or None
        if classe == "tipo_de_valor":
            b = self.resolver(base)[0] if base not in ENDERECO else base
            pref = (dentro + ".") if dentro else ""
            return f"{pref}{nome} (sobre {b})", "tipo_de_valor", b in ENDERECO, "; ".join(obs) or None
        if classe == "struct":
            return f"struct {dentro + '.' if dentro else ''}{nome}", "struct", False, "; ".join(obs) or None
        return None, classe, None, "; ".join(obs) or None


def decodificar_mapa(sm):
    out, ant = [], ["", "", "", "", ""]
    for ent in (sm or "").split(";"):
        cur = list(ant)
        for i, p in enumerate(ent.split(":")):
            if p != "" and i < 5:
                cur[i] = p
        out.append(cur)
        ant = cur
    return out


def inicios_de_instrucao(code):
    pos, i = {}, 0
    k = 0
    while i < len(code):
        op = code[i]
        pos[i] = k
        k += 1
        i += 1 + (op - 0x5f if 0x60 <= op <= 0x7f else 0)
    return pos


# ------------------------------------------------------------------------------------------------ conferencia
def conferir_contrato(cert, reg, cwd):
    end = cert["contrato"]["endereco"]
    comp = reg["compilation"]
    arquivo, contrato = comp["fullyQualifiedName"].rsplit(":", 1)
    rt = reg.get("runtimeBytecode") or {}
    consts = [k for k in cert["constantes"] if k["construto"].startswith("imutavel:")]
    regs_por_construto = {}
    for r in cert["regioes"]:
        regs_por_construto.setdefault(r["construto"], []).append(r)
    out = {"endereco": end, "compilador": comp["compilerVersion"], "grau": cert["acervo"].get("grau_instantaneo"),
           "contrato_compilado": comp["fullyQualifiedName"], "falhas": []}
    F = out["falhas"]

    # codigo da cadeia guardado pelo acervo, conferido pelo resumo da certidao
    c_a = hex_para_bytes(rt.get("onchainBytecode"))
    out["onchainBytecode_resumo_igual_certidao"] = k256(c_a) == cert["contrato"]["resumo_codigo"]
    if not out["onchainBytecode_resumo_igual_certidao"]:
        F.append("onchainBytecode do acervo difere do resumo da certidao")

    # ---------------- via A
    std, acrescidas = entrada_de_compilacao(reg)
    out["A_ajustes_dos_metadados"] = acrescidas
    out["A_ajustes_iguais_aos_da_certidao"] = acrescidas == cert["recompilacao"].get("ajustes_dos_metadados")
    solc = localizar_solc(comp["compilerVersion"])
    exe = solc.pop("_exe", None)
    out["A_solc"] = solc
    if exe is None:
        F.append("binario do compilador ausente do cache")
        return out
    rc = compilar(exe, std, arquivo, contrato, cwd)
    out["A_segundos_de_compilacao"] = rc["segundos"]
    if rc["erros"]:
        F.append("erros de compilacao: " + " | ".join(rc["erros"][:3]))
        return out
    ind, repetidos = indexar_ast(rc["asts"])
    out["A_nos_da_ast"] = len(ind)
    out["A_ids_repetidos_na_ast"] = repetidos
    ok, motivo = reproduz_codigo(rc["objeto"], rc["ligacoes"], cert["regioes"], c_a)
    out["A_recompilacao_reproduz_codigo_fora_de_F"] = ok
    if not ok:
        F.append("recompilacao nao reproduz o codigo: " + motivo)
    imut_rc = {k: sorted(x["start"] for x in v) for k, v in rc["imutaveis"].items() if k != "library_deploy_address"}
    ids_cert = sorted(k["construto"].split(":", 1)[1] for k in consts)
    out["A_ids_da_recompilacao_iguais_aos_da_certidao"] = sorted(imut_rc) == ids_cert

    # ---------------- vinculo com o acervo pela posicao
    pos_para_id_acervo = {}
    for t in rt.get("transformations") or []:
        if t.get("reason") == "immutable" and str(t.get("id")) != "library_deploy_address" and \
                t.get("type") == "replace":
            pos_para_id_acervo[int(t["offset"])] = str(t["id"])
    imut_acervo = {k: sorted(x["start"] for x in v) for k, v in (rt.get("immutableReferences") or {}).items()
                   if k != "library_deploy_address"}

    # ---------------- via B: mapa de fontes do acervo e texto
    fontes = Fontes(reg["stdJsonInput"]["sources"])
    srcs_acervo = reg.get("sources") or {}
    out["B_fontes_iguais_as_do_campo_sources"] = all(
        (srcs_acervo.get(k) or {}).get("content") == v.get("content") for k, v in reg["stdJsonInput"]["sources"].items()
        if k in srcs_acervo)
    rec = hex_para_bytes(rt.get("recompiledBytecode"))
    instr = inicios_de_instrucao(rec)
    mapa = decodificar_mapa(rt.get("sourceMap"))
    indice_para_arquivo = {v["id"]: k for k, v in (reg.get("sourceIds") or {}).items()}
    out["B_indices_de_fonte_do_acervo"] = {"fontes": len(indice_para_arquivo),
                                          "maior_indice": max(indice_para_arquivo) if indice_para_arquivo else None,
                                          "fontes_na_entrada_guardada": len(reg["stdJsonInput"]["sources"]),
                                          "fontes_nos_metadados": len((reg.get("metadata") or {}).get("sources")
                                                                      or {})}

    # ---------------- ABI do acervo
    abi = reg.get("abi") or []
    so_abi = (((reg.get("stdJsonOutput") or {}).get("contracts") or {}).get(arquivo) or {}).get(contrato, {}).get("abi")
    meta_abi = ((reg.get("metadata") or {}).get("output") or {}).get("abi")
    canon = lambda a: sorted(json.dumps(x, sort_keys=True) for x in (a or []))
    out["C_abi_copias_iguais"] = {"abi_igual_stdJsonOutput": canon(abi) == canon(so_abi),
                                  "abi_igual_metadata_output": canon(abi) == canon(meta_abi)}

    res = []
    for k in consts:
        cid = k["construto"].split(":", 1)[1]
        regs = sorted(regs_por_construto.get(k["construto"], []), key=lambda r: r["inicio"])
        inicios = [r["inicio"] for r in regs]
        item = {"construto": k["construto"], "tipo_certidao": k["tipo"], "tau_certidao": k["tau_address"],
                "regioes": len(regs), "inicios": inicios}
        # A
        no = ind.get(int(cid))
        a = {"declaracao_achada": bool(no and no.get("nodeType") == "VariableDeclaration")}
        if a["declaracao_achada"]:
            a.update({"nome": no.get("name"), "visibilidade": no.get("visibility"),
                      "mutabilidade": no.get("mutability") or ("constant" if no.get("constant") else None),
                      "variavel_de_estado": no.get("stateVariable"), "src": no.get("src")})
            a.update(tipo_tau_ast(no, ind))
        a["posicoes_iguais_a_certidao"] = imut_rc.get(cid) == inicios
        por_pos = [i for i, p in imut_rc.items() if p == inicios]
        a["id_pela_posicao"] = por_pos[0] if len(por_pos) == 1 else por_pos
        a["tipo_igual"] = a.get("tipo") == k["tipo"]
        a["tau_igual"] = a.get("tau") == k["tau_address"]
        item["A_ast"] = a
        # vinculo com o acervo
        ids_ac = sorted({pos_para_id_acervo.get(p) for p in inicios}, key=str)
        id_ac = ids_ac[0] if len(ids_ac) == 1 else None
        item["id_acervo"] = id_ac if id_ac is not None else ids_ac
        item["id_difere_do_acervo"] = id_ac != cid
        item["posicoes_do_id_acervo_iguais"] = id_ac is not None and imut_acervo.get(id_ac) == inicios
        # B
        b = {"leituras": []}
        nomes, decl_no_mapa = set(), None
        for p in inicios:
            ii = instr.get(p - 1)
            leit = {"inicio": p}
            if ii is None or rec[p - 1] != 0x7f:
                leit["obs"] = "sem PUSH32 no recompilado do acervo"
            elif ii >= len(mapa) or not mapa[ii][2].lstrip("-").isdigit():
                leit["obs"] = "sem entrada no mapa de fontes"
            else:
                s, n, f = int(mapa[ii][0]), int(mapa[ii][1]), int(mapa[ii][2])
                arq = indice_para_arquivo.get(f)
                if arq is None or arq not in fontes.limpo:
                    leit["obs"] = f"indice de fonte {f} sem arquivo"
                else:
                    trecho_limpo = fontes.limpo[arq][s:s + n]
                    leit.update({"arquivo": arq, "inicio_no_fonte": s, "trecho": " ".join(fontes.trecho(arq, s, n).split())[:120]})
                    c = fontes.contrato_em(arq, s)
                    leit["contrato_do_trecho"] = c["nome"] if c else None
                    mm = re.fullmatch(r"\s*(" + IDENT + r")\s*", trecho_limpo)
                    d = fontes.declaracao_em(arq, s + (len(trecho_limpo) - len(trecho_limpo.lstrip())))
                    if mm:
                        nomes.add(mm.group(1))
                        leit["leitura"] = "identificador"
                    elif d:
                        nomes.add(d["nome"])
                        decl_no_mapa = d
                        leit["leitura"] = "declaracao (getter publico)"
                    else:
                        leit["obs"] = "trecho nao reconhecido"
            b["leituras"].append(leit)
        b["nomes"] = sorted(nomes)
        nome_b = b["nomes"][0] if len(nomes) == 1 else None
        b["nome"] = nome_b
        if decl_no_mapa:
            b["declaracao"] = decl_no_mapa
            b["declaracao_achada_por"] = "mapa de fontes (o trecho e a propria declaracao)"
            b["candidatas"] = 1
        elif nome_b:
            cands = fontes.declaracoes_imutaveis(nome_b)
            contratos_leitura = {x.get("contrato_do_trecho") for x in b["leituras"] if x.get("contrato_do_trecho")}
            mesmo = [c for c in cands if c["contrato"] in contratos_leitura]
            escolhidas = mesmo or cands
            b["candidatas"] = len(cands)
            b["declaracao_achada_por"] = ("nome, no contrato em que a variavel e lida" if mesmo else
                                          "nome, em todo o texto") if cands else "nao achada"
            tipos = {c["tipo_escrito"] for c in escolhidas}
            if len(tipos) == 1:
                b["declaracao"] = escolhidas[0] if len(escolhidas) == 1 else {**escolhidas[0], "outras_com_mesmo_tipo":
                                                                             [x["contrato"] for x in escolhidas[1:]]}
            elif tipos:
                b["declaracao_ambigua"] = escolhidas
        if b.get("declaracao"):
            tipo_b, cat_b, tau_b, obs_b = fontes.resolver(b["declaracao"]["tipo_escrito"])
            b.update({"tipo": tipo_b, "categoria": cat_b, "tau": tau_b, "obs_resolucao": obs_b,
                      "visibilidade": b["declaracao"]["visibilidade"]})
        b["nome_igual_ao_da_ast"] = nome_b is not None and nome_b == a.get("nome")
        b["visibilidade_igual_a_da_ast"] = b.get("visibilidade") == a.get("visibilidade")
        # conferencia a posteriori da escolha feita pelo texto: mesma declaracao (arquivo e posicao) que a AST aponta
        try:
            s_ini, _, s_arq = (a.get("src") or "").split(":")
            arq_ast = next((f for f, i in rc["ids_fonte"].items() if i == int(s_arq)), None)
            b["mesma_declaracao_que_a_ast"] = bool(b.get("declaracao")) and \
                (b["declaracao"]["arquivo"], b["declaracao"]["inicio"]) == (arq_ast, int(s_ini))
        except ValueError:
            b["mesma_declaracao_que_a_ast"] = False
        b["tipo_igual"] = b.get("tipo") == k["tipo"]
        b["tau_igual"] = b.get("tau") == k["tau_address"]
        item["B_texto"] = b
        # C (nome e visibilidade da via B, para nao depender da AST; iguais aos da AST nas 76)
        vis = b.get("visibilidade") or a.get("visibilidade")
        if vis == "public":
            nome = nome_b or a.get("nome")
            gs = [e for e in abi if e.get("type") == "function" and e.get("name") == nome and not e.get("inputs")]
            cc = {"getters": len(gs)}
            if len(gs) == 1 and len(gs[0].get("outputs") or []) == 1:
                o = gs[0]["outputs"][0]
                cc.update({"internalType": o.get("internalType"), "type": o.get("type"),
                           "stateMutability": gs[0].get("stateMutability")})
                cc["internalType_igual_tipo_certidao"] = o.get("internalType") == sem_sobre(k["tipo"])
                cc["internalType_igual_typeString_ast"] = o.get("internalType") == a.get("typeString")
                cc["tau_pela_abi"] = o.get("type") == "address"
                cc["tau_igual"] = cc["tau_pela_abi"] == k["tau_address"]
            item["C_abi"] = cc
        res.append(item)
    out["constantes"] = res
    for it in res:
        for via, chaves in (("A_ast", ("declaracao_achada", "posicoes_iguais_a_certidao", "tipo_igual", "tau_igual")),
                            ("B_texto", ("nome_igual_ao_da_ast", "tipo_igual", "tau_igual"))):
            for ch in chaves:
                if not it[via].get(ch):
                    F.append(f"{it['construto']}: {via}.{ch} falso")
        if "C_abi" in it and not (it["C_abi"].get("internalType_igual_tipo_certidao") and it["C_abi"].get("tau_igual")):
            F.append(f"{it['construto']}: C_abi diverge")
        if it["A_ast"].get("tau") != it["A_ast"].get("tau_pelo_typeString"):
            F.append(f"{it['construto']}: as duas formulacoes de tau divergem")
    out["_exe"] = exe
    out["_std"] = std
    return out


def testar_causa_ids(cert, reg, exe, base, cwd):
    """Recompila so com as fontes listadas nos metadados do acervo e compara ids e posicoes com os do acervo."""
    nomes = list(((reg.get("metadata") or {}).get("sources") or {}).keys())
    std = copy.deepcopy(base)
    faltam = [n for n in nomes if n not in std["sources"]]
    r = {"fontes_na_entrada_guardada": len(std["sources"]), "fontes_nos_metadados": len(nomes),
         "fontes_dos_metadados_ausentes_da_entrada": len(faltam)}
    if faltam:
        r["aplicavel"] = False
        return r
    if set(nomes) == set(std["sources"]):
        r["aplicavel"] = False
        r["obs"] = ("a entrada guardada ja tem exatamente as fontes dos metadados; os ids do acervo vem de compilacao "
                    "com mais fontes, que o acervo nao guarda")
        return r
    std["sources"] = {n: std["sources"][n] for n in nomes}
    arquivo, contrato = reg["compilation"]["fullyQualifiedName"].rsplit(":", 1)
    rc = compilar(exe, std, arquivo, contrato, cwd)
    r["aplicavel"] = True
    r["erros"] = rc["erros"]
    if rc["erros"]:
        return r
    rt = reg.get("runtimeBytecode") or {}
    imut_acervo = {k: sorted(x["start"] for x in v) for k, v in (rt.get("immutableReferences") or {}).items()}
    imut_rc = {k: sorted(x["start"] for x in v) for k, v in rc["imutaveis"].items()}
    r["ids_iguais_aos_do_acervo"] = sorted(imut_rc) == sorted(imut_acervo)
    r["posicoes_iguais_as_do_acervo"] = imut_rc == imut_acervo
    ind, _ = indexar_ast(rc["asts"])
    r["declaracoes_pelos_ids_do_acervo"] = {}
    for i in sorted(imut_acervo, key=int):
        no = ind.get(int(i)) or {}
        r["declaracoes_pelos_ids_do_acervo"][i] = {"nome": no.get("name"), "nodeType": no.get("nodeType"),
                                                   **({"tipo": tipo_tau_ast(no, ind)["tipo"]} if no else {})}
    return r


def main():
    api = abrir_ro(CACHE_API)
    certs, todos_os_enderecos = [], []
    contexto = {"constantes_com_tau_verdadeiro_por_motivo": {}, "contratos_com_indicador_1": 0,
                "contratos_com_indicador_1_por_variavel_imutavel": 0,
                "contratos_com_indicador_1_so_por_variavel_imutavel": 0}
    for p in sorted(CERTIDOES.glob("*.json"), key=lambda x: x.name):
        c = json.loads(p.read_text(encoding="utf-8"))
        todos_os_enderecos.append(c["contrato"]["endereco"])
        if any(k["construto"].startswith("imutavel:") for k in c.get("constantes", [])):
            certs.append(c)
        mot = [k["motivo"] for k in c.get("constantes", []) if k["tau_address"]]
        for m in mot:
            contexto["constantes_com_tau_verdadeiro_por_motivo"][m] = \
                contexto["constantes_com_tau_verdadeiro_por_motivo"].get(m, 0) + 1
        if c.get("indicador_equacao_2") == 1:
            contexto["contratos_com_indicador_1"] += 1
            contexto["contratos_com_indicador_1_por_variavel_imutavel"] += "immutable" in mot
            contexto["contratos_com_indicador_1_so_por_variavel_imutavel"] += set(mot) == {"immutable"}
    n_certidoes = len(todos_os_enderecos)
    res = []
    # o compilador so le a entrada padrao e escreve na saida padrao; a pasta de trabalho fica fora do repositorio
    with tempfile.TemporaryDirectory() as cwd:
        for c in certs:
            end = c["contrato"]["endereco"]
            reg = registro_api(api, end)
            print("conferindo", end, c["acervo"]["compilador"], flush=True)
            r = conferir_contrato(c, reg, cwd)
            exe, std = r.pop("_exe", None), r.pop("_std", None)
            if exe and any(x["id_difere_do_acervo"] for x in r.get("constantes", [])):
                t = testar_causa_ids(c, reg, exe, std, cwd)
                r["teste_da_causa_dos_ids_divergentes"] = t
                if t.get("aplicavel") and not t.get("erros"):
                    # casamento pelo id do acervo: declaracao que o id do acervo aponta na recompilacao so com as fontes
                    # dos metadados, comparada (nome e tipo) com a que o id da certidao aponta na recompilacao principal
                    iguais = 0
                    for x in r["constantes"]:
                        dd = t["declaracoes_pelos_ids_do_acervo"].get(str(x["id_acervo"])) or {}
                        x["declaracao_pelo_id_do_acervo"] = dd
                        x["mesmo_nome_e_tipo_pelo_id_do_acervo"] = (dd.get("nome") == x["A_ast"].get("nome")
                                                                     and dd.get("tipo") == x["tipo_certidao"])
                        iguais += x["mesmo_nome_e_tipo_pelo_id_do_acervo"]
                    t["constantes_do_contrato"] = len(r["constantes"])
                    t["constantes_com_mesmo_nome_e_tipo_pelo_id_do_acervo"] = iguais
            res.append(r)

    todas = [x for r in res for x in r.get("constantes", [])]
    publicas = [x for x in todas if "C_abi" in x]
    cat = {}
    for x in todas:
        chave = f"{'tau verdadeiro' if x['A_ast'].get('tau') else 'tau falso'}: {x['A_ast'].get('categoria')}"
        cat[chave] = cat.get(chave, 0) + 1
    divergentes = [x for x in todas if x["id_difere_do_acervo"]]
    diferente_por_contrato = {r["endereco"]: sum(1 for x in r.get("constantes", []) if x["id_difere_do_acervo"])
                              for r in res if any(x["id_difere_do_acervo"] for x in r.get("constantes", []))}
    totais = {
        "certidoes_lidas": n_certidoes,
        "contratos_com_imutavel": len(res),
        "contratos_por_grau": {g: sum(1 for r in res if r["grau"] == g) for g in sorted({r["grau"] for r in res})},
        "versoes_do_compilador": sorted({r["compilador"] for r in res},
                                        key=lambda v: tuple(int(x) for x in v.split("+")[0].split("."))),
        "constantes": len(todas),
        "A_ast": {
            "binario_conferido_com_lista_oficial": sum(1 for r in res if r.get("A_solc", {}).get("sha256_igual_lista_oficial")),
            "recompilacao_reproduz_codigo_fora_de_F": sum(1 for r in res if r.get("A_recompilacao_reproduz_codigo_fora_de_F")),
            "ids_da_recompilacao_iguais_aos_da_certidao_contratos": sum(1 for r in res if r.get("A_ids_da_recompilacao_iguais_aos_da_certidao")),
            "declaracao_achada": sum(1 for x in todas if x["A_ast"].get("declaracao_achada")),
            "posicoes_iguais_a_certidao": sum(1 for x in todas if x["A_ast"].get("posicoes_iguais_a_certidao")),
            "tipo_igual": sum(1 for x in todas if x["A_ast"]["tipo_igual"]),
            "tau_igual": sum(1 for x in todas if x["A_ast"]["tau_igual"]),
            "duas_formulacoes_de_tau_coincidem": sum(1 for x in todas if x["A_ast"].get("tau") == x["A_ast"].get("tau_pelo_typeString")),
            "categorias": dict(sorted(cat.items())),
            "tipos_declarados": dict(sorted({t: sum(1 for x in todas if x["A_ast"].get("tipo") == t)
                                             for t in {x["A_ast"].get("tipo") for x in todas}}.items())),
        },
        "B_texto": {
            "nome_pelo_mapa_de_fontes_do_acervo": sum(1 for x in todas if x["B_texto"].get("nome")),
            "nome_igual_ao_da_ast": sum(1 for x in todas if x["B_texto"]["nome_igual_ao_da_ast"]),
            "declaracao_achada": sum(1 for x in todas if x["B_texto"].get("declaracao")),
            "declaracao_pelo_proprio_mapa_de_fontes": sum(1 for x in todas if (x["B_texto"].get("declaracao_achada_por") or "").startswith("mapa")),
            "declaracao_pelo_nome": sum(1 for x in todas if (x["B_texto"].get("declaracao_achada_por") or "").startswith("nome")),
            "declaracao_pelo_nome_com_mais_de_uma_candidata": sum(1 for x in todas if (x["B_texto"].get("candidatas") or 0) > 1),
            "mesma_declaracao_que_a_ast": sum(1 for x in todas if x["B_texto"].get("mesma_declaracao_que_a_ast")),
            "visibilidade_igual_a_da_ast": sum(1 for x in todas if x["B_texto"]["visibilidade_igual_a_da_ast"]),
            "tipo_igual": sum(1 for x in todas if x["B_texto"]["tipo_igual"]),
            "tau_igual": sum(1 for x in todas if x["B_texto"]["tau_igual"]),
        },
        "C_abi": {
            "publicas": len(publicas),
            "publicas_em_contratos_de_correspondencia_exata": sum(1 for r in res for x in r.get("constantes", [])
                                                                  if "C_abi" in x and r["grau"] == "exata"),
            "getter_unico_achado": sum(1 for x in publicas if x["C_abi"].get("getters") == 1),
            "internalType_igual_tipo_certidao": sum(1 for x in publicas if x["C_abi"].get("internalType_igual_tipo_certidao")),
            "tau_pelo_type_da_abi_igual": sum(1 for x in publicas if x["C_abi"].get("tau_igual")),
        },
        "ids": {
            "igual_ao_do_acervo": len(todas) - len(divergentes),
            "diferente_do_acervo": len(divergentes),
            "contratos_com_id_diferente": len(diferente_por_contrato),
            "diferente_por_contrato": diferente_por_contrato,
            "divergentes_com_posicoes_do_id_acervo_iguais": sum(1 for x in divergentes if x["posicoes_do_id_acervo_iguais"]),
            "divergentes_com_nome_do_acervo_igual_ao_da_ast": sum(1 for x in divergentes if x["B_texto"]["nome_igual_ao_da_ast"]),
            "divergentes_tipo_e_tau_iguais_nas_vias_A_e_B": sum(1 for x in divergentes if x["A_ast"]["tipo_igual"] and x["A_ast"]["tau_igual"] and x["B_texto"]["tipo_igual"] and x["B_texto"]["tau_igual"]),
            "divergentes_com_mesmo_nome_e_tipo_pelo_id_do_acervo_na_recompilacao_so_com_fontes_dos_metadados":
                sum(1 for x in divergentes if x.get("mesmo_nome_e_tipo_pelo_id_do_acervo")),
            "teste_da_causa": {r["endereco"]: {k: v for k, v in r["teste_da_causa_dos_ids_divergentes"].items()
                                               if k != "declaracoes_pelos_ids_do_acervo"}
                               for r in res if "teste_da_causa_dos_ids_divergentes" in r},
        },
        "contratos_sem_falha": sum(1 for r in res if not r["falhas"]),
        "contexto_nas_385_certidoes": contexto,
    }
    doc = {
        "programa": Path(__file__).resolve().relative_to(RAIZ).as_posix(),
        "gerado_em_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "python": sys.version.split()[0],
        "entradas": {
            "certidoes": "dados/certidoes/*.json",
            "cache_api": {"arquivo": ".cache/sourcify_api.sqlite", "modo": "somente leitura",
                          "sha256": sha256_arquivo(CACHE_API)},
            "compiladores": ".cache/solc/solc-v<versao>/solc.exe (executados, nao alterados)",
        },
        "totais": totais,
        "contratos": res,
    }
    sem_binario = sorted({r["compilador"] for r in res if "binario do compilador ausente do cache" in r["falhas"]})
    if sem_binario:
        sys.exit("faltam em .cache/solc os compiladores " + ", ".join(sem_binario) +
                 " (o verificador os baixa); nada foi gravado")
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    with open(SAIDA, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1, ensure_ascii=False)
    print(json.dumps(totais, indent=1, ensure_ascii=False))
    for r in res:
        if r["falhas"]:
            print("FALHAS", r["endereco"], r["falhas"][:6])


if __name__ == "__main__":
    main()
