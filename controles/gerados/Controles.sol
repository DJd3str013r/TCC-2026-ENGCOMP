// SPDX-License-Identifier: MIT
// Contratos-controle do TCC (subsecao 3.4). Modelo: os campos {{...}} sao preenchidos por controles/executar.py com
// os valores usados na implantacao; a versao preenchida fica em controles/gerados/.
pragma solidity 0.8.37;

/// Alvo auxiliar com codigo (nao e controle): da aos tipos de contrato e de interface um endereco com codigo.
interface IAlvo {
    function valor() external view returns (uint256);
}

contract Alvo is IAlvo {
    function valor() external pure returns (uint256) {
        return 42;
    }
}

/// Tipos de valor definidos pelo usuario sobre address e sobre address payable.
type Endereco is address;
type EnderecoPagavel is address payable;

/// Motivo 1, positivo: variaveis imutaveis de cada tipo que o criterio de tau(r) = address abrange e uma uint256.
contract ControleImutavelPositivo {
    address public immutable a1;
    address payable public immutable a2;
    Alvo public immutable a3;
    IAlvo public immutable a4;
    Endereco public immutable a5;
    EnderecoPagavel public immutable a6;
    uint256 public immutable n1;

    constructor(address x1, address payable x2, Alvo x3, IAlvo x4, Endereco x5, EnderecoPagavel x6, uint256 y) {
        a1 = x1;
        a2 = x2;
        a3 = x3;
        a4 = x4;
        a5 = x5;
        a6 = x6;
        n1 = y;
    }

    function soma() external view returns (uint256) {
        return n1 + uint160(a1) + uint160(address(a2)) + uint160(address(a3)) + uint160(address(a4))
            + uint160(Endereco.unwrap(a5)) + uint160(address(EnderecoPagavel.unwrap(a6)));
    }
}

/// Motivo 1, negativo: os mesmos valores como constantes (constant), gravados pelo compilador no proprio codigo.
contract ControleImutavelNegativo {
    address public constant a1 = 0x1111111111111111111111111111111111111111;
    address payable public constant a2 = payable(0x1a642f0E3c3aF545E7AcBD38b07251B3990914F1);
    Alvo public constant a3 = Alvo(0x32dCAB0EF3FB2De2fce1D2E0799D36239671F04A);
    IAlvo public constant a4 = IAlvo(0x32dCAB0EF3FB2De2fce1D2E0799D36239671F04A);
    Endereco public constant a5 = Endereco.wrap(0x0000000000000000000000000000000000000000);
    EnderecoPagavel public constant a6 = EnderecoPagavel.wrap(payable(0x2222222222222222222222222222222222222222));
    uint256 public constant n1 = 123456789;

    function soma() external pure returns (uint256) {
        return n1 + uint160(a1) + uint160(address(a2)) + uint160(address(a3)) + uint160(address(a4))
            + uint160(Endereco.unwrap(a5)) + uint160(address(EnderecoPagavel.unwrap(a6)));
    }
}

/// Motivo 3, positivo: biblioteca implantada, com funcao externa que altera estado (protecao de chamada).
library BibliotecaControle {
    struct Caixa {
        uint256 v;
    }

    function grava(Caixa storage c, uint256 v) external {
        c.v = v;
    }

    function dobro(uint256 x) external pure returns (uint256) {
        return 2 * x;
    }
}

/// Motivo 3, negativo: contrato comum de mesma funcao.
contract ControleChamadaNegativo {
    uint256 public v;

    function grava(uint256 x) external {
        v = x;
    }

    function dobro(uint256 x) external pure returns (uint256) {
        return 2 * x;
    }
}

/// Motivo 2: contrato que chama a biblioteca do controle de protecao de chamada. Positivo: vinculada apos a
/// compilacao (marcador na saida do compilador). Negativo: o mesmo codigo-fonte compilado com o endereco da
/// biblioteca informado ao compilador.
contract ControleBiblioteca {
    BibliotecaControle.Caixa private c;

    function usa(uint256 x) external returns (uint256) {
        BibliotecaControle.grava(c, x);
        return BibliotecaControle.dobro(c.v);
    }
}
