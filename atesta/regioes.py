# -*- coding: utf-8 -*-
"""Delimitacao das regioes nao atestadas F(a) (subsecao 3.4 do artigo).

Uma regiao pertence a F(a) quando o confronto entre o codigo de execucao lido da cadeia (c_a) e o recompilado
registra nela transformacao de substituicao ou insercao:
- variavel imutavel: posicoes de evm.deployedBytecode.immutableReferences (id da declaracao na AST);
- endereco de biblioteca vinculada apos a compilacao: posicoes de evm.deployedBytecode.linkReferences (marcadores
  que sobraram na saida, isto e, bibliotecas nao informadas ao compilador);
- protecao de chamada: 20 bytes apos o PUSH20 inicial das bibliotecas (pipeline tradicional) ou a entrada
  library_deploy_address das posicoes de imutaveis (viaIR);
- blocos de metadados (CBOR): posicoes registradas pelo acervo entre os artefatos do codigo de execucao; entram
  todos, e so quando o recompilado precisa recebe-los da cadeia para coincidir com c_a (como o Sourcify registra).
Substituidos nessas posicoes os bytes lidos da cadeia, o recompilado tem de coincidir byte a byte com c_a; do
contrario, a falha e do instrumento."""
from dataclasses import dataclass, field, asdict

ZERO20 = b"\x00" * 20


class FalhaInstrumento(Exception):
    pass


@dataclass
class Regiao:
    inicio: int
    comprimento: int
    motivo: str          # immutable | library | callProtection | cborAuxdata
    construto: str
    valor: str = ""      # hex dos bytes lidos da cadeia
    tipo: str = ""       # tipo declarado (imutaveis) ou 'address' / 'metadados'
    tau_address: bool = False


@dataclass
class Constante:
    construto: str
    motivo: str
    tipo: str
    tau_address: bool
    regioes: int
    valores: list = field(default_factory=list)   # enderecos (20 bytes) se tau_address; senao, hex da palavra
    valores_distintos: int = 0


# ------------------------------------------------------------------------------------------------ AST e tipos
def indice_ast(asts):
    ind = {}

    def andar(no):
        if isinstance(no, dict):
            if "id" in no and ("nodeType" in no or "name" in no):
                ind.setdefault(no["id"], no)
            for v in no.values():
                andar(v)
        elif isinstance(no, list):
            for v in no:
                andar(v)

    for ast in (asts or {}).values():
        andar(ast)
    return ind


TIPOS_ENDERECO = ("address", "address payable")


def tipo_e_tau(ind, id_decl):
    """Tipo declarado da variavel imutavel e se ele representa endereco de conta (criterio de 3.4): address,
    address payable, tipo de contrato ou de interface, tipo de valor definido pelo usuario sobre address."""
    no = ind.get(int(id_decl)) if str(id_decl).isdigit() else None
    if no is None or no.get("nodeType") != "VariableDeclaration":
        return ("desconhecido", False)
    ts = (no.get("typeDescriptions") or {}).get("typeString") or ""
    if ts in TIPOS_ENDERECO or ts.startswith("contract "):
        return (ts, True)
    tn = no.get("typeName") or {}
    ref = tn.get("referencedDeclaration")
    if tn.get("nodeType") == "UserDefinedTypeName" and ref is not None:
        alvo = ind.get(ref) or {}
        if alvo.get("nodeType") == "UserDefinedValueTypeDefinition":
            base = ((alvo.get("underlyingType") or {}).get("typeDescriptions") or {}).get("typeString", "")
            return (f"{ts} (sobre {base})", base in TIPOS_ENDERECO)
    return (ts, False)


def tipo_contrato(asts, arquivo, nome):
    ast = (asts or {}).get(arquivo)
    if not ast:
        return None
    for no in ast.get("nodes", []):
        if no.get("nodeType") == "ContractDefinition" and no.get("name") == nome:
            return no.get("contractKind")
    return None


# ------------------------------------------------------------------------------------------------ bytes
def decodificar(objeto_hex, ligacoes):
    """Hex do codigo com marcadores de biblioteca -> bytes, com zeros nos marcadores (posicoes de linkReferences)."""
    h = list(objeto_hex[2:] if objeto_hex.startswith("0x") else objeto_hex)
    for libs in (ligacoes or {}).values():
        for refs in libs.values():
            for ref in refs:
                ini, n = ref["start"], ref["length"]
                h[2 * ini:2 * (ini + n)] = list("00" * n)
    s = "".join(h)
    if "_" in s:
        raise FalhaInstrumento("marcador de biblioteca sem posicao em linkReferences")
    return bytes.fromhex(s)


def primeira_diferenca(a, b):
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return i
    return min(len(a), len(b)) if len(a) != len(b) else None


# ------------------------------------------------------------------------------------------------ delimitacao
def delimitar(c_a, comp, arquivo, nome, cbor_acervo=None, transformacoes_acervo=None):
    """Devolve (regioes, info). c_a: bytes lidos da cadeia; comp: saida de compilador.compilar; cbor_acervo: dict
    id -> {offset, value} das posicoes dos blocos de metadados registradas pelo acervo (codigo de execucao)."""
    R = decodificar(comp["objeto"], comp["ligacoes"])
    ind = indice_ast(comp.get("ast"))
    tipo_ctr = tipo_contrato(comp.get("ast"), arquivo, nome)
    regioes = []
    info = {"tipo_contrato": tipo_ctr, "tamanho_recompilado": len(R), "tamanho_cadeia": len(c_a)}

    for chave, refs in (comp.get("imutaveis") or {}).items():
        if chave == "library_deploy_address":
            for ref in refs:
                regioes.append(Regiao(ref["start"], ref["length"], "callProtection", "protecao_de_chamada:viaIR",
                                      tipo="address", tau_address=True))
            continue
        tipo, tau = tipo_e_tau(ind, chave)
        for ref in refs:
            regioes.append(Regiao(ref["start"], ref["length"], "immutable", f"imutavel:{chave}", tipo=tipo,
                                  tau_address=tau))

    for arq, libs in (comp.get("ligacoes") or {}).items():
        for lib, refs in libs.items():
            for ref in refs:
                regioes.append(Regiao(ref["start"], ref["length"], "library", f"biblioteca:{arq}:{lib}",
                                      tipo="address", tau_address=True))

    via_ir = any(r.construto == "protecao_de_chamada:viaIR" for r in regioes)
    eh_biblioteca = (tipo_ctr == "library") if tipo_ctr else None
    prefixo = len(R) >= 21 and R[0] == 0x73 and R[1:21] == ZERO20
    if prefixo and not via_ir and eh_biblioteca is not False:
        regioes.append(Regiao(1, 20, "callProtection", "protecao_de_chamada", tipo="address", tau_address=True))

    # remocao de bloco de metadados registrada pelo acervo (codigo da cadeia sem o bloco que o recompilado tem)
    removidos = []
    for t in (transformacoes_acervo or []):
        if t.get("type") == "delete" and t.get("reason") == "cborAuxdata":
            bloco = (cbor_acervo or {}).get(str(t.get("id")))
            n = t.get("length") or (len(bytes.fromhex(bloco["value"][2:])) if bloco else None)
            if n:
                removidos.append((t["offset"], n))
    for ini, n in sorted(removidos, reverse=True):
        R = R[:ini] + R[ini + n:]
    info["blocos_removidos"] = len(removidos)

    if len(R) != len(c_a):
        raise FalhaInstrumento(f"comprimentos diferentes: recompilado {len(R)} x cadeia {len(c_a)}")

    R2 = bytearray(R)
    for r in regioes:
        R2[r.inicio:r.inicio + r.comprimento] = c_a[r.inicio:r.inicio + r.comprimento]
    info["metadados_em_F"] = False
    if bytes(R2) != c_a:
        blocos = []
        for bid, b in sorted((cbor_acervo or {}).items(), key=lambda x: x[1]["offset"]):
            blocos.append((b["offset"], len(bytes.fromhex(b["value"][2:])), bid))
        info["posicoes_metadados"] = "acervo" if blocos else "dois_ultimos_bytes"
        if not blocos and len(R) >= 2:
            n = int.from_bytes(R[-2:], "big") + 2
            blocos = [(len(R) - n, n, "ultimo")]
        R3 = bytearray(R2)
        for ini, n, _ in blocos:
            R3[ini:ini + n] = c_a[ini:ini + n]
        if bytes(R3) != c_a:
            d = primeira_diferenca(bytes(R3), c_a)
            raise FalhaInstrumento(f"recompilado difere da cadeia fora das regioes conhecidas (byte {d})")
        for ini, n, bid in blocos:
            regioes.append(Regiao(ini, n, "cborAuxdata", f"metadados:{bid}", tipo="metadados", tau_address=False))
        info["metadados_em_F"] = True

    for r in regioes:
        r.valor = "0x" + c_a[r.inicio:r.inicio + r.comprimento].hex()
    regioes.sort(key=lambda r: r.inicio)
    return regioes, info


def constantes(regioes, endereco):
    """Agrupa as regioes (exceto metadados) por construto; o valor de enderecos e lido nos 20 bytes finais."""
    grupos = {}
    for r in regioes:
        if r.motivo == "cborAuxdata":
            continue
        grupos.setdefault(r.construto, []).append(r)
    out = []
    for construto, rs in grupos.items():
        tau = rs[0].tau_address
        valores = []
        for r in rs:
            b = bytes.fromhex(r.valor[2:])
            v = "0x" + b[-20:].hex() if tau else r.valor
            if v not in valores:
                valores.append(v)
        out.append(Constante(construto, rs[0].motivo, rs[0].tipo, tau, len(rs), valores, len(valores)))
    return out


def cobertura(regioes, tamanho):
    return 1 - sum(r.comprimento for r in regioes) / tamanho if tamanho else None


def confronto_acervo(regioes, transformacoes_acervo):
    """Compara (motivo, inicio) do verificador com as transformacoes de substituicao/insercao do acervo."""
    norm = []
    for t in transformacoes_acervo or []:
        if t.get("type") not in ("replace", "insert"):
            continue
        motivo = t.get("reason")
        if motivo == "immutable" and str(t.get("id")) == "library_deploy_address":
            motivo = "callProtection"
        norm.append((motivo, int(t["offset"])))
    a = set(norm)
    v = set((r.motivo, r.inicio) for r in regioes)
    return {"so_no_acervo": sorted(a - v), "so_no_verificador": sorted(v - a), "coincide": a == v}


def para_dict(objs):
    return [asdict(o) for o in objs]
