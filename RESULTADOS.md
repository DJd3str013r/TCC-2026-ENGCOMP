# Resultados da rodada que alimenta o artigo

Gerado por `python -m analise.resumo_md` a partir de `saidas/resultados.json`, sem números digitados à mão.

## Rodada

| Item | Valor |
|---|---|
| Instantâneo do acervo | listado em 2026-10-29T05:30:04+00:00 |
| Implantações na rede principal | 8.372.084 |
| Base de amostragem (Solidity, correspondência no código de execução) | 8.274.941 (parcial 7.350.722; exata 924.219) |
| Bloco de referência | 26.296.341 (2026-10-29T05:35:35+00:00) |
| Semente (resumo do bloco) | `0x3f17a1f32676e57461a80b819efbe1fa59a0477cc0cae6b812ae6e337b9f9570` |
| Gerador | numpy 2.5.4 PCG64, permutation(N) |
| Examinados / elegíveis / excluídos | 385 / 385 / 0 |
| Processados / perdas | 385 / 0 |
| Amostra por grau | parcial 337; exata 48 |
| Verificador | 1.7.0 (16 rodadas de validação antes da última medição e 1 depois; todas aprovadas) |
| Confronto com as transformações do acervo | 385 coincidem, 0 divergem |

## Validação nos contratos-controle (última rodada antes da medição)

| Motivo | VP | FP | FN | P | R |
|---|---|---|---|---|---|
| immutable | 14 | 0 | 0 | 1 | 1 |
| library | 2 | 0 | 0 | 1 | 1 |
| callProtection | 1 | 0 | 0 | 1 | 1 |
| cborAuxdata | 1 | 0 | 0 | 1 | 1 |

Compilador dos controles 0.8.37+commit.f401782d, py-evm em memória (Cancun); divergências de τ: 0.

## Hipóteses

| Grupo | n | k | p̂ | IC 95% (Wilson) |
|---|---|---|---|---|
| Amostra | 385 | 13 | 0,0338 | [0,0198; 0,0569] |
| Parcial | 337 | 6 | 0,0178 | [0,0082; 0,0383] |
| Exata | 48 | 7 | 0,1458 | [0,0725; 0,2717] |
| Diferença entre parcial e exata | | | −0,1280 | [−0,2542; −0,0519] (Newcombe) |

- Central (limiar 0,10): refutada; decisão firme: sim.
- Secundária: refutada (intervalo inteiramente negativo: o grau exato tem a fração maior).
- Sem o positivo que só aponta para o endereço nulo ou para o próprio contrato: 0,0312 [0,0179; 0,0537].

| Grau e época do compilador | n | positivos |
|---|---|---|
| exata, a partir de 0.6.5 | 46 | 7 |
| exata, antes de 0.6.5 | 2 | 0 |
| parcial, a partir de 0.6.5 | 57 | 5 |
| parcial, antes de 0.6.5 | 280 | 1 |

A partir da 0.6.5, os dois graus juntos (descritivo, não previsto na 3.8): 12 de 103, 0,1165 [0,0679; 0,1927] (Wilson); diferença entre parcial e exata −0,0645 [−0,2037; 0,0628] (Newcombe).

## Cobertura C(a)

| Grupo | n | mínimo | Q1 | mediana | Q3 | máximo |
|---|---|---|---|---|---|---|
| total | 385 | 0,1613 | 0,9211 | 0,9615 | 0,9901 | 1,0000 |
| parcial | 337 | 0,1613 | 0,9211 | 0,9483 | 0,9718 | 1,0000 |
| exata | 48 | 0,7366 | 1,0000 | 1,0000 | 1,0000 | 1,0000 |

Contratos com C(a) = 1: 44. Menor cobertura: `0x73b6e45c3d4ef160dd7bed6551b154919c382b4a` (52 de 62 bytes não atestados). Mais bytes não atestados: `0xae0f58c408514e60cc6d844cc80965aeab4bf6ff` (3.072 bytes).

Figura: `saidas/figuras/figura2_cobertura.png`.

## Regiões de F(a)

| Motivo | Regiões | Contratos | Bytes |
|---|---|---|---|
| metadados | 331 | 331 | 15.147 |
| imutável | 256 | 15 | 8.192 |
| biblioteca | 4 | 1 | 80 |
| proteção de chamada | 0 | 0 | 0 |

Constantes por motivo e τ: immutable com τ = address: 37; immutable com τ = outro: 39; library com τ = address: 1. Imutáveis do tipo address por tipo declarado: address: 17, contrato ou interface: 20. Constantes com valores distintos entre regiões: 0.

## Classe do alvo

| Classe | Valores | Contratos |
|---|---|---|
| endereço nulo | 2 | 1 |
| próprio contrato | 3 | 3 |
| conta sem código | 1 | 1 |
| conta externa com delegação | 0 | 0 |
| contrato verificado no acervo | 31 | 11 |
| contrato sem verificação no acervo | 1 | 1 |

Alvos com código e substituíveis pelo padrão ERC-1967: contrato verificado no acervo: 0 de 31; próprio contrato: 0 de 3; contrato sem verificação no acervo: 0 de 1 (31 endereços distintos).

## Código de criação (descritivo, não previsto na 3.8)

- Correspondência do código de criação registrada no acervo: 361 de 385 contratos, todos com o mesmo grau da do código de execução (361); entre os positivos, 13 de 13.
- Valores do tipo address que aparecem no código de criação recompilado: 3 de 38, em 2 contratos.
- Positivos com ao menos um valor fora dos dois confrontos (sem nulo, próprio contrato e literal): 12, isto é, 0,0312 [0,0179; 0,0537].

## Metadados nos contratos de correspondência parcial sem bloco em F(a)

- Sem bloco no código da cadeia: 4; bloco sem o resumo do arquivo de metadados: 2; bloco com resumo: 0.

## Histórico do verificador

| Versão | Validações | Ensaio (contratos / falhas) | Amostra (processados / falhas) |
|---|---|---|---|
| 1.0.0 | 2 | 80 / 14 |  |
| 1.1.0 | 2 | 80 / 3 |  |
| 1.2.0 | 2 | 160 / 0 |  |
| 1.3.0 | 2 |  | 381 / 4 |
| 1.4.0 | 2 |  |  |
| 1.5.0 | 2 |  | 384 / 1 |
| 1.6.0 | 2 |  | 385 / 0 |
| 1.7.0 | 2 |  | 385 / 0 |

Falhas do ensaio refeitas com a versão final: 14 com a 1.7.0, 14 processadas. Diagnóstico de cada falha em `dados/falhas_diagnosticadas.json`; causas em `PROBLEMAS.md`.
