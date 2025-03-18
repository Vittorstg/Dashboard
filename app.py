from flask import Flask, jsonify, request, render_template
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import requests
import os

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///messaggi.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

class Messaggio(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False)
    msg = db.Column(db.String(200), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# Crea il database e le tabelle
with app.app_context():
    db.create_all()

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/meteo', methods=['GET'])
def get_meteo():
    try:
        # Coordinate di Bosa
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": 40.2993,
            "longitude": 8.4983,
            "current": ["temperature_2m", "relative_humidity_2m", "weather_code"],
            "timezone": "Europe/Rome"
        }
        
        response = requests.get(url, params=params)
        response.raise_for_status()  # Solleva un'eccezione per errori HTTP
        data = response.json()
        
        current = data.get('current', {})
        return jsonify({
            "temperature": current.get('temperature_2m'),
            "humidity": current.get('relative_humidity_2m'),
            "weather_code": current.get('weather_code'),
            "time": current.get('time')
        })
    except Exception as e:
        app.logger.error(f"Errore nel recupero del meteo: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/messaggi', methods=['GET', 'POST'])
def gestisci_messaggi():
    if request.method == 'POST':
        try:
            data = request.json
            if not data or 'username' not in data or 'messaggio' not in data:
                return jsonify({"error": "Dati mancanti"}), 400
            
            username = data['username'].strip()
            messaggio = data['messaggio'].strip()
            
            if not username or not messaggio:
                return jsonify({"error": "Username e messaggio non possono essere vuoti"}), 400
            
            if len(username) > 80 or len(messaggio) > 200:
                return jsonify({"error": "Username o messaggio troppo lunghi"}), 400
            
            nuovo_messaggio = Messaggio(username=username, msg=messaggio)
            db.session.add(nuovo_messaggio)
            db.session.commit()
            return jsonify({"message": "Messaggio inviato con successo!"}), 201
            
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Errore nell'invio del messaggio: {str(e)}")
            return jsonify({"error": str(e)}), 500

    elif request.method == 'GET':
        try:
            messaggi = Messaggio.query.order_by(Messaggio.timestamp.desc()).limit(50).all()
            return jsonify([{
                "username": m.username,
                "msg": m.msg,
                "timestamp": m.timestamp.strftime("%d/%m/%Y %H:%M:%S")
            } for m in messaggi])
        except Exception as e:
            app.logger.error(f"Errore nel recupero dei messaggi: {str(e)}")
            return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True) 