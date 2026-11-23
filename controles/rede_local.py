# -*- coding: utf-8 -*-
"""Rede local de desenvolvimento em memoria (py-evm, regras do Cancun) para os contratos-controle. A conta que
implanta usa uma chave de teste fixa e publica (32 bytes 0x01), sem valor, usada so nesta cadeia em memoria."""
from eth import constants
from eth.chains.base import MiningChain
from eth.db.atomic import AtomicDB
from eth.vm.forks import CancunVM
from eth_keys import keys

CHAVE_TESTE = keys.PrivateKey(b"\x01" * 32)   # chave de teste deterministica (cadeia em memoria)
REMETENTE = CHAVE_TESTE.public_key.to_canonical_address()


class RedeLocal:
    def __init__(self):
        klass = MiningChain.configure(__name__="RedeLocalTCC", vm_configuration=((0, CancunVM),))
        genesis = {
            "coinbase": constants.ZERO_ADDRESS, "difficulty": 0, "gas_limit": 30_000_000, "timestamp": 1_700_000_000,
            "extra_data": b"", "nonce": b"\x00" * 8, "mix_hash": constants.ZERO_HASH32,
        }
        estado = {REMETENTE: {"balance": 10 ** 24, "nonce": 0, "code": b"", "storage": {}}}
        self.cadeia = klass.from_genesis(AtomicDB(), genesis, estado)
        self.nonce = 0

    def implantar(self, codigo_criacao):
        vm = self.cadeia.get_vm()
        tx = vm.create_unsigned_transaction(nonce=self.nonce, gas_price=10 ** 10, gas=15_000_000, to=b"", value=0,
                                            data=codigo_criacao).as_signed_transaction(CHAVE_TESTE)
        _, recibo, computacao = self.cadeia.apply_transaction(tx)
        if computacao.is_error:
            raise RuntimeError(f"implantacao falhou: {computacao.error}")
        self.nonce += 1
        self.cadeia.mine_block()
        return "0x" + computacao.msg.storage_address.hex()

    def bloco_atual(self):
        return self.cadeia.get_canonical_head().block_number

    @property
    def remetente(self):
        return "0x" + REMETENTE.hex()
