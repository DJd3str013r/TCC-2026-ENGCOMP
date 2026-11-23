# -*- coding: utf-8 -*-
"""Troca do codigo executado por delegacao, em execucao local (subsecao 4.6 do artigo). Leitura complementar,
descritiva, nao prevista nas subsecoes 3.6 e 3.8: py-evm em memoria, regras do Cancun, sem rede.

Contraprova dinamica, independente da leitura do codigo-fonte:
  T1. nos tres positivos apontados como proxy, o codigo de execucao da cadeia (cache da API do acervo, so leitura,
      keccak256 conferido com a certidao) recebe uma chamada com seletor inexistente; registra-se o destino de cada
      DELEGATECALL. Depois troca-se, no proprio codigo, o valor gravado em todas as regioes da constante do tipo address
      (as regioes nao atestadas da certidao) por outro endereco e repete-se a chamada: se o destino acompanha o valor
      da regiao, a escolha do codigo executado esta na regiao nao atestada. Repete-se com chamada sem dados (receive).
  T2. na SmartWallet, chama-se cada funcao publica (com a biblioteca SmartWalletLib, codigo lido no bloco de
      referencia na coleta, no endereco gravado nas regioes de biblioteca) e registra-se o destino dos DELEGATECALL;
      depois troca-se o endereco nas quatro regioes por outro, com o mesmo codigo de biblioteca.
  T3. no USDC (FiatTokenProxy, codigo lido na coleta), com os compartimentos lidos por proxies_administrador.py:
      name() delega a implementacao; o administrador lido no compartimento (remetente simulado, so nesta cadeia em
      memoria) chama upgradeTo(novo endereco com codigo); confere-se o compartimento e o destino de name() depois da
      troca; como controle, outro remetente chama upgradeTo e o compartimento nao muda. O codigo do proxy nao e
      alterado.
As transacoes do remetente de teste sao assinadas com uma chave de teste fixa e publica (32 bytes 0x07), sem valor,
usada so nesta cadeia em memoria; a do administrador no T3 usa remetente simulado, sem assinatura.

Le dados/certidoes/*.json, .cache/sourcify_api.sqlite e .cache/rpc_rede_principal.sqlite (publicados a parte,
abertos com mode=ro e immutable=1), saidas/complementares/proxies_administrador.json e
dados/complementares/proxies_administrador_respostas.jsonl (codigo da implementacao). Grava
saidas/complementares/proxies_troca_local.json. Nao acessa a rede.

Uso: python analise/complementares/proxies_troca_local.py"""
import glob
import json
import sqlite3
import sys
from pathlib import Path

from Crypto.Hash import keccak
from eth import constants
from eth.chains.base import MiningChain
from eth.db.atomic import AtomicDB
from eth.vm.forks import CancunVM
from eth.vm.spoof import SpoofTransaction
from eth_keys import keys

RAIZ = Path(__file__).resolve().parents[2]
CERT = RAIZ / "dados" / "certidoes"
API = RAIZ / ".cache" / "sourcify_api.sqlite"
RPC = RAIZ / ".cache" / "rpc_rede_principal.sqlite"
ADMINISTRADOR = RAIZ / "saidas" / "complementares" / "proxies_administrador.json"
RESPOSTAS_ADMINISTRADOR = RAIZ / "dados" / "complementares" / "proxies_administrador_respostas.jsonl"
SAIDA = RAIZ / "saidas" / "complementares"
BLOCO_HEX = "0x1914015"
CHAVE_TESTE = keys.PrivateKey(b"\x07" * 32)   # chave de teste deterministica (cadeia em memoria)
REMETENTE = CHAVE_TESTE.public_key.to_canonical_address()


def k256(b):
    h = keccak.new(digest_bits=256)
    h.update(b)
    return h.digest()


def ro(c):
    return sqlite3.connect("file:" + Path(c).as_posix() + "?mode=ro&immutable=1", uri=True)


def sel(assinatura):
    return k256(assinatura.encode())[:4]


def addr(h):
    return bytes.fromhex(h[2:] if h.startswith("0x") else h)


def palavra_end(b20):
    return b"\x00" * 12 + b20


class Cadeia:
    def __init__(self, contas):
        klass = MiningChain.configure(__name__="CadeiaLocal", vm_configuration=((0, CancunVM),))
        genesis = {"coinbase": constants.ZERO_ADDRESS, "difficulty": 0, "gas_limit": 30_000_000,
                   "timestamp": 1_700_000_000, "extra_data": b"", "nonce": b"\x00" * 8, "mix_hash": constants.ZERO_HASH32}
        estado = {REMETENTE: {"balance": 10 ** 24, "nonce": 0, "code": b"", "storage": {}}}
        estado.update(contas)
        self.chain = klass.from_genesis(AtomicDB(), genesis, estado)
        self.vm = self.chain.get_vm()
        self.state = self.vm.state

    def enviar(self, para, dados, de=None, valor=0):
        de = de or REMETENTE
        nonce = self.state.get_nonce(de)
        tx = self.vm.create_unsigned_transaction(nonce=nonce, gas_price=10 ** 10, gas=5_000_000, to=para, value=valor,
                                                 data=dados)
        tx = tx.as_signed_transaction(CHAVE_TESTE) if de == REMETENTE else SpoofTransaction(tx, from_=de)
        self.state.lock_changes()
        comp = self.state.apply_transaction(tx)
        return comp

    def storage(self, a, slot):
        return self.state.get_storage(a, slot)


def filhos(comp):
    """Chamadas filhas: classifica DELEGATECALL (mesmo contexto de armazenamento e mesmo remetente da mae, sem
    transferencia de valor) e CALLCODE (contexto da mae, remetente = a propria mae, codigo de outro endereco)."""
    out = []

    def rec(c):
        for f in c.children:
            m, p = f.msg, c.msg
            if (not m.should_transfer_value and m.storage_address == p.storage_address and m.sender == p.sender
                    and not m.is_static):
                tipo = "DELEGATECALL"
            elif m.storage_address == p.storage_address and m.sender == p.storage_address and m.code_address != m.storage_address:
                tipo = "CALLCODE"
            else:
                tipo = "outra"
            out.append({"tipo": tipo, "codigo_de": "0x" + m.code_address.hex(), "contexto": "0x" + m.storage_address.hex(),
                        "erro": f.is_error})
            rec(f)
    rec(comp)
    return out


def destinos(comp):
    return sorted({f["codigo_de"] for f in filhos(comp) if f["tipo"] == "DELEGATECALL"})


def trocar_regioes(codigo, regioes, novo20):
    c = bytearray(codigo)
    for r in regioes:
        ini, n = r["inicio"], r["comprimento"]
        val = novo20.rjust(n, b"\x00") if n >= 20 else novo20[-n:]
        c[ini:ini + n] = val
    return bytes(c)


def main():
    for p in (CERT, API, RPC, ADMINISTRADOR, RESPOSTAS_ADMINISTRADOR):
        if not p.exists():
            sys.exit(f"entrada ausente: {p.relative_to(RAIZ).as_posix()}")
    api, rpc = ro(API), ro(RPC)
    certs = {}
    for p in glob.glob(str(CERT / "*.json")):
        c = json.load(open(p, encoding="utf-8"))
        certs[c["contrato"]["endereco"]] = c

    def codigo_api(end):
        reg = json.loads(api.execute("SELECT v FROM kv WHERE k = ?", ("1:" + end,)).fetchone()[0])
        cod = bytes.fromhex(reg["runtimeBytecode"]["onchainBytecode"][2:])
        assert "0x" + k256(cod).hex() == certs[end]["contrato"]["resumo_codigo"], end
        return cod

    def codigo_rpc(end):
        r = rpc.execute("SELECT v FROM kv WHERE k = ?", ('eth_getCode["%s","%s"]' % (end, BLOCO_HEX),)).fetchone()
        return bytes.fromhex(json.loads(r[0])[2:])

    out = {}
    outro = k256(b"troca local: outro endereco")[-20:]

    # T1. tres proxies
    t1 = {}
    for end in ("0xc420b590f4d06c74afbd7f30a9c0b67bca6aeffe", "0x2d90afaeea73aa6a3313f191349ce4a9b86c7996",
                "0x32dafdb716dcd5dd799369a62d9d660ca6bc855f"):
        cert = certs[end]
        k = [x for x in cert["constantes"] if x.get("tau_address")]
        assert len(k) == 1
        k = k[0]
        regs = [r for r in cert["regioes"] if r["construto"] == k["construto"]]
        valor = k["valores"][0]
        cod = codigo_api(end)
        res = {"constante": k["construto"], "valor": valor, "regioes": [(r["inicio"], r["comprimento"]) for r in regs]}
        for rotulo, codigo in (("codigo_da_cadeia", cod), ("codigo_com_outro_valor_nas_regioes", trocar_regioes(cod, regs, outro))):
            cad = Cadeia({addr(end): {"balance": 0, "nonce": 1, "code": codigo, "storage": {}}})
            c1 = cad.enviar(addr(end), bytes.fromhex("deadbeef") + b"\x00" * 32)
            cad2 = Cadeia({addr(end): {"balance": 0, "nonce": 1, "code": codigo, "storage": {}}})
            c2 = cad2.enviar(addr(end), b"")
            res[rotulo] = {"chamada_com_seletor_inexistente": {"erro": c1.is_error, "delegou_a": destinos(c1)},
                           "chamada_sem_dados": {"erro": c2.is_error, "delegou_a": destinos(c2)}}
        res["destino_acompanha_a_regiao"] = (
            res["codigo_da_cadeia"]["chamada_com_seletor_inexistente"]["delegou_a"] == [valor]
            and res["codigo_com_outro_valor_nas_regioes"]["chamada_com_seletor_inexistente"]["delegou_a"] == ["0x" + outro.hex()])
        t1[end] = res
    out["T1_proxies"] = t1
    out["T1_proxies_cujo_destino_acompanha_a_regiao"] = sum(r["destino_acompanha_a_regiao"] for r in t1.values())

    # T2. SmartWallet
    end = "0x56ab918a1b58fbfd8ab3d0fd85970195ab714628"
    cert = certs[end]
    k = [x for x in cert["constantes"] if x.get("tau_address")][0]
    regs = [r for r in cert["regioes"] if r["construto"] == k["construto"]]
    lib = k["valores"][0]
    cod = codigo_api(end)
    cod_lib = codigo_rpc(lib)
    a1 = b"\x00" * 12 + b"\x11" * 20
    chamadas = {
        "setUserWithdrawalAccount(address)": sel("setUserWithdrawalAccount(address)") + a1,
        "transferToUserWithdrawalAccount(address,uint256,address,uint256)":
            sel("transferToUserWithdrawalAccount(address,uint256,address,uint256)") + a1 + (1).to_bytes(32, "big") + a1 + (0).to_bytes(32, "big"),
        "requestWithdraw()": sel("requestWithdraw()"),
        "performUserWithdraw(address)": sel("performUserWithdraw(address)") + a1,
        "wallet()": sel("wallet()"),
    }
    t2 = {"biblioteca": lib, "tamanho_codigo_biblioteca": len(cod_lib), "regioes": [(r["inicio"], r["comprimento"]) for r in regs]}
    for rotulo, codigo, end_lib in (("codigo_da_cadeia", cod, addr(lib)),
                                    ("codigo_com_outro_valor_nas_regioes", trocar_regioes(cod, regs, outro), outro)):
        r_ = {}
        for nome, dados in chamadas.items():
            cad = Cadeia({addr(end): {"balance": 0, "nonce": 1, "code": codigo, "storage": {}},
                          end_lib: {"balance": 0, "nonce": 1, "code": cod_lib, "storage": {}}})
            c = cad.enviar(addr(end), dados)
            r_[nome] = {"erro_na_transacao": c.is_error, "delegou_a": destinos(c)}
        t2[rotulo] = r_
    t2["funcoes_que_delegam_a_biblioteca_da_regiao"] = sum(
        1 for n, x in t2["codigo_da_cadeia"].items() if x["delegou_a"] == [lib])
    t2["funcoes_que_acompanham_a_troca"] = sum(
        1 for n, x in t2["codigo_com_outro_valor_nas_regioes"].items() if x["delegou_a"] == ["0x" + outro.hex()])
    out["T2_smartwallet"] = t2

    # T3. USDC
    lido = json.load(open(ADMINISTRADOR, encoding="utf-8"))
    usdc = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
    s_zos = int.from_bytes(k256(b"org.zeppelinos.proxy.implementation"), "big")
    s_adm = int.from_bytes(k256(b"org.zeppelinos.proxy.admin"), "big")
    imp = "0x" + lido["leituras"][f"{usdc}|zeppelinos_implementacao"]["valor"][-40:]
    adm = "0x" + lido["leituras"][f"{usdc}|zeppelinos_admin"]["valor"][-40:]
    cod_imp = None
    for lin in open(RESPOSTAS_ADMINISTRADOR, encoding="utf-8"):
        d = json.loads(lin)
        if d["metodo"] == "eth_getCode" and d["params"][0] == imp and d.get("resposta_bruta"):
            cod_imp = bytes.fromhex(json.loads(d["resposta_bruta"])["result"][2:])
            break
    cod_px = codigo_rpc(usdc)
    novo = k256(b"troca local: nova implementacao")[-20:]
    contas = {addr(usdc): {"balance": 0, "nonce": 1, "code": cod_px, "storage": {s_zos: int(imp, 16), s_adm: int(adm, 16)}},
              addr(imp): {"balance": 0, "nonce": 1, "code": cod_imp, "storage": {}},
              novo: {"balance": 0, "nonce": 1, "code": cod_imp, "storage": {}},
              addr(adm): {"balance": 10 ** 24, "nonce": 0, "code": b"", "storage": {}}}
    cad = Cadeia(contas)
    c_a = cad.enviar(addr(usdc), sel("name()"))
    antes = {"name_delegou_a": destinos(c_a), "erro": c_a.is_error,
             "compartimento": "0x%040x" % cad.storage(addr(usdc), s_zos)}
    # controle: outro remetente tenta upgradeTo
    c_ctrl = cad.enviar(addr(usdc), sel("upgradeTo(address)") + palavra_end(novo))
    ctrl = {"erro": c_ctrl.is_error, "delegou_a": destinos(c_ctrl),
            "compartimento_depois": "0x%040x" % cad.storage(addr(usdc), s_zos)}
    # administrador (remetente simulado) troca a implementacao
    c_up = cad.enviar(addr(usdc), sel("upgradeTo(address)") + palavra_end(novo), de=addr(adm))
    up = {"erro": c_up.is_error, "delegou_a": destinos(c_up),
          "compartimento_depois": "0x%040x" % cad.storage(addr(usdc), s_zos)}
    c_d = cad.enviar(addr(usdc), sel("name()"))
    depois = {"name_delegou_a": destinos(c_d), "erro": c_d.is_error}
    out["T3_usdc"] = {"implementacao_lida": imp, "admin_lido": adm, "tamanho_codigo_proxy": len(cod_px),
                      "tamanho_codigo_implementacao": len(cod_imp) if cod_imp else None,
                      "novo_endereco": "0x" + novo.hex(), "antes": antes,
                      "controle_outro_remetente_chama_upgradeTo": ctrl,
                      "admin_chama_upgradeTo": up, "depois": depois,
                      "troca_pelo_admin_sem_mudar_o_codigo_do_proxy": (
                          antes["name_delegou_a"] == [imp] and ctrl["compartimento_depois"] == imp
                          and not up["erro"] and up["compartimento_depois"] == "0x" + novo.hex()
                          and depois["name_delegou_a"] == ["0x" + novo.hex()])}
    SAIDA.mkdir(parents=True, exist_ok=True)
    json.dump(out, open(SAIDA / "proxies_troca_local.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(json.dumps(out, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
