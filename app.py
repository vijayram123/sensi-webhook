from flask import Flask, request, jsonify, abort
import gspread, requests, os
from seam import Seam
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

app = Flask(__name__)
seam = Seam(api_key=os.getenv("SEAM_API_KEY"))

# 🔐 Token for authenticating webhook access
WEBHOOK_AUTH_TOKEN = os.getenv("WEBHOOK_AUTH_TOKEN")

# 🌡️ Get outdoor temperature from OpenWeather API
def get_outdoor_temp(zip="28348"):
    r = requests.get(
        f"https://api.openweathermap.org/data/2.5/weather?zip={zip},us&units=imperial&appid={os.getenv('WEATHER_API_KEY')}"
    )
    return r.json()["main"]["temp"]

# 🧠 Set thermostat based on mode and temperature
def set_thermostat(mode, temp_f):
    devices = seam.devices.list()
    sensi = next((d for d in devices if d.nickname == "SensiHanover"), None)
    if sensi is None:
        return {"error": "Thermostat not found"}

    dev = seam.devices.get(device_id=sensi.device_id)

    if mode.lower() == "cool" and getattr(dev, "can_hvac_cool", False):
        resp = seam.thermostats.cool(device_id=sensi.device_id, cooling_set_point_fahrenheit=temp_f)
    elif mode.lower() == "heat" and getattr(dev, "can_hvac_heat", False):
        resp = seam.thermostats.heat(device_id=sensi.device_id, heating_set_point_fahrenheit=temp_f)
    elif mode.lower() == "off" and getattr(dev, "can_turn_off_hvac", False):
        resp = seam.thermostats.off(device_id=sensi.device_id)
    else:
        return {"error": f"Unsupported mode '{mode}' or missing capability"}

    if hasattr(resp, "dict"):
        return resp.dict()
    elif hasattr(resp, "model_dump"):
        return resp.model_dump()
    else:
        return {"result": str(resp)}

# 📋 Log action to Google Sheet
def log_action_to_sheet(action_type, outdoor_temp, mode, setpoint, notes):
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
    client = gspread.authorize(creds)
    sheet = client.open("sensiwebhooklogs").sheet1

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_row = [timestamp, action_type, outdoor_temp, mode, setpoint if setpoint is not None else "", notes]
    log_sheet.append_row(log_row, value_input_option="USER_ENTERED")

# 🔐 Require token authentication
def require_auth():
    token = request.headers.get("Authorization")
    if not token or token != f"Bearer {WEBHOOK_AUTH_TOKEN}":
        abort(401, description="Unauthorized")

# 🚪 Main webhook route
@app.route("/adjust-temp", methods=["POST"])
def adjust_temp():
    require_auth()

    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
    client = gspread.authorize(creds)
    sheet = client.open("casahanoverbookingssheet").sheet1

    today = datetime.today().date()
    rows = sheet.get_all_records()
    accepted_rows = [r for r in rows if r.get("Status", "").strip().lower() == "accepted"]

    def parse_date(date_str):
        date_part = date_str.strip().split(" ")[0]
        return datetime.strptime(date_part, "%Y-%m-%d").date()

    checkin_today = any(parse_date(r["Check-in"]) == today for r in accepted_rows)
    checkout_today = any(parse_date(r["Check-out"]) == today for r in accepted_rows)
    same_day_turnover = checkin_today and checkout_today

    temp = get_outdoor_temp()

    if checkin_today:
        if temp >= 75:
            resp = set_thermostat("cool", 73)
            log_action_to_sheet("checkin", temp, "cool", 73, str(resp))
        elif temp <= 65:
            resp = set_thermostat("heat", 70)
            log_action_to_sheet("checkin", temp, "heat", 70, str(resp))
        else:
            resp = {"status": "no_temp_threshold_met_for_checkin"}
            log_action_to_sheet("checkin", temp, "none", None, str(resp))
        return jsonify({"status": "checkin_adjusted", "detail": resp})

    elif checkout_today and not same_day_turnover:
        if temp >= 75:
            resp = set_thermostat("cool", 77)
            log_action_to_sheet("checkout", temp, "cool", 77, str(resp))
        elif temp <= 65:
            resp = set_thermostat("heat", 65)
            log_action_to_sheet("checkout", temp, "heat", 65, str(resp))
        else:
            resp = set_thermostat("off", None)
            log_action_to_sheet("checkout", temp, "off", None, str(resp))
        return jsonify({"status": "checkout_adjusted", "detail": resp})

    log_action_to_sheet("none", temp, "none", None, "no_action_taken")
    return jsonify({"status": "no_action"})


