from flask import Flask, render_template, jsonify, request, Response
import random
import time
import json
import os
import csv
import shutil
from datetime import datetime

app = Flask(__name__)

# --- CONFIGURATION ---
DB_FILE = "data.json"
last_log_time = time.time()
last_light_time = time.time()
current_light_phase = "A_GREEN" # Phases: A_GREEN, YELLOW_TO_B, B_GREEN, YELLOW_TO_A

# --- HELPER FUNCTIONS (File Storage) ---
def read_db():
    """Read the JSON database file. Create if missing."""
    if not os.path.exists(DB_FILE):
        with open(DB_FILE, "w") as f:
            json.dump({"records": []}, f)
        return {"records": []}
        
    try:
        with open(DB_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {"records": []}

def write_db(data):
    """Write data to the JSON database file."""
    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=4)

# --- GLOBAL SYSTEM STATE (In-Memory for Real-time Control) ---
system_state = {
    "mode": "AUTO",  # AUTO, MANUAL, EMERGENCY, VIP_CLEARANCE
    "total_carbon_saved_tons": 0.00,
    "junctions": {
        "A": {"green": True, "timer": 60},
        "B": {"green": False, "timer": 60}
    },
    "emergency_active": False,
    "vip_route_active": False,
    "road_status": {
        "Road 1": "Normal",
        "Road 2": "Normal",
        "Road 3": "Normal",
        "Road 4": "Normal"
    },
    "lanes": {
        "Lane 1": "Open",
        "Lane 2": "Open"
    },
    "settings": {
        "congestion_threshold": 45,
        "green_light_duration": 60,
        "yellow_light_duration": 5,
        "admin_zone": "Hospital Area",
        "data_logging": True,
        "weather": "Sunny",  # Sunny, Rainy, Foggy
        "simulation_factor": 1.0, # 1.0=Normal, 2.0=Rush Hour, 0.2=Empty
        "night_mode_schedule": False,
        "ai_confidence_level": 95,
        "speed_limit": 80
    }
}

@app.route('/')
def index():
    """Serve the Dashboard UI."""
    return render_template('index.html')

# --- REAL-TIME SIMULATION & POLling ENDPOINT ---
@app.route('/traffic-data')
def traffic_data():
    global last_log_time, last_light_time, current_light_phase
    db = read_db()
    
    # Get the latest record for Road 1 from the database
    latest_record = {
        "density": 0,
        "vehicles": 0,
        "pollution": 0,
        "noise": 0,
        "id": 0 # Track ID to know when data changes
    }
    
    if db["records"]:
        last_entry = db["records"][-1]
        latest_record = {
            "density": last_entry.get("density", 0),
            "vehicles": last_entry.get("vehicles", 0),
            "pollution": last_entry.get("pollution", 0),
            "noise": last_entry.get("noise", 0),
            "id": last_entry.get("id", 0)
        }

    # For other roads, we return static/zero data for now 
    # since data.json mostly tracks Road 1.
    def generate_static_road_data(road_name):
        return {"density": 0, "vehicles": 0, "pollution": 0, "noise": 0}

    # Derive extra metrics for the frontend Dashboard
    speed_limit = system_state["settings"].get("speed_limit", 80)
    weather = system_state["settings"].get("weather", "Sunny")
    
    avg_speed = speed_limit # Default speed is speed limit
    
    # Weather Impact Engine on Speed
    if weather == "Rainy":
        avg_speed = min(speed_limit * 0.8, avg_speed)
    elif weather == "Foggy":
        avg_speed = min(speed_limit * 0.7, avg_speed)

    if latest_record["density"] > 70:
        avg_speed = min(15, speed_limit)
    elif latest_record["density"] > 40:
        avg_speed = min(35, speed_limit)
        
    ped_count = max(0, latest_record["density"] // 3) # Simple correlation
    
    # Real-Time Carbon Tracking Calculation
    # If the system is efficiently moving traffic (green light active for a while during congestion), we save carbon
    now = time.time()
    elapsed = now - last_light_time
    if system_state["mode"] == "AUTO" and not system_state["emergency_active"]:
        if current_light_phase in ["A_GREEN", "B_GREEN"] and latest_record["density"] > 40 and elapsed > 20:
            # Increment carbon savings on every polled second of efficient flow
            system_state["total_carbon_saved_tons"] += 0.002

    # Scenario Action Deployments (Simulated Physical Feedback)
    if system_state["emergency_active"]:
        # Vehicles pull over for emergency
        avg_speed = 0
        latest_record["density"] = max(0, latest_record["density"] - 15)
    elif system_state["vip_route_active"]:
        # Path is cleared, speed is maximized
        avg_speed = min(speed_limit, avg_speed + 20)
        latest_record["density"] = max(0, latest_record["density"] - 25)

    avg_speed = int(avg_speed)

    data = {
        "Road 1": latest_record,
        "Road 2": generate_static_road_data("Road 2"),
        "Road 3": generate_static_road_data("Road 3"),
        "Road 4": generate_static_road_data("Road 4"),
        "system": system_state,
        "metrics": {
            "average_speed": avg_speed,
            "pedestrian_count": ped_count,
            "carbon_saved": round(system_state["total_carbon_saved_tons"], 2)
        }
    }

    # Auto-generation of simulated data if logging is enabled
    if system_state["settings"]["data_logging"] and (time.time() - last_log_time > 5):
        last_log_time = time.time()
        try:
            factor = system_state["settings"].get("simulation_factor", 1.0)
            weather = system_state["settings"].get("weather", "Sunny")
            ai_conf = system_state["settings"].get("ai_confidence_level", 95)
            
            # AI confidence modifies the auto-gen density slightly
            ai_modifier = 1.0 + ((100 - ai_conf) / 100.0)

            weather_penalty = 1.0
            density_floor = 10
            if weather == "Rainy":
                weather_penalty = 1.3
                density_floor = 30 # Artificial baseline floor rises
            elif weather == "Foggy":
                weather_penalty = 1.15
            
            base_density = random.randint(density_floor, 80)
            
            if system_state["emergency_active"]:
                final_density = random.randint(5, 20)
            elif system_state["vip_route_active"]:
                final_density = random.randint(0, 15)
            else:
                final_density = min(100, int(base_density * factor * weather_penalty * ai_modifier))
            
            new_id = 1
            if db["records"]:
                new_id = db["records"][-1]["id"] + 1

            record = {
                "id": new_id,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "road": "Road 1",
                "density": final_density,
                "vehicles": max(0, final_density // 2),
                "pollution": final_density * 2 + random.randint(0, 50),
                "noise": 50 + (final_density // 2) + random.randint(0, 20)
            }
            db["records"].append(record)
            write_db(db)
            
            # Make sure we return this new record instantly
            data["Road 1"] = record
        except Exception as e:
            print("Auto-gen error:", e)

    # 3. Auto-logic simulation (Timer Logic)
    now = time.time()
    elapsed = now - last_light_time
    g_dur = system_state["settings"].get("green_light_duration", 60)
    y_dur = system_state["settings"].get("yellow_light_duration", 5)

    if system_state["settings"].get("night_mode_schedule", False):
        # Override: flashing yellows (simulate by turning off green)
        system_state["junctions"]["A"]["green"] = False
        system_state["junctions"]["B"]["green"] = False
        system_state["junctions"]["A"]["timer"] = 0
        system_state["junctions"]["B"]["timer"] = 0
    elif system_state["mode"] == "AUTO" and not system_state["emergency_active"] and not system_state["vip_route_active"]:
        if current_light_phase == "A_GREEN":
            system_state["junctions"]["A"]["green"] = True
            system_state["junctions"]["B"]["green"] = False
            system_state["junctions"]["A"]["timer"] = max(0, int(g_dur - elapsed))
            system_state["junctions"]["B"]["timer"] = max(0, int(g_dur - elapsed))
            if elapsed >= g_dur:
                current_light_phase = "YELLOW_TO_B"
                last_light_time = now
        elif current_light_phase == "YELLOW_TO_B":
            system_state["junctions"]["A"]["green"] = False
            system_state["junctions"]["B"]["green"] = False
            system_state["junctions"]["A"]["timer"] = max(0, int(y_dur - elapsed))
            system_state["junctions"]["B"]["timer"] = max(0, int(y_dur - elapsed))
            if elapsed >= y_dur:
                current_light_phase = "B_GREEN"
                last_light_time = now
        elif current_light_phase == "B_GREEN":
            system_state["junctions"]["A"]["green"] = False
            system_state["junctions"]["B"]["green"] = True
            system_state["junctions"]["A"]["timer"] = max(0, int(g_dur - elapsed))
            system_state["junctions"]["B"]["timer"] = max(0, int(g_dur - elapsed))
            if elapsed >= g_dur:
                current_light_phase = "YELLOW_TO_A"
                last_light_time = now
        elif current_light_phase == "YELLOW_TO_A":
            system_state["junctions"]["A"]["green"] = False
            system_state["junctions"]["B"]["green"] = False
            system_state["junctions"]["A"]["timer"] = max(0, int(y_dur - elapsed))
            system_state["junctions"]["B"]["timer"] = max(0, int(y_dur - elapsed))
            if elapsed >= y_dur:
                current_light_phase = "A_GREEN"
                last_light_time = now

    return jsonify(data)

# --- CONTROL APIs (State Management) ---
@app.route('/api/set-mode', methods=['POST'])
def set_mode():
    try:
        req = request.json
        new_mode = req.get('mode', 'AUTO')
        if new_mode == "EMERGENCY":
            system_state["mode"] = "EMERGENCY"
            system_state["emergency_active"] = True
            system_state["vip_route_active"] = False
            system_state["junctions"]["A"]["green"] = True
            system_state["junctions"]["B"]["green"] = False
        elif new_mode == "VIP_CLEARANCE":
            system_state["mode"] = "VIP_CLEARANCE"
            system_state["emergency_active"] = False
            system_state["vip_route_active"] = True
            # VIP clearance opens all main arteries
            system_state["junctions"]["A"]["green"] = True
            system_state["junctions"]["B"]["green"] = True
        else:
            system_state["mode"] = new_mode
            system_state["emergency_active"] = False
            system_state["vip_route_active"] = False
        return jsonify({"status": "success", "mode": system_state["mode"]})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/set-lane-status', methods=['POST'])
def set_lane_status():
    try:
        req = request.json
        lane = req.get('lane')
        status = req.get('status')
        if lane in system_state["lanes"]:
            system_state["lanes"][lane] = status
            return jsonify({"status": "success", "lane": lane, "state": status})
        return jsonify({"status": "error", "message": "Invalid Lane"}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/set-road-status', methods=['POST'])
def set_road_status():
    try:
        req = request.json
        road = req.get('road')
        status = req.get('status')
        if road in system_state["road_status"]:
            system_state["road_status"][road] = status
            return jsonify({"status": "success", "road": road, "state": status})
        return jsonify({"status": "error", "message": "Invalid Road"}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/control-light', methods=['POST'])
def control_light():
    if system_state["mode"] != "MANUAL":
        return jsonify({"status": "error", "message": "Switch to MANUAL mode first."}), 403
    try:
        req = request.json
        junction = req.get('junction')
        if junction in system_state["junctions"]:
            system_state["junctions"][junction]["green"] = not system_state["junctions"][junction]["green"]
            return jsonify({"status": "success", "state": system_state["junctions"][junction]})
        return jsonify({"status": "error", "message": "Invalid Junction"}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# --- SETTINGS & DATA MANAGEMENT APIs ---

@app.route('/api/update-settings', methods=['POST'])
def update_settings():
    try:
        req = request.json
        # Update only existing keys to be safe
        for key in req:
            if key in system_state["settings"]:
                val = req[key]
                # Convert to int if it looks like a number, unless boolean
                if isinstance(val, str) and val.isdigit():
                    val = int(val)
                system_state["settings"][key] = val
        return jsonify({"status": "success", "settings": system_state["settings"]})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/clear-data', methods=['POST'])
def clear_data():
    try:
        empty_db = {"records": []}
        write_db(empty_db)
        return jsonify({"status": "success", "message": "Database cleared."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/backup-data', methods=['POST'])
def backup_data():
    try:
        if os.path.exists(DB_FILE):
            shutil.copy(DB_FILE, "data_backup.json")
            return jsonify({"status": "success", "message": "Database backed up successfully."})
        return jsonify({"status": "error", "message": "No database to backup."}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/restore-data', methods=['POST'])
def restore_data():
    try:
        if os.path.exists("data_backup.json"):
            shutil.copy("data_backup.json", DB_FILE)
            return jsonify({"status": "success", "message": "Database restored successfully."})
        return jsonify({"status": "error", "message": "No backup found to restore."}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# --- DATA EXPORT & IOT APIs ---

# CSV EXPORT (STEP C)
@app.route('/export-csv')
def export_csv():
    db = read_db()
    
    def generate():
        yield "id,timestamp,road,density,vehicles,pollution,noise\n"
        for r in db["records"]:
            yield f'{r["id"]},{r["timestamp"]},{r["road"]},{r["density"]},{r["vehicles"]},{r["pollution"]},{r["noise"]}\n'

    return Response(generate(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment;filename=traffic_data.csv"})

# ESP32 INTEGRATION (STEP D)
@app.route('/esp32-data', methods=['POST'])
def esp32_data():
    try:
        db = read_db()
        payload = request.json

        new_id = 1
        if db["records"]:
            new_id = db["records"][-1]["id"] + 1

        record = {
            "id": new_id,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "road": payload.get("road", "Unknown"),
            "density": payload.get("density", 0),
            "vehicles": payload.get("vehicles", 0),
            "pollution": payload.get("pollution", 0),
            "noise": payload.get("noise", 0)
        }

        db["records"].append(record)
        write_db(db)

        return jsonify({"status": "Data received", "id": new_id}), 201
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# --- CRUD APIs (Manual) ---

@app.route('/add-data', methods=['POST'])
def add_data():
    try:
        db = read_db()
        payload = request.json
        new_id = 1
        if db["records"]:
            new_id = db["records"][-1]["id"] + 1
        record = {
            "id": new_id,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "road": payload.get("road", "Unknown"),
            "density": payload.get("density", 0),
            "vehicles": payload.get("vehicles", 0),
            "pollution": payload.get("pollution", 0),
            "noise": payload.get("noise", 0)
        }
        db["records"].append(record)
        write_db(db)
        return jsonify({"message": "Data saved successfully", "record": record}), 201
    except Exception as e:
         return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/get-data')
def get_data():
    db = read_db()
    # Return last 100 for performance if list is huge
    return jsonify(db["records"])

@app.route('/update-data/<int:record_id>', methods=['PUT'])
def update_data(record_id):
    db = read_db()
    payload = request.json
    for r in db["records"]:
        if r["id"] == record_id:
            r.update(payload)
            r["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            write_db(db)
            return jsonify({"message": "Record updated successfully", "record": r})
    return jsonify({"error": "Record not found"}), 404

@app.route('/delete-data/<int:record_id>', methods=['DELETE'])
def delete_data(record_id):
    db = read_db()
    original_count = len(db["records"])
    db["records"] = [r for r in db["records"] if r["id"] != record_id]
    if len(db["records"]) < original_count:
        write_db(db)
        return jsonify({"message": "Record deleted successfully"})
    return jsonify({"error": "Record not found"}), 404

if __name__ == '__main__':
    app.run(debug=True, port=5000)
