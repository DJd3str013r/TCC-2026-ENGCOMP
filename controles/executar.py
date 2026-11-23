# -*- coding: utf-8 -*-
"""Etapas 3 e 4 (subsecao 3.4): implanta os oito contratos-controle numa rede local em memoria, registra o gabarito
(posicao, comprimento, valor, construto e tipo de cada regiao esperada) e valida o verificador por precisao e
revocacao (Equacoes 6 e 7) em cada motivo de transformacao, conferindo tambem o tipo declarado e tau(r) das variaveis
imutaveis (desde a 1.7.0, P-17). Cada rodada e anexada a
saidas/validacao_historico.jsonl (relatada versao a versao, como pede a subsecao 3.8).

Uso: python controles/executar.py"""
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from atesta import VERSAO  # noqa: E402
from atesta.classificacao import keccak256  # noqa: E402
from atesta.compilador import compilar, _lista_oficial  # noqa: E402
from atesta.config import SAIDAS  # noqa: E402
from atesta.estatistica import precisao, revocacao  # noqa: E402
from atesta.rpc import ProvedorMemoria  # noqa: E402
from atesta.verificador import verificar  # noqa: E402
from controles.rede_local import RedeLocal, REMETENTE  # noqa: E402

AQUI = Path(__file__).resolve().parent
GERADOS = AQUI / "gerados"
VERSAO_SOLC = "0.8.37"
AJUSTES = {"optimizer": {"enabled": True, "runs": 200}, "evmVersion": "cancun"}
MOTIVOS = ["immutable", "library", "callProtection", "cborAuxdata"]
# tipo declarado de cada variavel imutavel do controle positivo, na forma em que o verificador o registra
TIPOS = {"a1": "address", "a2": "address payable", "a3": "contract Alvo", "a4": "contract IAlvo",
         "a5": "Endereco (sobre address)", "a6": "EnderecoPagavel (sobre address payable)", "n1": "uint256"}


def checksum(end):
    h = keccak256(end[2:].lower().encode()).hex()
    return "0x" + "".join(c.upper() if c.isalpha() and int(h[i], 16) >= 8 else c for i, c in enumerate(end[2:].lower()))


def endereco_create(remetente, nonce):
    """Endereco criado por CREATE: keccak(rlp([remetente, nonce]))[12:] (nonce < 128)."""
    n = bytes([nonce]) if 0 < nonce < 0x80 else (b"\x80" if nonce == 0 else None)
    corpo = b"\x94" + remetente + n
    return "0x" + keccak256(bytes([0xc0 + len(corpo)]) + corpo)[12:].hex()


def versao_longa():
    b = next(x for x in _lista_oficial()["builds"] if x["version"] == VERSAO_SOLC)
    return b["longVersion"]


def entrada(arquivos, bibliotecas=None, via_ir=False):
    aj = json.loads(json.dumps(AJUSTES))
    if bibliotecas:
        aj["libraries"] = bibliotecas
    if via_ir:
        aj["viaIR"] = True
    return {"language": "Solidity", "sources": {k: {"content": v} for k, v in arquivos.items()}, "settings": aj}


def criacao(std, arquivo, nome):
    """Codigo de criacao e saidas uteis do contrato (compilacao local, a mesma do verificador)."""
    import subprocess
    from atesta.compilador import executavel
    e = json.loads(json.dumps(std))
    e["settings"]["outputSelection"] = {arquivo: {nome: ["evm.bytecode.object", "evm.bytecode.linkReferences",
                                                         "evm.deployedBytecode.object",
                                                         "evm.deployedBytecode.immutableReferences",
                                                         "evm.deployedBytecode.linkReferences"]},
                                        "*": {"": ["ast"]}}
    r = subprocess.run([str(executavel(versao_longa())), "--standard-json"], input=json.dumps(e).encode(),
                       capture_output=True, check=True)
    s = json.loads(r.stdout)
    erros = [x for x in s.get("errors", []) if x["severity"] == "error"]
    if erros:
        raise RuntimeError(erros[0]["formattedMessage"])
    return s["contracts"][arquivo][nome], s["sources"]


def vincular(hex_criacao, link_refs, endereco):
    h = list(hex_criacao)
    for libs in link_refs.values():
        for refs in libs.values():
            for ref in refs:
                h[2 * ref["start"]:2 * (ref["start"] + ref["length"])] = list(endereco[2:].lower())
    return "".join(h)


def nomes_imutaveis(fontes, contrato):
    """id da declaracao -> nome da variavel, a partir da AST."""
    ids = {}

    def andar(no):
        if isinstance(no, dict):
            if no.get("nodeType") == "VariableDeclaration" and no.get("mutability") == "immutable":
                ids[str(no["id"])] = no["name"]
            for v in no.values():
                andar(v)
        elif isinstance(no, list):
            for v in no:
                andar(v)

    andar(fontes)
    return ids


def palavra(v):
    if isinstance(v, int):
        return "0x" + v.to_bytes(32, "big").hex()
    return "0x" + "00" * 12 + v[2:].lower()


def registro(std, arquivo, nome, grau, cbor=None):
    return {"matchId": None, "runtimeMatch": grau,
            "compilation": {"compilerVersion": versao_longa(), "language": "Solidity",
                            "fullyQualifiedName": f"{arquivo}:{nome}"},
            "stdJsonInput": std, "runtimeBytecode": {"cborAuxdata": cbor or {}, "transformations": []}}


def cbor_final(implantado):
    b = bytes.fromhex(implantado)
    n = int.from_bytes(b[-2:], "big") + 2
    return len(b) - n, b[len(b) - n:]


def main(registrar=True):
    """Valida o verificador nos oito controles e devolve o resultado. Com registrar=False (testes), nao grava o
    gabarito, as certidoes, saidas/validacao.json nem a linha do historico de validacao."""
    GERADOS.mkdir(exist_ok=True)
    rede = RedeLocal()
    eoa = checksum("0x" + REMETENTE.hex())
    alvo = checksum(endereco_create(REMETENTE, 0))
    lib = checksum(endereco_create(REMETENTE, 1))
    valores = {"A1": "0x1111111111111111111111111111111111111111", "A2": eoa, "A3": alvo, "A4": alvo,
               "A5": "0x0000000000000000000000000000000000000000", "A6": "0x2222222222222222222222222222222222222222",
               "N1": 123456789}
    tpl = (AQUI / "contratos" / "Controles.sol.tpl").read_text(encoding="utf-8")
    fonte = re.sub(r"\{\{(\w+)\}\}", lambda m: str(valores[m.group(1)]), tpl)
    (GERADOS / "Controles.sol").write_text(fonte, encoding="utf-8")
    meta = (AQUI / "contratos" / "Metadados.sol").read_text(encoding="utf-8")
    meta_coment = meta.rstrip("\n") + "\n// copia submetida a verificacao: difere do original apenas neste comentario\n"
    (GERADOS / "Metadados.comentario.sol").write_text(meta_coment, encoding="utf-8")

    F = "Controles.sol"
    std = entrada({F: fonte})
    std_lib = entrada({F: fonte}, bibliotecas={F: {"BibliotecaControle": lib}})
    std_meta, std_meta_c = entrada({"Metadados.sol": meta}), entrada({"Metadados.sol": meta_coment})

    implantados, gabarito = {}, {}

    c_alvo, _ = criacao(std, F, "Alvo")
    assert rede.implantar(bytes.fromhex(c_alvo["evm"]["bytecode"]["object"])).lower() == alvo.lower()
    c_lib, _ = criacao(std, F, "BibliotecaControle")
    assert rede.implantar(bytes.fromhex(c_lib["evm"]["bytecode"]["object"])).lower() == lib.lower()
    implantados["chamada+"] = (lib, registro(std, F, "BibliotecaControle", "exact_match"))
    gabarito["chamada+"] = [{"inicio": 1, "comprimento": 20, "motivo": "callProtection",
                              "construto": "protecao_de_chamada", "valor": lib.lower(), "tau_address": True}]

    c_imm, fontes = criacao(std, F, "ControleImutavelPositivo")
    args = b"".join(bytes.fromhex(palavra(valores[k])[2:]) for k in ("A1", "A2", "A3", "A4", "A5", "A6", "N1"))
    end = rede.implantar(bytes.fromhex(c_imm["evm"]["bytecode"]["object"]) + args)
    implantados["imutavel+"] = (end, registro(std, F, "ControleImutavelPositivo", "exact_match"))
    nomes = nomes_imutaveis(fontes, "ControleImutavelPositivo")
    chave = {"a1": "A1", "a2": "A2", "a3": "A3", "a4": "A4", "a5": "A5", "a6": "A6", "n1": "N1"}
    gab = []
    for idd, refs in c_imm["evm"]["deployedBytecode"]["immutableReferences"].items():
        nome = nomes[idd]
        for ref in refs:
            gab.append({"inicio": ref["start"], "comprimento": ref["length"], "motivo": "immutable",
                        "construto": f"imutavel:{idd}", "valor": palavra(valores[chave[nome]]),
                        "tipo": TIPOS[nome], "tau_address": nome != "n1", "variavel": nome})
    gabarito["imutavel+"] = gab

    for rot, nome in (("imutavel-", "ControleImutavelNegativo"), ("chamada-", "ControleChamadaNegativo")):
        c, _ = criacao(std, F, nome)
        implantados[rot] = (rede.implantar(bytes.fromhex(c["evm"]["bytecode"]["object"])),
                            registro(std, F, nome, "exact_match"))
        gabarito[rot] = []

    c_bib, _ = criacao(std, F, "ControleBiblioteca")
    vinc = vincular(c_bib["evm"]["bytecode"]["object"], c_bib["evm"]["bytecode"]["linkReferences"], lib)
    implantados["biblioteca+"] = (rede.implantar(bytes.fromhex(vinc)), registro(std, F, "ControleBiblioteca", "exact_match"))
    gabarito["biblioteca+"] = [{"inicio": r["start"], "comprimento": r["length"], "motivo": "library",
                                "construto": f"biblioteca:{F}:BibliotecaControle", "valor": lib.lower(),
                                "tau_address": True}
                               for libs in c_bib["evm"]["deployedBytecode"]["linkReferences"].values()
                               for refs in libs.values() for r in refs]
    c_bib_neg, _ = criacao(std_lib, F, "ControleBiblioteca")
    implantados["biblioteca-"] = (rede.implantar(bytes.fromhex(c_bib_neg["evm"]["bytecode"]["object"])),
                                  registro(std_lib, F, "ControleBiblioteca", "exact_match"))
    gabarito["biblioteca-"] = []

    c_meta, _ = criacao(std_meta, "Metadados.sol", "ControleMetadados")
    c_meta_c, _ = criacao(std_meta_c, "Metadados.sol", "ControleMetadados")
    off, valor_cbor = cbor_final(c_meta["evm"]["deployedBytecode"]["object"])
    off_c, valor_c = cbor_final(c_meta_c["evm"]["deployedBytecode"]["object"])
    assert off == off_c and valor_cbor != valor_c
    cbor_reg = {"1": {"offset": off_c, "value": "0x" + valor_c.hex()}}
    implantados["metadados+"] = (rede.implantar(bytes.fromhex(c_meta["evm"]["bytecode"]["object"])),
                                 registro(std_meta_c, "Metadados.sol", "ControleMetadados", "match", cbor_reg))
    gabarito["metadados+"] = [{"inicio": off, "comprimento": len(valor_cbor), "motivo": "cborAuxdata",
                               "construto": "metadados:1", "valor": "0x" + valor_cbor.hex(), "tau_address": False}]
    cbor_neg = {"1": {"offset": off, "value": "0x" + valor_cbor.hex()}}
    implantados["metadados-"] = (rede.implantar(bytes.fromhex(c_meta["evm"]["bytecode"]["object"])),
                                 registro(std_meta, "Metadados.sol", "ControleMetadados", "exact_match", cbor_neg))
    gabarito["metadados-"] = []

    bloco = rede.bloco_atual()
    prov = ProvedorMemoria(rede.cadeia)

    # valores esperados: o gabarito compara enderecos em 20 bytes e palavras imutaveis em 32 bytes
    def norm(reg):
        v = reg["valor"].lower()
        if reg["motivo"] in ("library", "callProtection"):
            v = "0x" + v[-40:]
        return (reg["inicio"], reg["comprimento"], reg["motivo"], reg["construto"], v)

    contagem = {m: {"VP": 0, "FP": 0, "FN": 0} for m in MOTIVOS}
    tau_divergente, tipo_divergente, certidoes = [], [], {}
    for rot, (end, reg) in implantados.items():
        cert = verificar(end, bloco, prov, reg, rede=0)
        certidoes[rot] = cert
        if cert["situacao"] != "processado":
            print(rot, "FALHA:", cert.get("causa"))
            for g in gabarito[rot]:
                contagem[g["motivo"]]["FN"] += 1
            continue
        achadas = {norm(r): r for r in cert["regioes"]}
        esperadas = {norm(g): g for g in gabarito[rot]}
        for k, r in achadas.items():
            if k in esperadas:
                contagem[r["motivo"]]["VP"] += 1
                if r["tau_address"] != esperadas[k]["tau_address"]:
                    tau_divergente.append((rot, k))
                if "tipo" in esperadas[k] and r["tipo"] != esperadas[k]["tipo"]:
                    tipo_divergente.append((rot, k, r["tipo"], esperadas[k]["tipo"]))
            else:
                contagem[r["motivo"]]["FP"] += 1
        for k, g in esperadas.items():
            if k not in achadas:
                contagem[g["motivo"]]["FN"] += 1

    por_motivo = {m: {**c, "P": precisao(c["VP"], c["FP"]), "R": revocacao(c["VP"], c["FN"])}
                  for m, c in contagem.items()}
    aprovado = (all(c["P"] == 1 and c["R"] == 1 for c in por_motivo.values()) and not tau_divergente
                and not tipo_divergente)
    resultado = {
        "quando": datetime.now(timezone.utc).isoformat(timespec="seconds"), "verificador": VERSAO,
        "compilador_controles": versao_longa(), "ajustes": AJUSTES, "rede": "py-evm em memoria (Cancun)",
        "bloco": bloco, "enderecos": {k: v[0] for k, v in implantados.items()}, "por_motivo": por_motivo,
        "tau_divergente": tau_divergente, "tipo_divergente": tipo_divergente,
        "tipos_conferidos": sorted({g["tipo"] for g in gabarito["imutavel+"]}), "aprovado": aprovado,
        "regioes_esperadas": {k: len(v) for k, v in gabarito.items()},
    }
    if registrar:
        (GERADOS / "gabarito.json").write_text(json.dumps(gabarito, indent=1, ensure_ascii=False), encoding="utf-8")
        (GERADOS / "certidoes_controles.json").write_text(json.dumps(certidoes, indent=1, ensure_ascii=False),
                                                         encoding="utf-8")
        (SAIDAS / "validacao.json").write_text(json.dumps(resultado, indent=1, ensure_ascii=False), encoding="utf-8")
        with open(SAIDAS / "validacao_historico.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(resultado, ensure_ascii=False) + "\n")
    for m, c in por_motivo.items():
        print(f"{m:15s} VP={c['VP']:3d} FP={c['FP']} FN={c['FN']} P={c['P']} R={c['R']}")
    print("tau divergente:", tau_divergente, "| tipo divergente:", tipo_divergente)
    print("APROVADO" if aprovado else "REPROVADO")
    return resultado


if __name__ == "__main__":
    sys.exit(0 if main()["aprovado"] else 1)
