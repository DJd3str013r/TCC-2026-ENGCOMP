# -*- coding: utf-8 -*-
"""Gera RESULTADOS.md a partir de saidas/resultados.json (nenhum numero digitado a mao).

    python -m analise.resumo_md
"""
import json
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
r = json.loads((RAIZ / "saidas" / "resultados.json").read_text(encoding="utf-8"))
manifesto = json.loads((RAIZ / "dados" / "instantaneo" / "manifesto.json").read_text(encoding="utf-8"))


def d(x, casas=4):
    return f"{x:.{casas}f}".replace(".", ",").replace("-", "−")


def mil(n):
    return f"{n:,}".replace(",", ".")


def ic(a, b):
    return f"[{d(a)}; {d(b)}]"


s, b, am = r["sorteio"], r["base"], r["amostra"]
hc, hs, cob, reg, alv = r["hipotese_central"], r["hipotese_secundaria"], r["cobertura"], r["regioes"], r["alvos"]
val = r["validacao"]
grau = {bool(k): n for k, n in b["base_por_grau"]}
MOTIVOS = [("cborAuxdata", "metadados"), ("immutable", "imutável"), ("library", "biblioteca"),
           ("callProtection", "proteção de chamada")]
CLASSES = [("endereco_nulo", "endereço nulo"), ("proprio_contrato", "próprio contrato"),
           ("conta_sem_codigo", "conta sem código"), ("conta_externa_com_delegacao", "conta externa com delegação"),
           ("contrato_verificado_no_acervo", "contrato verificado no acervo"),
           ("contrato_sem_verificacao_no_acervo", "contrato sem verificação no acervo")]

L = [
    "# Resultados da rodada que alimenta o artigo",
    "",
    "Gerado por `python -m analise.resumo_md` a partir de `saidas/resultados.json`, sem números digitados à mão.",
    "",
    "## Rodada",
    "",
    "| Item | Valor |",
    "|---|---|",
    f"| Instantâneo do acervo | listado em {manifesto.get('listado_em', '?')} |",
    f"| Implantações na rede principal | {mil(b['mainnet_implantacoes'])} |",
    f"| Base de amostragem (Solidity, correspondência no código de execução) | {mil(b['base'])} "
    f"(parcial {mil(grau[False])}; exata {mil(grau[True])}) |",
    f"| Bloco de referência | {mil(s['bloco_referencia'])} ({s['data_bloco_utc']}) |",
    f"| Semente (resumo do bloco) | `{s['hash_bloco']}` |",
    f"| Gerador | {s['gerador']} |",
    f"| Examinados / elegíveis / excluídos | {s['examinados']} / {s['elegiveis']} / {s['excluidos']} |",
    f"| Processados / perdas | {am['processados']} / {len(am['perdas'])} |",
    f"| Amostra por grau | parcial {am['por_grau']['parcial']}; exata {am['por_grau']['exata']} |",
    f"| Verificador | {val['ultima']['verificador']} ({sum(r['historico']['validacoes_por_versao'].values())} rodadas de "
    f"validação antes da última medição e {r['historico']['validacoes_depois_da_ultima_rodada']} depois; todas aprovadas) |",
    f"| Confronto com as transformações do acervo | {r['confronto_acervo']['coincide']} coincidem, "
    f"{r['confronto_acervo']['divergem']} divergem |",
    "",
    "## Validação nos contratos-controle (última rodada antes da medição)",
    "",
    "| Motivo | VP | FP | FN | P | R |",
    "|---|---|---|---|---|---|",
]
for m, v in val["ultima"]["por_motivo"].items():
    L.append(f"| {m} | {v['VP']} | {v['FP']} | {v['FN']} | {d(v['P'], 0)} | {d(v['R'], 0)} |")
L += [
    "",
    f"Compilador dos controles {val['ultima']['compilador_controles']}, "
    f"{val['ultima']['rede'].replace('memoria', 'memória')}; "
    f"divergências de τ: {len(val['ultima']['tau_divergente'])}.",
    "",
    "## Hipóteses",
    "",
    "| Grupo | n | k | p̂ | IC 95% (Wilson) |",
    "|---|---|---|---|---|",
    f"| Amostra | {hc['n']} | {hc['k']} | {d(hc['p'])} | {ic(hc['l'], hc['u'])} |",
    f"| Parcial | {hs['parcial']['n']} | {hs['parcial']['k']} | {d(hs['parcial']['p'])} | {ic(*hs['parcial']['ic'])} |",
    f"| Exata | {hs['exata']['n']} | {hs['exata']['k']} | {d(hs['exata']['p'])} | {ic(*hs['exata']['ic'])} |",
    f"| Diferença entre parcial e exata | | | {d(hs['delta'])} | {ic(hs['L'], hs['U'])} (Newcombe) |",
    "",
    f"- Central (limiar {d(hc['limiar'], 2)}): {hc['decisao']}; decisão firme: {'sim' if hc['decisao_firme'] else 'não'}.",
    f"- Secundária: {hs['decisao']} (intervalo inteiramente negativo: o grau exato tem a fração maior).",
    f"- Sem o positivo que só aponta para o endereço nulo ou para o próprio contrato: "
    f"{d(r['autorreferencia']['total']['p_sem_triviais'])} {ic(*r['autorreferencia']['total']['ic_sem_triviais'])}.",
    "",
    "| Grau e época do compilador | n | positivos |",
    "|---|---|---|",
]
era = r["indicador_por_grau_e_era"]
for k, v in sorted(era.items()):
    if isinstance(v, dict) and "positivos" in v:
        L.append(f"| {k.replace('|', ', ')} | {v['n']} | {v['positivos']} |")
if "a_partir_de_0.6.5_juntos" in era:
    j = era["a_partir_de_0.6.5_juntos"]
    L += ["", f"A partir da 0.6.5, os dois graus juntos (descritivo, não previsto na 3.8): {j['k']} de {j['n']}, "
          f"{d(j['p'])} {ic(*j['ic'])} (Wilson); diferença entre parcial e exata {d(era['delta_a_partir_de_0.6.5'])} "
          f"{ic(*era['newcombe_a_partir_de_0.6.5'])} (Newcombe)."]
L += [
    "",
    "## Cobertura C(a)",
    "",
    "| Grupo | n | mínimo | Q1 | mediana | Q3 | máximo |",
    "|---|---|---|---|---|---|---|",
]
for g in ("total", "parcial", "exata"):
    c = cob[g]
    L.append(f"| {g} | {c['n']} | {d(c['minimo'])} | {d(c['q1'])} | {d(c['mediana'])} | {d(c['q3'])} | {d(c['maximo'])} |")
L += [
    "",
    f"Contratos com C(a) = 1: {cob['contratos_com_cobertura_1']}. Menor cobertura: "
    f"`{r['extremos']['menor_cobertura'][0]['endereco']}` ({r['extremos']['menor_cobertura'][0]['bytes_nao_atestados']} "
    f"de {r['extremos']['menor_cobertura'][0]['tamanho']} bytes não atestados). Mais bytes não atestados: "
    f"`{r['extremos']['mais_bytes'][0]['endereco']}` ({mil(r['extremos']['mais_bytes'][0]['bytes_nao_atestados'])} bytes).",
    "",
    "Figura: `saidas/figuras/figura2_cobertura.png`.",
    "",
    "## Regiões de F(a)",
    "",
    "| Motivo | Regiões | Contratos | Bytes |",
    "|---|---|---|---|",
]
for m, rot in MOTIVOS:
    L.append(f"| {rot} | {reg['regioes_por_motivo'].get(m, 0)} | {reg['contratos_com_motivo'].get(m, 0)} | "
             f"{mil(reg['bytes_por_motivo'].get(m, 0))} |")
cpm = "; ".join(f"{k.split('|')[0]} com τ = {k.split('|')[1]}: {v}"
                 for k, v in reg["constantes_por_motivo_e_tau"].items())
iat = ", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in reg["imutaveis_address_por_tipo"].items())
L += [
    "",
    f"Constantes por motivo e τ: {cpm}. Imutáveis do tipo address por tipo declarado: {iat}. "
    f"Constantes com valores distintos entre regiões: {len(reg['constantes_com_valores_distintos'])}.",
    "",
    "## Classe do alvo",
    "",
    "| Classe | Valores | Contratos |",
    "|---|---|---|",
]
for k, rot in CLASSES:
    L.append(f"| {rot} | {alv['por_valor'][k]} | {alv['por_contrato'][k]} |")
sub = alv["substituivel"]
cc, hist, mp = r["codigo_de_criacao"], r["historico"], r["metadados_parciais"]["por_situacao"]
L += [
    "",
    "Alvos com código e substituíveis pelo padrão ERC-1967: " +
    "; ".join(f"{dict(CLASSES)[k]}: {v['substituiveis']} de {v['com_codigo']}" for k, v in sub.items()) +
    f" ({alv['enderecos_distintos_com_codigo']} endereços distintos).",
    "",
    "## Código de criação (descritivo, não previsto na 3.8)",
    "",
    f"- Correspondência do código de criação registrada no acervo: {cc['com_correspondencia_de_criacao']} de "
    f"{hc['n']} contratos, todos com o mesmo grau da do código de execução ({cc['mesmo_grau']}); entre os positivos, "
    f"{cc['positivos_com_correspondencia_de_criacao']} de {cc['positivos']}.",
    f"- Valores do tipo address que aparecem no código de criação recompilado: {cc['literais']} de {cc['valores']}, "
    f"em {cc['contratos_com_literal']} contratos.",
    f"- Positivos com ao menos um valor fora dos dois confrontos (sem nulo, próprio contrato e literal): "
    f"{cc['positivos_com_valor_fora_dos_dois_confrontos']}, isto é, {d(cc['p'])} {ic(*cc['ic'])}.",
    "",
    "## Metadados nos contratos de correspondência parcial sem bloco em F(a)",
    "",
    f"- Sem bloco no código da cadeia: {mp.get('sem_bloco', 0)}; bloco sem o resumo do arquivo de metadados: "
    f"{mp.get('sem_resumo', 0)}; bloco com resumo: {mp.get('com_resumo', 0)}.",
    "",
    "## Histórico do verificador",
    "",
    "| Versão | Validações | Ensaio (contratos / falhas) | Amostra (processados / falhas) |",
    "|---|---|---|---|",
]
rod = {x["verificador"]: x for x in hist["rodadas_amostra"]}
for ver, nval in hist["validacoes_por_versao"].items():
    en = hist["ensaio"].get(ver)
    am_ = rod.get(ver)
    L.append(f"| {ver} | {nval} | " + (f"{en['contratos']} / {sum(en['falhas'].values())}" if en else "") + " | " +
             (f"{am_['processados']} / {sum(am_['falhas'].values())}" if am_ else "") + " |")
refeitos = "; ".join(f"{sum(x.values())} com a {v}, {x.get('processado', 0)} processadas"
                     for v, x in hist["ensaio_refeitos"].items())
L += [
    "",
    f"Falhas do ensaio refeitas com a versão final: {refeitos}. Diagnóstico de cada falha em "
    "`dados/falhas_diagnosticadas.json`; causas em `PROBLEMAS.md`.",
    "",
]
(RAIZ / "RESULTADOS.md").write_text("\n".join(L), encoding="utf-8")
print(f"RESULTADOS.md: {len(L)} linhas")
