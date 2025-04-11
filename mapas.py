# -*- coding: utf-8 -*- # Añadir encoding por si acaso
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

# --- Constantes de Nombres de Columnas (Definidos SIN espacios extra) ---
# El código ahora limpiará los nombres leídos del CSV para que coincidan con estos.
COLUMNA_DIRECCION_ORIGINAL = u'¿Dónde ocurre este problema? (Por favor indica la dirección lo más exacta posible, Calle, Numero y Comuna)'
COLUMNA_TIPO_ORIGINAL = u'¿Qué tipo de problema estás reportando?' # SIN espacios extra
COLUMNA_DIRECCION_NUEVA = 'Direccion'

# --- Paleta de Colores Base ---
BASE_COLOR_PALETTE = [
    'blue', 'green', 'purple', 'orange', 'darkred', 'cadetblue',
    'darkgreen', 'pink', 'red', 'lightblue', 'darkpurple', 'beige'
]
COLOR_DESCONOCIDO = 'lightgray'
DEFAULT_ASSIGN_COLOR = 'black'

# --- Funciones ---
@st.cache_data
def obtener_calles_conchali():
    # ... (sin cambios) ...
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
    # ... (sin cambios) ...
    """Normaliza el texto: quita acentos, convierte a mayúsculas, elimina no alfanuméricos (excepto espacios) y espacios extra."""
    try:
        texto = unidecode(str(texto)).upper()
        texto = re.sub(r'[^\w\s0-9]', '', texto)
        texto = re.sub(r'\s+', ' ', texto).strip()
        return texto
    except Exception as e:
        return str(texto).upper().strip()

def corregir_direccion(direccion_input, calles_df, umbral=80):
    # ... (sin cambios) ...
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
            if posibles_matches: mejor_match = possibles_matches[0]

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
    # ... (sin cambios) ...
    """Obtiene coordenadas (lat, lon) para una dirección en Conchalí usando Nominatim."""
    if not direccion_corregida_completa: return None
    direccion_query = f"{direccion_corregida_completa}, Conchalí, Región Metropolitana, Chile"
    geolocator = Nominatim(user_agent=f"mapa_conchali_app_v9_{int(time.time())}", timeout=10) # Incrementar versión agente
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

# --- VERSIÓN CORREGIDA: LIMPIA NOMBRES DE COLUMNA ---
def cargar_csv_predeterminado():
    """Carga datos, LIMPIA nombres de columna (elimina espacios extra),
       renombra DIRECCIÓN y procesa TIPO."""
    print(">>> Cargando CSV...")
    url = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSAitwliDu4GoT-HU2zXh4eFUDnky9o3M-B9PHHp7RbLWktH7vuHu1BMT3P5zqfVIHAkTptZ8VaZ-F7/pub?gid=1694829461&single=true&output=csv"
    try:
        # Cargar los datos primero
        data = pd.read_csv(url)
        print("--- Columnas Originales Detectadas (Pre-Limpieza) ---")
        # Imprimir con comillas para visualizar espacios extra
        print([f"'{col}'" for col in data.columns])

        # --- *** PASO CLAVE: Limpiar espacios de TODOS los nombres de columna *** ---
        data.columns = data.columns.str.strip()
        print("--- Columnas Después de Limpiar Espacios (str.strip) ---")
        print([f"'{col}'" for col in data.columns]) # Imprimir nombres limpios

        # --- Ahora, proceder usando los nombres LIMPIOS definidos en las constantes ---

        # Verificar y procesar columna Dirección (usando nombre limpio)
        if COLUMNA_DIRECCION_ORIGINAL in data.columns:
            # Especificar dtype ANTES de renombrar/procesar
            data[COLUMNA_DIRECCION_ORIGINAL] = data[COLUMNA_DIRECCION_ORIGINAL].astype(str)
            # Renombrar usando el nombre limpio
            data.rename(columns={COLUMNA_DIRECCION_ORIGINAL: COLUMNA_DIRECCION_NUEVA}, inplace=True)
            print(f"Columna dirección renombrada a '{COLUMNA_DIRECCION_NUEVA}'")
            # Procesar la columna renombrada
            data[COLUMNA_DIRECCION_NUEVA] = data[COLUMNA_DIRECCION_NUEVA].str.strip()
        else:
            st.error(f"Error crítico: No se encontró la columna de dirección '{COLUMNA_DIRECCION_ORIGINAL}' DESPUÉS de limpiar nombres.")
            # Podríamos añadir una lista de posibles nombres si falla, pero por ahora error.
            st.info(f"Columnas disponibles: {list(data.columns)}")
            return None

        # Verificar y procesar columna Tipo (usando nombre limpio)
        if COLUMNA_TIPO_ORIGINAL in data.columns:
             # Especificar dtype ANTES de procesar
            data[COLUMNA_TIPO_ORIGINAL] = data[COLUMNA_TIPO_ORIGINAL].astype(str)
            print(f"Procesando columna de tipo: '{COLUMNA_TIPO_ORIGINAL}'...")
            data[COLUMNA_TIPO_ORIGINAL] = data[COLUMNA_TIPO_ORIGINAL].fillna("DESCONOCIDO")
            data[COLUMNA_TIPO_ORIGINAL] = data[COLUMNA_TIPO_ORIGINAL].str.strip().str.upper()
            data[COLUMNA_TIPO_ORIGINAL] = data[COLUMNA_TIPO_ORIGINAL].replace(r'^\s*$', 'DESCONOCIDO', regex=True)
        else:
            st.warning(f"Advertencia: No se encontró la columna de tipo '{COLUMNA_TIPO_ORIGINAL}' DESPUÉS de limpiar nombres. Se creará con valor 'DESCONOCIDO'.")
            st.info(f"Columnas disponibles: {list(data.columns)}")
            data[COLUMNA_TIPO_ORIGINAL] = "DESCONOCIDO" # Crear con el nombre limpio


        print("--- Columnas Finales en DataFrame ---")
        print(data.columns)
        print(f"<<< CSV Cargado y Procesado: {len(data)} filas.")
        return data

    except Exception as e:
        st.error(f"Error general al cargar o procesar el CSV: {e}")
        st.error(traceback.format_exc())
        return None
# --- FIN VERSIÓN CORREGIDA ---


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
        # Cargar datos CSV (usando la función actualizada que limpia columnas)
        data_cargada = cargar_csv_predeterminado()

        if data_cargada is not None and not data_cargada.empty:
            st.session_state.data = data_cargada

            # --- Generación Dinámica de Mapa de Colores ---
            # Usar el nombre de columna LIMPIO
            print("--- Generando Mapa de Colores Dinámico... ---")
            dynamic_color_map = {}
            if COLUMNA_TIPO_ORIGINAL in st.session_state.data.columns:
                unique_types = sorted(list(st.session_state.data[COLUMNA_TIPO_ORIGINAL].unique()))
                print(f"Tipos únicos encontrados para mapa de colores (post-limpieza): {unique_types}")
                palette_len = len(BASE_COLOR_PALETTE)
                color_index = 0
                if "DESCONOCIDO" in unique_types:
                    dynamic_color_map["DESCONOCIDO"] = COLOR_DESCONOCIDO
                for utype in unique_types:
                    if utype not in dynamic_color_map:
                        dynamic_color_map[utype] = BASE_COLOR_PALETTE[color_index % palette_len]
                        color_index += 1
                print("--- Mapa de Colores Generado ---")
                print(dynamic_color_map)
            else:
                st.warning(f"Columna '{COLUMNA_TIPO_ORIGINAL}' no encontrada para generar mapa de colores.")
                dynamic_color_map["DESCONOCIDO"] = COLOR_DESCONOCIDO

            # --- Corregir direcciones ---
            # Usar el nombre nuevo/limpio de la columna de dirección ('Direccion')
            print("--- Corrigiendo Direcciones (CSV)... ---")
            if COLUMNA_DIRECCION_NUEVA in st.session_state.data.columns:
                # Usar dropna() sin inplace=True para evitar SettingWithCopyWarning potencial
                data_valid_direccion = st.session_state.data.dropna(subset=[COLUMNA_DIRECCION_NUEVA])
                if not data_valid_direccion.empty:
                    def safe_corregir(x, df_calles):
                        try: return corregir_direccion(x, df_calles)
                        except Exception as e_corr:
                            print(f"Error corrigiendo '{x}': {e_corr}")
                            return x
                    # Aplicar sobre el DF filtrado y asignar de vuelta o a nueva columna
                    st.session_state.data["direccion_corregida"] = data_valid_direccion[COLUMNA_DIRECCION_NUEVA].apply(safe_corregir, args=(calles_df,))
                    # Rellenar NaNs introducidos por la diferencia de índices si es necesario
                    st.session_state.data["direccion_corregida"].fillna(pd.NA, inplace=True) # O usar '' si se prefiere string vacío
                else:
                    st.session_state.data["direccion_corregida"] = pd.NA # Crear columna vacía si no hay direcciones válidas
                    st.warning("No hay direcciones válidas para corregir.")

            else:
                 st.error(f"Falta la columna '{COLUMNA_DIRECCION_NUEVA}' después de cargar/renombrar.")
                 st.stop()

            # --- Mostrar tabla ---
            st.markdown("### Datos cargados y corregidos (CSV):")
            display_cols = []
            # Usar nombres limpios/nuevos
            if COLUMNA_DIRECCION_NUEVA in st.session_state.data.columns: display_cols.append(COLUMNA_DIRECCION_NUEVA)
            if "direccion_corregida" in st.session_state.data.columns: display_cols.append("direccion_corregida")
            if COLUMNA_TIPO_ORIGINAL in st.session_state.data.columns: display_cols.append(COLUMNA_TIPO_ORIGINAL)

            if display_cols and not st.session_state.data.empty:
                 # Mostrar solo filas con dirección corregida no nula si esa columna existe
                 df_display = st.session_state.data
                 #if "direccion_corregida" in df_display.columns:
                 #    df_display = df_display.dropna(subset=["direccion_corregida"])

                 st.dataframe(df_display[display_cols].head(20))
                 if len(df_display) > 20: st.caption(f"... y {len(df_display) - 20} más.")
            else:
                 st.warning("No hay datos o columnas relevantes para mostrar en la tabla.")

            # --- Obtener coordenadas ---
            print("--- Obteniendo Coordenadas (CSV)... ---")
            if "direccion_corregida" in st.session_state.data.columns:
                 # Filtrar NaNs en direccion_corregida ANTES de aplicar geocoding
                 data_to_geocode = st.session_state.data.dropna(subset=["direccion_corregida"])

                 if not data_to_geocode.empty:
                     with st.spinner(f"Obteniendo coordenadas para {len(data_to_geocode)} direcciones..."):
                         def safe_coords(x):
                             try: return obtener_coords(x)
                             except Exception as e_coords:
                                 print(f"Error en geocoding para '{x}': {e_coords}")
                                 return None
                         # Aplicar al subset y luego unir/mapear de vuelta al DF principal
                         coords_series = data_to_geocode["direccion_corregida"].apply(safe_coords)
                         # Usar map para asignar coordenadas al DataFrame original basado en el índice
                         st.session_state.data["coords"] = st.session_state.data.index.map(coords_series)


                     original_rows = len(st.session_state.data.dropna(subset=["direccion_corregida"])) # Contar sobre las que se intentó geocodificar
                     # Filtrar NaNs en la nueva columna 'coords'
                     data_with_coords = st.session_state.data.dropna(subset=["coords"])
                     found_rows = len(data_with_coords)

                     if original_rows > 0:
                         st.success(f"Se encontraron coordenadas para {found_rows} de {original_rows} direcciones procesadas.")
                     else:
                         st.info("No había direcciones válidas para intentar geocodificar.")
                     print(f"Coordenadas encontradas: {found_rows}/{original_rows}")
                     # Actualizar st.session_state.data para que solo contenga filas con coordenadas
                     st.session_state.data = data_with_coords

                 else:
                      st.warning("No quedaron direcciones válidas después de la corrección para geocodificar.")
                      st.session_state.data["coords"] = None # Asegurar columna existe vacía
            else:
                 st.warning("No se pudo proceder a la geocodificación (falta 'direccion_corregida').")
                 st.session_state.data["coords"] = None # Asegurar columna existe vacía

            # --- Crear el mapa ---
            # Ahora st.session_state.data ya está filtrado para tener solo filas con coordenadas
            if "coords" in st.session_state.data.columns and not st.session_state.data.empty:
                print("--- Creando Mapa Folium (CSV)... ---")
                coords_list = st.session_state.data['coords'].tolist()
                map_center = [-33.38, -70.65]
                if coords_list: # Ya sabemos que no está vacío y no tiene NaNs
                    valid_coords = [c for c in coords_list if isinstance(c, tuple) and len(c) == 2]
                    if valid_coords: # Chequeo extra por si algo raro pasó
                        avg_lat = sum(c[0] for c in valid_coords) / len(valid_coords)
                        avg_lon = sum(c[1] for c in valid_coords) / len(valid_coords)
                        map_center = [avg_lat, avg_lon]

                mapa_obj = folium.Map(location=map_center, zoom_start=13)
                coords_agregadas = 0
                tipos_en_mapa = set()

                print("--- Añadiendo Marcadores al Mapa ---")
                for i, row in st.session_state.data.iterrows(): # Iterar sobre el DF ya filtrado
                    try:
                        # Obtener tipo usando el NOMBRE ORIGINAL limpio
                        tipo = str(row.get(COLUMNA_TIPO_ORIGINAL, "DESCONOCIDO")).strip().upper()
                        if tipo == '': tipo = "DESCONOCIDO"

                        marker_color = dynamic_color_map.get(tipo, DEFAULT_ASSIGN_COLOR)
                        tipos_en_mapa.add(tipo)

                        # Debug: Imprimir tipo y color para algunas filas
                        if i < 5 or i % 50 == 0:
                             print(f"Row {i}: Tipo='{tipo}', Color='{marker_color}' (In Map? {tipo in dynamic_color_map})")

                        popup_text = f"<b>Tipo:</b> {tipo.capitalize()}<br>"
                        if "direccion_corregida" in row and pd.notna(row['direccion_corregida']):
                             popup_text += f"<b>Corregida:</b> {row['direccion_corregida']}<br>"
                        if COLUMNA_DIRECCION_NUEVA in row and pd.notna(row[COLUMNA_DIRECCION_NUEVA]):
                             popup_text += f"<b>Original:</b> {row[COLUMNA_DIRECCION_NUEVA]}"

                        tooltip_text = row.get('direccion_corregida', 'Ubicación') + f" ({tipo.capitalize()})"

                        folium.Marker(
                            location=row["coords"], # Ya sabemos que no es NaN
                            popup=folium.Popup(popup_text, max_width=300),
                            tooltip=tooltip_text,
                            icon=folium.Icon(color=marker_color, icon='info-sign')
                        ).add_to(mapa_obj)
                        coords_agregadas += 1
                    except Exception as marker_err:
                        st.warning(f"No se pudo añadir marcador para fila con índice {i}: {marker_err}")


                if coords_agregadas > 0:
                    # Leyenda
                    legend_html = """
                        <div style="position: fixed; bottom: 50px; left: 10px; width: 180px; height: auto; max-height: 250px; border:2px solid grey; z-index:9999; font-size:12px; background-color:rgba(255, 255, 255, 0.9); overflow-y: auto; padding: 10px; border-radius: 5px;">
                        <b style="font-size: 14px;">Leyenda de Tipos</b><br> """
                    tipos_relevantes_leyenda = sorted([t for t in dynamic_color_map.keys() if t in tipos_en_mapa])
                    print(f"--- Tipos para la leyenda: {tipos_relevantes_leyenda} ---")
                    for tipo_leg in tipos_relevantes_leyenda:
                         color_leg = dynamic_color_map.get(tipo_leg, DEFAULT_ASSIGN_COLOR)
                         legend_html += f'<i style="background:{color_leg}; border-radius:50%; width: 12px; height: 12px; display: inline-block; margin-right: 6px; border: 1px solid #CCC;"></i>{tipo_leg.capitalize()}<br>'
                    legend_html += "</div>"
                    mapa_obj.get_root().html.add_child(folium.Element(legend_html))

                    st.session_state.mapa_csv = mapa_obj
                    st.session_state.mostrar_mapa = 'csv'
                    print("--- Mapa CSV Generado y Guardado en Sesión ---")
                else:
                    st.warning("No se agregaron puntos al mapa del CSV (post-filtrado de coordenadas).")
                    st.session_state.mapa_csv = None
                    if st.session_state.mostrar_mapa == 'csv': st.session_state.mostrar_mapa = None
            else:
                 st.warning("No se pudo generar el mapa (sin coordenadas válidas después del filtrado).")
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
     # ... (sin cambios en la lógica manual) ...
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
    st_folium(csv_map_obj, key="folium_map_csv_v5", width='100%', height=600, returned_objects=[]) # Nueva key
elif map_to_show == 'manual' and manual_map_obj:
    st.markdown("### 🗺️ Mapa Dirección Manual")
    st_folium(manual_map_obj, key="folium_map_manual_v5", width='100%', height=500, returned_objects=[]) # Nueva key
else:
    # Mensaje informativo si no hay mapa que mostrar
    if not usar_csv_button and not direccion_input:
        st.info("Ingresa una dirección o carga el CSV para ver el mapa aquí.")
    elif (usar_csv_button or direccion_input) and map_to_show is None:
         # Si se intentó pero falló, el error ya se mostró antes
         st.warning("No se pudo generar el mapa. Revisa los mensajes anteriores.")

print("--- Script Finalizado ---")
