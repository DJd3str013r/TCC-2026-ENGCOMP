# -*- coding: utf-8 -*-
"""Validacao do verificador nos oito contratos-controle (P = R = 1 por motivo e tau conferido) e ensaio adicional do
caminho viaIR da protecao de chamada (entrada library_deploy_address), previsto na subsecao 3.4."""
import json

from atesta.compilador import executavel
from atesta.rpc import ProvedorMemoria
from atesta.verificador import verificar
from controles import executar as ctl
from controles.rede_local import RedeLocal


def test_oito_controles_aprovam():
    v = ctl.main(registrar=False)   # o teste nao entra no historico oficial de validacao (P-20)
    assert v["aprovado"] and not v["tau_divergente"] and not v["tipo_divergente"]
    for m in ("immutable", "library", "callProtection", "cborAuxdata"):
        assert v["por_motivo"][m]["P"] == 1 and v["por_motivo"][m]["R"] == 1
        assert v["por_motivo"][m]["VP"] >= 1


def test_protecao_de_chamada_via_ir():
    import subprocess
    fonte = (ctl.AQUI / "gerados" / "Controles.sol").read_text(encoding="utf-8")
    std = ctl.entrada({"Controles.sol": fonte}, via_ir=True)
    e = json.loads(json.dumps(std))
    e["settings"]["outputSelection"] = {"Controles.sol": {"BibliotecaControle": [
        "evm.bytecode.object", "evm.deployedBytecode.immutableReferences"]}}
    s = json.loads(subprocess.run([str(executavel(ctl.versao_longa())), "--standard-json"],
                                  input=json.dumps(e).encode(), capture_output=True, check=True).stdout)
    c = s["contracts"]["Controles.sol"]["BibliotecaControle"]
    assert "library_deploy_address" in c["evm"]["deployedBytecode"]["immutableReferences"]
    rede = RedeLocal()
    end = rede.implantar(bytes.fromhex(c["evm"]["bytecode"]["object"]))
    reg = ctl.registro(std, "Controles.sol", "BibliotecaControle", "exact_match")
    cert = verificar(end, rede.bloco_atual(), ProvedorMemoria(rede.cadeia), reg, rede=0)
    assert cert["situacao"] == "processado", cert.get("causa")
    regs = [r for r in cert["regioes"] if r["motivo"] == "callProtection"]
    assert regs and all(r["construto"] == "protecao_de_chamada:viaIR" for r in regs)
    assert all(r["valor"].endswith(end[2:].lower()) for r in regs)
    assert cert["indicador_equacao_2"] == 1


def test_literal_no_codigo_de_criacao():
    """Valor de imutavel atribuido por literal do codigo-fonte aparece no codigo de criacao recompilado; o recebido
    como argumento de construtor, nao (P-18)."""
    fonte = ("// SPDX-License-Identifier: MIT\npragma solidity 0.8.37;\n"
             "contract ImutavelLiteral {\n"
             "    address public immutable x = 0x3333333333333333333333333333333333333333;\n"
             "    address public immutable y;\n"
             "    constructor(address a) { y = a; }\n"
             "}\n")
    std = ctl.entrada({"Literal.sol": fonte})
    c, _ = ctl.criacao(std, "Literal.sol", "ImutavelLiteral")
    rede = RedeLocal()
    arg = "0x4444444444444444444444444444444444444444"
    end = rede.implantar(bytes.fromhex(c["evm"]["bytecode"]["object"]) + bytes.fromhex(ctl.palavra(arg)[2:]))
    reg = ctl.registro(std, "Literal.sol", "ImutavelLiteral", "exact_match")
    cert = verificar(end, rede.bloco_atual(), ProvedorMemoria(rede.cadeia), reg, rede=0)
    assert cert["situacao"] == "processado", cert.get("causa")
    lit = {tuple(k["valores"]): k["literais_no_codigo_de_criacao"] for k in cert["constantes"]}
    assert lit[("0x3333333333333333333333333333333333333333",)] == ["0x3333333333333333333333333333333333333333"]
    assert lit[(arg,)] == []
