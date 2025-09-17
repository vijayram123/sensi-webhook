from flask import Flask, request
import gspread, seamapi, requests, os
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

app = Flask(__name__)
seam = seamapi.Client(api_key=os.getenv("SEAM_API_KEY"))

def get_outdoor_temp(zip="28348"):
    r = requests.get(
        f"https://api.openweathermap.org/data/2.5/weather?zip={zip},us&units=imperial&appid={os.getenv('WEATHER_API_KEY')}"
    )
    return r.json()["main"]["temp"]

def set_thermostat(mode, temp):
    devices = seam.devices.list()
    sensi = next(d for d in devices if d["device_type"] == "sensi_thermostat")
    seam.thermostats.set_temperature(
        device_id=sensi["device_id"],
        temperature_fahrenheit=temp,
        heating_enabled=(mode == "heat"),
        cooling_enabled=(mode == "cool")
    )

@app.route("/adjust-temp", methods=["POST"])
def adjust_temp():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
    client = gspread.authorize(creds)
    sheet = client.open("casahanoverbookingssheet").sheet1

    today = datetime.today().date()
    rows = sheet.get_all_records()

    # Filter only accepted reservations
    accepted_rows = [r for r in rows if r.get("Status", "").strip().lower() == "accepted"]

    checkin_today = any(
        datetime.strptime(r["Check-in"], "%Y-%m-%d").date() == today
        for r in accepted_rows
    )
    checkout_today = any(
        datetime.strptime(r["Check-out"], "%Y-%m-%d").date() == today
        for r in accepted_rows
    )
    same_day_turnover = checkin_today and checkout_today

    temp = get_outdoor_temp()

    if checkin_today:
        if temp >= 75:
            set_thermostat("cool", 73)
        elif temp <= 65:
            set_thermostat("heat", 70)
        return {"status": "checkin_adjusted"}

    elif checkout_today and not same_day_turnover:
        if temp >= 75:
            set_thermostat("cool", 77)
        elif temp <= 65:
            set_thermostat("heat", 65)
        return {"status": "checkout_adjusted"}

    return {"status": "no_action"}