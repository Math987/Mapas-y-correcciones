# -*- coding: utf-8 -*- # Añadir encoding por si acaso con los nombres largos
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
print("--- Script Iniciado ---")

# --- Constantes de Nombres de Columnas ---
COLUMNA_DIRECCION_ORIGINAL = u'¿Dónde ocurre este problema? (Por favor indica la dirección lo más exacta posible, Calle, Numero y Comuna)' # Usar u'' para unicode explícito
COLUMNA_TIPO_ORIGINAL = u' ¿Qué tipo de problema estás reportando? ' # Usar u'' para unicode explícito
COLUMNA_DIRECCION_NUEVA = 'Direccion'

# --- Paleta de Colores Base ---
BASE_COLOR_PALETTE = [
    'blue', 'green', 'purple', 'orange', 'darkred', 'cadetblue',
    'darkgreen', 'pink', 'red', 'lightblue', 'darkpurple', 'beige'
]
COLOR_DESCONOCIDO = 'lightgray'
DEFAULT_ASSIGN_COLOR = 'black' # Color si el tipo no se encuentra en el mapa

# --- Funciones ---
@st.cache_data
def obtener_calles_conchali():
    """Obtiene la lista de calles oficiales de Conchalí desde una fuente web."""
    print(">>> Ejecutando obtener_calles_conchali (o usando caché)...")
    url = "https://codigo-postal.co/chile/santiago/calles-de-conchali/"
    try:
        response = requests.get(url, timeout=10)
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
    """Normaliza el texto: quita acentos, convierte a mayúsculas, elimina no alfanuméricos (excepto espacios) y espacios extra."""
    try:
        texto = unidecode(str(texto)).upper()
        texto = re.sub(r'[^\w\s0-9]', '', texto)
        texto = re.sub(r'\s+', ' ', texto).strip()
        return texto
    except Exception as e:
        return str(texto).upper().strip()

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
            mejor_match = None

    direccion_final = direccion_corregida_texto + (" " + numero_direccion if numero_direccion else "")
    return direccion_final.strip()

@st.cache_data(ttl=3600)
def obtener_coords(direccion_corregida_completa):
    """Obtiene coordenadas (lat, lon) para una dirección en Conchalí usando Nominatim."""
    if not direccion_corregida_completa: return None
    direccion_query = f"{direccion_corregida_completa}, Conchalí, Región Metropolitana, Chile"
    geolocator = Nominatim(user_agent=f"mapa_conchali_app_v8_{int(time.time())}", timeout=10) # Incrementar versión agente
    try:
        location = geolocator.geocode(direccion_query, addressdetails=True)
        if location: return location.latitude, location.longitude
        else: return None
    except GeocoderUnavailable:
        st.warning("Servicio de geocodificación no disponible temporalmente.")
        return None
    except Exception as e:
        st.error(f"Error geocodificación para '{direccion_query}': {e}")
        return None

def cargar_csv_predeterminado():
    """Carga los datos desde la URL, renombra columna de DIRECCIÓN y procesa columna de TIPO (nombre original)."""
    print(">>> Cargando CSV...")
    url = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSAitwliDu4GoT-HU2zXh4eFUDnky9o3M-B9PHHp7RbLWktH7vuHu1BMT3P5zqfVIHAkTptZ8VaZ-F7/pub?gid=1694829461&single=true&output=csv"
    try:
        data = pd.read_csv(url, dtype={
            COLUMNA_DIRECCION_ORIGINAL: str,
            COLUMNA_TIPO_ORIGINAL: str
        })
        print("--- Columnas Originales Detectadas ---")
        print(data.columns)

        # --- Procesar Columna Dirección ---
        if COLUMNA_DIRECCION_ORIGINAL in data.columns:
            data.rename(columns={COLUMNA_DIRECCION_ORIGINAL: COLUMNA_DIRECCION_NUEVA}, inplace=True)
            print(f"Columna dirección renombrada a '{COLUMNA_DIRECCION_NUEVA}'")
            data[COLUMNA_DIRECCION_NUEVA] = data[COLUMNA_DIRECCION_NUEVA].str.strip()
        else:
            st.error(f"Error crítico: No se encontró la columna de dirección: '{COLUMNA_DIRECCION_ORIGINAL}'")
            return None

        # --- Procesar Columna Tipo (USANDO NOMBRE ORIGINAL) ---
        if COLUMNA_TIPO_ORIGINAL in data.columns:
            print(f"Procesando columna de tipo: '{COLUMNA_TIPO_ORIGINAL}'...")
            # Asegurar que ANTES de usar fillna, etc. la columna sea de tipo string
            data[COLUMNA_TIPO_ORIGINAL] = data[COLUMNA_TIPO_ORIGINAL].astype(str)
            data[COLUMNA_TIPO_ORIGINAL] = data[COLUMNA_TIPO_ORIGINAL].fillna("DESCONOCIDO") # Fillna ahora debería funcionar
            data[COLUMNA_TIPO_ORIGINAL] = data[COLUMNA_TIPO_ORIGINAL].str.strip().str.upper() # Aplicar strip y upper
            data[COLUMNA_TIPO_ORIGINAL] = data[COLUMNA_TIPO_ORIGINAL].replace(r'^\s*$', 'DESCONOCIDO', regex=True) # Reemplazar vacíos post-strip
            # Opcional: Ver valores únicos después de limpiar
            # print("Valores únicos en columna tipo (limpios):")
            # print(data[COLUMNA_TIPO_ORIGINAL].unique())
        else:
            st.warning(f"Advertencia: No se encontró la columna de tipo: '{COLUMNA_TIPO_ORIGINAL}'. Se creará con valor 'DESCONOCIDO'.")
            data[COLUMNA_TIPO_ORIGINAL] = "DESCONOCIDO"

        print("--- Columnas Finales en DataFrame ---")
        print(data.columns)
        print(f"<<< CSV Cargado y Procesado: {len(data)} filas.")
        return data

    except Exception as e:
        st.error(f"Error general al cargar o procesar el CSV: {e}")
        st.error(traceback.format_exc())
        return None

# --- Inicialización del Estado de Sesión ---
if "data" not in st.session_state: st.session_state.data = None
if "mapa_csv" not in st.session_state: st.session_state.mapa_csv = None
if "mapa_manual" not in st.session_state: st.session_state.mapa_manual = None
if "mostrar_mapa" not in st.session_state: st.session_state.mostrar_mapa = None

# --- Widgets de Entrada ---
direccion_input = st.text_input("Ingresa una dirección (ej: Tres Ote. 5317):", key="direccion_manual_key")
usar_csv_button = st.button("Usar csv predeterminado")
print("--- Widgets Definidos ---")

# --- Lógica Principal ---
if usar_csv_button:
    print("--- Botón CSV Presionado ---")
    st.session_state.mapa_manual = None
    st.session_state.mostrar_mapa = None
    st.session_state.data = None
    st.session_state.mapa_csv = None
    st.info("Procesando CSV predeterminado...")

    print("--- Cargando Calles (CSV)... ---")
    calles_df = obtener_calles_conchali()
    if calles_df is None or calles_df.empty:
        st.error("Fallo al cargar calles oficiales. No se puede continuar.")
        st.stop()

    try:
        data_cargada = cargar_csv_predeterminado()

        if data_cargada is not None and not data_cargada.empty:
            st.session_state.data = data_cargada

            # --- Generación Dinámica de Mapa de Colores ---
            print("--- Generando Mapa de Colores Dinámico... ---")
            dynamic_color_map = {}
            if COLUMNA_TIPO_ORIGINAL in st.session_state.data.columns:
                # Asegurarse que los tipos únicos se obtienen DESPUÉS de la limpieza en cargar_csv
                unique_types = sorted(list(st.session_state.data[COLUMNA_TIPO_ORIGINAL].unique()))
                print(f"Tipos únicos encontrados para mapa de colores: {unique_types}") # DEBUG
                palette_len = len(BASE_COLOR_PALETTE)
                color_index = 0
                # Asignar color DESCONOCIDO primero si existe
                if "DESCONOCIDO" in unique_types:
                    dynamic_color_map["DESCONOCIDO"] = COLOR_DESCONOCIDO
                # Asignar colores al resto
                for utype in unique_types:
                    if utype not in dynamic_color_map: # Evitar sobreescribir DESCONOCIDO
                        dynamic_color_map[utype] = BASE_COLOR_PALETTE[color_index % palette_len]
                        color_index += 1

                # --- DEBUG: Imprimir el mapa de colores generado ---
                print("--- Mapa de Colores Generado ---")
                print(dynamic_color_map)
                # --- FIN DEBUG ---

            else:
                st.warning(f"Columna '{COLUMNA_TIPO_ORIGINAL}' no encontrada para generar mapa de colores.")
                dynamic_color_map["DESCONOCIDO"] = COLOR_DESCONOCIDO # Default si falta la columna

            # --- Corregir direcciones ---
            print("--- Corrigiendo Direcciones (CSV)... ---")
            if COLUMNA_DIRECCION_NUEVA in st.session_state.data.columns:
                st.session_state.data = st.session_state.data.dropna(subset=[COLUMNA_DIRECCION_NUEVA])
                def safe_corregir(x, df_calles):
                    try: return corregir_direccion(x, df_calles)
                    except Exception as e_corr:
                        print(f"Error corrigiendo '{x}': {e_corr}")
                        return x
                st.session_state.data["direccion_corregida"] = st.session_state.data[COLUMNA_DIRECCION_NUEVA].apply(safe_corregir, args=(calles_df,))
            else:
                 st.error(f"Falta la columna '{COLUMNA_DIRECCION_NUEVA}' después de cargar/renombrar.")
                 st.stop()

            # --- Mostrar tabla ---
            st.markdown("### Datos cargados y corregidos (CSV):")
            display_cols = []
            if COLUMNA_DIRECCION_NUEVA in st.session_state.data.columns: display_cols.append(COLUMNA_DIRECCION_NUEVA)
            if "direccion_corregida" in st.session_state.data.columns: display_cols.append("direccion_corregida")
            if COLUMNA_TIPO_ORIGINAL in st.session_state.data.columns: display_cols.append(COLUMNA_TIPO_ORIGINAL)

            if display_cols and not st.session_state.data.empty:
                 st.dataframe(st.session_state.data[display_cols].head(20))
                 if len(st.session_state.data) > 20: st.caption(f"... y {len(st.session_state.data) - 20} más.")
            else:
                 st.warning("No hay datos o columnas relevantes para mostrar en la tabla.")

            # --- Obtener coordenadas ---
            print("--- Obteniendo Coordenadas (CSV)... ---")
            if "direccion_corregida" in st.session_state.data.columns:
                with st.spinner("Obteniendo coordenadas del CSV..."):
                    if "direccion_corregida" in st.session_state.data.columns:
                         st.session_state.data = st.session_state.data.dropna(subset=["direccion_corregida"])

                    if not st.session_state.data.empty:
                        def safe_coords(x):
                            try: return obtener_coords(x)
                            except Exception as e_coords:
                                print(f"Error en geocoding para '{x}': {e_coords}")
                                return None
                        st.session_state.data["coords"] = st.session_state.data["direccion_corregida"].apply(safe_coords)

                        original_rows = len(st.session_state.data)
                        st.session_state.data = st.session_state.data.dropna(subset=["coords"])
                        found_rows = len(st.session_state.data)
                        if original_rows > 0: # Evitar división por cero si no había filas
                            st.success(f"Se encontraron coordenadas para {found_rows} de {original_rows} direcciones procesadas.")
                        else:
                            st.info("No había direcciones válidas para geocodificar.")
                        print(f"Coordenadas encontradas: {found_rows}/{original_rows}")
                    else:
                         st.warning("No quedaron direcciones válidas después de limpiar nulos en 'direccion_corregida'.")
                         st.session_state.data["coords"] = None
            else:
                st.warning("No se pudo proceder a la geocodificación (falta 'direccion_corregida').")
                st.session_state.data["coords"] = None

            # --- Crear el mapa ---
            if "coords" in st.session_state.data.columns and not st.session_state.data.empty and not st.session_state.data["coords"].isnull().all():
                print("--- Creando Mapa Folium (CSV)... ---")
                coords_list = st.session_state.data['coords'].tolist()
                map_center = [-33.38, -70.65]
                if coords_list:
                    valid_coords = [c for c in coords_list if isinstance(c, tuple) and len(c) == 2]
                    if valid_coords:
                        avg_lat = sum(c[0] for c in valid_coords) / len(valid_coords)
                        avg_lon = sum(c[1] for c in valid_coords) / len(valid_coords)
                        map_center = [avg_lat, avg_lon]

                mapa_obj = folium.Map(location=map_center, zoom_start=13)
                coords_agregadas = 0
                tipos_en_mapa = set()

                print("--- Añadiendo Marcadores al Mapa (DEBUG primeras 5 filas) ---") # DEBUG
                for i, row in st.session_state.data.iterrows():
                    try:
                        # Obtener tipo usando el NOMBRE ORIGINAL y estandarizar IGUAL que al crear el mapa de color
                        tipo = str(row.get(COLUMNA_TIPO_ORIGINAL, "DESCONOCIDO")).strip().upper()
                        if tipo == '': tipo = "DESCONOCIDO" # Asegurar que strings vacíos post-strip se traten como DESCONOCIDO

                        # Buscar color en el mapa generado
                        marker_color = dynamic_color_map.get(tipo, DEFAULT_ASSIGN_COLOR)
                        tipos_en_mapa.add(tipo) # Añadir tipo REAL encontrado para la leyenda

                        # --- DEBUG PRINT dentro del loop ---
                        if i < 5 or i % 50 == 0: # Imprimir para las primeras 5 y luego cada 50
                             print(f"Row {i}: Tipo='{tipo}', Color Lookup='{marker_color}' (Tipo existe en mapa? {tipo in dynamic_color_map})")
                        # --- FIN DEBUG PRINT ---

                        popup_text = f"<b>Tipo:</b> {tipo.capitalize()}<br>"
                        if "direccion_corregida" in row and pd.notna(row['direccion_corregida']):
                             popup_text += f"<b>Corregida:</b> {row['direccion_corregida']}<br>"
                        if COLUMNA_DIRECCION_NUEVA in row and pd.notna(row[COLUMNA_DIRECCION_NUEVA]):
                             popup_text += f"<b>Original:</b> {row[COLUMNA_DIRECCION_NUEVA]}"

                        tooltip_text = row.get('direccion_corregida', 'Ubicación') + f" ({tipo.capitalize()})"

                        folium.Marker(
                            location=row["coords"],
                            popup=folium.Popup(popup_text, max_width=300),
                            tooltip=tooltip_text,
                            icon=folium.Icon(color=marker_color, icon='info-sign')
                        ).add_to(mapa_obj)
                        coords_agregadas += 1
                    except Exception as marker_err:
                        st.warning(f"No se pudo añadir marcador para fila {i}: {marker_err} - Tipo problemático: '{row.get(COLUMNA_TIPO_ORIGINAL, 'N/A')}'")


                if coords_agregadas > 0:
                    # Leyenda
                    legend_html = """
                        <div style="position: fixed; bottom: 50px; left: 10px; width: 180px; height: auto; max-height: 250px; border:2px solid grey; z-index:9999; font-size:12px; background-color:rgba(255, 255, 255, 0.9); overflow-y: auto; padding: 10px; border-radius: 5px;">
                        <b style="font-size: 14px;">Leyenda de Tipos</b><br> """
                    # Usar dynamic_color_map para la leyenda, mostrando solo los tipos REALMENTE en el mapa
                    tipos_relevantes_leyenda = sorted([t for t in dynamic_color_map.keys() if t in tipos_en_mapa])
                    print(f"--- Tipos para la leyenda: {tipos_relevantes_leyenda} ---") # DEBUG
                    for tipo_leg in tipos_relevantes_leyenda:
                         color_leg = dynamic_color_map.get(tipo_leg, DEFAULT_ASSIGN_COLOR)
                         # Evitar duplicados si DESCONOCIDO fue añadido explícitamente y también existe en los datos
                         legend_html += f'<i style="background:{color_leg}; border-radius:50%; width: 12px; height: 12px; display: inline-block; margin-right: 6px; border: 1px solid #CCC;"></i>{tipo_leg.capitalize()}<br>'
                    legend_html += "</div>"
                    mapa_obj.get_root().html.add_child(folium.Element(legend_html))

                    st.session_state.mapa_csv = mapa_obj
                    st.session_state.mostrar_mapa = 'csv'
                    print("--- Mapa CSV Generado y Guardado en Sesión ---")
                else:
                    st.warning("No se agregaron puntos al mapa del CSV.")
                    st.session_state.mapa_csv = None
                    if st.session_state.mostrar_mapa == 'csv': st.session_state.mostrar_mapa = None
            else:
                 st.warning("No se pudo generar el mapa (sin coordenadas válidas).")
                 st.session_state.mapa_csv = None

        else:
            st.error("No se cargaron datos válidos del CSV.")
            st.session_state.data = None
            st.session_state.mapa_csv = None

    except Exception as e:
        st.error(f"Error inesperado durante el procesamiento del CSV: {str(e)}")
        st.error(traceback.format_exc())
        st.session_state.data = None
        st.session_state.mapa_csv = None
    print("--- Fin Procesamiento Botón CSV ---")

# --- Lógica Dirección Manual ---
elif direccion_input:
    print("--- Input Manual Detectado ---")
    st.session_state.mapa_csv = None
    st.session_state.data = None
    st.session_state.mostrar_mapa = None
    st.info(f"Procesando dirección manual: {direccion_input}")

    print("--- Cargando Calles (Manual)... ---")
    calles_df = obtener_calles_conchali()
    if calles_df is None or calles_df.empty:
        st.error("Fallo al cargar calles oficiales. La corrección puede no funcionar.")

    direccion_corregida = corregir_direccion(direccion_input, calles_df)
    print(f"Dirección manual corregida a: {direccion_corregida}")
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
            print("--- Mapa Manual Generado ---")
        except Exception as e:
            st.error(f"Error al crear mapa manual: {e}")
            st.session_state.mapa_manual = None
            st.session_state.mostrar_mapa = None
    else:
        st.warning("No se pudo obtener ubicación para la dirección corregida.")
        st.session_state.mapa_manual = None
    print("--- Fin Procesamiento Manual ---")

# --- Mostrar el mapa correspondiente ---
st.markdown("---")
map_to_show = st.session_state.get("mostrar_mapa")
csv_map_obj = st.session_state.get("mapa_csv")
manual_map_obj = st.session_state.get("mapa_manual")

print(f"--- Decidiendo qué Mapa Mostrar: {map_to_show} ---")

if map_to_show == 'csv' and csv_map_obj:
    st.markdown("### 🗺️ Mapa CSV")
    st_folium(csv_map_obj, key="folium_map_csv_v4", width='100%', height=600, returned_objects=[]) # Nueva key
elif map_to_show == 'manual' and manual_map_obj:
    st.markdown("### 🗺️ Mapa Dirección Manual")
    st_folium(manual_map_obj, key="folium_map_manual_v4", width='100%', height=500, returned_objects=[]) # Nueva key
else:
    if not usar_csv_button and not direccion_input and map_to_show is None:
        st.info("Ingresa una dirección o carga el CSV para ver el mapa aquí.")
    elif (usar_csv_button or direccion_input) and map_to_show is None:
         st.warning("No se pudo generar el mapa. Revisa los mensajes de error anteriores.")

print("--- Script Finalizado ---")
