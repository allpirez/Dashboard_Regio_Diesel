import streamlit as st
import pandas as pd
import plotly.express as px
import requests
import gspread
from google.oauth2.service_account import Credentials
from streamlit_echarts import st_echarts


def limpiar_lista_opciones(serie):
    """Devuelve una lista limpia de opciones únicas omitiendo nulos, N/A, vacíos o ceros."""
    opciones = serie.dropna().unique().tolist()
    opciones_limpias = [
        str(x).strip() for x in opciones 
        if str(x).strip().upper() not in ["", "N/A", "#N/A", "NAN", "NONE", "NULL", "NAT", "0"]
    ]
    return sorted(list(set(opciones_limpias)))

# ---------------------------------------------------------
# Control de Acceso / Autenticación
# ---------------------------------------------------------
def verificar_login():
    if "autenticado" not in st.session_state:
        st.session_state["autenticado"] = False

    if not st.session_state["autenticado"]:
        st.sidebar.title("🔐 Acceso Restringido")
        usuario = st.sidebar.text_input("Usuario (Correo):")
        password = st.sidebar.text_input("Contraseña:", type="password")

        if st.sidebar.button("Iniciar Sesión"):
            usuarios_validos = st.secrets.get("passwords", {})
            if usuario in usuarios_validos and usuarios_validos[usuario] == password:
                st.session_state["autenticado"] = True
                st.session_state["usuario_actual"] = usuario
                st.rerun()
            else:
                st.sidebar.error("Usuario o contraseña incorrectos")

        st.warning("Por favor inicia sesión en la barra lateral para acceder al tablero.")
        st.stop() # Detiene la ejecución del resto del dashboard si no está autenticado

# Ejecutar verificación antes de cargar los datos
verificar_login()



# ---------------------------------------------------------
# Configuración inicial de la página
# ---------------------------------------------------------
st.set_page_config(
    page_title="REGIO - Tablero Ejecutivo de Ventas",
    page_icon="⛽",
    layout="wide"
)

st.title("Tablero Ejecutivo de Utilidades y Ventas - Proyecto Diesel Regio Fuel")
st.caption("Visualizaciones interactivas conectadas a Google Sheets a la hoja de trabajo RF-DATABASE")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly"
]

@st.cache_data(ttl=60)
def obtener_datos(nombre_pestana):
    secrets_gsheets = dict(st.secrets["connections"]["gsheets"])
    if "private_key" in secrets_gsheets:
        secrets_gsheets["private_key"] = secrets_gsheets["private_key"].replace("\\n", "\n")

    creds = Credentials.from_service_account_info(secrets_gsheets, scopes=SCOPES)
    client = gspread.authorize(creds)
    
    spreadsheet_url = secrets_gsheets["spreadsheet"]
    sheet = client.open_by_url(spreadsheet_url)
    worksheet = sheet.worksheet(nombre_pestana)
    
    data = worksheet.get_all_records()
    return pd.DataFrame(data)

NOMBRE_PESTAÑA = "DASHBOARD_VENTAS"

try:
    df_raw = obtener_datos(NOMBRE_PESTAÑA)
    df = df_raw.copy()
    df.columns = [str(col).strip() for col in df.columns]

    # Convertir Fechas y ELIMINAR NaT
    col_fecha = [c for c in df.columns if "FECHA" in c.upper()]
    if col_fecha:
        df["FECHAS"] = pd.to_datetime(df[col_fecha[0]], errors="coerce")
        df = df.dropna(subset=["FECHAS"])
        df["AÑO_MES"] = df["FECHAS"].dt.to_period("M").astype(str)

    # Limpiar columnas numéricas (LITROS, FEE)
    for col in ["LITROS", "FEE"]:
        if col in df.columns:
            df[col] = (
                df[col]
                .astype(str)
                .str.replace("$", "", regex=False)
                .str.replace(",", "", regex=False)
                .str.strip()
            )
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # Categorización de PRODUCTO si no existe en la hoja
    if "PRODUCTO" not in df.columns and "SUBPRODUCTO" in df.columns:
        df["PRODUCTO"] = df["SUBPRODUCTO"].apply(
            lambda x: "Diesel" if "DIESEL" in str(x).upper() else "Gasolinas"
        )

    # Identificación de columna para Permiso (Columna M / TIPO DE PERMISO)
    col_tipo_permiso = [c for c in df.columns if "PERMISO" in c.upper()]
    col_permiso_str = col_tipo_permiso[0] if col_tipo_permiso else None

    # ---------------------------------------------------------
    # Sección de Filtros en la Barra Lateral
    # ---------------------------------------------------------
    st.sidebar.header("FILTROS")

    # 1. Filtro Producto
    if "PRODUCTO" in df.columns:
        prod_options = ["Todos"] + limpiar_lista_opciones(df["PRODUCTO"])
        prod_sel = st.sidebar.selectbox("Producto:", options=prod_options, index=0)
    else:
        prod_sel = "Todos"

    # 2. Filtro Subproducto
    if "SUBPRODUCTO" in df.columns:
        subp_options = limpiar_lista_opciones(df["SUBPRODUCTO"])
        subp_sel = st.sidebar.multiselect("Subproducto:", options=subp_options, default=subp_options)
    else:
        subp_sel = []
        subp_options = []

    # 3. Filtro Tipo de Permiso (Columna M)
    if col_permiso_str:
        permiso_options = limpiar_lista_opciones(df[col_permiso_str])
        permiso_sel = st.sidebar.multiselect("Tipo de Permiso:", options=permiso_options, default=permiso_options)
    else:
        permiso_sel = []
        permiso_options = []

    # 4. Filtro Periodo (Mes/Año con etiquetas)
    if "AÑO_MES" in df.columns:
        meses_options = limpiar_lista_opciones(df["AÑO_MES"])
        meses_sel = st.sidebar.multiselect("Periodo (Mes/Año):", options=meses_options, default=meses_options)
    else:
        meses_sel = []
        meses_options = []

    # ---------------------------------------------------------
    # Aplicar Filtros al Dataset
    # ---------------------------------------------------------
    df_filtered = df.copy()

    if prod_sel != "Todos" and "PRODUCTO" in df_filtered.columns:
        df_filtered = df_filtered[df_filtered["PRODUCTO"] == prod_sel]

    if subp_sel and "SUBPRODUCTO" in df_filtered.columns:
        if len(subp_sel) < len(subp_options):
            df_filtered = df_filtered[df_filtered["SUBPRODUCTO"].isin(subp_sel)]

    if permiso_sel and col_permiso_str:
        if len(permiso_sel) < len(permiso_options):
            df_filtered = df_filtered[df_filtered[col_permiso_str].isin(permiso_sel)]

    if meses_sel and "AÑO_MES" in df_filtered.columns:
        if len(meses_sel) < len(meses_options):
            df_filtered = df_filtered[df_filtered["AÑO_MES"].isin(meses_sel)]

    # Datos agregados por mes
    if "AÑO_MES" in df_filtered.columns:
        df_filtered_mes = df_filtered[~df_filtered["AÑO_MES"].astype(str).str.upper().isin(["NAT", "NONE", "NAN", ""])]
        df_mes = (
            df_filtered_mes.groupby("AÑO_MES", as_index=False)
            .agg(FEE=("FEE", "sum"), LITROS=("LITROS", "sum"), ORDERS=("FEE", "count"))
            .sort_values("AÑO_MES")
        )
    else:
        df_mes = pd.DataFrame(columns=["AÑO_MES", "FEE", "LITROS", "ORDERS"])

    # ---------------------------------------------------------
    # 1. Letreros Iniciales (3 KPIs con Sparklines ECharts)
    # ---------------------------------------------------------
    kpi_col1, kpi_col2, kpi_col3 = st.columns(3)

    total_fee = df_filtered["FEE"].sum() if "FEE" in df_filtered.columns else 0
    total_litros = df_filtered["LITROS"].sum() if "LITROS" in df_filtered.columns else 0
    total_orders = len(df_filtered)

    fee_trend = df_mes["FEE"].tolist() if not df_mes.empty else [0]
    litros_trend = df_mes["LITROS"].tolist() if not df_mes.empty else [0]
    orders_trend = df_mes["ORDERS"].tolist() if not df_mes.empty else [0]
    ejes_x = df_mes["AÑO_MES"].tolist() if not df_mes.empty else []

    # KPI 1: Total Revenue (FEE)
    with kpi_col1:
        st.markdown(f"### Total Utilidades (fee)\n## **${total_fee:,.2f}**")
        option_spark_fee = {
            "grid": {"top": 5, "bottom": 5, "left": 5, "right": 5},
            "xAxis": {"type": "category", "data": ejes_x, "show": False},
            "yAxis": {"type": "value", "show": False},
            "tooltip": {"trigger": "axis"},
            "series": [{
                "data": fee_trend,
                "type": "line",
                "smooth": True,
                "symbol": "none",
                "lineStyle": {"color": "#1890ff", "width": 3},
                "areaStyle": {"color": "rgba(24, 144, 255, 0.2)"}
            }],
        }
        st_echarts(options=option_spark_fee, height="80px")

    # KPI 2: Total Volume (LITROS)
    with kpi_col2:
        st.markdown(f"### Volumen total comercializado (litros)\n## **{total_litros:,.2f} Lts**")
        option_spark_litros = {
            "grid": {"top": 5, "bottom": 5, "left": 5, "right": 5},
            "xAxis": {"type": "category", "data": ejes_x, "show": False},
            "yAxis": {"type": "value", "show": False},
            "tooltip": {"trigger": "axis"},
            "series": [{
                "data": litros_trend,
                "type": "line",
                "smooth": True,
                "symbol": "none",
                "lineStyle": {"color": "#fa8c16", "width": 3},
                "areaStyle": {"color": "rgba(250, 140, 22, 0.2)"}
            }],
        }
        st_echarts(options=option_spark_litros, height="80px")

    # KPI 3: Total de Operaciones
    with kpi_col3:
        st.markdown(f"### Total de Operaciones\n## **{total_orders:,}**")
        option_spark_orders = {
            "grid": {"top": 5, "bottom": 5, "left": 5, "right": 5},
            "xAxis": {"type": "category", "data": ejes_x, "show": False},
            "yAxis": {"type": "value", "show": False},
            "tooltip": {"trigger": "axis"},
            "series": [{
                "data": orders_trend,
                "type": "bar",
                "barWidth": "60%",
                "itemStyle": {
                    "color": "#52c41a",
                    "borderRadius": [2, 2, 0, 0]
                }
            }],
        }
        st_echarts(options=option_spark_orders, height="80px")

    st.markdown("---")

    # ---------------------------------------------------------
    # 2. Gráfico Principal: Evolución Mes a Mes
    # ---------------------------------------------------------
    col_chart_head, col_chart_opt = st.columns([0.7, 0.3])

    with col_chart_head:
        st.subheader("Ventas mes a mes (Ingresos vs. Litros)")

    with col_chart_opt:
        tipo_grafico = st.radio(
            "Tipo de Gráfico:",
            options=["Línea Chart", "Bar Chart"],
            horizontal=True,
            index=0
        )

    chart_type_str = "line" if tipo_grafico == "Línea Chart" else "bar"

    option_dual_chart = {
        "tooltip": {"trigger": "axis", "axisPointer": {"type": "cross"}},
        "legend": {"data": ["FEE ($)", "Litros (Lts)"], "top": "0"},
        "grid": {"left": "3%", "right": "4%", "bottom": "3%", "containLabel": True},
        "xAxis": [{"type": "category", "data": ejes_x, "axisPointer": {"type": "shadow"}}],
        "yAxis": [
            {
                "type": "value",
                "name": "FEE ($)",
                "position": "left",
                "axisLine": {"show": True, "lineStyle": {"color": "#1890ff"}},
                "axisLabel": {"formatter": "${value}"}
            },
            {
                "type": "value",
                "name": "Litros (Lts)",
                "position": "right",
                "axisLine": {"show": True, "lineStyle": {"color": "#fa8c16"}},
                "axisLabel": {"formatter": "{value} Lts"}
            }
        ],
        "series": [
            {
                "name": "FEE ($)",
                "type": chart_type_str,
                "smooth": True,
                "yAxisIndex": 0,
                "data": [round(val, 2) for val in fee_trend],
                "itemStyle": {"color": "#1890ff"}
            },
            {
                "name": "Litros (Lts)",
                "type": chart_type_str,
                "smooth": True,
                "yAxisIndex": 1,
                "data": [round(val, 2) for val in litros_trend],
                "itemStyle": {"color": "#fa8c16"}
            }
        ]
    }
    st_echarts(options=option_dual_chart, height="400px")

    st.markdown("---")

    # ---------------------------------------------------------
    # 3. Fila de 2 Donas (Producto y Tipo de Permiso - Columna M)
    # ---------------------------------------------------------
    dona_col1, dona_col2 = st.columns(2)

    # --- DONA 1: Distribución por Producto ---
    with dona_col1:
        st.subheader("Distribución por Producto")
        if "PRODUCTO" in df_filtered.columns and not df_filtered.empty:
            df_prod_clean = df_filtered[
                ~df_filtered["PRODUCTO"].astype(str).str.upper().isin(["", "N/A", "#N/A", "NAN", "NONE", "NULL"])
            ]
            df_prod = df_prod_clean.groupby("PRODUCTO", as_index=False)["FEE"].sum()
            pie_prod = [{"value": round(r["FEE"], 2), "name": str(r["PRODUCTO"])} for _, r in df_prod.iterrows()]

            option_donut_prod = {
                "tooltip": {"trigger": "item", "formatter": "{b}:<br/>${c} ({d}%)"},
                "legend": {"orient": "horizontal", "bottom": "0"},
                "series": [{
                    "type": "pie",
                    "radius": ["40%", "70%"],
                    "avoidLabelOverlap": True,
                    "label": {"show": True, "formatter": "{b}\n{d}%"},
                    "data": pie_prod
                }]
            }
            st_echarts(options=option_donut_prod, height="360px")

    # --- DONA 2: Distribución por Tipo de Permiso (Columna M) ---
    with dona_col2:
        st.subheader("Distribución por Tipo de Permiso")
        if col_permiso_str and not df_filtered.empty:
            df_perm_clean = df_filtered[
                ~df_filtered[col_permiso_str].astype(str).str.upper().isin(["", "N/A", "#N/A", "NAN", "NONE", "NULL"])
            ]
            df_perm = df_perm_clean.groupby(col_permiso_str, as_index=False)["FEE"].sum()
            pie_perm = [{"value": round(r["FEE"], 2), "name": str(r[col_permiso_str])} for _, r in df_perm.iterrows()]

            option_donut_perm = {
                "tooltip": {"trigger": "item", "formatter": "{b}:<br/>${c} ({d}%)"},
                "legend": {"orient": "horizontal", "bottom": "0"},
                "series": [{
                    "type": "pie",
                    "radius": ["40%", "70%"],
                    "avoidLabelOverlap": True,
                    "label": {"show": True, "formatter": "{b}\n{d}%"},
                    "data": pie_perm
                }]
            }
            st_echarts(options=option_donut_perm, height="360px")

    st.markdown("---")

    # ---------------------------------------------------------
    # 4. Mapa Geográfico de México
    # ---------------------------------------------------------
    col_estado = [c for c in df.columns if "ESTADO" in c.upper() or "UBICACION" in c.upper()]
    if col_estado:
        st.subheader("Volumen de litros comercializados por Estado")
        
        df_geo = df_filtered.groupby(col_estado[0], as_index=False)[["LITROS", "FEE"]].sum()

        url_angelnmara = "https://raw.githubusercontent.com/angelnmara/geojson/master/mexicoHigh.json"
        
        try:
            res = requests.get(url_angelnmara, timeout=10)
            mx_geojson = res.json()
        except Exception:
            mx_geojson = None

        if mx_geojson:
            mapeo_angelnmara = {
                # Coahuila ajustado al nombre exacto del GeoJSON:
                "COAHUILA": "Coahuila",
                "COAHUILA DE ZARAGOZA": "Coahuila",
                
                # Otros estados comunes
                "NUEVO LEON": "Nuevo León", 
                "NUEVO LEÓN": "Nuevo León", 
                "NL": "Nuevo León",
                "CDMX": "Distrito Federal", 
                "CIUDAD DE MEXICO": "Distrito Federal", 
                "CIUDAD DE MÉXICO": "Distrito Federal", 
                "DISTRITO FEDERAL": "Distrito Federal",
                "EDOMEX": "México", 
                "ESTADO DE MEXICO": "México", 
                "ESTADO DE MÉXICO": "México", 
                "MEXICO": "México", 
                "MÉXICO": "México",
                "VERACRUZ": "Veracruz",
                "VERACRUZ DE IGNACIO DE LA LLAVE": "Veracruz",
                "MICHOACAN": "Michoacán", 
                "MICHOACÁN": "Michoacán",
                "QUERETARO": "Querétaro", 
                "QUERÉTARO": "Querétaro",
                "YUCATAN": "Yucatán", 
                "YUCATÁN": "Yucatán",
                "SAN LUIS POTOSI": "San Luis Potosí", 
                "SAN LUIS POTOSÍ": "San Luis Potosí",
                "TAMAULIPAS": "Tamaulipas", 
                "JALISCO": "Jalisco", 
                "CHIHUAHUA": "Chihuahua",
                "SONORA": "Sonora", 
                "SINALOA": "Sinaloa", 
                "GUANAJUATO": "Guanajuato", 
                "PUEBLA": "Puebla"
                }

            df_geo["ESTADO_MAPA"] = (
                df_geo[col_estado[0]]
                .astype(str)
                .str.upper()
                .str.strip()
                .map(lambda x: mapeo_angelnmara.get(x, x.title()))
            )

            todos_los_estados = [feature["properties"]["name"] for feature in mx_geojson["features"]]
            df_todos_estados = pd.DataFrame({"ESTADO_MAPA": todos_los_estados})
            
            df_map_full = pd.merge(df_todos_estados, df_geo, on="ESTADO_MAPA", how="left")
            df_map_full["LITROS_MAPA"] = df_map_full["LITROS"].apply(lambda x: x if pd.notnull(x) and x > 0 else None)

            escala_amarillo_rojo = [
                [0.0, "rgba(255, 255, 224, 0.4)"],
                [0.3, "#fde047"],
                [0.6, "#f97316"],
                [1.0, "#dc2626"]
            ]

            fig_map = px.choropleth(
                df_map_full,
                geojson=mx_geojson,
                locations="ESTADO_MAPA",
                featureidkey="properties.name",
                color="LITROS_MAPA",
                color_continuous_scale=escala_amarillo_rojo,
                title="Volumen de Litros por Estado",
                labels={"LITROS_MAPA": "Litros Totales (Lts)", "ESTADO_MAPA": "Estado"}
            )
            
            fig_map.update_traces(
                marker_line_color="#71717a",
                marker_line_width=1.2
            )
            
            fig_map.update_geos(
                fitbounds="locations",
                visible=False,
                bgcolor="rgba(0,0,0,0)"
            )
            
            fig_map.update_layout(
                height=520,
                margin={"r": 0, "t": 40, "l": 0, "b": 0},
                geo=dict(bgcolor="rgba(0,0,0,0)")
            )
            st.plotly_chart(fig_map, use_container_width=True)

    # ---------------------------------------------------------
    # 5. Tabla de Registros
    # ---------------------------------------------------------
    st.markdown("---")
    st.subheader("Detalle de Registros Filtrados")
    st.dataframe(df_filtered, use_container_width=True)

except Exception as e:
    st.error(f"Error al cargar el dashboard: {e}")