"""
Todas as barragens cadastradas no SNISB (ANA) — qualquer uso: água, irrigação, energia, rejeitos etc.
Fonte: https://www.snirh.gov.br/arcgis/rest/services/IG/SNISB/FeatureServer/0
"""

import io
import re
import unicodedata
from datetime import datetime

import folium
import pandas as pd
import requests
import streamlit as st
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium

URL_SNISB = "https://www.snirh.gov.br/arcgis/rest/services/IG/SNISB/FeatureServer/0/query"
URL_PORTAL = "https://www.snisb.gov.br/portal-snisb/consultar-barragem"
UFS = ["AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA", "PB", "PE", "PI",
       "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO"]

st.set_page_config(page_title="Barragens SNISB (ANA) — CREA-MS", page_icon="💧", layout="wide")


def norm(s) -> str:
    s = unicodedata.normalize("NFD", "" if s is None or (isinstance(s, float) and pd.isna(s)) else str(s))
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^A-Z0-9]+", " ", s.upper()).strip()


def sim(v) -> bool:
    return norm(v).startswith("SIM") or norm(v) in ("S", "1", "1 0")


def nivel(v) -> str:
    n = norm(v)
    if n.startswith("ALT"):
        return "Alto"
    if n.startswith("MED"):
        return "Médio"
    if n.startswith("BAIX"):
        return "Baixo"
    return "" if not n else str(v)


@st.cache_data(ttl=60 * 60 * 12, show_spinner="Consultando o SNISB (ANA)...")
def baixar_snisb(uf: str) -> tuple[pd.DataFrame, str]:
    linhas, offset = [], 0
    while True:
        params = {
            "where": f"ING_SG_UFMUNICIPIO = '{uf}'",
            "outFields": "*",
            "returnGeometry": "false",
            "orderByFields": "BAR_CD_SNISB",
            "resultOffset": offset,
            "resultRecordCount": 2000,
            "f": "json",
        }
        r = requests.get(URL_SNISB, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=90)
        r.raise_for_status()
        js = r.json()
        if "error" in js:
            raise RuntimeError(js["error"].get("message", js["error"]))
        feats = js.get("features", [])
        linhas += [f["attributes"] for f in feats]
        if not feats or not js.get("exceededTransferLimit"):
            break
        offset += len(feats)
    df = pd.DataFrame(linhas)
    for c in [c for c in df.columns if c.startswith(("BAR_DT", "INS_DT", "AUT_DT"))]:
        df[c] = pd.to_datetime(df[c], unit="ms", errors="coerce")
    return df, datetime.now().strftime("%d/%m/%Y %H:%M")


def pontuar(r) -> tuple[int, str]:
    p, m = 0, []
    dpa, cri = nivel(r.get("DANO_POTENCIAL")), nivel(r.get("CATEGORIA_RISCO"))
    pnsb = sim(r.get("REGULADA_PELO_PNSB"))
    if dpa == "Alto":
        p += 3; m.append("DPA alto")
    elif dpa == "Médio":
        p += 1; m.append("DPA médio")
    if cri == "Alto":
        p += 3; m.append("risco alto")
    elif cri == "Médio":
        p += 1; m.append("risco médio")
    if pnsb:
        p += 1; m.append("na PNSB")
        if not sim(r.get("POSSUI_PLANO_SEGURANCA")):
            p += 2; m.append("sem Plano de Segurança")
        if not sim(r.get("POSSUI_REVISAO_PERIODICA")):
            p += 1; m.append("sem Revisão Periódica")
        insp = r.get("INS_DT_INSPECAO")
        if pd.isna(insp):
            p += 2; m.append("sem inspeção registrada")
        elif (pd.Timestamp.now() - insp).days > 400:
            p += 2; m.append("inspeção com mais de 1 ano")
    if dpa == "Alto" and not sim(r.get("POSSUI_PAE")):
        p += 2; m.append("DPA alto sem PAE")
    perigo = norm(r.get("NIVEL_PERIGO"))
    if any(k in perigo for k in ("ALERTA", "EMERG", "ATENCAO")):
        p += 4; m.append(f"perigo: {r.get('NIVEL_PERIGO')}")
    if sim(r.get("BARRAGEM_AUTUADA")):
        p += 1; m.append("já autuada pelo fiscalizador")
    return p, ", ".join(m)


def ler_planilha(arq) -> pd.DataFrame:
    if arq.name.lower().endswith((".xlsx", ".xls")):
        return pd.read_excel(arq, dtype=str)
    bruto = arq.getvalue()
    for enc in ("utf-8-sig", "cp1252"):
        try:
            txt = bruto.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    sep = ";" if txt.splitlines()[0].count(";") > txt.splitlines()[0].count(",") else ","
    return pd.read_csv(io.StringIO(txt), sep=sep, dtype=str, keep_default_na=False)


SUFIXOS = r"\b(LTDA|S A|SA|EIRELI|ME|EPP|CIA|COMPANHIA|DE|DA|DO|DOS|DAS|E)\b"


def chave_nome(s) -> str:
    return re.sub(r"\s+", " ", re.sub(SUFIXOS, " ", norm(s))).strip()


# ---------------------------------------------------------------------------
st.title("💧 Todas as barragens — SNISB (ANA)")
st.caption("Qualquer uso: abastecimento, irrigação, dessedentação, energia, rejeitos. Fonte: ANA — SNISB.")

with st.sidebar:
    st.header("Consulta")
    uf = st.selectbox("UF", UFS, index=UFS.index("MS"))
    if st.button("🔄 Recarregar da ANA"):
        baixar_snisb.clear()

try:
    df, quando = baixar_snisb(uf)
except Exception as e:  # noqa: BLE001
    st.error(f"Não consegui consultar o SNISB ({e}). Tente recarregar em alguns minutos.")
    st.stop()

if df.empty:
    st.warning(f"Nenhuma barragem retornada para {uf}.")
    st.stop()

df["DPA"] = df.get("DANO_POTENCIAL", "").map(nivel)
df["CRI"] = df.get("CATEGORIA_RISCO", "").map(nivel)
pr = df.apply(pontuar, axis=1)
df["prioridade"] = [x[0] for x in pr]
df["motivos"] = [x[1] for x in pr]

with st.sidebar:
    st.header("Filtros")

    def ms(rotulo, col):
        if col not in df:
            return []
        return st.multiselect(rotulo, sorted(v for v in df[col].dropna().astype(str).unique() if v.strip()))

    mun_sel = ms("Município", "ING_NM_MUNICIPIO")
    uso_sel = ms("Uso principal", "USO_PRINCIPAL")
    org_sel = ms("Órgão fiscalizador", "ORG_NM_ORGANIZACAO")
    dpa_sel = ms("Dano Potencial (DPA)", "DPA")
    cri_sel = ms("Categoria de Risco (CRI)", "CRI")
    pnsb_sel = ms("Regulada pela PNSB", "REGULADA_PELO_PNSB")
    fase_sel = ms("Fase de vida", "FASE_DE_VIDA")
    so_pend = st.checkbox("Só com pendência (prioridade ≥ 4)")
    busca = st.text_input("Buscar (barragem ou empreendedor)")

    st.header("Cruzamento com o Crea")
    arq_crea = st.file_uploader("Planilha de ARTs/registros (CSV ou Excel)", type=["csv", "xlsx", "xls"], key="crea_ana")

f = df.copy()
for col, sel in [("ING_NM_MUNICIPIO", mun_sel), ("USO_PRINCIPAL", uso_sel), ("ORG_NM_ORGANIZACAO", org_sel),
                 ("DPA", dpa_sel), ("CRI", cri_sel), ("REGULADA_PELO_PNSB", pnsb_sel), ("FASE_DE_VIDA", fase_sel)]:
    if sel:
        f = f[f[col].astype(str).isin(sel)]
if so_pend:
    f = f[f["prioridade"] >= 4]
if busca:
    b = norm(busca)
    f = f[f["BAR_NM_NOME"].map(norm).str.contains(b, regex=False) | f["NM_EMPREENDEDOR"].map(norm).str.contains(b, regex=False)]

if arq_crea is not None:
    try:
        crea = ler_planilha(arq_crea)
        sug = next((c for c in crea.columns if any(k in norm(c) for k in ("CONTRATANTE", "NOME", "RAZAO", "PROPRIET"))), crea.columns[0])
        col_nome = st.sidebar.selectbox("Coluna com o nome do contratante/empresa", list(crea.columns),
                                        index=list(crea.columns).index(sug))
        nomes = set(crea[col_nome].map(chave_nome)) - {""}
        f = f.copy()
        f["crea"] = f["NM_EMPREENDEDOR"].map(
            lambda n: "sem empreendedor no SNISB" if not chave_nome(n) else ("encontrado" if chave_nome(n) in nomes else "NÃO encontrado"))
        mask = f["crea"] == "NÃO encontrado"
        f.loc[mask, "prioridade"] += 3
        f.loc[mask, "motivos"] = f.loc[mask, "motivos"].map(lambda s: (s + ", " if s else "") + "sem ART no Crea")
        st.sidebar.caption("O SNISB não traz CPF/CNPJ do empreendedor: o cruzamento é pelo nome e pode falhar "
                           "em abreviações. Confira os 'NÃO encontrado' antes de agir.")
    except Exception as e:  # noqa: BLE001
        st.sidebar.error(f"Não consegui ler a planilha: {e}")

f = f.sort_values(["prioridade", "BAR_NM_NOME"], ascending=[False, True])

st.caption(f"{uf}: {len(df)} barragens no SNISB · consultado em {quando}")
k = st.columns(6)
k[0].metric("Barragens", len(f))
k[1].metric("Na PNSB", int(f["REGULADA_PELO_PNSB"].map(sim).sum()) if "REGULADA_PELO_PNSB" in f else 0)
k[2].metric("DPA alto", int((f["DPA"] == "Alto").sum()))
k[3].metric("Risco alto", int((f["CRI"] == "Alto").sum()))
k[4].metric("PNSB sem Plano de Segurança", int(f.apply(lambda r: sim(r.get("REGULADA_PELO_PNSB")) and not sim(r.get("POSSUI_PLANO_SEGURANCA")), axis=1).sum()) if len(f) else 0)
k[5].metric("Sem empreendedor", int(f["NM_EMPREENDEDOR"].map(lambda x: not norm(x)).sum()))

aba_mapa, aba_tab, aba_ficha, aba_resumo = st.tabs(["🗺️ Mapa", "📋 Prioridades", "🔎 Ficha", "📊 Resumo"])

COLS = {
    "prioridade": "Prioridade", "motivos": "Motivos", "crea": "ART/registro no Crea",
    "BAR_NM_NOME": "Barragem", "NM_EMPREENDEDOR": "Empreendedor", "ING_NM_MUNICIPIO": "Município",
    "USO_PRINCIPAL": "Uso principal", "DPA": "DPA", "CRI": "CRI", "REGULADA_PELO_PNSB": "PNSB",
    "POSSUI_PLANO_SEGURANCA": "Plano de Segurança", "POSSUI_PAE": "PAE", "POSSUI_REVISAO_PERIODICA": "Revisão Periódica",
    "INS_DT_INSPECAO": "Última inspeção", "TP_INSPECAO": "Tipo inspeção",
    "BAR_NU_ALT_MAX_NIVEL_TERRENO": "Altura (m)", "BAR_NU_CAP_TOTAL_RESERV": "Capacidade (hm³)",
    "ORG_NM_ORGANIZACAO": "Fiscalizador", "FASE_DE_VIDA": "Fase de vida", "AUT_NU_AUTORIZACAO": "Outorga/licença",
    "BARRAGEM_AUTUADA": "Autuada", "COMPLETUDE": "Completude cadastro", "BAR_CD_SNISB": "Código SNISB",
}
cols = [c for c in COLS if c in f.columns]

with aba_mapa:
    pts = f.dropna(subset=["BAR_NU_LATITUDE", "BAR_NU_LONGITUDE"])
    if pts.empty:
        st.info("Nenhuma barragem com coordenada nos filtros.")
    else:
        mapa = folium.Map(location=[pts["BAR_NU_LATITUDE"].mean(), pts["BAR_NU_LONGITUDE"].mean()], zoom_start=6, tiles=None)
        folium.TileLayer(tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
                         attr="Esri", name="Satélite (Esri)").add_to(mapa)
        folium.TileLayer("OpenStreetMap", name="Mapa").add_to(mapa)
        grupo = MarkerCluster(disableClusteringAtZoom=11).add_to(mapa) if len(pts) > 300 else mapa
        cor = {"Alto": "red", "Médio": "orange", "Baixo": "green"}
        for _, r in pts.head(3000).iterrows():
            html = (f"<b>{r['BAR_NM_NOME']}</b><br>{r.get('NM_EMPREENDEDOR') or '-'}<br>{r.get('ING_NM_MUNICIPIO')}<br>"
                    f"Uso: {r.get('USO_PRINCIPAL') or '-'}<br>DPA: {r['DPA'] or '-'} · CRI: {r['CRI'] or '-'}<br>"
                    f"<b>Prioridade {r['prioridade']}</b><br>{r['motivos']}")
            folium.CircleMarker([r["BAR_NU_LATITUDE"], r["BAR_NU_LONGITUDE"]], radius=4 + min(r["prioridade"], 10),
                                color=cor.get(r["DPA"], "gray"), fill=True, fill_opacity=0.8,
                                popup=folium.Popup(html, max_width=300), tooltip=r["BAR_NM_NOME"]).add_to(grupo)
        folium.LayerControl().add_to(mapa)
        st_folium(mapa, height=580, use_container_width=True, returned_objects=[])
        st.caption("Cor = DPA (vermelho alto, laranja médio, verde baixo, cinza sem classificação). Tamanho = prioridade."
                   + (" Mostrando as 3.000 primeiras por prioridade." if len(pts) > 3000 else ""))

with aba_tab:
    tab = f[cols].rename(columns=COLS)
    st.dataframe(tab, width="stretch", hide_index=True, height=500)
    c1, c2 = st.columns(2)
    buf = io.BytesIO()
    tab.to_excel(buf, index=False)
    c1.download_button("⬇️ Excel", buf.getvalue(), f"snisb_{uf}.xlsx")
    c2.download_button("⬇️ CSV", tab.to_csv(index=False, sep=";").encode("utf-8-sig"), f"snisb_{uf}.csv")
    with st.expander("Como a prioridade é calculada"):
        st.markdown(
            "- DPA alto +3, médio +1 · Risco alto +3, médio +1\n"
            "- Na PNSB +1, e então: sem Plano de Segurança +2, sem Revisão Periódica +1, "
            "sem inspeção ou inspeção com mais de 1 ano +2\n"
            "- DPA alto sem PAE +2 · Nível de perigo em atenção/alerta/emergência +4 · Já autuada +1\n"
            "- Empreendedor não encontrado na planilha do Crea +3"
        )

with aba_ficha:
    if f.empty:
        st.info("Nenhuma barragem nos filtros.")
    else:
        rot = f.apply(lambda r: f"{r['BAR_NM_NOME']} — {r.get('NM_EMPREENDEDOR') or 's/ empreendedor'} ({r.get('ING_NM_MUNICIPIO')})", axis=1)
        i = st.selectbox("Barragem", rot.index, format_func=lambda x: rot[x])
        r = f.loc[i]
        st.subheader(r["BAR_NM_NOME"])
        st.write(f"**Prioridade {r['prioridade']}:** {r['motivos'] or '—'}")
        st.link_button("Abrir no portal SNISB", URL_PORTAL)
        linha = r.drop(labels=["prioridade", "motivos"]).dropna()
        linha = linha[linha.astype(str).str.strip() != ""]
        st.dataframe(linha.astype(str).rename("valor"), width="stretch")

with aba_resumo:
    a, b = st.columns(2)
    for alvo, col in ((a, "USO_PRINCIPAL"), (b, "ORG_NM_ORGANIZACAO")):
        if col in f:
            alvo.markdown(f"**{COLS.get(col, col)}**")
            alvo.dataframe(f[col].fillna("Não informado").value_counts().rename("barragens"), width="stretch")
    if "ING_NM_MUNICIPIO" in f:
        st.markdown("**Municípios com mais barragens priorizadas (≥ 4)**")
        st.dataframe(f[f["prioridade"] >= 4]["ING_NM_MUNICIPIO"].value_counts().head(20).rename("barragens"), width="stretch")

st.divider()
st.caption("Dados públicos do SNISB, informados por cada órgão fiscalizador. Conferir no portal antes de autuar.")
