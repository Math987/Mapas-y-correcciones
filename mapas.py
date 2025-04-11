import streamlit as st
import pandas as pd
import requests
import re
from bs4 import BeautifulSoup
from unidecode import unidecode
from fuzzywuzzy import process, fuzz
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderUnavailable
import folium
from streamlit_folium import st_folium
import time
import traceback

# --- Configuración de Página ---
st.set_page_config(page_title="Mapa de Direcciones Corregidas", layout="wide")
st.title("🗺️ Mapa de Direcciones Corregidas en Conchalí")
print("--- Script Iniciado ---") # Log para ver inicio en consola

# --- Paleta de Colores Base ---
BASE_COLOR_PALETTE = [
    'blue', 'green', 'purple', 'orange', 'darkred', 'cadetblue',
    'darkgreen', 'pink', 'red', 'lightblue', 'darkpurple', 'beige'
]
COLOR_DESCONOCIDO = 'lightgray'
DEFAULT_ASSIGN_COLOR = 'black'

# --- Funciones (sin cambios) ---
@st.cache_data
def obtener_calles_conchali():
    # ... (código idéntico a la versión anterior) ...
    """Obtiene la lista de calles oficiales de Conchalí desde una fuente web."""
    print(">>> Ejecutando obtener_calles_conchali (o usando caché)...") # Log
    url = "https://codigo-postal.co/chile/santiago/calles-de-conchali/"
    try:
        response = requests.get(url, timeout=10) # Reducir timeout un poco?
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        ul_cities = soup.find("ul", class_="cities")
        if not ul_cities:
            st.error("No se pudo encontrar la lista de calles en la URL.")
            return pd.DataFrame(columns=["Calle", "normalizado"])
        li_items = ul_cities.find_all("li")
        calles = [li.find("a").text.strip() for li in li_items if li.find("a")]
        if not calles:
             st.error("No se extrajeron calles de la lista encontrada.")
             return pd.DataFrame(columns=["Calle", "normalizado"])
        df_calles_conchali = pd.DataFrame(calles, columns=["Calle"])
        df_calles_conchali["normalizado"] = df_calles_conchali["Calle"].apply(normalizar)
        print(f"<<< Calles oficiales cargadas/cacheadas: {len(df_calles_conchali)}")
        return df_calles_conchali
    except requests.exceptions.RequestException as e:
        st.error(f"Error de red al obtener las calles: {e}")
        return pd.DataFrame(columns=["Calle", "normalizado"])
    except Exception as e:
        st.error(f"Error inesperado al procesar las calles: {e}")
        return pd.DataFrame(columns=["Calle", "normalizado"])

def normalizar(texto):
    # ... (código idéntico) ...
    """Normaliza el texto: quita acentos, convierte a mayúsculas, elimina no alfanuméricos (excepto espacios) y espacios extra."""
    try:
        texto = unidecode(str(texto)).upper()
        texto = re.sub(r'[^\w\s0-9]', '', texto) # Permite letras, números, espacios y guión bajo
        texto = re.sub(r'\s+', ' ', texto).strip()
        return texto
    except Exception as e:
        # print(f"Error normalizando texto '{texto}': {e}") # Opcional
        return str(texto).upper().strip() # Fallback simple


def corregir_direccion(direccion_input, calles_df, umbral=80):
    # ... (código idéntico) ...
    """Intenta corregir el nombre de la calle usando fuzzy matching contra la lista oficial."""
    original_completa = str(direccion_input).strip()
    match = re.match(r"(.*?)(\s*\d+)$", original_completa)
    if match:
        direccion_texto = match.group(1).strip()
        numero_direccion = match.group(2).strip()
    else:
        direccion_texto = original_completa
        numero_direccion = ""

    if not direccion_texto: return original_completa

    entrada_norm = normalizar(direccion_texto)
    mejor_match = None
    direccion_corregida_texto = direccion_texto

    if calles_df is not None and not calles_df.empty and "normalizado" in calles_df.columns:
        try:
            posibles_matches = process.extract(entrada_norm, calles_df["normalizado"], scorer=fuzz.token_sort_ratio, limit=1)
            if posibles_matches: mejor_match = posibles_matches[0]

            if mejor_match and mejor_match[1] >= umbral:
                idx = calles_df["normalizado"] == mejor_match[0]
                if idx.any(): direccion_corregida_texto = calles_df.loc[idx, "Calle"].values[0]
                else: mejor_match = None
        except Exception as e:
            # print(f"ERROR en fuzzywuzzy o indexación para '{entrada_norm}': {e}") # Opcional
            mejor_match = None

    # score_txt = f"Score: {mejor_match[1]}" if (mejor_match and mejor_match[1] >= umbral) else f"Score: {mejor_match[1] if mejor_match else 'N/A'}"
    # if direccion_corregida_texto.upper() != direccion_texto.upper(): print(f"DEBUG CORRECCION: '{direccion_texto}' -> '{direccion_corregida_texto}' ({score_txt})")
    # else: print(f"DEBUG CORRECCION: '{direccion_texto}' -> NO CORREGIDO ({score_txt})")

    direccion_final = direccion_corregida_texto + (" " + numero_direccion if numero_direccion else "")
    return direccion_final.strip()


@st.cache_data(ttl=3600)
def obtener_coords(direccion_corregida_completa):
    # ... (código idéntico) ...
    """Obtiene coordenadas (lat, lon) para una dirección en Conchalí usando Nominatim."""
    if not direccion_corregida_completa: return None
    direccion_query = f"{direccion_corregida_completa}, Conchalí, Región Metropolitana, Chile"
    # print(f"DEBUG GEO: Buscando: {direccion_query}") # Log opcional
    geolocator = Nominatim(user_agent=f"mapa_conchali_app_v5_{int(time.time())}", timeout=10)
    try:
        location = geolocator.geocode(direccion_query, addressdetails=True)
        if location: return location.latitude, location.longitude
        else: return None
    except GeocoderUnavailable:
        st.warning("Servicio de geocodificación no disponible temporalmente.")
        # time.sleep(5) # Evitar sleep en producción de Streamlit Cloud si es posible
        return None
    except Exception as e:
        st.error(f"Error geocodificación para '{direccion_query}': {e}")
        return None

def cargar_csv_predeterminado():
    # ... (código idéntico) ...
    """Carga los datos desde la URL y prepara la columna 'Que es'."""
    print(">>> Cargando CSV...") # Log
    url = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSAitwliDu4GoT-HU2zXh4eFUDnky9o3M-B9PHHp7RbLWktH7vuHu1BMT3P5zqfVIHAkTptZ8VaZ-F7/pub?gid=1694829461&single=true&output=csv"
    try:
        data = pd.read_csv(url, dtype={'Direccion': str, 'Que es': str})
        if "Direccion" not in data.columns:
            st.error("Columna 'Direccion' no encontrada en el CSV.")
            return None
        data["Direccion"] = data["Direccion"].str.strip()
        if "Que es" in data.columns:
            data["Que es"] = data["Que es"].fillna("DESCONOCIDO").astype(str).str.strip().str.upper()
            data["Que es"] = data["Que es"].replace(r'^\s*$', 'DESCONOCIDO', regex=True)
        else:
            st.warning("Columna 'Que es' no encontrada. Se asignará 'DESCONOCIDO'.")
            data["Que es"] = "DESCONOCIDO"
        print(f"<<< CSV Cargado: {len(data)} filas.") # Log
        return data
    except Exception as e:
        st.error(f"Error al cargar CSV: {e}")
        # st.error(traceback.format_exc()) # Opcional: mostrar error completo
        return None


# --- Inicialización del Estado de Sesión ---
# (Sin cambios)
if "data" not in st.session_state: st.session_state.data = None
if "mapa_csv" not in st.session_state: st.session_state.mapa_csv = None
if "mapa_manual" not in st.session_state: st.session_state.mapa_manual = None
if "mostrar_mapa" not in st.session_state: st.session_state.mostrar_mapa = None

# --- Carga de Datos Estáticos (Calles Oficiales) ---
# calles_df = obtener_calles_conchali() # <-- LÍNEA REMOVIDA DEL ÁMBITO GLOBAL

# --- Widgets de Entrada ---
direccion_input = st.text_input("Ingresa una dirección (ej: Tres Ote. 5317):", key="direccion_manual_key")
usar_csv_button = st.button("Usar csv predeterminado")
print("--- Widgets Definidos ---") # Log

# --- Lógica Principal ---

if usar_csv_button:
    print("--- Botón CSV Presionado ---") # Log
    st.session_state.mapa_manual = None
    st.session_state.mostrar_mapa = None
    st.info("Procesando CSV predeterminado...")

    # --- Carga Perezosa de Calles ---
    print("--- Cargando Calles (CSV)... ---")
    calles_df = obtener_calles_conchali()
    if calles_df.empty:
        st.error("Fallo al cargar calles oficiales. No se puede continuar con el CSV.")
        st.stop() # Detener ejecución si las calles son necesarias y fallan
    # --- Fin Carga Perezosa ---

    try:
        # 1. Cargar datos CSV
        data_cargada = cargar_csv_predeterminado() # Ya tiene logs internos

        if data_cargada is not None and not data_cargada.empty:
            st.session_state.data = data_cargada

            # --- Generación Dinámica de Mapa de Colores ---
            print("--- Generando Mapa de Colores Dinámico... ---") # Log
            dynamic_color_map = {}
            if "Que es" in st.session_state.data.columns:
                unique_types = sorted(list(st.session_state.data["Que es"].unique()))
                palette_len = len(BASE_COLOR_PALETTE)
                color_index = 0
                if "DESCONOCIDO" in unique_types:
                    dynamic_color_map["DESCONOCIDO"] = COLOR_DESCONOCIDO
                for utype in unique_types:
                    if utype not in dynamic_color_map:
                        dynamic_color_map[utype] = BASE_COLOR_PALETTE[color_index % palette_len]
                        color_index += 1
                # st.write("Categorías y colores asignados:") # Opcional mostrar en UI
                # st.json(dynamic_color_map)
                print(f"Mapa de colores generado: {dynamic_color_map}") # Log consola
            else:
                 st.warning("No se generó mapa de colores (falta columna 'Que es').")
            # --- Fin Generación Dinámica ---

            # 2. Corregir direcciones
            print("--- Corrigiendo Direcciones (CSV)... ---") # Log
            st.session_state.data = st.session_state.data.dropna(subset=["Direccion"])
            # Añadir manejo de errores por si corregir_direccion falla en una fila
            def safe_corregir(x, df_calles):
                try: return corregir_direccion(x, df_calles)
                except Exception as e_corr:
                    print(f"Error corrigiendo '{x}': {e_corr}")
                    return x # Devolver original si falla
            st.session_state.data["direccion_corregida"] = st.session_state.data["Direccion"].apply(safe_corregir, args=(calles_df,))


            # (Mostrar tabla - sin cambios)
            st.markdown("### Datos cargados y corregidos (CSV):")
            display_cols = ["Direccion", "direccion_corregida"]
            if "Que es" in st.session_state.data.columns: display_cols.append("Que es")
            st.dataframe(st.session_state.data[display_cols].head(20))
            if len(st.session_state.data) > 20: st.caption(f"... y {len(st.session_state.data) - 20} más.")

            # 3. Obtener coordenadas
            print("--- Obteniendo Coordenadas (CSV)... ---") # Log
            with st.spinner("Obteniendo coordenadas del CSV..."):
                 st.session_state.data = st.session_state.data.dropna(subset=["direccion_corregida"])
                 # Añadir manejo de errores por si obtener_coords falla
                 def safe_coords(x):
                     try: return obtener_coords(x)
                     except Exception as e_coords:
                         print(f"Error en geocoding para '{x}': {e_coords}")
                         return None
                 st.session_state.data["coords"] = st.session_state.data["direccion_corregida"].apply(safe_coords)

            # 4. Filtrar filas sin coordenadas
            original_rows = len(st.session_state.data)
            st.session_state.data = st.session_state.data.dropna(subset=["coords"])
            found_rows = len(st.session_state.data)
            st.success(f"Se encontraron coordenadas para {found_rows} de {original_rows} direcciones.")
            print(f"Coordenadas encontradas: {found_rows}/{original_rows}") # Log


            if not st.session_state.data.empty:
                 # 5. Crear el mapa
                print("--- Creando Mapa Folium (CSV)... ---") # Log
                mapa_obj = folium.Map(location=[-33.38, -70.65], zoom_start=13)
                coords_agregadas = 0
                tipos_en_mapa = set()

                for i, row in st.session_state.data.iterrows():
                    try:
                        tipo = str(row.get("Que es", "DESCONOCIDO")).upper()
                        marker_color = dynamic_color_map.get(tipo, DEFAULT_ASSIGN_COLOR)
                        tipos_en_mapa.add(tipo)
                        popup_text = f"<b>Tipo:</b> {tipo.capitalize()}<br><b>Corregida:</b> {row['direccion_corregida']}<br><b>Original:</b> {row['Direccion']}"
                        tooltip_text = f"{row['direccion_corregida']} ({tipo.capitalize()})"

                        # print(f"DEBUG MARKER: Tipo='{tipo}', Color='{marker_color}'") # Log opcional marcador

                        folium.Marker(
                            location=row["coords"],
                            popup=folium.Popup(popup_text, max_width=300),
                            tooltip=tooltip_text,
                            icon=folium.Icon(color=marker_color, icon='info-sign')
                        ).add_to(mapa_obj)
                        coords_agregadas += 1
                    except Exception as marker_err:
                         st.warning(f"No se pudo añadir marcador para {row.get('direccion_corregida','N/A')}: {marker_err}")

                if coords_agregadas > 0:
                    # (Añadir Leyenda - sin cambios)
                    legend_html = """
                        <div style="position: fixed; bottom: 50px; left: 10px; width: 180px; height: auto; max-height: 250px; border:2px solid grey; z-index:9999; font-size:12px; background-color:rgba(255, 255, 255, 0.9); overflow-y: auto; padding: 10px; border-radius: 5px;">
                        <b style="font-size: 14px;">Leyenda de Tipos</b><br> """
                    colores_usados_para_leyenda = {}
                    for tipo_leg in sorted(list(tipos_en_mapa)):
                        color_leg = dynamic_color_map.get(tipo_leg, DEFAULT_ASSIGN_COLOR)
                        if color_leg not in colores_usados_para_leyenda:
                             colores_usados_para_leyenda[color_leg] = tipo_leg
                             legend_html += f'<i style="background:{color_leg}; border-radius:50%; width: 12px; height: 12px; display: inline-block; margin-right: 6px; border: 1px solid #CCC;"></i>{tipo_leg.capitalize()}<br>'
                    legend_html += "</div>"
                    mapa_obj.get_root().html.add_child(folium.Element(legend_html))

                    st.session_state.mapa_csv = mapa_obj
                    st.session_state.mostrar_mapa = 'csv'
                    st.success(f"Mapa del CSV generado con {coords_agregadas} puntos.")
                    print("--- Mapa CSV Generado y Guardado en Sesión ---") # Log
                else:
                     st.warning("No se agregaron puntos al mapa del CSV.")
                     st.session_state.mapa_csv = None
            else:
                st.warning("No se encontraron coordenadas válidas en el CSV.")
                st.session_state.mapa_csv = None
        else:
             st.error("No se cargaron datos del CSV.")
             st.session_state.data = None
             st.session_state.mapa_csv = None
    except Exception as e:
        st.error(f"Error general al procesar el CSV: {str(e)}")
        st.error(traceback.format_exc())
        st.session_state.data = None
        st.session_state.mapa_csv = None
    print("--- Fin Procesamiento Botón CSV ---") # Log

# --- Lógica Dirección Manual ---
elif direccion_input:
    print("--- Input Manual Detectado ---") # Log
    st.session_state.mapa_csv = None
    st.info(f"Procesando dirección manual: {direccion_input}")

    # --- Carga Perezosa de Calles ---
    print("--- Cargando Calles (Manual)... ---")
    calles_df = obtener_calles_conchali()
    if calles_df.empty:
        st.error("Fallo al cargar calles oficiales. La corrección puede no funcionar.")
        # No detenemos, pero la corrección podría fallar
    # --- Fin Carga Perezosa ---

    # (Resto de lógica manual sin cambios)
    direccion_corregida = corregir_direccion(direccion_input, calles_df)
    print(f"Dirección manual corregida a: {direccion_corregida}") # Log
    with st.spinner("Obteniendo coordenadas..."):
        coords = obtener_coords(direccion_corregida)
    st.markdown("---")
    st.markdown("### ✅ Resultado Dirección Manual:")
    st.write(f"**Dirección original:** {direccion_input}")
    st.write(f"**Dirección corregida:** {direccion_corregida}")
    if coords:
        st.write(f"**Ubicación aproximada:** {coords[0]:.5f}, {coords[1]:.5f}")
        try:
            mapa_manual_obj = folium.Map(location=coords, zoom_start=16)
            folium.Marker(
                location=coords,
                popup=folium.Popup(f"Corregida: {direccion_corregida}<br>Original: {direccion_input}", max_width=300),
                tooltip=direccion_corregida
                ).add_to(mapa_manual_obj)
            st.session_state.mapa_manual = mapa_manual_obj
            st.session_state.mostrar_mapa = 'manual'
            st.success("Mapa para dirección manual generado.")
            print("--- Mapa Manual Generado ---") # Log
        except Exception as e:
             st.error(f"Error al crear mapa manual: {e}")
             st.session_state.mapa_manual = None
             st.session_state.mostrar_mapa = None
    else:
        st.warning("No se pudo obtener ubicación para dirección corregida.")
        st.session_state.mapa_manual = None
        if st.session_state.mostrar_mapa == 'manual': st.session_state.mostrar_mapa = None
    print("--- Fin Procesamiento Manual ---") # Log


# --- Mostrar el mapa correspondiente ---
st.markdown("---")
map_to_show = st.session_state.get("mostrar_mapa")
csv_map_obj = st.session_state.get("mapa_csv")
manual_map_obj = st.session_state.get("mapa_manual")

print(f"--- Mostrando Mapa: {map_to_show} ---") # Log

if map_to_show == 'csv' and csv_map_obj:
    st.markdown("### 🗺️ Mapa CSV (Colores Dinámicos)")
    st_folium(csv_map_obj, key="folium_map_csv_dynamic_color", width=700, height=500, returned_objects=[])
elif map_to_show == 'manual' and manual_map_obj:
    st.markdown("### 🗺️ Mapa Dirección Manual")
    st_folium(manual_map_obj, key="folium_map_manual", width=700, height=500, returned_objects=[])
else:
    if not usar_csv_button and not direccion_input: # Mostrar solo si no se está procesando nada
        st.info("Mapa aparecerá aquí después de procesar datos.")

print("--- Script Finalizado ---") # Log
