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

# --- Configuración, Funciones (sin cambios, omitidas por brevedad) ---
st.set_page_config(page_title="Mapa de Direcciones Corregidas", layout="wide")
st.title("🗺️ Mapa de Direcciones Corregidas en Conchalí")

@st.cache_data
def obtener_calles_conchali():
    # ... (código original de la función)
    url = "https://codigo-postal.co/chile/santiago/calles-de-conchali/"
    response = requests.get(url)
    soup = BeautifulSoup(response.text, "html.parser")
    ul_cities = soup.find("ul", class_="cities")
    li_items = ul_cities.find_all("li")
    calles = [li.find("a").text.strip() for li in li_items]
    df_calles_conchali = pd.DataFrame(calles, columns=["Calle"])
    df_calles_conchali["normalizado"] = df_calles_conchali["Calle"].apply(normalizar)
    return df_calles_conchali

def normalizar(texto):
    # ... (código original de la función)
    texto = unidecode(str(texto)).upper()
    texto = re.sub(r'[^\w\s0-9]', '', texto)
    texto = re.sub(r'\s+', ' ', texto).strip()
    return texto

def corregir_direccion(direccion_input, calles_df, umbral=80):
    # ... (código original de la función)
    match = re.match(r"(.*?)(\s*\d+)$", direccion_input.strip())
    if match:
        direccion_texto = match.group(1).strip()
        numero_direccion = match.group(2).strip()
    else:
        direccion_texto = direccion_input.strip()
        numero_direccion = ""
    entrada_norm = normalizar(direccion_texto)
    mejor_match = process.extractOne(entrada_norm, calles_df["normalizado"], scorer=fuzz.token_set_ratio)
    if mejor_match and mejor_match[1] >= umbral:
        # Asegúrate de que values[0] exista, aunque el índice debería ser único
        try:
            idx = calles_df["normalizado"] == mejor_match[0]
            direccion_corregida = calles_df.loc[idx, "Calle"].values[0]
        except IndexError:
             direccion_corregida = direccion_texto # Fallback si hay problema con el índice
    else:
        direccion_corregida = direccion_texto
    return direccion_corregida + (" " + numero_direccion if numero_direccion else "")

@st.cache_data # Cachear también geocoding puede ser útil, pero con cuidado por si la dirección cambia
def obtener_coords(direccion):
    # ... (código original de la función, con el user_agent cambiado)
    geolocator = Nominatim(user_agent="streamlit_app_map_fix_v2", timeout=10)
    try:
        location = geolocator.geocode(f"{direccion}, Conchalí, Chile", addressdetails=True) # Pedir detalles puede ayudar a filtrar
        # Opcional: Verificar si realmente está en Conchalí
        if location and location.raw.get('address', {}).get('suburb') == 'Conchalí':
             return location.latitude, location.longitude
        elif location:
             st.warning(f"Geocodificación encontró '{location.address}' pero no parece estar en Conchalí. Descartando.")
             return None
        else:
             # st.warning(f"No se encontró ubicación para: {direccion}") # Puede ser muy verboso
             pass
    except GeocoderUnavailable:
        st.warning("Servicio de geocodificación no disponible temporalmente. Intenta de nuevo más tarde.")
        return None
    except Exception as e:
        st.error(f"Error inesperado durante la geocodificación para '{direccion}': {e}")
        return None
    return None

def cargar_csv_predeterminado():
    # ... (código original de la función)
    url = "https://docs.google.com/spreadsheets/d/e/2PACX-1vR1sj1BfL4P6_EO0EGhN2e2qeQA78Rmvl0s7nGhrlGnEBo7ZCa6OrJL1B0gF_JoaiMEpqmtap7WfzxI/pub?gid=0&single=true&output=csv"
    try:
        data = pd.read_csv(url)
        return data
    except Exception as e:
        st.error(f"Error al cargar el CSV desde la URL: {e}")
        return None

# --- Inicialización del estado de sesión (sin cambios) ---
if "data" not in st.session_state:
    st.session_state.data = None
if "mapa_csv" not in st.session_state:
    st.session_state.mapa_csv = None
if "mapa_manual" not in st.session_state:
    st.session_state.mapa_manual = None
if "mostrar_mapa" not in st.session_state:
    st.session_state.mostrar_mapa = None

# --- Widgets de entrada ---
# Añadir una key al text_input ayuda a Streamlit a manejar su estado
direccion_input = st.text_input("Ingresa una dirección (ej: Tres Ote. 5317):", key="direccion_manual_key")
usar_csv_button = st.button("Usar csv predeterminado")

# --- Lógica Principal (CON PRIORIDAD DE BOTÓN) ---

if usar_csv_button:
    # Si se presiona el botón, esta es la única lógica de procesamiento que corre
    st.session_state.mapa_manual = None # Limpiar mapa manual anterior explícitamente
    st.session_state.mostrar_mapa = None # Resetear qué mostrar hasta que termine el CSV
    try:
        # Cargar datos CSV
        data_cargada = cargar_csv_predeterminado()
        if data_cargada is not None:
            st.session_state.data = data_cargada
            if "Direccion" not in st.session_state.data.columns:
                st.error("❌ El archivo CSV no contiene una columna llamada 'Direccion'.")
                st.session_state.data = None
                st.session_state.mapa_csv = None
            else:
                # Procesar las direcciones
                calles_df = obtener_calles_conchali()
                st.session_state.data["direccion_corregida"] = st.session_state.data["Direccion"].astype(str).apply(lambda x: corregir_direccion(x, calles_df))
                with st.spinner("Obteniendo coordenadas del CSV... Esto puede tardar."):
                    st.session_state.data["coords"] = st.session_state.data["direccion_corregida"].apply(obtener_coords)
                st.session_state.data = st.session_state.data.dropna(subset=["coords"])

                if not st.session_state.data.empty:
                    st.markdown("### ✅ Direcciones del CSV encontradas y procesadas:")
                    # Mostrar solo las primeras N para no saturar si es muy grande
                    st.dataframe(st.session_state.data[["Direccion", "direccion_corregida"]].head(20))
                    if len(st.session_state.data) > 20:
                         st.caption(f"... y {len(st.session_state.data) - 20} más.")

                    # Crear el mapa y guardarlo
                    mapa_obj = folium.Map(location=[-33.38, -70.65], zoom_start=13)
                    for i, row in st.session_state.data.iterrows():
                        # Usar try-except por si alguna coordenada es inválida a pesar del dropna
                        try:
                            folium.Marker(location=row["coords"], popup=f"{row['direccion_corregida']} (Original: {row['Direccion']})").add_to(mapa_obj)
                        except Exception as marker_err:
                             st.warning(f"No se pudo añadir marcador para {row['direccion_corregida']}: {marker_err}")

                    st.session_state.mapa_csv = mapa_obj
                    st.session_state.mostrar_mapa = 'csv' # Indicar que se debe mostrar este mapa
                    st.success("Mapa del CSV cargado.")

                else:
                    st.warning("⚠️ No se encontraron coordenadas válidas para ninguna dirección en el CSV.")
                    st.session_state.mapa_csv = None
                    # No establecemos mostrar_mapa aquí para que no oculte un posible mapa manual previo si el CSV falla

        else:
             st.error("No se pudieron cargar los datos del CSV.")
             st.session_state.mapa_csv = None


    except Exception as e:
        st.error(f"⚠️ Error general al procesar el CSV: {str(e)}")
        st.session_state.data = None
        st.session_state.mapa_csv = None
        # No establecemos mostrar_mapa aquí

# Usar 'elif' para que esto solo se ejecute si el botón NO fue presionado
elif direccion_input:
    # Si no se presionó el botón Y hay texto en el input manual
    st.session_state.mapa_csv = None # Limpiar mapa CSV anterior explícitamente
    calles_df = obtener_calles_conchali()
    direccion_corregida = corregir_direccion(direccion_input, calles_df)
    coords = obtener_coords(direccion_corregida)

    st.markdown("---") # Separador visual
    st.markdown("### ✅ Resultado Dirección Manual:")
    st.write(f"Dirección original: {direccion_input}")
    st.write(f"Dirección corregida: {direccion_corregida}")

    if coords:
        st.write(f"Ubicación aproximada: {coords[0]}, {coords[1]}")
        # Crear un mapa para la dirección manual y guardarlo
        mapa_manual_obj = folium.Map(location=coords, zoom_start=15)
        folium.Marker(location=coords, popup=direccion_corregida).add_to(mapa_manual_obj)
        st.session_state.mapa_manual = mapa_manual_obj
        st.session_state.mostrar_mapa = 'manual' # Indicar que se muestre este mapa
    else:
        st.write("No se pudo obtener la ubicación para la dirección corregida.")
        st.session_state.mapa_manual = None # Limpiar si no hay coords
        # Si el mapa manual era el que se estaba mostrando, dejar de mostrarlo
        if st.session_state.mostrar_mapa == 'manual':
             st.session_state.mostrar_mapa = None

# --- Mostrar el mapa correspondiente (FUERA de los bloques 'if'/'elif') ---
st.markdown("---") # Separador visual

if st.session_state.get("mostrar_mapa") == 'csv' and st.session_state.get("mapa_csv"):
    st.markdown("### 🗺️ Mapa con direcciones del CSV")
    # Usar la key ayuda a Streamlit a diferenciar componentes si se recrean
    st_folium(st.session_state.mapa_csv, key="folium_map_csv", width=700, height=500, returned_objects=[])
elif st.session_state.get("mostrar_mapa") == 'manual' and st.session_state.get("mapa_manual"):
    st.markdown("### 🗺️ Mapa con la dirección manual")
    st_folium(st.session_state.mapa_manual, key="folium_map_manual", width=700, height=500, returned_objects=[])
# elif st.session_state.get("mostrar_mapa") is None: # Opcional: Mensaje si no hay nada que mostrar
#     st.info("Ingresa una dirección o carga el CSV para ver el mapa.")
