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

# --- Funciones ---
@st.cache_data
def obtener_calles_conchali():
    """Obtiene la lista de calles oficiales de Conchalí desde una fuente web."""
    print(">>> Ejecutando obtener_calles_conchali (o usando caché)...") # Log
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
        texto = re.sub(r'[^\w\s0-9]', '', texto) # Permite letras, números, espacios y guión bajo
        texto = re.sub(r'\s+', ' ', texto).strip()
        return texto
    except Exception as e:
        # print(f"Error normalizando texto '{texto}': {e}") # Opcional
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

    direccion_final = direccion_corregida_texto + (" " + numero_direccion if numero_direccion else "")
    return direccion_final.strip()


@st.cache_data(ttl=3600)
def obtener_coords(direccion_corregida_completa):
    """Obtiene coordenadas (lat, lon) para una dirección en Conchalí usando Nominatim."""
    if not direccion_corregida_completa: return None
    direccion_query = f"{direccion_corregida_completa}, Conchalí, Región Metropolitana, Chile"
    # print(f"DEBUG GEO: Buscando: {direccion_query}") # Log opcional
    # Es buena práctica variar el user_agent para no ser bloqueado. Usar un identificador único si es posible.
    geolocator = Nominatim(user_agent=f"mapa_conchali_app_v6_{int(time.time())}", timeout=10)
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

# --- VERSIÓN ACTUALIZADA ---
def cargar_csv_predeterminado():
    """Carga los datos desde la URL, renombra columnas clave y prepara la columna 'Que es'."""
    print(">>> Cargando CSV...") # Log
    url = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSAitwliDu4GoT-HU2zXh4eFUDnky9o3M-B9PHHp7RbLWktH7vuHu1BMT3P5zqfVIHAkTptZ8VaZ-F7/pub?gid=1694829461&single=true&output=csv"
    try:
        # Nombres originales de las columnas que nos interesan - ¡VERIFICAR QUE SEAN EXACTOS!
        original_direccion_col = '¿Dónde ocurre este problema? (Por favor indica la dirección lo más exacta posible, Calle, Numero y Comuna)'
        original_tipo_col = '¿Qué tipo de problema estás reportando?'

        # Especificar dtype usando los nombres originales
        data = pd.read_csv(url, dtype={
            original_direccion_col: str,
            original_tipo_col: str
        })
        print("--- Columnas Originales Detectadas ---")
        print(data.columns) # DEBUG: Para ver las columnas tal como las lee pandas

        # Verificar si las columnas originales existen antes de renombrar
        if original_direccion_col not in data.columns:
            st.error(f"Error crítico: No se encontró la columna de dirección esperada: '{original_direccion_col}'")
            return None

        # Procesar columna de tipo: Renombrar si existe, crear si no.
        if original_tipo_col not in data.columns:
            st.warning(f"Advertencia: No se encontró la columna de tipo esperada: '{original_tipo_col}'. Se usará 'DESCONOCIDO'.")
            # Si falta la columna de tipo, la creamos directamente con el nombre nuevo 'Que es'
            data['Que es'] = 'DESCONOCIDO'
            # Renombramos solo la columna de dirección si existe
            if original_direccion_col in data.columns: # Doble chequeo por si acaso
                 data.rename(columns={original_direccion_col: 'Direccion'}, inplace=True)

        else:
            # Si ambas columnas originales existen, procedemos a renombrar ambas
             data.rename(columns={
                original_direccion_col: 'Direccion',
                original_tipo_col: 'Que es'
            }, inplace=True)

        print("--- Columnas Después de Renombrar/Asegurar ---")
        print(data.columns) # DEBUG: Para ver las columnas después del proceso

        # --- Ahora, trabajar SÓLO con los nombres nuevos 'Direccion' y 'Que es' ---

        # Asegurar que la columna 'Direccion' existe (podría haber fallado el rename si el original no estaba)
        if "Direccion" not in data.columns:
             st.error("Error después de renombrar: Falta la columna 'Direccion'.")
             # Podríamos intentar usar la original si aún existe, pero es mejor parar si el rename falló.
             return None
        # Aplicar strip() sólo si la columna no es nula para evitar errores
        data["Direccion"] = data["Direccion"].str.strip()

        # Asegurar que la columna 'Que es' existe y procesarla
        if "Que es" in data.columns:
            data["Que es"] = data["Que es"].fillna("DESCONOCIDO").astype(str).str.strip().str.upper()
            data["Que es"] = data["Que es"].replace(r'^\s*$', 'DESCONOCIDO', regex=True)
        else:
            # Este caso no debería ocurrir si la lógica anterior funcionó, pero por si acaso:
            st.warning("Columna 'Que es' inesperadamente ausente después del procesamiento inicial. Se asignará 'DESCONOCIDO'.")
            data["Que es"] = "DESCONOCIDO"

        print(f"<<< CSV Cargado y Procesado: {len(data)} filas.")
        return data

    except Exception as e:
        st.error(f"Error general al cargar o procesar el CSV: {e}")
        st.error(traceback.format_exc()) # Mostrar stack trace para más detalles
        return None
# --- FIN VERSIÓN ACTUALIZADA ---


# --- Inicialización del Estado de Sesión ---
if "data" not in st.session_state: st.session_state.data = None
if "mapa_csv" not in st.session_state: st.session_state.mapa_csv = None
if "mapa_manual" not in st.session_state: st.session_state.mapa_manual = None
if "mostrar_mapa" not in st.session_state: st.session_state.mostrar_mapa = None

# --- Carga de Datos Estáticos (Calles Oficiales) ---
# calles_df = obtener_calles_conchali() # <-- Se carga bajo demanda ahora

# --- Widgets de Entrada ---
direccion_input = st.text_input("Ingresa una dirección (ej: Tres Ote. 5317):", key="direccion_manual_key")
usar_csv_button = st.button("Usar csv predeterminado")
print("--- Widgets Definidos ---") # Log

# --- Lógica Principal ---

if usar_csv_button:
    print("--- Botón CSV Presionado ---") # Log
    st.session_state.mapa_manual = None
    st.session_state.mostrar_mapa = None
    # Limpiar datos anteriores para evitar confusión si falla la carga
    st.session_state.data = None
    st.session_state.mapa_csv = None
    st.info("Procesando CSV predeterminado...")

    # --- Carga Perezosa de Calles ---
    print("--- Cargando Calles (CSV)... ---")
    calles_df = obtener_calles_conchali()
    if calles_df is None or calles_df.empty: # Chequeo más robusto
        st.error("Fallo al cargar calles oficiales. No se puede continuar con el CSV.")
        st.stop() # Detener ejecución si las calles son necesarias y fallan
    # --- Fin Carga Perezosa ---

    try:
        # 1. Cargar datos CSV (usando la función actualizada)
        data_cargada = cargar_csv_predeterminado() # Ya tiene logs internos y manejo de nombres

        if data_cargada is not None and not data_cargada.empty:
            st.session_state.data = data_cargada

            # --- Generación Dinámica de Mapa de Colores ---
            print("--- Generando Mapa de Colores Dinámico... ---") # Log
            dynamic_color_map = {}
            # Trabajar siempre con 'Que es' porque la función de carga lo asegura
            if "Que es" in st.session_state.data.columns:
                unique_types = sorted(list(st.session_state.data["Que es"].unique()))
                palette_len = len(BASE_COLOR_PALETTE)
                color_index = 0
                if "DESCONOCIDO" in unique_types:
                    dynamic_color_map["DESCONOCIDO"] = COLOR_DESCONOCIDO
                for utype in unique_types:
                    if utype not in dynamic_color_map: # Asegura que DESCONOCIDO no se sobrescriba si está al inicio
                        dynamic_color_map[utype] = BASE_COLOR_PALETTE[color_index % palette_len]
                        color_index += 1
                print(f"Mapa de colores generado: {dynamic_color_map}") # Log consola
            else:
                # Este caso es menos probable ahora, pero mantenemos la advertencia
                st.warning("No se pudo generar mapa de colores (columna 'Que es' no encontrada después del procesamiento).")
                dynamic_color_map["DESCONOCIDO"] = COLOR_DESCONOCIDO # Asegurar que existe al menos este

            # --- Fin Generación Dinámica ---

            # 2. Corregir direcciones
            print("--- Corrigiendo Direcciones (CSV)... ---") # Log
            # Trabajar siempre con 'Direccion' porque la función de carga lo asegura
            if "Direccion" in st.session_state.data.columns:
                st.session_state.data = st.session_state.data.dropna(subset=["Direccion"])
                def safe_corregir(x, df_calles):
                    try: return corregir_direccion(x, df_calles)
                    except Exception as e_corr:
                        print(f"Error corrigiendo '{x}': {e_corr}")
                        return x # Devolver original si falla
                st.session_state.data["direccion_corregida"] = st.session_state.data["Direccion"].apply(safe_corregir, args=(calles_df,))
            else:
                 st.error("Falta la columna 'Direccion' después de cargar/renombrar el CSV.")
                 st.stop()


            # (Mostrar tabla)
            st.markdown("### Datos cargados y corregidos (CSV):")
            display_cols = []
            # Usar los nombres nuevos y la columna generada
            if "Direccion" in st.session_state.data.columns: display_cols.append("Direccion")
            if "direccion_corregida" in st.session_state.data.columns: display_cols.append("direccion_corregida")
            if "Que es" in st.session_state.data.columns: display_cols.append("Que es")

            if display_cols and not st.session_state.data.empty: # Mostrar solo si hay columnas y datos
                 st.dataframe(st.session_state.data[display_cols].head(20))
                 if len(st.session_state.data) > 20: st.caption(f"... y {len(st.session_state.data) - 20} más.")
            else:
                 st.warning("No hay datos o columnas relevantes ('Direccion', 'direccion_corregida', 'Que es') para mostrar en la tabla.")


            # 3. Obtener coordenadas
            print("--- Obteniendo Coordenadas (CSV)... ---") # Log
            if "direccion_corregida" in st.session_state.data.columns:
                with st.spinner("Obteniendo coordenadas del CSV..."):
                    # Asegurarse que la columna existe antes de aplicar dropna
                    if "direccion_corregida" in st.session_state.data.columns:
                         st.session_state.data = st.session_state.data.dropna(subset=["direccion_corregida"])

                    if not st.session_state.data.empty: # Solo proceder si hay datos después de limpiar nulos
                        def safe_coords(x):
                            try: return obtener_coords(x)
                            except Exception as e_coords:
                                print(f"Error en geocoding para '{x}': {e_coords}")
                                return None
                        st.session_state.data["coords"] = st.session_state.data["direccion_corregida"].apply(safe_coords)

                        # 4. Filtrar filas sin coordenadas VÁLIDAS
                        original_rows = len(st.session_state.data)
                        # dropna en 'coords' es seguro porque la creamos arriba
                        st.session_state.data = st.session_state.data.dropna(subset=["coords"])
                        found_rows = len(st.session_state.data)
                        st.success(f"Se encontraron coordenadas para {found_rows} de {original_rows} direcciones procesadas.")
                        print(f"Coordenadas encontradas: {found_rows}/{original_rows}") # Log
                    else:
                         st.warning("No quedaron direcciones válidas después de limpiar nulos en 'direccion_corregida'.")
                         st.session_state.data["coords"] = None # Asegurar que la columna existe aunque vacía

            else:
                st.warning("No se pudo proceder a la geocodificación porque falta la columna 'direccion_corregida'.")
                st.session_state.data["coords"] = None # Asegurar que la columna existe aunque vacía


            # 5. Crear el mapa (solo si hay coordenadas válidas)
            if "coords" in st.session_state.data.columns and not st.session_state.data.empty and not st.session_state.data["coords"].isnull().all():
                print("--- Creando Mapa Folium (CSV)... ---") # Log
                coords_list = st.session_state.data['coords'].tolist() # Lista de tuplas (lat, lon)
                if coords_list:
                     # Calcular centroide de forma segura
                    valid_coords = [c for c in coords_list if isinstance(c, tuple) and len(c) == 2]
                    if valid_coords:
                        avg_lat = sum(c[0] for c in valid_coords) / len(valid_coords)
                        avg_lon = sum(c[1] for c in valid_coords) / len(valid_coords)
                        map_center = [avg_lat, avg_lon]
                    else:
                         map_center = [-33.38, -70.65] # Centro fijo si no hay coords válidas
                else:
                    map_center = [-33.38, -70.65] # Centro fijo de Conchalí

                mapa_obj = folium.Map(location=map_center, zoom_start=13)
                coords_agregadas = 0
                tipos_en_mapa = set()

                # Iterar sobre filas que SÍ tienen coordenadas válidas
                for i, row in st.session_state.data.iterrows():
                    try:
                        # No necesitamos chequear pd.notna(row["coords"]) porque ya filtramos con dropna
                        # Usar siempre 'Que es' y 'Direccion' / 'direccion_corregida'
                        tipo = str(row.get("Que es", "DESCONOCIDO")).upper() # Usar .get() por seguridad
                        marker_color = dynamic_color_map.get(tipo, DEFAULT_ASSIGN_COLOR)
                        tipos_en_mapa.add(tipo)

                        popup_text = f"<b>Tipo:</b> {tipo.capitalize()}<br>"
                        if "direccion_corregida" in row and pd.notna(row['direccion_corregida']):
                             popup_text += f"<b>Corregida:</b> {row['direccion_corregida']}<br>"
                        if "Direccion" in row and pd.notna(row['Direccion']):
                             popup_text += f"<b>Original:</b> {row['Direccion']}"

                        tooltip_text = row.get('direccion_corregida', 'Ubicación') + f" ({tipo.capitalize()})"

                        folium.Marker(
                            location=row["coords"],
                            popup=folium.Popup(popup_text, max_width=300),
                            tooltip=tooltip_text,
                            icon=folium.Icon(color=marker_color, icon='info-sign')
                        ).add_to(mapa_obj)
                        coords_agregadas += 1
                    except Exception as marker_err:
                        st.warning(f"No se pudo añadir marcador para fila {i} ({row.get('direccion_corregida','N/A')}): {marker_err}")

                if coords_agregadas > 0:
                    # (Añadir Leyenda)
                    legend_html = """
                        <div style="position: fixed; bottom: 50px; left: 10px; width: 180px; height: auto; max-height: 250px; border:2px solid grey; z-index:9999; font-size:12px; background-color:rgba(255, 255, 255, 0.9); overflow-y: auto; padding: 10px; border-radius: 5px;">
                        <b style="font-size: 14px;">Leyenda de Tipos</b><br> """
                    # Usar el dynamic_color_map que generamos, priorizando los tipos que sí están en el mapa
                    tipos_relevantes = sorted([t for t in dynamic_color_map.keys() if t in tipos_en_mapa])
                    for tipo_leg in tipos_relevantes:
                         color_leg = dynamic_color_map.get(tipo_leg, DEFAULT_ASSIGN_COLOR)
                         legend_html += f'<i style="background:{color_leg}; border-radius:50%; width: 12px; height: 12px; display: inline-block; margin-right: 6px; border: 1px solid #CCC;"></i>{tipo_leg.capitalize()}<br>'

                    legend_html += "</div>"
                    mapa_obj.get_root().html.add_child(folium.Element(legend_html))

                    st.session_state.mapa_csv = mapa_obj
                    st.session_state.mostrar_mapa = 'csv'
                    # El mensaje de éxito ya se mostró antes al encontrar coordenadas
                    # st.success(f"Mapa del CSV generado con {coords_agregadas} puntos.")
                    print("--- Mapa CSV Generado y Guardado en Sesión ---") # Log
                else:
                    st.warning("No se agregaron puntos al mapa del CSV (aunque se encontraron algunas coordenadas).")
                    st.session_state.mapa_csv = None # Asegurar que no se muestre un mapa vacío
                    if st.session_state.mostrar_mapa == 'csv': st.session_state.mostrar_mapa = None

            # else: Casos cubiertos por mensajes anteriores (no se encontraron coords, faltaba columna, etc.)
            #    st.warning("No se pudo generar el mapa porque no hay coordenadas válidas.")
            #    st.session_state.mapa_csv = None # Asegurar estado limpio

        else:
            # Mensaje si cargar_csv_predeterminado devolvió None o vacío
            st.error("No se cargaron datos válidos del CSV.")
            st.session_state.data = None # Asegurar estado limpio
            st.session_state.mapa_csv = None

    except Exception as e:
        st.error(f"Error inesperado durante el procesamiento del CSV: {str(e)}")
        st.error(traceback.format_exc()) # Mostrar el stack trace completo para debug
        st.session_state.data = None # Asegurar estado limpio
        st.session_state.mapa_csv = None
    print("--- Fin Procesamiento Botón CSV ---") # Log

# --- Lógica Dirección Manual ---
elif direccion_input: # Usar elif para evitar que se ejecute si se presionó el botón CSV
    print("--- Input Manual Detectado ---") # Log
    st.session_state.mapa_csv = None # Limpiar mapa CSV si se ingresa dirección manual
    st.session_state.data = None # Limpiar datos CSV
    st.session_state.mostrar_mapa = None # Resetear mapa a mostrar
    st.info(f"Procesando dirección manual: {direccion_input}")

    # --- Carga Perezosa de Calles ---
    print("--- Cargando Calles (Manual)... ---")
    calles_df = obtener_calles_conchali()
    if calles_df is None or calles_df.empty: # Chequeo más robusto
        st.error("Fallo al cargar calles oficiales. La corrección puede no funcionar correctamente.")
        # No detenemos, pero advertimos al usuario
    # --- Fin Carga Perezosa ---

    # (Resto de lógica manual)
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
            st.session_state.mostrar_mapa = None # Asegurar que no intente mostrarlo
    else:
        st.warning("No se pudo obtener ubicación para la dirección corregida.")
        st.session_state.mapa_manual = None
        # No es necesario resetear st.session_state.mostrar_mapa aquí, ya se reseteó al inicio del bloque elif
    print("--- Fin Procesamiento Manual ---") # Log


# --- Mostrar el mapa correspondiente ---
st.markdown("---")
map_to_show = st.session_state.get("mostrar_mapa")
csv_map_obj = st.session_state.get("mapa_csv")
manual_map_obj = st.session_state.get("mapa_manual")

print(f"--- Decidiendo qué Mapa Mostrar: {map_to_show} ---") # Log
# print(f"    mapa_csv existe: {csv_map_obj is not None}")
# print(f"    mapa_manual existe: {manual_map_obj is not None}")


if map_to_show == 'csv' and csv_map_obj:
    st.markdown("### 🗺️ Mapa CSV (Colores Dinámicos)")
    st_folium(csv_map_obj, key="folium_map_csv_dynamic_color_v2", width='100%', height=600, returned_objects=[]) # Cambiar key por si acaso
elif map_to_show == 'manual' and manual_map_obj:
    st.markdown("### 🗺️ Mapa Dirección Manual")
    st_folium(manual_map_obj, key="folium_map_manual_v2", width='100%', height=500, returned_objects=[]) # Cambiar key por si acaso
else:
    # Mostrar mensaje solo si NO se ha presionado el botón Y NO se ha ingresado texto Y no hay mapa listo para mostrar
    # O si se intentó procesar pero falló (map_to_show es None pero se intentó algo)
    if not usar_csv_button and not direccion_input and map_to_show is None:
        st.info("Ingresa una dirección o carga el CSV para ver el mapa aquí.")
    elif (usar_csv_button or direccion_input) and map_to_show is None:
         # Si se intentó procesar pero map_to_show es None, es porque falló algo crítico antes de generar el mapa.
         st.warning("No se pudo generar el mapa. Revisa los mensajes de error anteriores en la aplicación o la consola.")

print("--- Script Finalizado ---") # Log
