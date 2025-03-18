from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
from datetime import datetime, timedelta
import ephem
import math
import logging
import random
import json
import requests

# Configurazione logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # Abilita CORS per tutte le route

# Configurazione OpenWeatherMap
OPENWEATHER_API_KEY = "8431ed635eb791b0a11711c1c73c8d62"  # API key fornita dall'utente
OPENWEATHER_BASE_URL = "http://api.openweathermap.org/data/2.5"

# Storage per i messaggi e configurazione
messaggi = []
sstv_live_transmissions = []  # Lista per le trasmissioni SSTV live
DEFAULT_LAT = 40.2958  # Bosa
DEFAULT_LON = 8.5006
USER_LOCATION = {
    "lat": DEFAULT_LAT,
    "lon": DEFAULT_LON,
    "city": "Bosa",
    "timezone": "Europe/Rome"
}

# Database delle bande radioamatoriali con limiti di potenza italiani
RADIO_BANDS = {
    "HF": [
        {"name": "160m", "range": "1.830-1.850 MHz", "modes": ["CW", "SSB", "Digital"], "max_power": "500W"},
        {"name": "80m", "range": "3.500-3.800 MHz", "modes": ["CW", "SSB", "Digital"], "max_power": "500W"},
        {"name": "40m", "range": "7.000-7.200 MHz", "modes": ["CW", "SSB", "Digital"], "max_power": "500W"},
        {"name": "30m", "range": "10.100-10.150 MHz", "modes": ["CW", "Digital"], "max_power": "150W"},
        {"name": "20m", "range": "14.000-14.350 MHz", "modes": ["CW", "SSB", "Digital"], "max_power": "500W"},
        {"name": "17m", "range": "18.068-18.168 MHz", "modes": ["CW", "SSB", "Digital"], "max_power": "500W"},
        {"name": "15m", "range": "21.000-21.450 MHz", "modes": ["CW", "SSB", "Digital"], "max_power": "500W"},
        {"name": "12m", "range": "24.890-24.990 MHz", "modes": ["CW", "SSB", "Digital"], "max_power": "500W"},
        {"name": "10m", "range": "28.000-29.700 MHz", "modes": ["CW", "SSB", "Digital", "FM"], "max_power": "500W"}
    ],
    "VHF": [
        {"name": "6m", "range": "50.000-52.000 MHz", "modes": ["CW", "SSB", "Digital", "FM"], "max_power": "500W"},
        {"name": "2m", "range": "144.000-146.000 MHz", "modes": ["CW", "SSB", "Digital", "FM"], "max_power": "500W"}
    ],
    "UHF": [
        {"name": "70cm", "range": "430.000-440.000 MHz", "modes": ["CW", "SSB", "Digital", "FM"], "max_power": "500W"},
        {"name": "23cm", "range": "1240.000-1300.000 MHz", "modes": ["CW", "SSB", "Digital", "FM"], "max_power": "500W"}
    ]
}

# Configurazione dei satelliti
SATELLITES = {
    "ISS": {
        "norad_id": "25544",
        "frequency_downlink": "145.800",
        "frequency_uplink": "145.200",
        "modes": ["FM Voice", "SSTV", "Packet"],
        "active": True
    },
    "NOAA 18": {
        "norad_id": "28654",
        "frequency": "137.9125",
        "modes": ["APT"],
        "active": True
    },
    "NOAA 19": {
        "norad_id": "33591",
        "frequency": "137.1000",
        "modes": ["APT"],
        "active": True
    },
    "METEOR-M2": {
        "norad_id": "40069",
        "frequency": "137.1000",
        "modes": ["LRPT"],
        "active": True
    }
}

def get_solar_data():
    """Simula dati solari realistici"""
    now = datetime.now()
    hour = now.hour
    
    # Simula variazione giornaliera del flusso solare
    base_flux = 120  # Valore medio tipico
    daily_variation = math.sin(hour * math.pi / 12) * 10
    solar_flux = base_flux + daily_variation
    
    # Simula indice K con variazioni più realistiche
    k_index = max(0, min(9, random.gauss(3, 1)))
    
    return solar_flux, k_index

def get_band_conditions(solar_flux, k_index):
    """Calcola condizioni di propagazione realistiche basate su dati solari"""
    conditions = {}
    
    for band in ["80m", "40m", "30m", "20m", "17m", "15m", "12m", "10m"]:
        # Calcola MUF (Maximum Usable Frequency)
        if band == "80m": base_muf = 4
        elif band == "40m": base_muf = 8
        elif band == "30m": base_muf = 12
        elif band == "20m": base_muf = 16
        elif band == "17m": base_muf = 19
        elif band == "15m": base_muf = 22
        elif band == "12m": base_muf = 25
        else: base_muf = 28
        
        # Modifica MUF basata su flusso solare e indice K
        muf = base_muf * (1 + (solar_flux - 120) / 200) * (1 - k_index / 20)
        
        # Calcola rumore di banda
        noise = -120 + k_index * 2 + random.uniform(-5, 5)
        
        # Determina condizione generale
        if k_index <= 3 and solar_flux >= 110:
            condition = "Eccellente"
            reliability = random.uniform(85, 100)
        elif k_index <= 5 and solar_flux >= 90:
            condition = "Buona"
            reliability = random.uniform(70, 85)
        elif k_index <= 7:
            condition = "Discreta"
            reliability = random.uniform(50, 70)
        else:
            condition = "Scarsa"
            reliability = random.uniform(20, 50)
            
        conditions[band] = {
            "condition": condition,
            "noise_level": round(noise, 1),
            "muf": round(muf, 1),
            "reliability": round(reliability, 1)
        }
    
    return conditions

def get_signal_quality(elevation):
    """Stima la qualità del segnale basata sull'elevazione"""
    try:
        if elevation > 60:
            return "Eccellente", -50
        elif elevation > 40:
            return "Buono", -65
        elif elevation > 20:
            return "Discreto", -75
        else:
            return "Debole", -85
    except Exception:
        return "Non disponibile", -100

def calculate_distance(lat1, lon1, lat2, lon2):
    """Calcola la distanza tra due punti usando la formula di Haversine"""
    R = 6371  # Raggio della Terra in km
    
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    return R * c

def calculate_azimuth(lat1, lon1, lat2, lon2):
    """Calcola l'azimuth tra due punti"""
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlon = lon2 - lon1
    
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    azimuth = math.degrees(math.atan2(y, x))
    return (azimuth + 360) % 360

def grid_to_latlon(grid):
    """Converte un Maidenhead Grid Locator in coordinate geografiche"""
    if len(grid) < 4:
        return None
        
    grid = grid.upper()
    lon = (ord(grid[0]) - ord('A')) * 20 - 180
    lat = (ord(grid[1]) - ord('A')) * 10 - 90
    
    lon += (ord(grid[2]) - ord('0')) * 2
    lat += (ord(grid[3]) - ord('0'))
    
    if len(grid) >= 6:
        lon += (ord(grid[4]) - ord('A')) / 12
        lat += (ord(grid[5]) - ord('A')) / 24
    
    return {"lat": lat, "lon": lon}

def latlon_to_grid(lat, lon):
    """Converte coordinate geografiche in Maidenhead Grid Locator"""
    lon += 180
    lat += 90
    
    field_lon = chr(ord('A') + int(lon / 20))
    field_lat = chr(ord('A') + int(lat / 10))
    
    square_lon = str(int((lon % 20) / 2))
    square_lat = str(int(lat % 10))
    
    subsquare_lon = chr(ord('A') + int((lon % 2) * 12))
    subsquare_lat = chr(ord('A') + int((lat % 1) * 24))
    
    return field_lon + field_lat + square_lon + square_lat + subsquare_lon + subsquare_lat

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/meteo', methods=['GET'])
def get_meteo():
    try:
        # Ottieni dati meteo attuali
        current_url = f"{OPENWEATHER_BASE_URL}/weather"
        params = {
            "lat": USER_LOCATION["lat"],
            "lon": USER_LOCATION["lon"],
            "appid": OPENWEATHER_API_KEY,
            "units": "metric",
            "lang": "it"
        }
        
        current_response = requests.get(current_url, params=params)
        current_data = current_response.json()
        logger.info(f"OpenWeatherMap response: {current_data}")
        
        if current_response.status_code != 200:
            error_msg = current_data.get('message', 'Errore nel recupero dei dati meteo')
            logger.error(f"OpenWeatherMap API error: {error_msg}")
            return jsonify({"error": error_msg}), current_response.status_code
            
        # Ottieni previsioni per 5 giorni
        forecast_url = f"{OPENWEATHER_BASE_URL}/forecast"
        forecast_response = requests.get(forecast_url, params=params)
        forecast_data = forecast_response.json()
        
        if forecast_response.status_code != 200:
            error_msg = forecast_data.get('message', 'Errore nel recupero delle previsioni')
            logger.error(f"OpenWeatherMap Forecast API error: {error_msg}")
            return jsonify({"error": error_msg}), forecast_response.status_code
        
        # Elabora i dati attuali
        current_temp = current_data["main"]["temp"]
        current_humidity = current_data["main"]["humidity"]
        current_wind = current_data["wind"]["speed"] * 3.6  # Converti m/s in km/h
        current_rain = current_data.get("rain", {}).get("1h", 0)  # Pioggia nell'ultima ora
        
        # Organizza le previsioni per giorno
        forecast_by_day = {}
        for item in forecast_data["list"]:
            day = datetime.fromtimestamp(item["dt"]).strftime("%d/%m")
            if day not in forecast_by_day:
                forecast_by_day[day] = []
            
            forecast_by_day[day].append({
                "temperature": round(item["main"]["temp"], 1),
                "description": item["weather"][0]["description"].capitalize(),
                "humidity": item["main"]["humidity"],
                "wind": round(item["wind"]["speed"] * 3.6, 1)  # Converti m/s in km/h
            })
        
        return jsonify({
            "temperature": round(current_temp, 1),
            "humidity": round(current_humidity, 1),
            "wind": round(current_wind, 1),
            "rain": round(current_rain, 1),
            "forecast": forecast_by_day
        })
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Errore di rete: {str(e)}")
        return jsonify({"error": "Errore di connessione al servizio meteo"}), 503
    except KeyError as e:
        logger.error(f"Errore nei dati: {str(e)}")
        return jsonify({"error": "Dati meteo non validi"}), 500
    except Exception as e:
        logger.error(f"Errore generico: {str(e)}")
        return jsonify({"error": "Errore interno del server"}), 500

@app.route('/set_location', methods=['POST'])
def set_location():
    try:
        data = request.json
        lat = float(data.get('lat', DEFAULT_LAT))
        lon = float(data.get('lon', DEFAULT_LON))
        
        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            raise ValueError("Coordinate non valide")

        USER_LOCATION.update({
            "lat": lat,
            "lon": lon,
            "city": "Posizione personalizzata",
            "timezone": "Europe/Rome"
        })
        
        return jsonify({"status": "success", "location": USER_LOCATION})
    except Exception as e:
        logger.error(f"Errore nell'impostazione della posizione: {str(e)}")
        return jsonify({"error": "Errore nel processare la richiesta"}), 500

@app.route('/noaa', methods=['GET'])
def get_noaa():
    try:
        # Ottieni dati per tutti i satelliti configurati
        satellite_data = {}
        for sat_name, sat_info in SATELLITES.items():
            pass_data = get_satellite_pass(sat_name)
            quality, signal_strength = get_signal_quality(pass_data["max_elevation"])
            
            satellite_data[sat_name] = {
                "frequency": sat_info.get("frequency", sat_info.get("frequency_downlink", "N/A")),
                "modes": sat_info["modes"],
                "active": sat_info["active"],
                "next_pass": {
                    "rise": pass_data["rise_time"].strftime("%H:%M:%S"),
                    "max": pass_data["max_time"].strftime("%H:%M:%S"),
                    "set": pass_data["set_time"].strftime("%H:%M:%S"),
                    "elevation": pass_data["max_elevation"],
                    "duration": pass_data["duration"]
                },
                "signal_quality": quality,
                "signal_strength": signal_strength
            }
            
            # Aggiungi prossimi passaggi
            upcoming_passes = []
            last_pass = pass_data["rise_time"]
            for _ in range(3):
                next_pass = get_satellite_pass(sat_name)
                next_pass["rise_time"] = last_pass + timedelta(hours=random.randint(2, 4))
                upcoming_passes.append({
                    "rise": next_pass["rise_time"].strftime("%d/%m %H:%M"),
                    "elevation": next_pass["max_elevation"],
                    "duration": next_pass["duration"]
                })
                last_pass = next_pass["rise_time"]
            
            satellite_data[sat_name]["upcoming_passes"] = upcoming_passes
        
        return jsonify({
            "location": USER_LOCATION,
            "satellites": satellite_data
        })
    except Exception as e:
        logger.error(f"Errore nel recupero dei dati satellitari: {str(e)}")
        return jsonify({"error": "Errore nel recupero dei dati"}), 500

@app.route('/sstv/transmit', methods=['POST'])
def transmit_sstv():
    try:
        data = request.json
        frequency = data.get('frequency')
        mode = data.get('mode')
        message = data.get('message')
        operator = data.get('operator')
        
        if not all([frequency, mode, message, operator]):
            return jsonify({"error": "Tutti i campi sono richiesti"}), 400
            
        transmission = {
            "id": len(sstv_live_transmissions) + 1,
            "frequency": frequency,
            "mode": mode,
            "message": message,
            "operator": operator,
            "start_time": datetime.now().strftime("%H:%M"),
            "active": True,
            "signal_quality": "Eccellente"
        }
        
        sstv_live_transmissions.append(transmission)
        
        # Mantieni solo le ultime 10 trasmissioni
        if len(sstv_live_transmissions) > 10:
            sstv_live_transmissions.pop(0)
            
        return jsonify({"status": "success", "transmission": transmission})
    except Exception as e:
        logger.error(f"Errore nella trasmissione SSTV: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/sstv', methods=['GET'])
def get_sstv():
    # Combina le trasmissioni simulate con quelle live
    modes = ["Robot 36", "Martin M1", "Scottie S1"]
    operators = ["IZ1ABC", "IK2XYZ", "IW3DEF"]
    
    simulated_signals = [
        {
            "frequency": f"14.{random.randint(230,235)}",
            "mode": random.choice(modes),
            "operator": random.choice(operators),
            "start_time": datetime.now().strftime("%H:%M"),
            "signal_quality": random.choice(["Buono", "Discreto", "Eccellente"]),
            "type": "simulated"
        } for _ in range(random.randint(1,2))
    ]
    
    # Filtra solo le trasmissioni live attive degli ultimi 5 minuti
    current_time = datetime.now()
    active_live = [
        {**trans, "type": "live"}
        for trans in sstv_live_transmissions
        if (current_time - datetime.strptime(trans["start_time"], "%H:%M")).total_seconds() < 300
    ]
    
    return jsonify({
        "active_signals": active_live + simulated_signals
    })

@app.route('/messaggi', methods=['GET', 'POST'])
def handle_messaggi():
    if request.method == 'POST':
        try:
            data = request.json
            username = data.get('username')
            msg = data.get('messaggio')
            
            if not all([username, msg]):
                return jsonify({"error": "Tutti i campi sono richiesti"}), 400
            
            # Sanitizza l'input
            username = username.strip()[:50]  # Limita la lunghezza dell'username
            msg = msg.strip()[:500]  # Limita la lunghezza del messaggio
            
            # Controlla che l'username non sia vuoto dopo la sanitizzazione
            if not username or not msg:
                return jsonify({"error": "Username e messaggio non possono essere vuoti"}), 400
            
            nuovo_msg = {
                "username": username,
                "msg": msg,
                "timestamp": datetime.now().strftime("%d/%m/%Y %H:%M")
            }
            messaggi.append(nuovo_msg)
            
            # Mantieni solo gli ultimi 100 messaggi
            if len(messaggi) > 100:
                messaggi.pop(0)
            
            return jsonify({"status": "success"})
        except Exception as e:
            logger.error(f"Errore nella gestione del messaggio: {str(e)}")
            return jsonify({"error": "Errore interno del server"}), 500
    
    # GET request - Restituisci i messaggi in ordine cronologico inverso
    return jsonify(list(reversed(messaggi)))

@app.route('/radio/bands', methods=['GET'])
def get_radio_bands():
    """Restituisce il database delle bande radioamatoriali"""
    return jsonify(RADIO_BANDS)

@app.route('/radio/grid', methods=['POST'])
def convert_grid():
    """Converte tra Grid Locator e coordinate geografiche"""
    try:
        data = request.json
        if 'grid' in data:
            result = grid_to_latlon(data['grid'])
            if result:
                return jsonify(result)
            return jsonify({"error": "Grid Locator non valido"}), 400
        elif 'lat' in data and 'lon' in data:
            try:
                lat = float(data['lat'])
                lon = float(data['lon'])
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    grid = latlon_to_grid(lat, lon)
                    return jsonify({"grid": grid})
                return jsonify({"error": "Coordinate non valide"}), 400
            except:
                return jsonify({"error": "Coordinate non valide"}), 400
        return jsonify({"error": "Dati mancanti"}), 400
    except Exception as e:
        logger.error(f"Errore nella conversione grid: {str(e)}")
        return jsonify({"error": "Errore interno del server"}), 500

@app.route('/radio/distance', methods=['POST'])
def calculate_path():
    """Calcola distanza e azimuth tra due punti"""
    try:
        data = request.json
        lat1 = float(data['lat1'])
        lon1 = float(data['lon1'])
        lat2 = float(data['lat2'])
        lon2 = float(data['lon2'])
        
        # Usa ephem per calcoli più precisi
        obs = ephem.Observer()
        obs.lat = str(lat1)
        obs.lon = str(lon1)
        
        target = ephem.FixedBody()
        target._ra = ephem.degrees(str(lon2))
        target._dec = ephem.degrees(str(lat2))
        
        target.compute(obs)
        
        # Calcola distanza con Haversine
        distance = calculate_distance(lat1, lon1, lat2, lon2)
        
        return jsonify({
            "distance": round(distance, 2),
            "azimuth": round(math.degrees(float(target.az)), 2),
            "elevation": round(math.degrees(float(target.alt)), 2)
        })
    except Exception as e:
        logger.error(f"Errore nel calcolo del percorso: {str(e)}")
        return jsonify({"error": "Dati non validi"}), 400

@app.route('/radio/linkbudget', methods=['POST'])
def calculate_link_budget():
    """Calcola il link budget per un collegamento radio"""
    try:
        data = request.json
        freq_mhz = float(data['frequency'])
        distance_km = float(data['distance'])
        tx_power_w = float(data['tx_power'])
        tx_gain_dbi = float(data['tx_gain'])
        rx_gain_dbi = float(data['rx_gain'])
        
        # Calcolo perdita in spazio libero più realistico
        freq_hz = freq_mhz * 1e6
        distance_m = distance_km * 1000
        
        # Formula migliorata per FSPL
        fspl = 20 * math.log10(distance_m) + 20 * math.log10(freq_hz) - 147.55
        
        # Aggiungi perdite atmosferiche
        atmospheric_loss = 0.1 * distance_km  # 0.1 dB/km è un valore tipico
        
        # Potenza di trasmissione in dBm
        tx_power_dbm = 10 * math.log10(tx_power_w * 1000)
        
        # Calcolo potenza ricevuta
        rx_power_dbm = tx_power_dbm + tx_gain_dbi + rx_gain_dbi - fspl - atmospheric_loss
        
        # Calcolo SNR assumendo un noise floor di -102 dBm
        snr = rx_power_dbm + 102
        
        return jsonify({
            "tx_power_dbm": round(tx_power_dbm, 2),
            "path_loss_db": round(fspl + atmospheric_loss, 2),
            "rx_power_dbm": round(rx_power_dbm, 2),
            "snr_db": round(snr, 2),
            "link_quality": "Ottimo" if snr > 20 else "Buono" if snr > 10 else "Sufficiente" if snr > 5 else "Scarso"
        })
    except Exception as e:
        logger.error(f"Errore nel calcolo del link budget: {str(e)}")
        return jsonify({"error": "Dati non validi"}), 400

@app.route('/radio/propagation', methods=['GET'])
def get_propagation():
    """Fornisce condizioni di propagazione HF realistiche"""
    try:
        solar_flux, k_index = get_solar_data()
        conditions = get_band_conditions(solar_flux, k_index)
        
        return jsonify({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "solar_flux": round(solar_flux, 1),
            "k_index": round(k_index, 1),
            "bands": conditions
        })
    except Exception as e:
        logger.error(f"Errore nel recupero dati propagazione: {str(e)}")
        return jsonify({"error": "Errore interno del server"}), 500

def get_satellite_pass(sat_name):
    """Calcola il prossimo passaggio del satellite"""
    now = datetime.now()
    
    # Simula un passaggio realistico
    if sat_name == "ISS":
        next_pass = now + timedelta(minutes=random.randint(30, 90))
        duration = random.randint(8, 12)
    else:  # NOAA e METEOR hanno orbite più alte
        next_pass = now + timedelta(minutes=random.randint(60, 180))
        duration = random.randint(12, 15)
        
    max_elevation = random.randint(15, 85)
    
    return {
        "rise_time": next_pass,
        "max_time": next_pass + timedelta(minutes=duration/2),
        "set_time": next_pass + timedelta(minutes=duration),
        "max_elevation": max_elevation,
        "duration": duration
    }

@app.route('/status', methods=['GET'])
def get_status():
    """Controlla lo stato di tutti i servizi"""
    try:
        services_status = {
            "openweather": {
                "name": "OpenWeather API",
                "status": False,
                "last_check": datetime.now().strftime("%H:%M:%S")
            },
            "satellites": {
                "name": "Sistema Satelliti",
                "status": True,  # Simulato perché è un sistema locale
                "last_check": datetime.now().strftime("%H:%M:%S")
            },
            "radio": {
                "name": "Sistema Radio",
                "status": True,  # Simulato perché è un sistema locale
                "last_check": datetime.now().strftime("%H:%M:%S")
            },
            "sstv": {
                "name": "Sistema SSTV",
                "status": True,  # Simulato perché è un sistema locale
                "last_check": datetime.now().strftime("%H:%M:%S")
            }
        }

        # Verifica OpenWeather API
        try:
            params = {
                "lat": USER_LOCATION["lat"],
                "lon": USER_LOCATION["lon"],
                "appid": OPENWEATHER_API_KEY,
                "units": "metric"
            }
            response = requests.get(f"{OPENWEATHER_BASE_URL}/weather", params=params)
            services_status["openweather"]["status"] = response.status_code == 200
        except:
            services_status["openweather"]["status"] = False

        return jsonify(services_status)
    except Exception as e:
        logger.error(f"Errore nel controllo dello stato dei servizi: {str(e)}")
        return jsonify({"error": "Errore interno del server"}), 500

if __name__ == '__main__':
    # In produzione, disabilita il debug e usa HTTPS
    app.run(host='0.0.0.0', port=5000, debug=False)