from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO
from datetime import datetime, timedelta
import json
import os
from typing import List, Dict
import requests
import pymysql
from pymysql.cursors import DictCursor

app = Flask(__name__)
socketio = SocketIO(app)

# Store sensor data in memory (you might want to use a database in production)
sensor_data = {
    'temperature': [],
    'humidity': [],
    'motion': False,
    'last_updated': None
}

# ================= MySQL Configuration (XAMPP) =================
# You can override these via environment variables if needed.
MYSQL_HOST = os.getenv('MYSQL_HOST', 'localhost')
MYSQL_PORT = int(os.getenv('MYSQL_PORT', '3306'))
MYSQL_USER = os.getenv('MYSQL_USER', 'root')
MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD', '')
MYSQL_DB = os.getenv('MYSQL_DB', 'greenswitch')

# Assumed mains voltage for Wh calculation (demo). Adjust if needed.
MAINS_VOLTAGE_V = float(os.getenv('MAINS_VOLTAGE_V', '230'))


def _connect_without_db():
    return pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        cursorclass=DictCursor,
        autocommit=True,
    )


def _connect_with_db():
    return pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DB,
        cursorclass=DictCursor,
        autocommit=True,
    )


def init_db():
    """Create database and readings table if not exists. Non-intrusive."""
    try:
        # Create database if missing
        conn = _connect_without_db()
        with conn.cursor() as cur:
            cur.execute(f"CREATE DATABASE IF NOT EXISTS `{MYSQL_DB}`")
        conn.close()

        # Create table if missing
        conn = _connect_with_db()
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS readings (
                    id BIGINT PRIMARY KEY AUTO_INCREMENT,
                    ts DATETIME(6) NOT NULL,
                    relay1_on TINYINT(1) NOT NULL,
                    relay2_on TINYINT(1) NOT NULL,
                    current1_a DOUBLE NOT NULL,
                    current2_a DOUBLE NOT NULL,
                    INDEX idx_ts (ts)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """
            )
        conn.close()
    except Exception as e:
        # Log but do not crash the app; dashboard should still work without DB
        print(f"[DB INIT] Warning: {e}")


def insert_reading(ts: datetime, relay1_on: bool, relay2_on: bool, current1_a: float, current2_a: float):
    try:
        conn = _connect_with_db()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO readings (ts, relay1_on, relay2_on, current1_a, current2_a)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (ts, 1 if relay1_on else 0, 1 if relay2_on else 0, float(current1_a or 0.0), float(current2_a or 0.0))
            )
        conn.close()
    except Exception as e:
        print(f"[DB INSERT] Warning: {e}")


def fetch_readings(start_ts: datetime = None, end_ts: datetime = None) -> List[Dict]:
    try:
        conn = _connect_with_db()
        with conn.cursor() as cur:
            if start_ts and end_ts:
                cur.execute(
                    "SELECT ts, relay1_on, relay2_on, current1_a, current2_a FROM readings WHERE ts BETWEEN %s AND %s ORDER BY ts ASC",
                    (start_ts, end_ts),
                )
            elif start_ts:
                cur.execute(
                    "SELECT ts, relay1_on, relay2_on, current1_a, current2_a FROM readings WHERE ts >= %s ORDER BY ts ASC",
                    (start_ts,),
                )
            else:
                cur.execute(
                    "SELECT ts, relay1_on, relay2_on, current1_a, current2_a FROM readings ORDER BY ts ASC"
                )
            rows = cur.fetchall() or []
        conn.close()
        return rows
    except Exception as e:
        print(f"[DB FETCH] Warning: {e}")
        return []


def integrate_energy_wh(rows: List[Dict]):
    """Compute total energy in Wh for relay1, relay2, and combined using trapezoidal integration.
    Assumes current is in Amps and mains voltage is constant (MAINS_VOLTAGE_V).
    """
    if not rows or len(rows) < 2:
        return 0.0, 0.0, 0.0

    e1_wh = 0.0
    e2_wh = 0.0
    for i in range(1, len(rows)):
        prev = rows[i - 1]
        curr = rows[i]
        dt = (curr['ts'] - prev['ts']).total_seconds()
        if dt <= 0:
            continue
        # Average current over interval (simple trapezoid)
        i1_avg = (float(prev['current1_a']) + float(curr['current1_a'])) / 2.0
        i2_avg = (float(prev['current2_a']) + float(curr['current2_a'])) / 2.0
        # Gate by relay state (use current sample's relay state)
        r1_on = bool(curr.get('relay1_on', 0))
        r2_on = bool(curr.get('relay2_on', 0))
        if not r1_on:
            i1_avg = 0.0
        if not r2_on:
            i2_avg = 0.0
        # Energy Wh = V * I (A) * dt(s) / 3600
        e1_wh += MAINS_VOLTAGE_V * i1_avg * (dt / 3600.0)
        e2_wh += MAINS_VOLTAGE_V * i2_avg * (dt / 3600.0)

    return e1_wh, e2_wh, (e1_wh + e2_wh)


def last_hour_timeseries(rows: List[Dict]):
    """Return labels (minute marks) and cumulative Wh over the last 60 minutes (combined). Approximate by bucketing per minute.
    """
    now = datetime.now()
    window_start = now - timedelta(minutes=60)

    # Initialize 60 buckets for per-minute energy (Wh)
    buckets = [0.0] * 60  # oldest -> newest

    if rows and len(rows) >= 2:
        for i in range(1, len(rows)):
            prev = rows[i - 1]
            curr = rows[i]
            if curr['ts'] < window_start:
                continue
            if curr['ts'] > now:
                continue
            dt = (curr['ts'] - prev['ts']).total_seconds()
            if dt <= 0:
                continue
            i1_avg = (float(prev['current1_a']) + float(curr['current1_a'])) / 2.0
            i2_avg = (float(prev['current2_a']) + float(curr['current2_a'])) / 2.0
            r1_on = bool(curr.get('relay1_on', 0))
            r2_on = bool(curr.get('relay2_on', 0))
            if not r1_on:
                i1_avg = 0.0
            if not r2_on:
                i2_avg = 0.0
            e_wh = MAINS_VOLTAGE_V * (i1_avg + i2_avg) * (dt / 3600.0)

            # Map curr.ts to bucket index (0 oldest, 59 newest), approx
            minutes_ago = int((now - curr['ts']).total_seconds() // 60)
            idx = 59 - minutes_ago
            if 0 <= idx < 60:
                buckets[idx] += e_wh

    # Build labels and cumulative series
    labels = []
    cumulative = []
    total = 0.0
    for m in range(60):
        ts_label = (now - timedelta(minutes=59 - m)).strftime('%H:%M')
        labels.append(ts_label)
        total += buckets[m]
        cumulative.append(total)

    return labels, cumulative

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/manual-control')
def manual_control():
    return render_template('manual-control.html')


@app.route('/usage')
def usage_page():
    return render_template('usage.html')

@app.route('/api/data', methods=['POST'])
def receive_data():
    data = request.json
    current_time = datetime.now().strftime('%H:%M:%S')
    now_dt = datetime.now()
    
    # Update sensor data
    sensor_data['temperature'].append({
        'time': current_time,
        'value': data['temperature'],
        'fahrenheit': (data['temperature'] * 9/5) + 32
    })
    sensor_data['humidity'].append({
        'time': current_time,
        'value': data['humidity']
    })
    sensor_data['motion'] = data['motion']
    sensor_data['last_updated'] = current_time
    # Add relay, duration, and current info
    sensor_data['relay1'] = data.get('relay1', False)
    sensor_data['relay2'] = data.get('relay2', False)
    sensor_data['light1_duration'] = data.get('light1_duration', 0)
    sensor_data['light2_duration'] = data.get('light2_duration', 0)
    sensor_data['current1'] = data.get('current1', 0.0)
    sensor_data['current2'] = data.get('current2', 0.0)
    sensor_data['current_total'] = data.get('current_total', 0.0)

    # Non-intrusive: also insert into MySQL readings table (does not affect existing behavior)
    try:
        insert_reading(
            ts=now_dt,
            relay1_on=bool(data.get('relay1', False)),
            relay2_on=bool(data.get('relay2', False)),
            current1_a=float(data.get('current1', 0.0) or 0.0),
            current2_a=float(data.get('current2', 0.0) or 0.0),
        )
    except Exception as e:
        # Log and continue
        print(f"[DB INSERT] {e}")

    # Keep only last 50 readings
    if len(sensor_data['temperature']) > 50:
        sensor_data['temperature'].pop(0)
        sensor_data['humidity'].pop(0)

    # Emit the new data to all connected clients
    socketio.emit('sensor_update', {
        'temperature': data['temperature'],
        'fahrenheit': (data['temperature'] * 9/5) + 32,
        'humidity': data['humidity'],
        'motion': data['motion'],
        'relay1': data.get('relay1', False),
        'relay2': data.get('relay2', False),
        'light1_duration': data.get('light1_duration', 0),
        'light2_duration': data.get('light2_duration', 0),
        'current1': data.get('current1', 0.0),
        'current2': data.get('current2', 0.0),
        'current_total': data.get('current_total', 0.0),
        'time': current_time
    })
    return jsonify({'status': 'success'})

@app.route('/api/data', methods=['GET'])
def get_data():
    return jsonify(sensor_data)


@app.route('/api/usage/totals', methods=['GET'])
def api_usage_totals():
    """Return lifetime totals in Wh per relay and combined."""
    rows = fetch_readings()
    e1, e2, total = integrate_energy_wh(rows)
    return jsonify({
        'relay1_wh': round(e1, 3),
        'relay2_wh': round(e2, 3),
        'total_wh': round(total, 3),
        'voltage_v': MAINS_VOLTAGE_V,
        'unit': 'Wh'
    })


@app.route('/api/usage/last-hour', methods=['GET'])
def api_usage_last_hour():
    """Return labels and cumulative Wh over the last hour (combined)."""
    now = datetime.now()
    start = now - timedelta(minutes=60)
    rows = fetch_readings(start_ts=start, end_ts=now)
    labels, cumulative = last_hour_timeseries(rows)
    return jsonify({
        'labels': labels,
        'cumulative_wh': [round(x, 3) for x in cumulative],
        'unit': 'Wh'
    })



# Manual control API endpoint
@app.route('/api/manual-control', methods=['POST'])
def manual_control_api():
    data = request.json
    channel = data.get('channel')
    state = data.get('state')
    esp32_ip = '10.148.248.88'  # Provided by user
    # Map channel and state to ESP32 HTTP request
    if channel in [1, 2] and state in ['on', 'off']:
        zone = channel
        state_str = 'ON' if state == 'on' else 'OFF'
        url = f'http://{esp32_ip}/light?zone={zone}&state={state_str}'
        try:
            resp = requests.get(url, timeout=2)
            if resp.status_code == 200:
                return jsonify({'message': f'Relay {channel} turned {state.upper()} successfully.'})
            else:
                return jsonify({'message': f'Failed to control relay {channel}. ESP32 responded with status {resp.status_code}.'}), 500
        except Exception as e:
            return jsonify({'message': f'Error communicating with ESP32: {str(e)}'}), 500
    else:
        return jsonify({'message': 'Invalid channel or state.'}), 400

if __name__ == '__main__':
    # Initialize database lazily; if MySQL is not running, app still serves existing dashboard.
    init_db()
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)