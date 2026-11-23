# -*- coding: utf-8 -*-
"""Delegacao nos contratos positivos (subsecao 4.6 do artigo). Leitura complementar, descritiva, nao prevista nas
subsecoes 3.6 e 3.8: confere se os 13 contratos positivos delegam a execucao ao endereco nao atestado.

Para cada certidao com indicador_equacao_2 = 1:
  1. lista as constantes do tipo address (construto, motivo, tipo, valor, classe do alvo, substituivel, tamanho do
     codigo do alvo) e o nome do contrato apontado no instantaneo (extrato dados/complementares/proxies_extrato.csv,
     gravado por proxies_extrato.py);
  2. le o registro da API do acervo no cache (.cache/sourcify_api.sqlite, publicado a parte, so leitura) e confere
     que o keccak256 do codigo da cadeia guardado nele e o resumo_codigo da certidao;
  3. da nome a cada constante: a instrucao PUSH32 ou PUSH20 de cada regiao (em inicio - 1) e levada ao mapa de
     fonte (sourceMap) do codigo de execucao recompilado pelo acervo, e o trecho apontado da o identificador lido ou a
     declaracao;
  4. percorre o codigo-fonte verificado (comentarios removidos, linhas preservadas) atras de toda chamada
     delegatecall (Solidity e assembly), extrai o destino, resolve uma atribuicao local e decide se ele e a variavel
     imutavel nao atestada; registra a funcao que contem a chamada (fallback, construtor etc.);
  5. no codigo de execucao (fora dos blocos de metadados), localiza toda instrucao DELEGATECALL e CALLCODE, leva cada
     uma ao codigo-fonte pelo mapa de fonte e a classifica: delegatecall escrito no fonte (com o destino do passo 4),
     chamada a funcao de biblioteca vinculada apos a compilacao (endereco em regiao nao atestada) ou chamada a
     biblioteca vinculada na compilacao (settings.libraries, endereco no codigo confrontado);
  6. para a constante de biblioteca, segue o fluxo a partir de cada regiao (PUSH20 do endereco) ate o DELEGATECALL,
     atravessando o JUMPI da conferencia de EXTCODESIZE.

Decisao: e "proxy cuja implementacao e o endereco nao atestado" o contrato cujo fallback faz DELEGATECALL para o
valor de uma variavel imutavel do tipo address nao atestada. A delegacao por chamada a biblioteca vinculada apos a
compilacao e relatada a parte, porque nao e proxy. A leitura do codigo-fonte de cada positivo esta em
LEITURA_DO_CODIGO; o programa para com erro se a decisao automatica divergir dela ou se sobrar DELEGATECALL sem
explicacao.

Le dados/certidoes/*.json, .cache/sourcify_api.sqlite e dados/complementares/proxies_extrato.csv. Grava
saidas/complementares/proxies_delegacao_positivos.json, saidas/complementares/proxies_delegacao_resumo.json e
saidas/complementares/proxies_delegacao_constantes.csv. Nao acessa a rede.

Uso: python analise/complementares/proxies_delegacao.py"""
import csv
import glob
import json
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from Crypto.Hash import keccak

RAIZ = Path(__file__).resolve().parents[2]
CERTIDOES = RAIZ / "dados" / "certidoes"
CACHE_API = RAIZ / ".cache" / "sourcify_api.sqlite"
EXTRATO = RAIZ / "dados" / "complementares" / "proxies_extrato.csv"
SAIDA = RAIZ / "saidas" / "complementares"

OP_DELEGATECALL, OP_CALLCODE, OP_JUMP, OP_JUMPI, OP_JUMPDEST = 0xF4, 0xF2, 0x56, 0x57, 0x5B
PARADAS = {0x00, 0xF3, 0xFD, 0xFE, 0xFF}  # STOP, RETURN, REVERT, INVALID, SELFDESTRUCT

# Leitura do codigo-fonte verificado de cada positivo (mesmo cache). O programa confere que a decisao automatica e
# esta: "proxy" (fallback delega toda chamada ao endereco nao atestado), "biblioteca" (funcoes publicas da biblioteca
# vinculada apos a compilacao, chamadas por DELEGATECALL) ou "nao".
LEITURA_DO_CODIGO = {
    "0xc420b590f4d06c74afbd7f30a9c0b67bca6aeffe": ("proxy", "Proxy da Argent: o fallback copia a chamada e faz delegatecall para a imutavel implementation; o receive so emite evento."),
    "0x2d90afaeea73aa6a3313f191349ce4a9b86c7996": ("proxy", "InitializedProxy: o fallback faz delegatecall para a imutavel logic; o construtor tambem delega a inicializacao ao mesmo endereco; o receive e vazio."),
    "0x32dafdb716dcd5dd799369a62d9d660ca6bc855f": ("proxy", "NonReceivableInitializedProxy: o fallback faz delegatecall para a imutavel logic; o construtor delega a inicializacao ao mesmo endereco; nao ha receive."),
    "0x56ab918a1b58fbfd8ab3d0fd85970195ab714628": ("biblioteca", "SmartWallet: as quatro funcoes que alteram estado chamam funcoes publicas de SmartWalletLib, que o compilador executa por DELEGATECALL no endereco vinculado apos a compilacao; nao ha fallback que delegue."),
    "0xb677fa3dd5c2c0472f7520b48aa3f642f9c4af11": ("nao", "KaliDAOcrowdsale: o unico delegatecall e o do multicall, para address(this)."),
    "0x2305027c7d83b33b34ec217d22ffc240d39c59cc": ("nao", "NttManager e implementacao (usada atras de proxy ERC-1967); os DELEGATECALL do codigo sao chamadas a biblioteca TransceiverStructs, cujo endereco foi fixado na compilacao (settings.libraries) e esta no codigo confrontado; nenhum vai para as imutaveis token, deployer e _this."),
    "0x17314f8499b68f6eba37a7b951aa7f2b14d2f625": ("nao", "UsdcFactory: functionDelegateCall da OpenZeppelin esta no codigo-fonte, mas nao e chamada; nao ha DELEGATECALL no codigo."),
    "0xae0f58c408514e60cc6d844cc80965aeab4bf6ff": ("nao", "Curve3poolStrategy: functionDelegateCall da OpenZeppelin esta no codigo-fonte, mas nao e chamada; nao ha DELEGATECALL no codigo."),
    "0x05c35038bd55afacb4bfdf36754f75f723851afd": ("nao", "AiGodfatherProtocol: nenhum delegatecall."),
    "0x40f1cb91325dd8ef24dfac085c9ba46ea309e5e2": ("nao", "NoProtocolFeeLiquidityBootstrappingPool: nenhum delegatecall."),
    "0x4ae304be5b0f211f69cc97dfb6913d6d13f45418": ("nao", "COIN996: nenhum delegatecall."),
    "0x7a4523a9349a99ac16d1484728e82eab6eda027f": ("nao", "UserWallet: nenhum delegatecall; a imutavel factory so controla acesso (onlyFactory)."),
    "0x95ec567b7bc3e5aa7c581b44dc3028fa417c297f": ("nao", "LogProver: nenhum delegatecall."),
}


def k256(b):
    h = keccak.new(digest_bits=256)
    h.update(b)
    return "0x" + h.hexdigest()


def abrir_cache():
    # mode=ro e immutable=1: so leitura, sem trava e sem abrir ou criar os arquivos -wal e -shm
    return sqlite3.connect("file:" + CACHE_API.as_posix() + "?mode=ro&immutable=1", uri=True)


def ler_extrato():
    """Linhas da tabela vigente_endereco do instantaneo gravadas por proxies_extrato.py, por endereco; campos vazios
    (None) quando o endereco nao tem verificacao vigente."""
    with open(EXTRATO, encoding="utf-8", newline="") as f:
        return {r["address"]: {k: (v or None) for k, v in r.items()} for r in csv.DictReader(f)}


def registro_api(con, endereco):
    linha = con.execute("SELECT v FROM kv WHERE k = ?", ("1:" + endereco,)).fetchone()
    return None if linha is None else json.loads(linha[0])


def desmontar(codigo):
    """Varredura linear: lista de (pc, opcode, dado do PUSH)."""
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


def descomprimir_mapa(mapa):
    """sourceMap do solc (s:l:f:j:m, campos vazios herdam o anterior) -> lista de (s, l, f)."""
    saida, s, l, f = [], 0, 0, -1
    for item in mapa.split(";"):
        campos = item.split(":")
        if len(campos) > 0 and campos[0] != "":
            s = int(campos[0])
        if len(campos) > 1 and campos[1] != "":
            l = int(campos[1])
        if len(campos) > 2 and campos[2] != "":
            f = int(campos[2])
        saida.append((s, l, f))
    return saida


def sem_comentarios(texto):
    """Troca comentarios por espacos, preservando quebras de linha e o conteudo de cadeias de caracteres."""
    out, i, n = [], 0, len(texto)
    estado = None
    while i < n:
        c = texto[i]
        d = texto[i + 1] if i + 1 < n else ""
        if estado is None:
            if c == "/" and d == "/":
                estado = "linha"
                out.append("  ")
                i += 2
                continue
            if c == "/" and d == "*":
                estado = "bloco"
                out.append("  ")
                i += 2
                continue
            if c in ("'", '"'):
                estado = c
            out.append(c)
            i += 1
            continue
        if estado == "linha":
            if c == "\n":
                estado = None
                out.append("\n")
            else:
                out.append(" ")
            i += 1
            continue
        if estado == "bloco":
            if c == "*" and d == "/":
                estado = None
                out.append("  ")
                i += 2
                continue
            out.append("\n" if c == "\n" else " ")
            i += 1
            continue
        if c == "\\":
            out.append(texto[i:i + 2])
            i += 2
            continue
        if c == estado:
            estado = None
        out.append(c)
        i += 1
    return "".join(out)


def trecho(linhas, ini, fim):
    """Ate 3 linhas (numeradas a partir de 1), sem espacos nas pontas."""
    fim = min(fim, ini + 2)
    return "\n".join(linhas[k - 1].strip() for k in range(ini, fim + 1))


def args_de_chamada(texto, pos_abre):
    """Argumentos de nivel superior a partir do '(' em pos_abre."""
    nivel, atual, args, i = 0, [], [], pos_abre
    while i < len(texto):
        c = texto[i]
        if c == "(":
            nivel += 1
            if nivel > 1:
                atual.append(c)
        elif c == ")":
            nivel -= 1
            if nivel == 0:
                args.append("".join(atual).strip())
                return args
            atual.append(c)
        elif c == "," and nivel == 1:
            args.append("".join(atual).strip())
            atual = []
        else:
            atual.append(c)
        i += 1
    return args


CABECALHO = re.compile(r"^\s*(function\s+\w+|function\s*\(|fallback\s*\(|receive\s*\(|constructor\s*\(|modifier\s+\w+)")


def funcao_que_contem(linhas_sc, num):
    for k in range(num, 0, -1):
        m = CABECALHO.match(linhas_sc[k - 1])
        if m:
            cab = m.group(1)
            tipo = ("fallback" if cab.startswith("fallback") or re.match(r"function\s*\(", cab) else
                    "receive" if cab.startswith("receive") else
                    "construtor" if cab.startswith("constructor") else
                    "modificador" if cab.startswith("modifier") else "funcao")
            return {"linha": k, "cabecalho": linhas_sc[k - 1].strip()[:120], "tipo": tipo}
    return {"linha": None, "cabecalho": None, "tipo": "desconhecido"}


def resolver_local(linhas_sc, num, alvo):
    """Atribuicao local mais proxima (ate 40 linhas acima) do identificador alvo: 'address alvo = E;' ou 'alvo := E'."""
    if not re.fullmatch(r"[A-Za-z_]\w*", alvo or ""):
        return None
    pad = re.compile(r"(?:\baddress(?:\s+payable)?\s+|\blet\s+)?\b" + re.escape(alvo) + r"\s*(?::=|=(?!=))\s*([^;{}]+)")
    for k in range(num, max(0, num - 40), -1):
        m = pad.search(linhas_sc[k - 1])
        if m and not re.search(r"delegatecall", linhas_sc[k - 1][:m.start()]):
            return {"linha": k, "expressao": m.group(1).strip()}
    return None


def seguir_ate_delegatecall(instr, idx_pc, i0, limite=80):
    """A partir da instrucao i0, segue o fluxo: em JUMP ou JUMPI precedido de PUSH, vai ao destino (no JUMPI, o ramo
    tomado e o da conferencia de EXTCODESIZE bem-sucedida). Devolve o pc do DELEGATECALL alcancado ou None."""
    i, passos, caminho = i0, 0, []
    while i is not None and i < len(instr) and passos < limite:
        pc, op, _ = instr[i]
        if op == OP_DELEGATECALL:
            return pc, caminho
        if op in PARADAS:
            return None, caminho
        if op in (OP_JUMP, OP_JUMPI) and i > 0 and 0x60 <= instr[i - 1][1] <= 0x7F:
            destino = int.from_bytes(instr[i - 1][2], "big")
            j = idx_pc.get(destino)
            if j is None or instr[j][1] != OP_JUMPDEST:
                return None, caminho
            caminho.append({"salto_em": pc, "para": destino})
            i = j
        else:
            i += 1
        passos += 1
    return None, caminho


def main():
    for p in (CERTIDOES, CACHE_API, EXTRATO):
        if not p.exists():
            sys.exit(f"entrada ausente: {p.relative_to(RAIZ).as_posix()}")
    con_api = abrir_cache()
    extrato = ler_extrato()

    def nome_no_instantaneo(endereco):
        if endereco not in extrato:
            sys.exit(f"endereco fora do extrato: {endereco} (rode analise/complementares/proxies_extrato.py)")
        return extrato[endereco]["fully_qualified_name"]

    positivos = []
    for p in sorted(glob.glob(str(CERTIDOES / "*.json"))):
        c = json.load(open(p, encoding="utf-8"))
        if c.get("indicador_equacao_2") == 1:
            positivos.append(c)
    assert len(positivos) == 13, len(positivos)

    contratos, linhas_csv = [], []
    for cert in positivos:
        end = cert["contrato"]["endereco"].lower()
        reg = registro_api(con_api, end)
        assert reg is not None, end
        rt = reg["runtimeBytecode"]
        codigo = bytes.fromhex(rt["onchainBytecode"][2:])
        conf_codigo = {"keccak_onchainBytecode_do_cache": k256(codigo),
                       "resumo_codigo_da_certidao": cert["contrato"]["resumo_codigo"],
                       "iguais": k256(codigo) == cert["contrato"]["resumo_codigo"],
                       "matchId_cache": str(reg.get("matchId")), "match_id_certidao": str(cert["acervo"].get("match_id"))}
        assert conf_codigo["iguais"], end

        fontes = {fn: s["content"] for fn, s in reg["sources"].items()}
        fontes_b = {fn: t.encode("utf-8") for fn, t in fontes.items()}
        id_para_arquivo = {v["id"]: fn for fn, v in (reg.get("sourceIds") or {}).items()}
        linhas = {fn: t.splitlines() for fn, t in fontes.items()}
        linhas_sc = {fn: sem_comentarios(t).splitlines() for fn, t in fontes.items()}

        instr = desmontar(codigo)
        idx_pc = {pc: i for i, (pc, _, _) in enumerate(instr)}
        regioes = [(r["inicio"], r["inicio"] + r["comprimento"]) for r in cert["regioes"]]
        meta = [(r["inicio"], r["inicio"] + r["comprimento"]) for r in cert["regioes"] if r["motivo"] == "cborAuxdata"]

        def em(pc, faixas):
            return any(a <= pc < b for a, b in faixas)

        mapa = descomprimir_mapa(rt.get("sourceMap") or "")

        def fonte_da_instrucao(i):
            if i is None or i >= len(mapa):
                return None
            s, l, f = mapa[i]
            fn = id_para_arquivo.get(f)
            if fn is None:
                return None
            b = fontes_b[fn]
            return {"arquivo": fn, "linha": b[:s].count(b"\n") + 1,
                    "texto": " ".join(b[s:s + l].decode("utf-8", "replace").split())[:200]}

        # constantes do tipo address, com nome pelo mapa de fonte
        consts = []
        for k in cert["constantes"]:
            if not k.get("tau_address"):
                continue
            regs = sorted((r for r in cert["regioes"] if r["construto"] == k["construto"]), key=lambda r: r["inicio"])
            leituras = []
            for r in regs:
                i = idx_pc.get(r["inicio"] - 1)
                op = instr[i][1] if i is not None else None
                item = {"inicio": r["inicio"], "instrucao": (f"PUSH{op - 0x5F}" if op and 0x60 <= op <= 0x7F else None)}
                fi = fonte_da_instrucao(i)
                if fi:
                    item.update(fi)
                if k["motivo"] == "library" and i is not None:
                    pc_dc, caminho = seguir_ate_delegatecall(instr, idx_pc, i)
                    item["delegatecall_alcancado"] = pc_dc
                    item["saltos_ate_o_delegatecall"] = caminho
                leituras.append(item)
            nomes = Counter()
            for it in leituras:
                t = it.get("texto") or ""
                if re.fullmatch(r"[A-Za-z_]\w*", t):
                    nomes[t] += 1
                else:
                    m = re.search(r"\bimmutable\b.*?\b([A-Za-z_]\w*)\s*(?:=|;|$)", t)
                    if m:
                        nomes[m.group(1)] += 1
            nome = nomes.most_common(1)[0][0] if nomes else None
            if k["motivo"] == "library":
                nome = k["construto"].split(":")[-1]
            decl = []
            if nome and k["motivo"] == "immutable":
                pad = re.compile(r"\bimmutable\b[^;]*\b" + re.escape(nome) + r"\b\s*(?:=|;)")
                for fn, ls in linhas_sc.items():
                    for num, l in enumerate(ls, 1):
                        if pad.search(l):
                            decl.append({"arquivo": fn, "linha": num, "trecho": linhas[fn][num - 1].strip()})
            elif nome and k["motivo"] == "library":
                for fn, ls in linhas_sc.items():
                    for num, l in enumerate(ls, 1):
                        if re.search(r"^\s*library\s+" + re.escape(nome) + r"\b", l):
                            decl.append({"arquivo": fn, "linha": num, "trecho": linhas[fn][num - 1].strip()})
            for v in k["valores"]:
                a = (k.get("alvos") or {}).get(v) or {}
                consts.append({"construto": k["construto"], "motivo": k["motivo"], "tipo": k["tipo"], "nome": nome,
                               "declaracao": decl, "valor": v, "classe_do_alvo": a.get("classe"),
                               "substituivel_erc1967": a.get("substituivel"), "tamanho_codigo_alvo": a.get("tamanho_codigo"),
                               "nome_do_alvo_no_instantaneo": nome_no_instantaneo(v) if a.get("tamanho_codigo") else None,
                               "regioes": leituras})

        nomes_imut = {c_["nome"] for c_ in consts if c_["motivo"] == "immutable" and c_["nome"]}

        # chamadas delegatecall escritas no codigo-fonte
        ocorr = []
        for fn, ls in linhas_sc.items():
            texto_sc = "\n".join(ls)
            for m in re.finditer(r"\bdelegatecall\b", texto_sc):
                num = texto_sc.count("\n", 0, m.start()) + 1
                antes = texto_sc[:m.start()]
                if antes.rstrip().endswith("."):
                    forma = "solidity"
                    rec = re.search(r"([A-Za-z_][\w\.]*(?:\([^()]*\))?)\s*\.\s*$", antes)
                    alvo = rec.group(1) if rec else None
                else:
                    forma = "assembly"
                    pos = texto_sc.find("(", m.end())
                    args = args_de_chamada(texto_sc, pos) if pos >= 0 else []
                    alvo = args[1] if len(args) > 1 else None
                fun = funcao_que_contem(ls, num)
                res = resolver_local(ls, num, alvo)
                expr_final = res["expressao"] if res else alvo
                if expr_final in nomes_imut or alvo in nomes_imut:
                    destino = "imutavel_nao_atestada:" + (expr_final if expr_final in nomes_imut else alvo)
                elif (expr_final or "").replace(" ", "") == "address(this)":
                    destino = "proprio_contrato"
                else:
                    destino = "outro: " + str(expr_final)
                evid_o = []
                if res:
                    evid_o.append({"arquivo": fn, "linhas": [res["linha"], res["linha"]],
                                   "trecho": trecho(linhas[fn], res["linha"], res["linha"]),
                                   "papel": f"atribuicao local de {alvo}"})
                evid_o.append({"arquivo": fn, "linhas": [num, num], "trecho": trecho(linhas[fn], num, num),
                               "papel": "chamada delegatecall"})
                ocorr.append({"arquivo": fn, "linha": num, "forma": forma, "alvo": alvo, "atribuicao_local": res,
                              "destino": destino, "funcao": fun, "evidencia": evid_o})

        # funcoes auxiliares que fazem delegatecall (chamadas fora da propria definicao)
        aux = []
        for fn, ls in linhas_sc.items():
            for num, l in enumerate(ls, 1):
                for nome_aux in ("functionDelegateCall", "_delegate"):
                    if re.search(r"\b" + nome_aux + r"\s*\(", l) and not re.search(r"\bfunction\s+" + nome_aux + r"\b", l):
                        aux.append({"auxiliar": nome_aux, "arquivo": fn, "linha": num, "trecho": linhas[fn][num - 1].strip(),
                                    "funcao": funcao_que_contem(ls, num)})

        # biblioteca vinculada apos a compilacao (constante de biblioteca): funcoes publicas e chamadas a elas
        bib = []
        for c_ in consts:
            if c_["motivo"] != "library":
                continue
            nome_bib = c_["nome"]
            for fn, ls in linhas_sc.items():
                texto_sc = "\n".join(ls)
                mb = re.search(r"\blibrary\s+" + re.escape(nome_bib) + r"\b", texto_sc)
                if not mb:
                    continue
                i, nivel = texto_sc.find("{", mb.end()), 0
                ini = i
                while i < len(texto_sc):
                    if texto_sc[i] == "{":
                        nivel += 1
                    elif texto_sc[i] == "}":
                        nivel -= 1
                        if nivel == 0:
                            break
                    i += 1
                corpo = texto_sc[ini:i]
                publicas = []
                for mf in re.finditer(r"\bfunction\s+(\w+)\s*\(([^)]*)\)([^{;]*)", corpo):
                    if re.search(r"\b(public|external)\b", mf.group(3)):
                        publicas.append({"funcao": mf.group(1), "linha": texto_sc.count("\n", 0, ini + mf.start()) + 1})
                nomes_pub = {x["funcao"] for x in publicas}
                l_ini, l_fim = texto_sc.count("\n", 0, mb.start()) + 1, texto_sc.count("\n", 0, i) + 1
                chamadas = []
                for num, l in enumerate(ls, 1):
                    if l_ini <= num <= l_fim:
                        continue
                    for mc in re.finditer(r"\.\s*(\w+)\s*\(", l):
                        if mc.group(1) in nomes_pub:
                            chamadas.append({"arquivo": fn, "linha": num, "funcao_chamada": mc.group(1),
                                             "trecho": linhas[fn][num - 1].strip(), "funcao": funcao_que_contem(ls, num)})
                bib.append({"biblioteca": nome_bib, "arquivo": fn, "linha_declaracao": l_ini,
                            "funcoes_publicas_ou_externas": publicas, "chamadas_no_contrato": chamadas})
        pub_bib_pos = {f_["funcao"]: b["biblioteca"] for b in bib for f_ in b["funcoes_publicas_ou_externas"]}

        # bibliotecas vinculadas na compilacao (settings.libraries): PUSH20 do endereco no codigo e nas regioes de F(a)
        libs_cfg = (reg.get("compilation") or {}).get("compilerSettings", {}).get("libraries") or {}
        pre = []
        for arq_lib, d in libs_cfg.items():
            for nome_lib, addr in (d or {}).items():
                ab = bytes.fromhex(addr.lower()[2:])
                pushes = [pc for pc, op, dado in instr if op == 0x73 and dado == ab]
                pre.append({"arquivo": arq_lib, "biblioteca": nome_lib, "endereco": addr.lower(),
                            "PUSH20_no_codigo": len(pushes),
                            "PUSH20_em_regiao_nao_atestada": sum(em(pc + 1, regioes) for pc in pushes)})
        nomes_pre = {p_["biblioteca"] for p_ in pre}

        # cada instrucao DELEGATECALL ou CALLCODE do codigo de execucao, levada ao codigo-fonte
        dcs = []
        for i, (pc, op, _) in enumerate(instr):
            if op not in (OP_DELEGATECALL, OP_CALLCODE) or em(pc, meta):
                continue
            fi = fonte_da_instrucao(i) or {}
            txt = fi.get("texto") or ""
            classe, destino, funcao = "nao_explicada", None, None
            if "delegatecall" in txt:
                o = next((o for o in ocorr if o["arquivo"] == fi.get("arquivo") and o["linha"] == fi.get("linha")), None)
                if o is not None:
                    classe, destino, funcao = "delegatecall_escrito_no_fonte", o["destino"], o["funcao"]["tipo"]
            else:
                mc = re.match(r"^([A-Za-z_]\w*)\s*\.\s*(\w+)\s*\(", txt)
                if mc and mc.group(1) in nomes_pre:
                    classe, destino = "biblioteca_vinculada_na_compilacao", mc.group(1)
                elif mc and mc.group(2) in pub_bib_pos:
                    classe, destino = "biblioteca_vinculada_apos_compilacao", pub_bib_pos[mc.group(2)]
            if fi.get("arquivo"):
                funcao = funcao or funcao_que_contem(linhas_sc[fi["arquivo"]], fi["linha"])["tipo"]
            dcs.append({"pc": pc, "instrucao": "DELEGATECALL" if op == OP_DELEGATECALL else "CALLCODE", **fi,
                        "classe": classe, "destino": destino, "funcao": funcao})
        nao_explicadas = [d for d in dcs if d["classe"] == "nao_explicada"]
        if nao_explicadas:
            sys.exit(f"DELEGATECALL sem explicacao em {end}: {nao_explicadas}")

        # decisao automatica
        para_imut = [o for o in ocorr if o["destino"].startswith("imutavel_nao_atestada") and o["funcao"]["tipo"] != "construtor"]
        proxy = any(d["classe"] == "delegatecall_escrito_no_fonte" and (d["destino"] or "").startswith("imutavel_nao_atestada")
                    and d["funcao"] == "fallback" for d in dcs)
        regs_bib = [r for c_ in consts if c_["motivo"] == "library" for r in c_["regioes"]]
        biblioteca = (any(d["classe"] == "biblioteca_vinculada_apos_compilacao" for d in dcs)
                      and bool(regs_bib) and all(r.get("delegatecall_alcancado") is not None for r in regs_bib))
        decisao = "proxy" if proxy else "biblioteca" if biblioteca else (
            "delegacao_parcial_para_imutavel" if para_imut else "nao")
        lida, nota = LEITURA_DO_CODIGO[end]
        if decisao != lida:
            sys.exit(f"decisao automatica diverge da leitura do codigo em {end}: {decisao} x {lida}")

        # evidencias (arquivo, linhas, trecho de ate 3 linhas)
        evid = []
        if decisao == "proxy":
            for c_ in consts:
                for d in c_["declaracao"]:
                    evid.append({"o_que": "declaracao da imutavel", "arquivo": d["arquivo"], "linhas": [d["linha"], d["linha"]],
                                 "trecho": d["trecho"]})
            for o in para_imut:
                evid.append({"o_que": "cabecalho da funcao que contem o delegatecall", "arquivo": o["arquivo"],
                             "linhas": [o["funcao"]["linha"], o["funcao"]["linha"]],
                             "trecho": linhas[o["arquivo"]][o["funcao"]["linha"] - 1].strip()})
                for e in o["evidencia"]:
                    evid.append({"o_que": f"{e['papel']} na funcao {o['funcao']['tipo']}",
                                 **{k: v for k, v in e.items() if k != "papel"}})
            for o in ocorr:
                if o["funcao"]["tipo"] == "construtor":
                    for e in o["evidencia"]:
                        evid.append({"o_que": f"{e['papel']} no construtor (codigo de criacao, executado uma vez)",
                                     **{k: v for k, v in e.items() if k != "papel"}})
        elif decisao == "biblioteca":
            for b in bib:
                evid.append({"o_que": "declaracao da biblioteca", "arquivo": b["arquivo"],
                             "linhas": [b["linha_declaracao"], b["linha_declaracao"]],
                             "trecho": linhas[b["arquivo"]][b["linha_declaracao"] - 1].strip()})
                for f_ in b["funcoes_publicas_ou_externas"][1:2]:
                    evid.append({"o_que": "funcao publica da biblioteca (chamada por DELEGATECALL)", "arquivo": b["arquivo"],
                                 "linhas": [f_["linha"], f_["linha"] + 1],
                                 "trecho": trecho(linhas[b["arquivo"]], f_["linha"], f_["linha"] + 1)})
                for ch in b["chamadas_no_contrato"]:
                    evid.append({"o_que": f"chamada a funcao da biblioteca ({ch['funcao']['tipo']}: {ch['funcao']['cabecalho']})",
                                 "arquivo": ch["arquivo"], "linhas": [ch["linha"], ch["linha"]], "trecho": ch["trecho"]})
        else:
            for o in ocorr:
                for e in o["evidencia"]:
                    evid.append({"o_que": f"{e['papel']} com destino {o['destino']} ({o['funcao']['tipo']}: "
                                          f"{o['funcao']['cabecalho']})",
                                 **{k: v for k, v in e.items() if k != "papel"}})
            for a_ in aux:
                evid.append({"o_que": f"chamada a {a_['auxiliar']} ({a_['funcao']['tipo']}: {a_['funcao']['cabecalho']})",
                             "arquivo": a_["arquivo"], "linhas": [a_["linha"], a_["linha"]], "trecho": a_["trecho"]})
            for d in dcs:
                if d["classe"] == "biblioteca_vinculada_na_compilacao":
                    evid.append({"o_que": f"instrucao DELEGATECALL em {d['pc']}: chamada a biblioteca {d['destino']} "
                                          f"vinculada na compilacao", "arquivo": d["arquivo"],
                                 "linhas": [d["linha"], d["linha"]], "trecho": trecho(linhas[d["arquivo"]], d["linha"], d["linha"])})

        imp = [c_ for c_ in consts if decisao == "proxy" and c_["nome"] and
               any(o["destino"] == "imutavel_nao_atestada:" + c_["nome"] for o in para_imut)]
        contrato = {
            "endereco": end, "contrato_compilado": cert["acervo"]["contrato_compilado"],
            "grau": cert["acervo"]["grau_instantaneo"], "compilador": cert["acervo"]["compilador"],
            "conferencia_do_codigo": conf_codigo,
            "proxyResolution_do_acervo": reg.get("proxyResolution"),
            "constantes_address": consts,
            "delegatecall_no_codigo_fonte": ocorr,
            "auxiliares_de_delegatecall_chamados": aux,
            "biblioteca_vinculada_apos_compilacao": bib,
            "bibliotecas_vinculadas_na_compilacao": pre,
            "codigo_de_execucao": {"tamanho": len(codigo),
                                   "instrucoes_DELEGATECALL_fora_dos_metadados": sum(d["instrucao"] == "DELEGATECALL" for d in dcs),
                                   "instrucoes_CALLCODE_fora_dos_metadados": sum(d["instrucao"] == "CALLCODE" for d in dcs),
                                   "por_classe": dict(Counter(d["classe"] for d in dcs)),
                                   "instrucoes": dcs},
            "decisao": decisao,
            "proxy_cuja_implementacao_e_o_endereco_nao_atestado": decisao == "proxy",
            "implementacao": [{"nome": c_["nome"], "valor": c_["valor"], "classe": c_["classe_do_alvo"],
                               "nome_no_instantaneo": c_["nome_do_alvo_no_instantaneo"]} for c_ in imp],
            "leitura_do_codigo": nota,
            "evidencias": evid,
        }
        contratos.append(contrato)
        for c_ in consts:
            linhas_csv.append([end, cert["acervo"]["contrato_compilado"], c_["construto"], c_["motivo"], c_["tipo"],
                               c_["nome"], c_["valor"], c_["classe_do_alvo"], c_["substituivel_erc1967"],
                               c_["tamanho_codigo_alvo"], c_["nome_do_alvo_no_instantaneo"], decisao,
                               "sim" if any(c_["valor"] == x["valor"] for x in contrato["implementacao"]) else "nao"])

    proxies = [c for c in contratos if c["decisao"] == "proxy"]
    bibs = [c for c in contratos if c["decisao"] == "biblioteca"]
    todas = [d for c in contratos for d in c["codigo_de_execucao"]["instrucoes"]]
    resumo = {
        "gerado_em_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "positivos": len(contratos),
        "constantes_address": sum(len({x["construto"] for x in c["constantes_address"]}) for c in contratos),
        "valores_address": sum(len(c["constantes_address"]) for c in contratos),
        "codigo_do_cache_igual_ao_da_certidao": sum(c["conferencia_do_codigo"]["iguais"] for c in contratos),
        "proxies_cuja_implementacao_e_o_endereco_nao_atestado": len(proxies),
        "proxies": [{"endereco": c["endereco"], "contrato": c["contrato_compilado"], "grau": c["grau"],
                     "implementacao": c["implementacao"]} for c in proxies],
        "proxies_com_implementacao_verificada_no_acervo": sum(
            all(i["classe"] == "contrato_verificado_no_acervo" for i in c["implementacao"]) for c in proxies),
        "proxies_por_grau": dict(Counter(c["grau"] for c in proxies)),
        "delegacao_por_biblioteca_vinculada_apos_compilacao": len(bibs),
        "contratos_delegacao_por_biblioteca": [
            {"endereco": c["endereco"], "contrato": c["contrato_compilado"],
             "biblioteca": [b["biblioteca"] for b in c["biblioteca_vinculada_apos_compilacao"]],
             "valor": [x["valor"] for x in c["constantes_address"] if x["motivo"] == "library"],
             "chamadas_em_funcoes": sum(ch["funcao"]["tipo"] != "construtor" for b in c["biblioteca_vinculada_apos_compilacao"]
                                        for ch in b["chamadas_no_contrato"]),
             "chamadas_no_construtor": sum(ch["funcao"]["tipo"] == "construtor" for b in c["biblioteca_vinculada_apos_compilacao"]
                                           for ch in b["chamadas_no_contrato"]),
             "regioes_que_alcancam_DELEGATECALL": sum(r.get("delegatecall_alcancado") is not None
                                                      for x in c["constantes_address"] if x["motivo"] == "library"
                                                      for r in x["regioes"]),
             "regioes": sum(len(x["regioes"]) for x in c["constantes_address"] if x["motivo"] == "library")}
            for c in bibs],
        "positivos_que_delegam_ao_endereco_nao_atestado": len(proxies) + len(bibs),
        "positivos_sem_delegacao_ao_endereco_nao_atestado": sum(c["decisao"] == "nao" for c in contratos),
        "positivos_sem_instrucao_DELEGATECALL_no_codigo": sum(
            c["codigo_de_execucao"]["instrucoes_DELEGATECALL_fora_dos_metadados"] == 0 for c in contratos),
        "instrucoes_DELEGATECALL_nos_13": sum(d["instrucao"] == "DELEGATECALL" for d in todas),
        "instrucoes_CALLCODE_nos_13": sum(d["instrucao"] == "CALLCODE" for d in todas),
        "instrucoes_por_classe_e_destino": dict(Counter(f"{d['classe']}|{d['destino']}|{d['funcao']}" for d in todas)),
        "DELEGATECALL_por_contrato": {c["endereco"]: c["codigo_de_execucao"]["instrucoes_DELEGATECALL_fora_dos_metadados"]
                                      for c in contratos},
        "bibliotecas_vinculadas_na_compilacao": {c["endereco"]: c["bibliotecas_vinculadas_na_compilacao"]
                                                 for c in contratos if c["bibliotecas_vinculadas_na_compilacao"]},
        "positivos_marcados_como_proxy_pelo_acervo": sum(bool((c["proxyResolution_do_acervo"] or {}).get("isProxy"))
                                                         for c in contratos),
        "decisoes": {c["endereco"]: c["decisao"] for c in contratos},
    }
    SAIDA.mkdir(parents=True, exist_ok=True)
    json.dump(contratos, open(SAIDA / "proxies_delegacao_positivos.json", "w", encoding="utf-8"), indent=1,
              ensure_ascii=False)
    json.dump(resumo, open(SAIDA / "proxies_delegacao_resumo.json", "w", encoding="utf-8"), indent=1,
              ensure_ascii=False)
    with open(SAIDA / "proxies_delegacao_constantes.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["endereco", "contrato", "construto", "motivo", "tipo", "nome", "valor", "classe_do_alvo",
                    "substituivel_erc1967", "tamanho_codigo_alvo", "nome_do_alvo_no_instantaneo", "decisao_do_contrato",
                    "valor_e_implementacao_delegada"])
        w.writerows(linhas_csv)
    print(json.dumps({k: v for k, v in resumo.items() if k not in ("decisoes", "bibliotecas_vinculadas_na_compilacao")},
                     indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
