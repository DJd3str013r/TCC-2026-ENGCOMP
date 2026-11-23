# -*- coding: utf-8 -*-
"""atesta: verificador de cobertura de atestacao de contratos verificados (TCC, Engenharia da Computacao, 2026/2).

Dado um endereco da rede principal e um bloco de referencia, recompila o contrato com a entrada que o acervo do
Sourcify guarda, delimita no codigo de execucao lido da cadeia as regioes nao atestadas (transformacoes de
substituicao ou insercao), atribui a cada uma o construto do codigo-fonte, materializa o valor gravado, calcula a
cobertura de atestacao (Equacao 1 do artigo) e o indicador da Equacao (2), classifica o alvo das constantes do tipo
address e emite a certidao em JSON."""

VERSAO = "1.7.0"
