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

# 1. Funciones auxiliares

@st.cache_data
def obtener_calles_conchali():
    url = "https://codigo-postal.co/chile/santiago/calles-de-conchali/"
    response = requests.get(url)
    soup = BeautifulSoup(response.text, "html.parser")
    ul_cities = soup.find("ul", class_="cities")
    li_items = ul_cities.find_all("li")
    calles = [li.find("a").text.strip() for li in li_items]
    return pd.DataFrame(calles, columns=["Calle"])

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
    mejor_match = process.extractOne(
        entrada_norm, 
        calles_df["normalizado"], 
        scorer=fuzz.token_set_ratio
    )
    if mejor_match and mejor_match[1] >= umbral:
        idx = calles_df["normalizado"] == mejor_match[0]
        direccion_corregida = calles_df.loc[idx, "original"].values[0]
    else:
        direccion_corregida = direccion_texto
    return direccion_corregida + (" " + numero_direccion if numero_direccion else "")

def geolocalizar(direccion):
    geolocator = Nominatim(user_agent="direccion_conchali_app")
    try:
        location = geolocator.geocode(f"{direccion}, Conchalí, Chile")
        if location:
            return location.latitude, location.longitude
    except:
        return None, None
    return None, None

# 2. Cargar base de calles
df_calles_conchali = obtener_calles_conchali()
calles_conchali = df_calles_conchali["Calle"].tolist()
df_calles = pd.DataFrame({
    "original": calles_conchali,
    "normalizado": [normalizar(c) for c in calles_conchali]
})

# 3. Interfaz de usuario
st.title("Corrección de direcciones en Conchalí")

direccion_input = st.text_input("Ingresa una dirección (ej: Tres Ote. 5317):", key="direccion_input")

if st.button("Corregir y ubicar"):
    direccion_corregida = corregir_direccion(direccion_input, df_calles)
    lat, lon = geolocalizar(direccion_corregida)

    st.session_state["resultado"] = {
        "original": direccion_input,
        "corregida": direccion_corregida,
        "lat": lat,
        "lon": lon
    }

# 4. Mostrar resultados guardados
if "resultado" in st.session_state:
    resultado = st.session_state["resultado"]
    st.write("**Dirección original:**", resultado["original"])
    st.write("**Dirección corregida:**", resultado["corregida"])

    if resultado["lat"] and resultado["lon"]:
        st.write("**Ubicación aproximada:**")
        m = folium.Map(location=[resultado["lat"], resultado["lon"]], zoom_start=17)
        folium.Marker([resultado["lat"], resultado["lon"]], tooltip=resultado["corregida"]).add_to(m)
        st_folium(m, width=700, height=500)
    else:
        st.warning("No se encontró ubicación para la dirección corregida.")
