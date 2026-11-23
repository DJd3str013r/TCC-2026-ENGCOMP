# -*- coding: utf-8 -*-
"""Delegacao nos alvos com codigo (subsecao 4.6 do artigo). Leitura complementar, descritiva, nao prevista nas
subsecoes 3.6 e 3.8: registra para onde delegam os alvos que tem DELEGATECALL.

Le o codigo dos 31 alvos lido por proxies_compartimentos.py (respostas eth_getCode no bloco 26.296.341, guardadas em
dados/complementares/proxies_compartimentos_respostas_codigo.jsonl) e o resultado dele
(saidas/complementares/proxies_compartimentos.json). Para cada alvo:
  1. varredura linear do codigo: posicoes das instrucoes DELEGATECALL (0xf4) e CALLCODE (0xf2), e se cada uma fica
     depois do ultimo INVALID (0xfe) anterior ao bloco CBOR final, isto e, na area de dados que o compilador anexa
     ao codigo; para essas, confere se os 32 bytes em volta sao o topico de um evento ERC-20 (dado, nao instrucao);
  2. execucao local (py-evm em memoria, regras do Cancun), sem estado da rede principal alem do codigo e dos
     compartimentos lidos por proxies_compartimentos.py:
     - nos alvos com uma instrucao DELEGATECALL e sem compartimento de implementacao preenchido, chama
       multicall(bytes[]) com uma chamada interna e registra o destino de cada DELEGATECALL executado;
     - no alvo com implementacao em compartimento de outro padrao (FiatTokenProxy), chama name() com o compartimento
       lido e, como contraprova, com outro valor no compartimento, sem mudar o codigo: o DELEGATECALL segue o valor
       do compartimento.
O NttManager, alvo que e o proprio contrato positivo, nao e executado aqui: seus DELEGATECALL foram levados ao
codigo-fonte por proxies_delegacao.py (chamadas a biblioteca vinculada na compilacao).
A transacao da cadeia em memoria e assinada com uma chave de teste fixa e publica (32 bytes 0x02), sem valor, usada
so nessa cadeia. Grava saidas/complementares/proxies_delegacao_alvos.json. Nao acessa a rede.

Uso: python analise/complementares/proxies_delegacao_alvos.py"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from Crypto.Hash import keccak
from eth import constants
from eth.chains.base import MiningChain
from eth.db.atomic import AtomicDB
from eth.vm.forks import CancunVM
from eth_keys import keys

RAIZ = Path(__file__).resolve().parents[2]
SAIDA = RAIZ / "saidas" / "complementares"
ARQ_COMPARTIMENTOS = SAIDA / "proxies_compartimentos.json"
ARQ_COD = RAIZ / "dados" / "complementares" / "proxies_compartimentos_respostas_codigo.jsonl"

CHAVE_TESTE = keys.PrivateKey(b"\x02" * 32)   # chave de teste deterministica (cadeia em memoria)
REMETENTE = CHAVE_TESTE.public_key.to_canonical_address()


def k256(b):
    h = keccak.new(digest_bits=256)
    h.update(b)
    return h.digest()


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


def inicio_cbor(codigo):
    n = int.from_bytes(codigo[-2:], "big")
    ini = len(codigo) - 2 - n
    if 0 < n < 200 and ini > 0 and codigo[ini] in (0xA1, 0xA2, 0xA3, 0xA4, 0xA5):
        return ini
    return len(codigo)


def codigos_lidos():
    """Ultima resposta valida de eth_getCode por endereco (respostas guardadas de proxies_compartimentos.py)."""
    cods = {}
    for linha in open(ARQ_COD, encoding="utf-8"):
        d = json.loads(linha)
        if d["metodo"] != "eth_getCode" or not d.get("resposta_bruta"):
            continue
        try:
            r = json.loads(d["resposta_bruta"]).get("result")
        except ValueError:
            continue
        if isinstance(r, str) and r.startswith("0x"):
            cods[d["params"][0].lower()] = {"codigo": bytes.fromhex(r[2:]), "no": d["no"], "data_utc": d["fim_utc"]}
    return cods


def nova_cadeia(contas):
    klass = MiningChain.configure(__name__="CadeiaLocal", vm_configuration=((0, CancunVM),))
    genesis = {"coinbase": constants.ZERO_ADDRESS, "difficulty": 0, "gas_limit": 30_000_000, "timestamp": 1_700_000_000,
               "extra_data": b"", "nonce": b"\x00" * 8, "mix_hash": constants.ZERO_HASH32}
    estado = {REMETENTE: {"balance": 10 ** 24, "nonce": 0, "code": b"", "storage": {}}}
    estado.update(contas)
    return klass.from_genesis(AtomicDB(), genesis, estado)


def executar(contas, destino, dados):
    cadeia = nova_cadeia(contas)
    vm = cadeia.get_vm()
    tx = vm.create_unsigned_transaction(nonce=0, gas_price=10 ** 10, gas=8_000_000, to=destino, value=0,
                                        data=dados).as_signed_transaction(CHAVE_TESTE)
    _, _, comp = cadeia.apply_transaction(tx)
    delegacoes, outras = [], 0

    def percorrer(c):
        nonlocal outras
        for f in c.children:
            m = f.msg
            # DELEGATECALL: a chamada filha conserva o contexto (mesmo endereco de armazenamento) e o remetente da
            # chamada mae, e executa o codigo de code_address (que pode ser o proprio contrato). CALL, STATICCALL e
            # CALLCODE trocam o remetente pelo endereco do contrato que chama.
            if m.storage_address == c.msg.storage_address and m.sender == c.msg.sender:
                delegacoes.append({"profundidade": m.depth, "contexto": "0x" + m.storage_address.hex(),
                                   "codigo_executado_de": "0x" + m.code_address.hex(), "erro": f.is_error})
            else:
                outras += 1
            percorrer(f)
    percorrer(comp)
    return {"erro_na_transacao": comp.is_error, "delegacoes": delegacoes, "outras_chamadas": outras}


def u256(n):
    return n.to_bytes(32, "big")


def main():
    for p in (ARQ_COMPARTIMENTOS, ARQ_COD):
        if not p.exists():
            sys.exit(f"entrada ausente: {p.relative_to(RAIZ).as_posix()}")
    b = json.load(open(ARQ_COMPARTIMENTOS, encoding="utf-8"))
    cods = codigos_lidos()
    topicos = {nome: k256(nome.encode()) for nome in ("Transfer(address,address,uint256)",
                                                       "Approval(address,address,uint256)")}
    sel_multicall = k256(b"multicall(bytes[])")[:4]
    sel_interno = k256(b"naoExiste()")[:4]
    sel_name = k256(b"name()")[:4]
    dados_multicall = sel_multicall + u256(32) + u256(1) + u256(32) + u256(4) + sel_interno.ljust(32, b"\x00")
    s_zos = int(b["resumo"]["keccak256"]["zeppelinos_implementacao"], 16)
    s_zos_adm = int(b["resumo"]["keccak256"]["zeppelinos_admin"], 16)

    alvos = []
    for a in b["alvos"]:
        v = a["alvo"]
        c = cods[v]["codigo"]
        ini_cbor = inicio_cbor(c)
        ins = desmontar(c[:ini_cbor])
        ult_invalid = max((pc for pc, op, _ in ins if op == 0xFE), default=None)
        ocorr = []
        for pc, op, _ in ins:
            if op not in (0xF4, 0xF2):
                continue
            item = {"pc": pc, "instrucao": "DELEGATECALL" if op == 0xF4 else "CALLCODE",
                    "depois_do_ultimo_INVALID": ult_invalid is not None and pc > ult_invalid}
            if item["depois_do_ultimo_INVALID"]:
                for nome, t in topicos.items():
                    for ini in range(max(0, pc - 31), pc + 1):
                        if c[ini:ini + 32] == t:
                            item["dentro_do_topico_do_evento"] = {"evento": nome, "inicio": ini}
            ocorr.append(item)
        reg = {"alvo": v, "nome": a["nome_no_instantaneo"], "tamanho": len(c), "no_do_codigo": cods[v]["no"],
               "ocorrencias": ocorr,
               "DELEGATECALL_no_codigo": sum(1 for o in ocorr if o["instrucao"] == "DELEGATECALL"
                                             and not o.get("dentro_do_topico_do_evento")),
               "CALLCODE_no_codigo": sum(1 for o in ocorr if o["instrucao"] == "CALLCODE"
                                         and not o.get("dentro_do_topico_do_evento"))}
        end_b = bytes.fromhex(v[2:])
        impl = a["complementos"].get("zeppelinos_implementacao", {})
        if reg["DELEGATECALL_no_codigo"] and impl:
            imp_end = impl["implementacao"]
            adm_end = (impl.get("compartimento_admin") or {}).get("endereco_guardado")
            contas = {end_b: {"balance": 0, "nonce": 1, "code": c,
                              "storage": {s_zos: int(imp_end, 16), s_zos_adm: int(adm_end, 16)}}}
            if imp_end in cods:
                contas[bytes.fromhex(imp_end[2:])] = {"balance": 0, "nonce": 1, "code": cods[imp_end]["codigo"],
                                                      "storage": {}}
            r1 = executar(contas, end_b, sel_name)
            outro = "0x" + k256(b"outra implementacao qualquer")[-20:].hex()
            contas2 = {end_b: {"balance": 0, "nonce": 1, "code": c,
                               "storage": {s_zos: int(outro, 16), s_zos_adm: int(adm_end, 16)}}}
            r2 = executar(contas2, end_b, sel_name)
            reg["execucao_local"] = {
                "chamada": "name() (0x" + sel_name.hex() + ")",
                "com_o_compartimento_lido": {"valor_no_compartimento": imp_end, **r1,
                                             "delegou_ao_valor_do_compartimento": any(
                                                 d["codigo_executado_de"] == imp_end for d in r1["delegacoes"])},
                "com_outro_valor_no_mesmo_compartimento": {"valor_no_compartimento": outro, **r2,
                                                           "delegou_ao_valor_do_compartimento": any(
                                                               d["codigo_executado_de"] == outro for d in r2["delegacoes"])},
                "codigo_igual_nas_duas_execucoes": True}
        elif reg["DELEGATECALL_no_codigo"] and a["classes"] != ["proprio_contrato"]:
            contas = {end_b: {"balance": 0, "nonce": 1, "code": c, "storage": {}}}
            r = executar(contas, end_b, dados_multicall)
            reg["execucao_local"] = {"chamada": "multicall(bytes[]) (0x" + sel_multicall.hex() + ") com uma chamada "
                                                "interna de seletor 0x" + sel_interno.hex(), **r,
                                     "delegou_so_ao_proprio_contrato": bool(r["delegacoes"]) and all(
                                         d["codigo_executado_de"] == v for d in r["delegacoes"])}
        alvos.append(reg)

    exec_mc = [x for x in alvos if "delegou_so_ao_proprio_contrato" in x.get("execucao_local", {})]
    exec_px = [x for x in alvos if "com_o_compartimento_lido" in x.get("execucao_local", {})]
    resumo = {
        "gerado_em_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "alvos": len(alvos),
        "alvos_sem_DELEGATECALL_nem_CALLCODE_no_codigo": sum(1 for x in alvos if not x["DELEGATECALL_no_codigo"]
                                                             and not x["CALLCODE_no_codigo"]),
        "ocorrencias_descartadas_por_estarem_em_dados": [
            {"alvo": x["alvo"], "nome": x["nome"], **o} for x in alvos for o in x["ocorrencias"]
            if o.get("dentro_do_topico_do_evento")],
        "alvos_com_DELEGATECALL_no_codigo": [{"alvo": x["alvo"], "nome": x["nome"], "instrucoes": x["DELEGATECALL_no_codigo"]}
                                             for x in alvos if x["DELEGATECALL_no_codigo"]],
        "multicall_executado": len(exec_mc),
        "multicall_delegou_so_ao_proprio_contrato": sum(x["execucao_local"]["delegou_so_ao_proprio_contrato"]
                                                        for x in exec_mc),
        "proxy_de_outro_padrao_executado": [
            {"alvo": x["alvo"], "nome": x["nome"],
             "delegou_ao_compartimento_lido": x["execucao_local"]["com_o_compartimento_lido"]["delegou_ao_valor_do_compartimento"],
             "delegou_ao_outro_valor": x["execucao_local"]["com_outro_valor_no_mesmo_compartimento"]["delegou_ao_valor_do_compartimento"]}
            for x in exec_px],
    }
    SAIDA.mkdir(parents=True, exist_ok=True)
    json.dump({"resumo": resumo, "alvos": alvos}, open(SAIDA / "proxies_delegacao_alvos.json", "w", encoding="utf-8"),
              indent=1, ensure_ascii=False)
    print(json.dumps(resumo, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
