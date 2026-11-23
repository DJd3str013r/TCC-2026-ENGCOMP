// SPDX-License-Identifier: MIT
// Motivo 4 (bloco de metadados). O positivo e implantado a partir deste arquivo e verificado com a copia que difere
// apenas por um comentario (Metadados.comentario.sol, gerada por controles/executar.py); o negativo e outra
// implantacao do mesmo codigo, verificada com este arquivo.
pragma solidity 0.8.37;

contract ControleMetadados {
    uint256 public x;

    function grava(uint256 v) external {
        x = v;
    }
}
// copia submetida a verificacao: difere do original apenas neste comentario
