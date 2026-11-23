"""
Painel de Fiscalização de Barragens de Mineração — CREA-MS
Fonte: ANM / SIGBM — dados abertos (https://dadosabertos.anm.gov.br/SIGBM/Barragens.csv)
"""

from __future__ import annotations

import io
import re
import unicodedata
from datetime import datetime

import folium
import pandas as pd
import requests
import streamlit as st
from streamlit_folium import st_folium

URL_SIGBM = "https://dadosabertos.anm.gov.br/SIGBM/Barragens.csv"
URL_SIGBM_PUBLICO = "https://app.anm.gov.br/SIGBM/Publico"

st.set_page_config(page_title="Fiscalização de Barragens — CREA-MS", page_icon="🏗️", layout="wide")


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def norm(s) -> str:
    """Maiúsculas, sem acento, só letras/dígitos."""
    s = unicodedata.normalize("NFD", "" if s is None else str(s))
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^A-Z0-9]+", "", s.upper())


def so_digitos(s) -> str:
    return re.sub(r"\D", "", "" if pd.isna(s) else str(s))


def coord_decimal(txt):
    """Aceita -19°00'41.100'' ou decimal (com vírgula ou ponto)."""
    if pd.isna(txt):
        return None
    s = str(txt).strip().replace(",", ".")
    m = re.match(r"^(-?)\s*(\d{1,3})\s*°\s*(\d{1,2})\s*'\s*([\d.]+)", s)
    if m:
        sinal, g, mi, se = m.groups()
        v = int(g) + int(mi) / 60 + float(se) / 3600
        return -v if sinal == "-" else v
    try:
        v = float(s)
        return v if abs(v) <= 180 else None
    except ValueError:
        return None


# Colunas do SIGBM -> nome interno (casamento por cabeçalho normalizado)
MAPA_COLUNAS = {
    "id": r"^ID$",
    "nome": r"^NOME$",
    "empreendedor": r"^EMPREENDEDOR$",
    "cpf_cnpj": r"^CPFCNPJ$",
    "mina": r"^NOMEDAMINA$",
    "uf": r"^UF$",
    "municipio": r"^MUNICIPIO$",
    "lat": r"^LATITUDE$",
    "lon": r"^LONGITUDE$",
    "cri": r"^CATEGORIADERISCO",
    "dpa": r"^DANOPOTENCIAL",
    "nivel": r"^NIVELDEEMERGENCIA$",
    "situacao": r"^SITUACAOOPERACIONAL$",
    "pnsb": r"^INSERIDANAPNSB$|^INSERIDONAPNSB$",
    "tipo": r"^TIPODEBARRAGEMDEMINERACAO$",
    "metodo": r"^METODOCONSTRUTIVODABARRAGEM$",
    "alteamento": r"^TIPODEALTEAMENTO$",
    "minerio": r"^MINERIOPRINCIPAL",
    "altura": r"^ALTURAMAXIMAATUAL",
    "volume": r"^VOLUMEATUALDORESERVATORIO",
    "populacao": r"^EXISTENCIADEPOPULACAOAJUSANTE$",
    "pessoas": r"^NUMERODEPESSOASPOSSIVELMENTE",
    "fase_desc": r"FASEDADESCARACTERIZACAO|FASEDEDESCARACTERIZACAO",
    "dt_dce": r"^DATADAFINALIZACAODADCE$",
}

ROTULOS = {
    "id": "ID SIGBM", "nome": "Barragem", "empreendedor": "Empreendedor", "cpf_cnpj": "CPF/CNPJ",
    "mina": "Mina", "uf": "UF", "municipio": "Município", "cri": "Categoria de Risco (CRI)",
    "dpa": "Dano Potencial (DPA)", "nivel": "Nível de emergência", "situacao": "Situação",
    "pnsb": "Na PNSB", "tipo": "Tipo", "metodo": "Método construtivo", "alteamento": "Alteamento",
    "minerio": "Minério", "altura": "Altura (m)", "volume": "Volume (m³)",
    "populacao": "População a jusante", "pessoas": "Pessoas a jusante",
    "fase_desc": "Fase descaracterização", "dt_dce": "Última DCE",
    "prioridade": "Prioridade", "motivos": "Motivos", "art_crea": "ART/registro no Crea",
}


def ler_csv(conteudo: bytes) -> pd.DataFrame:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            texto = conteudo.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    primeira = texto.splitlines()[0] if texto else ""
    sep = ";" if primeira.count(";") > primeira.count(",") else ","
    return pd.read_csv(io.StringIO(texto), sep=sep, dtype=str, keep_default_na=False)


@st.cache_data(ttl=60 * 60 * 12, show_spinner="Baixando Barragens.csv da ANM...")
def baixar_sigbm() -> tuple[bytes, str]:
    r = requests.get(URL_SIGBM, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
    r.raise_for_status()
    return r.content, datetime.now().strftime("%d/%m/%Y %H:%M")


def preparar(bruto: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    cab = {c: norm(c) for c in bruto.columns}
    achadas = {}
    for interno, padrao in MAPA_COLUNAS.items():
        for orig, n in cab.items():
            if re.search(padrao, n):
                achadas[interno] = orig
                break
    df = pd.DataFrame({k: bruto[v].astype(str).str.strip() for k, v in achadas.items()})
    for k in MAPA_COLUNAS:
        if k not in df:
            df[k] = ""
    faltando = [k for k in ("nome", "empreendedor", "uf", "municipio", "dpa", "cri") if k not in achadas]

    # Responsável técnico: colunas que começam com "RT" no SIGBM
    rt_cols = [c for c, n in cab.items() if n.startswith("RT")]
    for c in rt_cols:
        df["RT · " + c] = bruto[c].astype(str).str.strip()

    df["uf"] = df["uf"].str.upper().str[:2]
    df["lat_dec"] = df["lat"].map(coord_decimal)
    df["lon_dec"] = df["lon"].map(coord_decimal)
    df["doc"] = df["cpf_cnpj"].map(so_digitos)
    df["cnpj_raiz"] = df["doc"].where(df["doc"].str.len() == 14, "").str[:8]
    for c in ("altura", "volume", "pessoas"):
        df[c + "_num"] = pd.to_numeric(df[c].str.replace(".", "", regex=False).str.replace(",", ".", regex=False), errors="coerce")

    pri, mot = zip(*df.apply(pontuar, axis=1)) if len(df) else ((), ())
    df["prioridade"] = list(pri)
    df["motivos"] = list(mot)
    df["_bruto_idx"] = bruto.index
    return df, faltando


def pontuar(r) -> tuple[int, str]:
    """Pontuação simples de prioridade para fiscalização do exercício profissional."""
    p, m = 0, []
    dpa, cri, nivel = norm(r["dpa"]), norm(r["cri"]), norm(r["nivel"])
    if dpa == "ALTA":
        p += 3; m.append("DPA alto")
    elif dpa == "MEDIA":
        p += 1; m.append("DPA médio")
    if cri == "ALTA":
        p += 3; m.append("risco alto")
    elif cri == "MEDIA":
        p += 1; m.append("risco médio")
    if nivel and "SEMEMERGENCIA" not in nivel and nivel != "":
        p += 4; m.append(r["nivel"])
    met = norm(r["metodo"]) + norm(r["alteamento"])
    if "MONTANTE" in met or "DESCONHECIDO" in met:
        p += 2; m.append("montante/desconhecido")
    if "DESCARACTERIZ" in norm(r["situacao"]) or r["fase_desc"]:
        p += 1; m.append("em descaracterização")
    if norm(r["populacao"]) in ("SIM", "EXISTENTE"):
        p += 1; m.append("população a jusante")
    if r["dt_dce"]:
        try:
            dce = pd.to_datetime(r["dt_dce"], dayfirst=True, errors="coerce")
            if pd.notna(dce) and (pd.Timestamp.now() - dce).days > 400:
                p += 2; m.append("DCE desatualizada")
        except Exception:
            pass
    return p, ", ".join(m)


def ler_base_crea(arq) -> pd.DataFrame:
    if arq.name.lower().endswith((".xlsx", ".xls")):
        return pd.read_excel(arq, dtype=str)
    return ler_csv(arq.getvalue())


def para_excel(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name="Barragens")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Carga
# ---------------------------------------------------------------------------
st.title("🏗️ Fiscalização de Barragens de Mineração")
st.caption("CREA-MS · Fonte: ANM — SIGBM (dados abertos)")

with st.sidebar:
    st.header("Dados")
    upload = st.file_uploader("Barragens.csv (opcional, se o download falhar)", type=["csv"])
    if st.button("🔄 Recarregar da ANM"):
        baixar_sigbm.clear()

origem = ""
try:
    if upload is not None:
        conteudo, origem = upload.getvalue(), f"arquivo enviado ({upload.name})"
    else:
        conteudo, quando = baixar_sigbm()
        origem = f"ANM, baixado em {quando}"
    bruto = ler_csv(conteudo)
except Exception as e:  # noqa: BLE001
    st.error(
        f"Não consegui baixar o arquivo da ANM ({e}). Baixe manualmente em {URL_SIGBM} "
        "e envie pela barra lateral."
    )
    st.stop()

df, faltando = preparar(bruto)
if faltando:
    st.warning("Colunas não encontradas no arquivo (o layout da ANM pode ter mudado): " + ", ".join(faltando))

# ---------------------------------------------------------------------------
# Filtros
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Filtros")
    ufs = sorted(u for u in df["uf"].unique() if u)
    uf_sel = st.multiselect("UF", ufs, default=["MS"] if "MS" in ufs else [])
    base = df[df["uf"].isin(uf_sel)] if uf_sel else df

    def ms(rotulo, col):
        opcoes = sorted(v for v in base[col].unique() if v)
        return st.multiselect(rotulo, opcoes)

    mun_sel = ms("Município", "municipio")
    emp_sel = ms("Empreendedor", "empreendedor")
    dpa_sel = ms("Dano Potencial (DPA)", "dpa")
    cri_sel = ms("Categoria de Risco (CRI)", "cri")
    niv_sel = ms("Nível de emergência", "nivel")
    sit_sel = ms("Situação", "situacao")
    pnsb_sel = ms("Na PNSB", "pnsb")
    busca = st.text_input("Buscar (nome, mina, CNPJ)")

    st.header("Cruzamento com o Crea")
    arq_crea = st.file_uploader("Planilha de ARTs/registros (CSV ou Excel)", type=["csv", "xlsx", "xls"])

f = base.copy()
for col, sel in [("municipio", mun_sel), ("empreendedor", emp_sel), ("dpa", dpa_sel), ("cri", cri_sel),
                 ("nivel", niv_sel), ("situacao", sit_sel), ("pnsb", pnsb_sel)]:
    if sel:
        f = f[f[col].isin(sel)]
if busca:
    b = norm(busca)
    f = f[f.apply(lambda r: b in norm(r["nome"]) or b in norm(r["mina"]) or (so_digitos(busca) and so_digitos(busca) in r["doc"]), axis=1)]

# Cruzamento com base do Crea (por CNPJ/CPF do empreendedor)
if arq_crea is not None:
    try:
        crea = ler_base_crea(arq_crea)
        sugestao = next((c for c in crea.columns if any(k in norm(c) for k in ("CNPJ", "CPF", "CONTRATANTE", "DOCUMENTO"))), crea.columns[0])
        col_doc = st.sidebar.selectbox("Coluna do CPF/CNPJ na planilha", list(crea.columns), index=list(crea.columns).index(sugestao))
        docs = crea[col_doc].map(so_digitos)
        cheios = set(d for d in docs if len(d) in (11, 14))
        raizes = set(d[:8] for d in docs if len(d) == 14)
        contagem = docs.value_counts()

        def status(r):
            if not r["doc"]:
                return "sem CNPJ no SIGBM"
            if r["doc"] in cheios:
                return f"encontrado ({contagem.get(r['doc'], 0)} registro(s))"
            if r["cnpj_raiz"] and r["cnpj_raiz"] in raizes:
                return "só outra filial (mesma raiz)"
            return "NÃO encontrado"

        f = f.copy()
        f["art_crea"] = f.apply(status, axis=1)
        f.loc[f["art_crea"] == "NÃO encontrado", "prioridade"] += 3
        f.loc[f["art_crea"] == "NÃO encontrado", "motivos"] = f["motivos"].where(f["motivos"] == "", f["motivos"] + ", ") + "sem ART no Crea"
    except Exception as e:  # noqa: BLE001
        st.sidebar.error(f"Não consegui ler a planilha do Crea: {e}")

f = f.sort_values(["prioridade", "nome"], ascending=[False, True])

# ---------------------------------------------------------------------------
# Indicadores
# ---------------------------------------------------------------------------
st.caption(f"Origem dos dados: {origem} · {len(df)} barragens no arquivo")

k = st.columns(6)
k[0].metric("Barragens", len(f))
k[1].metric("Empreendedores", f["empreendedor"].nunique())
k[2].metric("Na PNSB", int((f["pnsb"].map(norm) == "SIM").sum()))
k[3].metric("DPA alto", int((f["dpa"].map(norm) == "ALTA").sum()))
k[4].metric("Em emergência", int(f["nivel"].map(lambda x: bool(x) and "SEMEMERGENCIA" not in norm(x)).sum()))
k[5].metric("Em descaracterização", int(f["situacao"].map(lambda x: "DESCARACTERIZ" in norm(x)).sum()))

aba_mapa, aba_tab, aba_ficha, aba_emp = st.tabs(["🗺️ Mapa", "📋 Prioridades", "🔎 Ficha da barragem", "🏢 Por empreendedor"])

# ---------------------------------------------------------------------------
# Mapa
# ---------------------------------------------------------------------------
with aba_mapa:
    pts = f.dropna(subset=["lat_dec", "lon_dec"])
    if pts.empty:
        st.info("Nenhuma barragem com coordenada nos filtros atuais.")
    else:
        mapa = folium.Map(location=[pts["lat_dec"].mean(), pts["lon_dec"].mean()], zoom_start=9 if len(pts) < 30 else 5,
                          tiles=None)
        folium.TileLayer(
            tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
            attr="Esri", name="Satélite (Esri)").add_to(mapa)
        folium.TileLayer("OpenStreetMap", name="Mapa").add_to(mapa)
        cor = {"ALTA": "red", "MEDIA": "orange", "BAIXA": "green"}
        for _, r in pts.iterrows():
            html = (f"<b>{r['nome']}</b><br>{r['empreendedor']}<br>{r['municipio']}/{r['uf']}<br>"
                    f"DPA: {r['dpa'] or '-'} · CRI: {r['cri'] or '-'}<br>{r['nivel'] or ''}<br>"
                    f"Situação: {r['situacao'] or '-'}<br><b>Prioridade {r['prioridade']}</b>"
                    + (f"<br>Crea: {r['art_crea']}" if "art_crea" in r else ""))
            folium.CircleMarker([r["lat_dec"], r["lon_dec"]], radius=6 + min(r["prioridade"], 10),
                                color=cor.get(norm(r["dpa"]), "gray"), fill=True, fill_opacity=0.8,
                                popup=folium.Popup(html, max_width=300), tooltip=r["nome"]).add_to(mapa)
        folium.LayerControl().add_to(mapa)
        st_folium(mapa, height=560, use_container_width=True, returned_objects=[])
        st.caption("Cor = Dano Potencial (vermelho alto, laranja médio, verde baixo). Tamanho = prioridade.")

# ---------------------------------------------------------------------------
# Tabela de prioridades
# ---------------------------------------------------------------------------
cols_tab = ["prioridade", "motivos"] + (["art_crea"] if "art_crea" in f else []) + [
    "nome", "empreendedor", "cpf_cnpj", "municipio", "uf", "dpa", "cri", "nivel", "situacao", "pnsb",
    "metodo", "minerio", "altura", "volume", "pessoas", "dt_dce", "id"]

with aba_tab:
    st.dataframe(f[cols_tab].rename(columns=ROTULOS), width="stretch", hide_index=True, height=480)
    c1, c2 = st.columns(2)
    saida = f[cols_tab + [c for c in f.columns if c.startswith("RT · ")]].rename(columns=ROTULOS)
    c1.download_button("⬇️ Excel", para_excel(saida), "barragens_fiscalizacao.xlsx")
    c2.download_button("⬇️ CSV", saida.to_csv(index=False, sep=";").encode("utf-8-sig"), "barragens_fiscalizacao.csv")
    with st.expander("Como a prioridade é calculada"):
        st.markdown(
            "- DPA alto +3, médio +1\n- Risco (CRI) alto +3, médio +1\n- Qualquer nível de emergência +4\n"
            "- Método a montante ou desconhecido +2\n- Em descaracterização +1\n- População a jusante +1\n"
            "- Última DCE com mais de ~13 meses +2\n- Empreendedor sem ART/registro na planilha do Crea +3"
        )

# ---------------------------------------------------------------------------
# Ficha
# ---------------------------------------------------------------------------
with aba_ficha:
    if f.empty:
        st.info("Nenhuma barragem nos filtros.")
    else:
        rot = f.apply(lambda r: f"{r['nome']} — {r['empreendedor']} ({r['municipio']})", axis=1)
        escolha = st.selectbox("Barragem", rot.index, format_func=lambda i: rot[i])
        r = f.loc[escolha]
        a, b2 = st.columns(2)
        with a:
            st.subheader(r["nome"])
            st.write(f"**Empreendedor:** {r['empreendedor']} · {r['cpf_cnpj']}")
            st.write(f"**Mina:** {r['mina'] or '-'} · **Município:** {r['municipio']}/{r['uf']}")
            st.write(f"**DPA:** {r['dpa'] or '-'} · **CRI:** {r['cri'] or '-'} · **PNSB:** {r['pnsb'] or '-'}")
            st.write(f"**Emergência:** {r['nivel'] or '-'} · **Situação:** {r['situacao'] or '-'}")
            st.write(f"**Prioridade {r['prioridade']}:** {r['motivos'] or '—'}")
            if "art_crea" in r:
                st.write(f"**Crea:** {r['art_crea']}")
            st.link_button("Abrir SIGBM Público", URL_SIGBM_PUBLICO)
        with b2:
            rts = {c.replace("RT · ", ""): r[c] for c in f.columns if c.startswith("RT · ") and r[c]}
            st.markdown("**Responsável técnico declarado no SIGBM**")
            st.write(rts if rts else "Não informado no arquivo.")
            st.markdown("**Documentos que exigem ART (Lei 12.334/2010 e Res. ANM 95/2022)**")
            st.markdown("- Projeto / as built\n- Plano de Segurança da Barragem (PSB)\n- Inspeções de segurança regulares e DCE\n"
                        "- Revisão Periódica de Segurança (RPSB)\n- PAEBM\n- Projeto e obras de descaracterização")
        with st.expander("Todas as colunas do SIGBM para esta barragem"):
            linha = bruto.loc[r["_bruto_idx"]]
            st.dataframe(linha[linha.astype(str).str.strip() != ""].rename("valor"), width="stretch")

# ---------------------------------------------------------------------------
# Por empreendedor
# ---------------------------------------------------------------------------
with aba_emp:
    if f.empty:
        st.info("Nenhuma barragem nos filtros.")
    else:
        g = f.groupby(["empreendedor", "cpf_cnpj"], dropna=False).agg(
            barragens=("nome", "count"),
            dpa_alto=("dpa", lambda s: int((s.map(norm) == "ALTA").sum())),
            emergencia=("nivel", lambda s: int(s.map(lambda x: bool(x) and "SEMEMERGENCIA" not in norm(x)).sum())),
            prioridade_max=("prioridade", "max"),
            municipios=("municipio", lambda s: ", ".join(sorted(set(s)))),
        ).reset_index().sort_values("prioridade_max", ascending=False)
        if "art_crea" in f:
            g = g.merge(f.groupby("empreendedor")["art_crea"].first().reset_index(), on="empreendedor", how="left")
        st.dataframe(g.rename(columns={"empreendedor": "Empreendedor", "cpf_cnpj": "CPF/CNPJ", "barragens": "Barragens",
                                       "dpa_alto": "DPA alto", "emergencia": "Em emergência",
                                       "prioridade_max": "Prioridade máx.", "municipios": "Municípios",
                                       "art_crea": "ART/registro no Crea"}),
                     width="stretch", hide_index=True)

st.divider()
st.caption("Apoio à fiscalização do exercício profissional. Dados públicos da ANM; conferir no SIGBM antes de autuar.")
