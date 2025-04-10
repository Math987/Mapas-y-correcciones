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
import gspread
from oauth2client.service_account import ServiceAccountCredentials

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

# 2. Leer desde Google Sheets
st.markdown("### 📑 URL del Google Sheet")
sheet_url = st.text_input("Pega aquí la URL del Google Sheet que contiene la columna 'direccion':")

if sheet_url:
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
        client = gspread.authorize(creds)
        sheet_id = sheet_url.split("/d/")[1].split("/")[0]
        sheet = client.open_by_key(sheet_id).sheet1
        data = pd.DataFrame(sheet.get_all_records())
        
        if "direccion" not in data.columns:
            st.error("❌ La hoja no contiene una columna llamada 'direccion'.")
        else:
            calles_df = obtener_calles_conchali()
            data["direccion_corregida"] = data["direccion"].apply(lambda x: corregir_direccion(x, calles_df))
            data["coords"] = data["direccion_corregida"].apply(obtener_coords)
            data = data.dropna(subset=["coords"])
            
            st.markdown("### ✅ Direcciones encontradas:")
            st.dataframe(data[["direccion", "direccion_corregida"]])
            
            # Mapa
            mapa = folium.Map(location=[-33.38, -70.65], zoom_start=13)
            for i, row in data.iterrows():
                folium.Marker(location=row["coords"], popup=row["direccion_corregida"]).add_to(mapa)
            st.markdown("### 🗺️ Mapa con direcciones corregidas")
            st_folium(mapa, width=700, height=500)
    except Exception as e:
        st.error(f"⚠️ Error: {str(e)}")
