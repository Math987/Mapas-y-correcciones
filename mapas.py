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

# Configuración
st.set_page_config(page_title="Mapa de Direcciones Corregidas", layout="wide")
st.title("🗺️ Mapa de Direcciones Corregidas en Conchalí")

# 1. Scraping de calles oficiales de Conchalí
@st.cache_data
def obtener_calles_conchali():
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
    texto = unidecode(str(texto)).upper()
    texto = re.sub(r'[^\w\s0-9]', '', texto)
    texto = re.sub(r'\s+', ' ', texto).strip()
    return texto

def corregir_direccion(direccion_input, calles_df, umbral=80):
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
    geolocator = Nominatim(user_agent="streamlit_app", timeout=10)
    try:
        location = geolocator.geocode(f"{direccion}, Conchalí, Chile")
        if location:
            return location.latitude, location.longitude
    except GeocoderUnavailable:
        return None
    return None

# 2. Leer desde el CSV de Google Sheets
st.markdown("### 📑 URL del Google Sheet")
sheet_url = st.text_input("Pega aquí la URL del Google Sheet que contiene la columna 'direccion':")

if sheet_url:
    try:
        # Leer el CSV directamente desde la URL pública
        data = pd.read_csv(sheet_url)

        # Verificar que la columna 'direccion' esté presente en los datos
        if "direccion" not in data.columns:
            st.error("❌ La hoja no contiene una columna llamada 'direccion'.")
        else:
            # Obtener las calles oficiales de Conchalí
            calles_df = obtener_calles_conchali()

            # Corregir direcciones y obtener coordenadas
            data["direccion_corregida"] = data["direccion"].apply(lambda x: corregir_direccion(x, calles_df))
            data["coords"] = data["direccion_corregida"].apply(obtener_coords)

            # Eliminar las filas sin coordenadas
            data = data.dropna(subset=["coords"])

            # Mostrar las direcciones corregidas
            st.markdown("### ✅ Direcciones encontradas:")
            st.dataframe(data[["direccion", "direccion_corregida"]])

            # Mostrar las direcciones originales y corregidas en formato de texto antes del mapa
            for index, row in data.iterrows():
                st.markdown(f"#### Dirección original: {row['direccion']}")
                st.markdown(f"#### Dirección corregida: {row['direccion_corregida']}")
                st.markdown("### Ubicación aproximada:")

            # Mapa
            mapa = folium.Map(location=[-33.38, -70.65], zoom_start=13)
            for i, row in data.iterrows():
                folium.Marker(location=row["coords"], popup=row["direccion_corregida"]).add_to(mapa)
            st.markdown("### 🗺️ Mapa con direcciones corregidas")
            st_folium(mapa, width=700, height=500)
    except Exception as e:
        st.error(f"⚠️ Error: {str(e)}")
