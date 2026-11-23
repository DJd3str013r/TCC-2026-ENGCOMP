# Especificação da certidão (`certidao-atesta/1`)

A certidão é o documento legível por máquina que o verificador emite para cada contrato (objetivo específico b e
subseção 3.6 do artigo). Formato: JSON, UTF-8, um arquivo por contrato (`dados/certidoes/<endereço>.json` na amostra; no
ensaio, `dados/piloto/<endereço>.json` e, nas falhas refeitas, `dados/piloto/refeitos-1.7.0/<endereço>.json`). As dos
oito contratos-controle ficam juntas em `controles/gerados/certidoes_controles.json`, uma por rótulo, com
`acervo.match_id` e `acervo.verificado_em` nulos, porque o registro de verificação dos controles é preparado pelos
autores. Só `amostra/executar.py` e `python -m atesta` acrescentam a classificação do alvo (`constantes[].alvos`); as
certidões do ensaio e as dos controles não a trazem. Endereços e valores em hexadecimal minúsculo com prefixo `0x`;
posições e comprimentos em bytes, a partir do início do código de execução.

## Campos

| Campo | Tipo | Conteúdo |
|---|---|---|
| `esquema` | texto | `certidao-atesta/1` |
| `verificador.nome`, `verificador.versao` | texto | Programa e versão que emitiram a certidão (a versão aprovada nos contratos-controle) |
| `contrato.rede` | inteiro | Identificador da rede (1 = rede principal; 0 = rede de teste local dos controles) |
| `contrato.endereco` | texto | Endereço do contrato |
| `contrato.bloco_referencia` | inteiro | Altura do bloco em que o código foi lido |
| `contrato.tamanho_codigo` | inteiro | Comprimento de c_a, em bytes |
| `contrato.resumo_codigo` | texto | Keccak-256 de c_a |
| `acervo.match_id`, `acervo.match_id_instantaneo`, `acervo.match_id_coincide` | texto, inteiro, booleano | Identificador da verificação fornecida pela API e, só nas certidões da amostra (gravados por `amostra/executar.py`), o vigente no instantâneo e se os dois coincidem |
| `acervo.grau_codigo_execucao`, `acervo.grau_instantaneo` | texto | `exata` ou `parcial` (da API e, só nas certidões da amostra, do instantâneo; a análise usa o do instantâneo) |
| `acervo.grau_codigo_criacao` | texto ou `null` | Grau de correspondência do código de criação registrado pelo acervo (`null` se não houver); desde a 1.7.0 |
| `acervo.compilador`, `acervo.linguagem`, `acervo.contrato_compilado`, `acervo.verificado_em` | texto | Versão longa do compilador, linguagem, nome qualificado e data da verificação |
| `situacao` | texto | `processado` ou `falha` (falha do instrumento; ver `causa`) |
| `causa` | texto | Só na certidão de falha: classe e mensagem do erro. A certidão de falha não traz `recompilacao`, `regioes`, `constantes`, `cobertura`, `bytes_nao_atestados`, `indicador_equacao_2` nem `confronto_acervo` (ver as 14 do ensaio em `dados/piloto/`) |
| `recompilacao.motor` | texto | `solc nativo` (binário oficial) ou `soljson` (compilador oficial em JavaScript) |
| `recompilacao.ajustes_dos_metadados` | lista | Configurações completadas a partir do arquivo de metadados do contrato |
| `recompilacao.tipo_contrato` | texto | `contract`, `library` ou `null` (quando a AST não está disponível) |
| `recompilacao.tamanho_recompilado`, `recompilacao.tamanho_cadeia` | inteiro | Comprimentos de R e de c_a, em bytes |
| `recompilacao.blocos_removidos` | inteiro | Blocos de metadados que o acervo registra como removidos do código da cadeia |
| `recompilacao.metadados_em_F` | booleano | Se os blocos de metadados entraram em F(a) |
| `recompilacao.posicoes_metadados` | texto | Origem das posições dos blocos de metadados (`acervo` ou `dois_ultimos_bytes`), só quando entraram em F(a) |
| `regioes[]` | lista | Uma por região de F(a): `inicio`, `comprimento`, `motivo` (`immutable`, `library`, `callProtection`, `cborAuxdata`), `construto`, `valor` (bytes lidos da cadeia), `tipo` (tipo declarado ou `address`/`metadados`), `tau_address` |
| `regioes[].construto` | texto | `imutavel:<id na AST>`, `biblioteca:<arquivo>:<nome>`, `protecao_de_chamada` (ou `protecao_de_chamada:viaIR`) ou `metadados:<id>` |
| `constantes[]` | lista | Uma por construto (exceto metadados): `construto`, `motivo`, `tipo`, `tau_address`, `regioes` (quantas), `valores` (endereços de 20 bytes se `tau_address`; senão, a palavra lida), `valores_distintos` |
| `constantes[].alvos` | objeto | Para cada valor do tipo address: `classe` (endereco_nulo, proprio_contrato, conta_sem_codigo, conta_externa_com_delegacao, contrato_verificado_no_acervo, contrato_sem_verificacao_no_acervo), `substituivel` (ERC-1967; `null` quando o alvo não tem código, isto é, no endereço nulo e na conta sem código; desde a 1.7.0 também calculado para o próprio contrato) e, quando houver, `erc1967_implementacao`, `erc1967_beacon`, `delegado`, `tamanho_codigo`; só em `contrato_sem_verificacao_no_acervo`, `verificado_com_outro_codigo` (verdadeiro quando o instantâneo registra verificação do endereço com outro código) |
| `constantes[].literais_no_codigo_de_criacao` | lista | Só nas constantes do tipo address: os valores (exceto o endereço nulo) que aparecem no código de criação recompilado, isto é, que constam do próprio código compilado e que o confronto do código de criação alcança; desde a 1.7.0. A busca é pelos 20 bytes do valor: não acha o endereço com bytes nulos à esquerda, que o compilador grava em instrução PUSH mais curta, e acha também o valor recebido por argumento de construtor quando ele aparece em outro ponto do código, como numa constante. Na amostra, os três valores achados são literais atribuídos no construtor, e a análise confere isso no código-fonte (`analise/analisar.py`, `codigo_de_criacao`) |
| `cobertura` | número | C(a), Equação (1) |
| `bytes_nao_atestados` | inteiro | Soma dos comprimentos das regiões de F(a) |
| `indicador_equacao_2` | 0 ou 1 | Indicador da Equação (2): alguma região de F(a) com τ(r) = address |
| `confronto_acervo` | objeto | `coincide`, `so_no_acervo`, `so_no_verificador`: comparação (motivo, início) com as transformações registradas no acervo |
| `segundos` | número | Tempo de processamento |
| `ordem` | inteiro | Posição do contrato na permutação do sorteio (só nas certidões da amostra, gravada por `amostra/executar.py`) |

## Uso por terceiros

Uma equipe de integração lê `indicador_equacao_2` e, se for 1, percorre `constantes[]` com `tau_address` verdadeiro:
cada valor é um endereço gravado na implantação que o confronto do código de execução não alcançou; se o valor está em
`literais_no_codigo_de_criacao` e `acervo.grau_codigo_criacao` não é `null`, o valor consta do código de criação
confrontado, o que, ressalvados os limites desse campo, indica que esse confronto o alcança. `alvos` diz para que tipo
de conta ele aponta e se o alvo é um *proxy* ERC-1967. As Equações (2), (3) e (5) podem ser recalculadas só com
`indicador_equacao_2` e `acervo.grau_instantaneo`.
