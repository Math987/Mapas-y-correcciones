import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
from unidecode import unidecode
import re
from fuzzywuzzy import fuzz, process
from geopy.geocoders import Nominatim
import folium
from streamlit_folium import st_folium

# -----------------------------
# Funciones
# -----------------------------
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
        direccion_corregida = calles_df.loc[idx, "original"].values[0]
    else:
        return None  # Marcar como no encontrada

    return direccion_corregida + (" " + numero_direccion if numero_direccion else "")

@st.cache_data(show_spinner=False)
def obtener_callejero():
    url = "https://codigo-postal.co/chile/santiago/calles-de-conchali/"
    response = requests.get(url)
    soup = BeautifulSoup(response.text, "html.parser")
    ul_cities = soup.find("ul", class_="cities")
    li_items = ul_cities.find_all("li")
    calles = [li.find("a").text.strip() for li in li_items]
    df_calles = pd.DataFrame({
        "original": calles,
        "normalizado": [normalizar(c) for c in calles]
    })
    return df_calles

@st.cache_data(show_spinner=False)
def geolocalizar_direccion(direccion):
    geolocator = Nominatim(user_agent="app_conchali", timeout=3)
    try:
        location = geolocator.geocode(f"{direccion}, Conchalí, Chile")
        if location:
            return location.latitude, location.longitude
    except:
        return None
    return None

# -----------------------------
# App
# -----------------------------
st.title("Corrector y Mapeador de Direcciones - Conchalí")

# Input de usuario
input_direcciones = st.text_area("Ingresa direcciones separadas por línea:", height=200)
direcciones = [line.strip() for line in input_direcciones.strip().split("\n") if line.strip()]

if st.button("Corregir y Geolocalizar") and direcciones:
    df_calles = obtener_callejero()
    df = pd.DataFrame(direcciones, columns=["Direccion_Original"])
    df["Direccion_Corregida"] = df["Direccion_Original"].apply(lambda x: corregir_direccion(x, df_calles, umbral=80))

    st.subheader("Direcciones Corregidas")
    st.dataframe(df)

    # Informe de no encontradas
    no_encontradas = df[df["Direccion_Corregida"].isnull()]["Direccion_Original"].tolist()
    if no_encontradas:
        st.warning("Direcciones no encontradas:")
        st.write(no_encontradas)

    # Mapa con las encontradas
    st.subheader("Mapa de Direcciones Corregidas")
    mapa = folium.Map(location=[-33.381, -70.678], zoom_start=13)
    for _, row in df.dropna().iterrows():
        geo = geolocalizar_direccion(row["Direccion_Corregida"])
        if geo:
            folium.Marker(
                location=geo,
                popup=row["Direccion_Corregida"],
                icon=folium.Icon(color="blue")
            ).add_to(mapa)

    st_folium(mapa, width=700, height=500)
else:
    st.info("Ingresa algunas direcciones para comenzar.")
