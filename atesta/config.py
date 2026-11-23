# -*- coding: utf-8 -*-
"""Caminhos, enderecos de servico e constantes. Valores locais (sem segredo) podem ser trocados em .env.local."""
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DADOS = RAIZ / "dados"
SAIDAS = RAIZ / "saidas"
CACHE = RAIZ / ".cache"
SOLC_DIR = CACHE / "solc"
INSTANTANEO = DADOS / "instantaneo"
CERTIDOES = DADOS / "certidoes"


def _env_local():
    arq = RAIZ / ".env.local"
    valores = {}
    if arq.exists():
        for linha in arq.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if linha and not linha.startswith("#") and "=" in linha:
                k, v = linha.split("=", 1)
                valores[k.strip()] = v.strip()
    return valores


_ENV = _env_local()

# Nos JSON-RPC publicos da rede principal com estado historico, sem chave (conferidos em 29/10/2026).
RPCS_REDE_PRINCIPAL = [u.strip() for u in _ENV.get("RPCS", os.environ.get("ATESTA_RPCS", "")).split(",") if u.strip()] or [
    "https://eth.drpc.org",
    "https://1rpc.io/eth",
    "https://eth-mainnet.public.blastapi.io",
]

SOURCIFY_API = _ENV.get("SOURCIFY_API", "https://sourcify.dev/server")
EXPORT_BASE = _ENV.get("EXPORT_BASE", "https://export.sourcify.dev/")
SOLC_LISTA = "https://binaries.soliditylang.org/windows-amd64/list.json"
SOLC_BASE = "https://binaries.soliditylang.org/windows-amd64/"

# ERC-1967: bytes32(uint256(keccak256('eip1967.proxy.X')) - 1), recalculados localmente
SLOT_IMPLEMENTACAO = 0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc
SLOT_BEACON = 0xa3f0ad74e5423aebfd80d3ef4346578335a9a72aeaee59ff6cb3582b35133d50

# EIP-7702: designador de delegacao = 0xef0100 || endereco (23 bytes)
PREFIXO_DELEGACAO = bytes.fromhex("ef0100")

TAMANHO_AMOSTRA = 385
REDE_PRINCIPAL = 1

for d in (DADOS, SAIDAS, CACHE, SOLC_DIR, INSTANTANEO, CERTIDOES):
    d.mkdir(parents=True, exist_ok=True)
