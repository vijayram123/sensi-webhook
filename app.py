from flask import Flask, request
import gspread, requests, os
from seam import Seam
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

app = Flask(__name__)
seam = Seam(api_key=os.getenv("SEAM_API_KEY"))

def get_outdoor_temp(zip="28348"):
    r = requests.get(
        f"https://api.openweathermap.org/data/2.5/weather?zip={zip},us&units=imperial&appid={os.getenv('WEATHER_API_KEY')}"
    )
    return r.json()["main"]["temp"]

def set_thermostat(mode, temp_f):
    devices = seam.devices.list()
    sensi = next((d for d in devices if d.nickname == "SensiHanover"), None)
    if sensi is None:
        return {"error": "Thermostat not found"}

    dev = seam.devices.get(device_id=sensi.device_id)

    if mode.lower() == "cool" and getattr(dev, "can_hvac_cool", False):
        return seam.thermostats.cool(
            device_id=sensi.device_id,
            cooling_set_point_fahrenheit=temp_f
        )
    elif mode.lower() == "heat" and getattr(dev, "can_hvac_heat", False):
        return seam.thermostats.heat(
            device_id=sensi.device_id,
            heating_set_point_fahrenheit=temp_f
        )
    elif mode.lower() == "off" and getattr(dev, "can_turn_off_hvac", False):
        return seam.thermostats.off(
            device_id=sensi.device_id
        )
    else:
        return {"error": f"Unsupported mode '{mode}' or missing capability"}

@app.route("/adjust-temp", methods=["POST"])
def adjust_temp():
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
        elif temp <= 65:
            resp = set_thermostat("heat", 70)
        else:
            resp = {"status":"no_temp_threshold_met_for_checkin"}
        return {"status": "checkin_adjusted", "detail": resp}

    elif checkout_today and not same_day_turnover:
        if temp >= 75:
            resp = set_thermostat("cool", 77)
        elif temp <= 65:
            resp = set_thermostat("heat", 65)
        else:
            resp = set_thermostat("off", None)
        return {"status": "checkout_adjusted", "detail": resp}

    return {"status": "no_action"}

