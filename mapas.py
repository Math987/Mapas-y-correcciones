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

# --- Configuración e Imports (igual que antes) ---
st.set_page_config(page_title="Mapa de Direcciones Corregidas", layout="wide")
st.title("🗺️ Mapa de Direcciones Corregidas en Conchalí")

# --- Funciones (obtener_calles_conchali, normalizar, corregir_direccion, obtener_coords, cargar_csv_predeterminado) ---
# (Sin cambios en las funciones, las omito por brevedad pero deben estar aquí)
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
        idx = calles_df["normalizado"] == mejor_match[0]
        direccion_corregida = calles_df.loc[idx, "Calle"].values[0]
    else:
        direccion_corregida = direccion_texto
    return direccion_corregida + (" " + numero_direccion if numero_direccion else "")

def obtener_coords(direccion):
    # ... (código original de la función)
    geolocator = Nominatim(user_agent="streamlit_app_map_fix", timeout=10) # Cambié un poco el user_agent
    try:
        location = geolocator.geocode(f"{direccion}, Conchalí, Chile")
        if location:
            return location.latitude, location.longitude
    except GeocoderUnavailable:
        st.warning("Servicio de geocodificación no disponible temporalmente. Intenta de nuevo más tarde.")
        return None
    except Exception as e:
        st.error(f"Error inesperado durante la geocodificación: {e}")
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

# --- Inicialización del estado de sesión ---
if "data" not in st.session_state:
    st.session_state.data = None
if "mapa_csv" not in st.session_state: # Usamos una clave específica para el mapa del CSV
    st.session_state.mapa_csv = None
if "mapa_manual" not in st.session_state: # Y otra para el mapa manual
    st.session_state.mapa_manual = None
if "mostrar_mapa" not in st.session_state: # Controla qué mapa mostrar
    st.session_state.mostrar_mapa = None # Puede ser 'csv' o 'manual'

# --- Widgets de entrada ---
direccion_input = st.text_input("Ingresa una dirección (ej: Tres Ote. 5317):")
usar_csv_button = st.button("Usar csv predeterminado")

# --- Lógica del botón CSV ---
if usar_csv_button:
    try:
        # Cargar datos CSV
        data_cargada = cargar_csv_predeterminado()
        if data_cargada is not None:
            st.session_state.data = data_cargada # Guardar en session state
            if "Direccion" not in st.session_state.data.columns:
                st.error("❌ El archivo CSV no contiene una columna llamada 'Direccion'.")
                st.session_state.data = None # Limpiar si hay error
                st.session_state.mapa_csv = None
            else:
                # Procesar las direcciones
                calles_df = obtener_calles_conchali()
                st.session_state.data["direccion_corregida"] = st.session_state.data["Direccion"].astype(str).apply(lambda x: corregir_direccion(x, calles_df))
                with st.spinner("Obteniendo coordenadas... Esto puede tardar un momento."): # Añadir spinner
                    st.session_state.data["coords"] = st.session_state.data["direccion_corregida"].apply(obtener_coords)
                st.session_state.data = st.session_state.data.dropna(subset=["coords"])

                if not st.session_state.data.empty:
                    st.markdown("### ✅ Direcciones encontradas y procesadas:")
                    st.dataframe(st.session_state.data[["Direccion", "direccion_corregida"]])

                    # Crear el mapa y guardarlo en el estado de sesión
                    mapa_obj = folium.Map(location=[-33.38, -70.65], zoom_start=13)
                    for i, row in st.session_state.data.iterrows():
                        folium.Marker(location=row["coords"], popup=row["direccion_corregida"]).add_to(mapa_obj)
                    st.session_state.mapa_csv = mapa_obj # Guardar el objeto mapa
                    st.session_state.mostrar_mapa = 'csv' # Indicar que se debe mostrar este mapa
                    st.session_state.mapa_manual = None # Ocultar el mapa manual si estaba visible
                else:
                    st.warning("⚠️ No se encontraron coordenadas válidas para ninguna dirección en el CSV.")
                    st.session_state.mapa_csv = None
                    st.session_state.mostrar_mapa = None

    except Exception as e:
        st.error(f"⚠️ Error al procesar el CSV: {str(e)}")
        st.session_state.data = None
        st.session_state.mapa_csv = None
        st.session_state.mostrar_mapa = None

# --- Lógica de la dirección manual ---
if direccion_input: # Procesar solo si hay texto en la entrada
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
        st.session_state.mapa_manual = mapa_manual_obj # Guardar en su propia variable de sesión
        st.session_state.mostrar_mapa = 'manual' # Indicar que se muestre este mapa
        st.session_state.mapa_csv = None # Ocultar el mapa CSV si estaba visible
    else:
        st.write("No se pudo obtener la ubicación para la dirección corregida.")
        st.session_state.mapa_manual = None # Limpiar si no hay coords
        if st.session_state.mostrar_mapa == 'manual': # Si el mapa manual era el último en mostrarse
             st.session_state.mostrar_mapa = None # Ya no mostrarlo

# --- Mostrar el mapa correspondiente (FUERA de los bloques 'if') ---
st.markdown("---") # Separador visual
if st.session_state.mostrar_mapa == 'csv' and st.session_state.mapa_csv:
    st.markdown("### 🗺️ Mapa con direcciones del CSV")
    st_folium(st.session_state.mapa_csv, key="mapa_csv_display", width=700, height=500) # Añadir key
elif st.session_state.mostrar_mapa == 'manual' and st.session_state.mapa_manual:
    st.markdown("### 🗺️ Mapa con la dirección manual")
    st_folium(st.session_state.mapa_manual, key="mapa_manual_display", width=700, height=500) # Añadir key
elif st.session_state.mostrar_mapa is None:
    st.info("Ingresa una dirección o carga el CSV para ver el mapa.")
