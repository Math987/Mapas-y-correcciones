import streamlit as st
import pandas as pd
import requests
import re
from bs4 import BeautifulSoup
from unidecode import unidecode
from fuzzywuzzy import process, fuzz # Asegúrate de tener instalado: pip install fuzzywuzzy python-Levenshtein
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderUnavailable
import folium
from streamlit_folium import st_folium
import time # Para posibles reintentos o esperas

# --- Configuración de Página ---
st.set_page_config(page_title="Mapa de Direcciones Corregidas", layout="wide")
st.title("🗺️ Mapa de Direcciones Corregidas en Conchalí")

# --- Funciones ---

@st.cache_data # Cachear para no descargar cada vez
def obtener_calles_conchali():
    """Obtiene la lista de calles oficiales de Conchalí desde una fuente web."""
    url = "https://codigo-postal.co/chile/santiago/calles-de-conchali/"
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status() # Lanza error para códigos 4xx/5xx
        soup = BeautifulSoup(response.text, "html.parser")
        ul_cities = soup.find("ul", class_="cities")
        if not ul_cities:
            st.error("No se pudo encontrar la lista de calles en la URL (estructura cambiada?).")
            return pd.DataFrame(columns=["Calle", "normalizado"]) # Devuelve DF vacío
        li_items = ul_cities.find_all("li")
        calles = [li.find("a").text.strip() for li in li_items if li.find("a")]
        if not calles:
             st.error("No se extrajeron calles de la lista encontrada.")
             return pd.DataFrame(columns=["Calle", "normalizado"])

        df_calles_conchali = pd.DataFrame(calles, columns=["Calle"])
        df_calles_conchali["normalizado"] = df_calles_conchali["Calle"].apply(normalizar)
        print(f"Calles oficiales cargadas: {len(df_calles_conchali)}") # Info en consola
        return df_calles_conchali
    except requests.exceptions.RequestException as e:
        st.error(f"Error al obtener las calles desde la URL: {e}")
        return pd.DataFrame(columns=["Calle", "normalizado"]) # Devuelve DF vacío en caso de error de red
    except Exception as e:
        st.error(f"Error inesperado al procesar las calles: {e}")
        return pd.DataFrame(columns=["Calle", "normalizado"])

def normalizar(texto):
    """Normaliza el texto: quita acentos, convierte a mayúsculas, elimina no alfanuméricos (excepto espacios) y espacios extra."""
    try:
        texto = unidecode(str(texto)).upper()
        texto = re.sub(r'[^\w\s0-9]', '', texto) # Permite letras, números, espacios y guión bajo
        texto = re.sub(r'\s+', ' ', texto).strip()
        return texto
    except Exception as e:
        print(f"Error normalizando texto '{texto}': {e}")
        return str(texto).upper().strip() # Fallback simple

def corregir_direccion(direccion_input, calles_df, umbral=80):
    """Intenta corregir el nombre de la calle usando fuzzy matching contra la lista oficial."""
    original_completa = str(direccion_input).strip()
    match = re.match(r"(.*?)(\s*\d+)$", original_completa)
    if match:
        direccion_texto = match.group(1).strip()
        numero_direccion = match.group(2).strip()
    else:
        direccion_texto = original_completa
        numero_direccion = ""

    if not direccion_texto:
        # print(f"DEBUG: No street text found in '{original_completa}'")
        return original_completa

    entrada_norm = normalizar(direccion_texto)
    mejor_match = None
    direccion_corregida_texto = direccion_texto # Default: no corregir texto de calle

    # Solo intentar corregir si hay calles oficiales cargadas
    if calles_df is not None and not calles_df.empty and "normalizado" in calles_df.columns:
        try:
            # token_sort_ratio es bueno para palabras desordenadas
            posibles_matches = process.extract(entrada_norm, calles_df["normalizado"], scorer=fuzz.token_sort_ratio, limit=1)
            if posibles_matches:
                 mejor_match = posibles_matches[0] # extract devuelve lista [(match, score)]

            if mejor_match and mejor_match[1] >= umbral:
                # Encontrar la calle original correspondiente al match normalizado
                idx = calles_df["normalizado"] == mejor_match[0]
                if idx.any():
                    direccion_corregida_texto = calles_df.loc[idx, "Calle"].values[0]
                else:
                    # Si no se encuentra el índice (raro), anular el match
                    print(f"WARN: Match '{mejor_match[0]}' no encontrado en índice df original.")
                    mejor_match = None
        except Exception as e:
            print(f"ERROR en fuzzywuzzy o indexación para '{entrada_norm}': {e}")
            mejor_match = None # Fallo en la corrección

    # ---- IMPRESION DEBUG (SE MOSTRARÁ EN LA CONSOLA/TERMINAL) ----
    score_txt = f"Score: {mejor_match[1]}" if (mejor_match and mejor_match[1] >= umbral) else f"Score: {mejor_match[1] if mejor_match else 'N/A'}"
    if direccion_corregida_texto.upper() != direccion_texto.upper():
        print(f"DEBUG CORRECCION: '{direccion_texto}' -> '{direccion_corregida_texto}' ({score_txt})")
    else:
        print(f"DEBUG CORRECCION: '{direccion_texto}' -> NO CORREGIDO ({score_txt})")
    # --------------------------------------------------------------

    direccion_final = direccion_corregida_texto + (" " + numero_direccion if numero_direccion else "")
    return direccion_final.strip()

# Usar cache para evitar llamar repetidamente a Nominatim para la *misma* dirección corregida
@st.cache_data(ttl=3600) # Cachear por 1 hora
def obtener_coords(direccion_corregida_completa):
    """Obtiene coordenadas (lat, lon) para una dirección en Conchalí usando Nominatim."""
    if not direccion_corregida_completa:
        return None

    # Añadir comuna y país mejora la precisión
    direccion_query = f"{direccion_corregida_completa}, Conchalí, Región Metropolitana, Chile"
    # print(f"DEBUG GEO: Buscando coordenadas para: '{direccion_query}'") # Descomentar para debug detallado

    geolocator = Nominatim(user_agent=f"mapa_conchali_app_v3_{int(time.time())}", timeout=10) # User agent único
    try:
        location = geolocator.geocode(direccion_query, addressdetails=True)
        if location:
            # Verificación opcional (puede ser demasiado estricta):
            # address = location.raw.get('address', {})
            # if address.get('suburb') == 'Conchalí' or address.get('city_district') == 'Conchalí':
            #     print(f"DEBUG GEO: Encontrado en Conchalí: {location.address}")
            #     return location.latitude, location.longitude
            # else:
            #     print(f"DEBUG GEO: Encontrado pero fuera de Conchalí?: {location.address}")
            #     return None # Descartar si no confirma comuna

            # Verificación más simple: confiar en Nominatim si devuelve algo con la query específica
            # print(f"DEBUG GEO: Encontrado: {location.address} -> ({location.latitude}, {location.longitude})")
            return location.latitude, location.longitude
        else:
             # print(f"DEBUG GEO: No encontrado: {direccion_query}")
             return None
    except GeocoderUnavailable:
        st.warning("Servicio de geocodificación (Nominatim) no disponible temporalmente. Reintentando en unos segundos...")
        time.sleep(5) # Esperar un poco antes de reintentar automáticamente (o manejarlo manualmente)
        # Se podría reintentar una vez aquí, o simplemente devolver None
        return None
    except Exception as e:
        st.error(f"Error inesperado durante geocodificación para '{direccion_query}': {e}")
        return None

def cargar_csv_predeterminado():
    """Carga los datos desde la URL del Google Sheet publicado."""
    url = "https://docs.google.com/spreadsheets/d/e/2PACX-1vR1sj1BfL4P6_EO0EGhN2e2qeQA78Rmvl0s7nGhrlGnEBo7ZCa6OrJL1B0gF_JoaiMEpqmtap7WfzxI/pub?gid=0&single=true&output=csv"
    try:
        data = pd.read_csv(url, dtype={'Direccion': str}) # Leer columna dirección como texto
        # Limpiar espacios extra en la columna de dirección original
        if "Direccion" in data.columns:
             data["Direccion"] = data["Direccion"].str.strip()
        return data
    except Exception as e:
        st.error(f"Error al cargar el CSV desde la URL: {e}")
        return None

# --- Inicialización del Estado de Sesión ---
if "data" not in st.session_state:
    st.session_state.data = None # DataFrame cargado
if "mapa_csv" not in st.session_state:
    st.session_state.mapa_csv = None # Objeto Folium Map para CSV
if "mapa_manual" not in st.session_state:
    st.session_state.mapa_manual = None # Objeto Folium Map para entrada manual
if "mostrar_mapa" not in st.session_state:
    st.session_state.mostrar_mapa = None # 'csv', 'manual', o None

# --- Carga de Datos Estáticos (Calles Oficiales) ---
calles_df = obtener_calles_conchali()
if calles_df.empty:
    st.error("No se pudieron cargar las calles oficiales. La corrección de direcciones no funcionará.")

# --- Widgets de Entrada ---
direccion_input = st.text_input("Ingresa una dirección (ej: Tres Ote. 5317):", key="direccion_manual_key")
usar_csv_button = st.button("Usar csv predeterminado")

# --- Lógica Principal (CON PRIORIDAD DE BOTÓN) ---

if usar_csv_button:
    # Si se presiona el botón, esta es la única lógica de procesamiento que corre
    st.session_state.mapa_manual = None # Limpiar mapa manual anterior
    st.session_state.mostrar_mapa = None # Resetear qué mostrar
    st.info("Procesando CSV predeterminado...")

    try:
        # Cargar datos CSV
        data_cargada = cargar_csv_predeterminado()
        if data_cargada is not None and not data_cargada.empty:
            st.session_state.data = data_cargada

            if "Direccion" not in st.session_state.data.columns:
                st.error("❌ El archivo CSV no contiene una columna llamada 'Direccion'.")
                st.session_state.data = None
                st.session_state.mapa_csv = None
            else:
                # Asegurarse de que la columna Dirección no tenga Nulos que rompan el apply
                st.session_state.data = st.session_state.data.dropna(subset=["Direccion"])
                st.session_state.data["Direccion"] = st.session_state.data["Direccion"].astype(str)

                # 1. Corregir direcciones
                st.session_state.data["direccion_corregida"] = st.session_state.data["Direccion"].apply(
                    lambda x: corregir_direccion(x, calles_df) if pd.notna(x) else None
                )

                # Mostrar tabla con correcciones antes de geocodificar
                st.markdown("### Correcciones aplicadas (CSV):")
                st.dataframe(st.session_state.data[["Direccion", "direccion_corregida"]].head(20))
                if len(st.session_state.data) > 20:
                    st.caption(f"... y {len(st.session_state.data) - 20} más.")

                # 2. Obtener coordenadas (usando la dirección corregida)
                with st.spinner("Obteniendo coordenadas del CSV... Esto puede tardar."):
                    st.session_state.data["coords"] = st.session_state.data["direccion_corregida"].apply(
                         lambda x: obtener_coords(x) if pd.notna(x) else None
                    )

                # 3. Filtrar filas sin coordenadas
                original_rows = len(st.session_state.data)
                st.session_state.data = st.session_state.data.dropna(subset=["coords"])
                found_rows = len(st.session_state.data)
                st.success(f"Se encontraron coordenadas para {found_rows} de {original_rows} direcciones procesadas.")

                if not st.session_state.data.empty:
                     # 4. Crear el mapa
                    mapa_obj = folium.Map(location=[-33.38, -70.65], zoom_start=13) # Centro aproximado de Conchalí
                    coords_agregadas = 0
                    for i, row in st.session_state.data.iterrows():
                        try:
                            popup_text = f"Corregida: {row['direccion_corregida']}<br>Original: {row['Direccion']}"
                            folium.Marker(
                                location=row["coords"],
                                popup=folium.Popup(popup_text, max_width=300), # Popup con ancho máx
                                tooltip=row['direccion_corregida'] # Tooltip simple al pasar el mouse
                            ).add_to(mapa_obj)
                            coords_agregadas += 1
                        except Exception as marker_err:
                             st.warning(f"No se pudo añadir marcador para {row['direccion_corregida']} en {row['coords']}: {marker_err}")

                    if coords_agregadas > 0:
                         st.session_state.mapa_csv = mapa_obj
                         st.session_state.mostrar_mapa = 'csv' # Indicar que se debe mostrar este mapa
                         st.success(f"Mapa del CSV generado con {coords_agregadas} puntos.")
                    else:
                         st.warning("No se pudieron agregar puntos al mapa del CSV.")
                         st.session_state.mapa_csv = None

                else:
                    st.warning("⚠️ No se encontraron coordenadas válidas para ninguna dirección en el CSV después del procesamiento.")
                    st.session_state.mapa_csv = None

        else:
             st.error("No se pudieron cargar los datos del CSV o el archivo está vacío.")
             st.session_state.data = None
             st.session_state.mapa_csv = None

    except Exception as e:
        st.error(f"⚠️ Error general al procesar el CSV: {str(e)}")
        import traceback
        st.error(traceback.format_exc()) # Mostrar traceback detallado para errores inesperados
        st.session_state.data = None
        st.session_state.mapa_csv = None

# Usar 'elif' para que esto solo se ejecute si el botón NO fue presionado Y hay texto en el input
elif direccion_input:
    st.session_state.mapa_csv = None # Limpiar mapa CSV anterior
    st.info(f"Procesando dirección manual: {direccion_input}")

    # 1. Corregir dirección manual
    direccion_corregida = corregir_direccion(direccion_input, calles_df)

    # 2. Obtener coordenadas (usando la dirección corregida)
    with st.spinner("Obteniendo coordenadas..."):
        coords = obtener_coords(direccion_corregida)

    st.markdown("---")
    st.markdown("### ✅ Resultado Dirección Manual:")
    st.write(f"**Dirección original:** {direccion_input}")
    st.write(f"**Dirección corregida:** {direccion_corregida}")

    if coords:
        st.write(f"**Ubicación aproximada:** {coords[0]:.5f}, {coords[1]:.5f}") # Mostrar con 5 decimales

        # 3. Crear mapa manual
        try:
            mapa_manual_obj = folium.Map(location=coords, zoom_start=16) # Zoom más cercano para una sola dirección
            folium.Marker(
                location=coords,
                popup=folium.Popup(f"Corregida: {direccion_corregida}<br>Original: {direccion_input}", max_width=300),
                tooltip=direccion_corregida
                ).add_to(mapa_manual_obj)
            st.session_state.mapa_manual = mapa_manual_obj
            st.session_state.mostrar_mapa = 'manual' # Indicar que se muestre este mapa
            st.success("Mapa para dirección manual generado.")
        except Exception as e:
             st.error(f"Error al crear el mapa manual: {e}")
             st.session_state.mapa_manual = None
             st.session_state.mostrar_mapa = None

    else:
        st.warning("No se pudo obtener la ubicación para la dirección corregida.")
        st.session_state.mapa_manual = None
        if st.session_state.mostrar_mapa == 'manual': # Si antes se mostraba el manual, ocultarlo
             st.session_state.mostrar_mapa = None

# --- Mostrar el mapa correspondiente (FUERA de los bloques 'if'/'elif') ---
st.markdown("---")

# Usar .get() para evitar errores si la clave no existe (aunque debería por la inicialización)
map_to_show = st.session_state.get("mostrar_mapa")
csv_map_obj = st.session_state.get("mapa_csv")
manual_map_obj = st.session_state.get("mapa_manual")

if map_to_show == 'csv' and csv_map_obj:
    st.markdown("### 🗺️ Mapa con direcciones del CSV")
    st_folium(csv_map_obj, key="folium_map_csv", width=700, height=500, returned_objects=[])
elif map_to_show == 'manual' and manual_map_obj:
    st.markdown("### 🗺️ Mapa con la dirección manual")
    st_folium(manual_map_obj, key="folium_map_manual", width=700, height=500, returned_objects=[])
else:
    # No mostrar nada o un mensaje si no hay mapa que mostrar
    st.info("Mapa aparecerá aquí después de procesar una dirección o el CSV.")
