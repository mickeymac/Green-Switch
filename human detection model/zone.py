import cv2
import requests
from ultralytics import YOLO
import time

ESP32_IP = "10.148.248.88"   # Replace with ESP32 IP shown in Serial Monitor jaimin's ("10.148.248.88") and UNIQUE(192.168.1.8) 
MODEL_NAME = "yolov8s.pt"

model = YOLO(MODEL_NAME)
cap = cv2.VideoCapture(0)

last_zone_state = {1: False, 2: False}

def test_esp32_connection():
    """Test if ESP32 is reachable before starting the main loop"""
    url = f"http://{ESP32_IP}/test"
    print(f"🔍 Testing connection to ESP32 at {ESP32_IP}...")
    try:
        response = requests.get(url, timeout=3)
        print("✅ ESP32 is reachable!")
        return True
    except requests.exceptions.Timeout:
        print("⏰ ESP32 connection timeout - device may be slow to respond")
        return False
    except requests.exceptions.ConnectionError:
        print("🔌 ESP32 connection failed - check IP address and network")
        return False
    except Exception as e:
        print(f"⚠️ ESP32 test failed: {str(e)}")
        return False

def send_command(zone, state):
    url = f"http://{ESP32_IP}/light?zone={zone}&state={state}"
    max_retries = 2
    
    for attempt in range(max_retries):
        try:
            response = requests.get(url, timeout=5)  # Increased timeout to 5 seconds
            if response.status_code == 200:
                print(f"✅ Zone {zone} -> {state}")
                return True
            else:
                print(f"⚠️ Zone {zone} -> {state} (HTTP {response.status_code})")
        except requests.exceptions.Timeout:
            if attempt == max_retries - 1:
                print(f"⏰ Zone {zone} -> {state} (Timeout after {max_retries} attempts)")
            else:
                print(f"⏰ Zone {zone} -> {state} (Timeout, retrying...)")
                time.sleep(0.5)  # Brief delay before retry
        except requests.exceptions.ConnectionError:
            print(f"🔌 Zone {zone} -> {state} (Connection Error - Check ESP32 IP/Network)")
            break  # Don't retry connection errors
        except Exception as e:
            print(f"❌ Zone {zone} -> {state} (Error: {str(e)})")
            break
    
    return False

# Test ESP32 connection before starting
if not test_esp32_connection():
    print("⚠️ Warning: ESP32 may not be reachable, but continuing anyway...")
    print("💡 Make sure:")
    print("   1. ESP32 is powered on and connected to WiFi")
    print("   2. IP address is correct in the code")
    print("   3. Both devices are on the same network")
    print("   4. No firewall is blocking the connection")
    input("Press Enter to continue or Ctrl+C to exit...")

while True:
    ret, frame = cap.read()
    if not ret:
        break

    (h, w) = frame.shape[:2]
    mid_x = w // 2

    zones = {
        1: (0, 0, mid_x, h),     # Left Half
        2: (mid_x, 0, w, h)      # Right Half
    }

    current_zone_state = {1: False, 2: False}

    results = model(frame, classes=0, verbose=False)
    for r in results:
        for box in r.boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            person_x = (x1 + x2) // 2
            person_y = y2

            for zone_id, (zx1, zy1, zx2, zy2) in zones.items():
                if zx1 < person_x < zx2 and zy1 < person_y < zy2:
                    current_zone_state[zone_id] = True

            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(frame, "Person", (x1, y1-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,0), 2)

    for zone_id, (zx1, zy1, zx2, zy2) in zones.items():
        if current_zone_state[zone_id] != last_zone_state[zone_id]:
            send_command(zone_id, "ON" if current_zone_state[zone_id] else "OFF")

        cv2.rectangle(frame, (zx1, zy1), (zx2, zy2), (255,255,0), 2)
        if current_zone_state[zone_id]:
            overlay = frame.copy()
            cv2.rectangle(overlay, (zx1, zy1), (zx2, zy2), (0,255,0), -1)
            frame = cv2.addWeighted(overlay, 0.3, frame, 0.7, 0)
            cv2.putText(frame, f"ZONE {zone_id} ACTIVE", (zx1+10, zy1+30), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255,255,255), 2)

    last_zone_state = current_zone_state.copy()

    cv2.imshow("YOLO Human Tracker", frame)
    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

print("Turning OFF all lights...")
for z in range(1, 3):
    send_command(z, "OFF")

cap.release()
cv2.destroyAllWindows()
