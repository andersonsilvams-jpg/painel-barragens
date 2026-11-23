# Fiscalização de Barragens de Mineração — CREA-MS

Painel Streamlit de apoio à fiscalização do exercício profissional em barragens de mineração.

**Fonte:** ANM — SIGBM, dados abertos: https://dadosabertos.anm.gov.br/SIGBM/Barragens.csv
(baixado automaticamente, cache de 12 h; se o download falhar, envie o CSV pela barra lateral).

## Páginas
- **app.py — Mineração (ANM/SIGBM):** barragens de mineração, com CPF/CNPJ do empreendedor e responsável técnico
- **pages/2_Todas_as_barragens_ANA.py — SNISB (ANA):** todas as barragens de qualquer uso, por UF, consultadas no serviço ArcGIS da ANA
  (https://www.snirh.gov.br/arcgis/rest/services/IG/SNISB/FeatureServer/0). O SNISB não traz CNPJ, então o cruzamento com o Crea é pelo nome.

## O que faz (página de mineração)
- Filtros por UF (padrão MS), município, empreendedor, DPA, CRI, nível de emergência, situação e PNSB
- Mapa com satélite Esri (cor = DPA, tamanho = prioridade)
- Lista de prioridades com motivos, exportável em Excel/CSV
- Ficha da barragem com o responsável técnico declarado no SIGBM e todas as colunas originais
- Cruzamento com planilha do Crea (ARTs/registros) pelo CPF/CNPJ do empreendedor

## Prioridade
DPA alto +3 / médio +1 · CRI alto +3 / médio +1 · emergência +4 · montante/desconhecido +2 ·
descaracterização +1 · população a jusante +1 · DCE com mais de ~13 meses +2 · sem ART no Crea +3

## Publicar
1. Repositório no GitHub com `app.py`, `pages/`, `requirements.txt` e este README
2. Em share.streamlit.io → New app → escolher o repositório, arquivo principal `app.py`
