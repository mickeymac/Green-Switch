
// editing with copilot and zaid acs712 calibirated code..

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <DHT.h>
#include <EEPROM.h>

// ===== WiFi Config =====
const char* ssid = "ONEPLUS JP";
const char* password = "11111111";
const char* serverUrl = "http://10.148.248.235:5000/api/data";   // Replace with your computer's IP

#define PIR_PIN 5
#define DHTPIN 4
#define DHTTYPE DHT11
#define RELAY1_PIN 14   // Zone 1 Light
#define RELAY2_PIN 27   // Zone 2 Light
#define ACS1_PIN 34     // ACS712 OUT for Light 1
#define ACS2_PIN 35     // ACS712 OUT for Light 2

// ===== Enhanced ACS712-15A Calibration System =====
#define EEPROM_SIZE 64
#define EEPROM_ADDR_ACS1 0
#define EEPROM_ADDR_ACS2 4
#define EEPROM_ADDR_VALID 8
#define EEPROM_MAGIC 0xAC15  // ACS712-15A magic number

class ACS712Calibrator {
private:
  float acs1_zero = 1.65;  // Default zero point for 3.3V system
  float acs2_zero = 1.65;  // Default zero point for 3.3V system
  bool is_calibrated = false;
  
  // ACS712-15A specifications
  const float ACS_SENSITIVITY = 0.133;  // 133mV/A for 15A model
  const float ACS_REFERENCE_V = 1.65;   // 3.3V/2 zero point
  const float ACS_DEADBAND = 0.05;     // 50mA noise threshold
  
public:
  void init() {
    EEPROM.begin(EEPROM_SIZE);
    loadCalibrationFromEEPROM();
    
    if (!is_calibrated) {
      Serial.println("🔧 No valid calibration found, starting auto-calibration...");
      performCalibration();
    } else {
      Serial.println("✅ Loaded calibration from EEPROM");
      Serial.printf("   ACS1 Zero: %.4fV, ACS2 Zero: %.4fV\n", acs1_zero, acs2_zero);
    }
  }
  
  void performCalibration() {
    Serial.println("🚨 ENSURE NO LOADS ARE CONNECTED TO RELAYS!");
    Serial.println("🔧 Starting ACS712-15A calibration...");
    delay(2000);  // Give time to read warning
    
    // Take multiple samples for accurate zero point
    const int samples = 150;
    long total1 = 0, total2 = 0;
    
    Serial.print("📊 Taking samples");
    for (int i = 0; i < samples; i++) {
      total1 += analogRead(ACS1_PIN);
      total2 += analogRead(ACS2_PIN);
      if (i % 30 == 0) Serial.print(".");
      delay(10);
    }
    Serial.println();
    
    // Calculate average ADC values and convert to voltage
    float avg1 = total1 / (float)samples;
    float avg2 = total2 / (float)samples;
    acs1_zero = (avg1 / 4095.0) * 3.3;  // ESP32 ADC: 0-4095 = 0-3.3V
    acs2_zero = (avg2 / 4095.0) * 3.3;
    
    // Validation: zero points should be close to 1.65V
    if (abs(acs1_zero - ACS_REFERENCE_V) > 0.3 || abs(acs2_zero - ACS_REFERENCE_V) > 0.3) {
      Serial.println("⚠️  Warning: Zero points seem unusual, using defaults");
      acs1_zero = ACS_REFERENCE_V;
      acs2_zero = ACS_REFERENCE_V;
    }
    
    is_calibrated = true;
    saveCalibrationToEEPROM();
    
    Serial.println("✅ ACS712-15A Calibration Complete!");
    Serial.printf("   Sensor 1 Zero Point: %.4fV\n", acs1_zero);
    Serial.printf("   Sensor 2 Zero Point: %.4fV\n", acs2_zero);
    Serial.printf("   Sensitivity: %.3fV/A (15A model)\n", ACS_SENSITIVITY);
  }
  
  float readCalibratedCurrent1() {
    return readCurrentFromPin(ACS1_PIN, acs1_zero);
  }
  
  float readCalibratedCurrent2() {
    return readCurrentFromPin(ACS2_PIN, acs2_zero);
  }
  
  void recalibrate() {
    Serial.println("🔄 Recalibrating sensors...");
    performCalibration();
  }
  
  bool isCalibrated() {
    return is_calibrated;
  }

private:
  float readCurrentFromPin(int pin, float zero_voltage) {
    // Take multiple samples for noise reduction
    const int samples = 50;
    long total = 0;
    
    for (int i = 0; i < samples; i++) {
      total += analogRead(pin);
      delayMicroseconds(800);
    }
    
    float avg_adc = total / (float)samples;
    float voltage = (avg_adc / 4095.0) * 3.3;
    float current = (voltage - zero_voltage) / ACS_SENSITIVITY;
    
    // Apply deadband to eliminate noise
    if (fabs(current) < ACS_DEADBAND) {
      current = 0.0;
    }
    
    // Ensure no negative current (physically impossible for power consumption)
    return max(0.0f, current);
  }
  
  void saveCalibrationToEEPROM() {
    EEPROM.put(EEPROM_ADDR_ACS1, acs1_zero);
    EEPROM.put(EEPROM_ADDR_ACS2, acs2_zero);
    EEPROM.put(EEPROM_ADDR_VALID, EEPROM_MAGIC);
    EEPROM.commit();
    Serial.println("💾 Calibration saved to EEPROM");
  }
  
  void loadCalibrationFromEEPROM() {
    uint16_t magic;
    EEPROM.get(EEPROM_ADDR_VALID, magic);
    
    if (magic == EEPROM_MAGIC) {
      EEPROM.get(EEPROM_ADDR_ACS1, acs1_zero);
      EEPROM.get(EEPROM_ADDR_ACS2, acs2_zero);
      is_calibrated = true;
    }
  }
};

// Global calibrator instance
ACS712Calibrator currentSensors;

// ===== Motion Timer Config =====
#define MOTION_TIMEOUT 5000  // 5 seconds timeout for single motion
unsigned long lastMotionTime = 0;
bool motionActive = false;
bool zone1_occupied = false;  // Track if camera detected someone in zone 1
bool zone2_occupied = false;  // Track if camera detected someone in zone 2
bool lastMotionState = false; // Track previous motion state

// ===== Light Duration Tracking =====
unsigned long light1OnTime = 0;  // When light 1 turned ON
unsigned long light2OnTime = 0;  // When light 2 turned ON
bool light1WasOn = false;  // Track previous state
bool light2WasOn = false;  // Track previous state

// ===== Data Sending Interval =====
unsigned long lastSendTime = 0;
const unsigned long SEND_INTERVAL = 5000;  // Send data every 5 seconds

// ===== Objects =====
DHT dht(DHTPIN, DHTTYPE);
WiFiServer server(80);

void setup() {
  Serial.begin(115200);

  pinMode(PIR_PIN, INPUT);
  pinMode(RELAY1_PIN, OUTPUT);
  pinMode(RELAY2_PIN, OUTPUT);

  dht.begin();

  // Default OFF (active LOW relays)
  digitalWrite(RELAY1_PIN, HIGH);
  digitalWrite(RELAY2_PIN, HIGH);

  WiFi.begin(ssid, password);
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\n✅ Connected to WiFi!");
  Serial.print("📡 ESP32 IP: ");
  Serial.println(WiFi.localIP());

  server.begin();

  // ===== Initialize Enhanced ACS712-15A Calibration =====
  Serial.println("🔧 Initializing ACS712-15A Current Sensors...");
  currentSensors.init();
  Serial.println("⚡ Current sensors ready!");
}

void updateLightTimers(bool relay1_state, bool relay2_state) {
    bool light1IsOn = !relay1_state;  // Invert because active LOW
    bool light2IsOn = !relay2_state;
    unsigned long currentTime = millis();

    // Light 1 state change
    if (light1IsOn && !light1WasOn) {
        light1OnTime = currentTime;  // Light just turned ON
    }
    light1WasOn = light1IsOn;

    // Light 2 state change
    if (light2IsOn && !light2WasOn) {
        light2OnTime = currentTime;  // Light just turned ON
    }
    light2WasOn = light2IsOn;
}

void sendSensorData(float temp, float humidity, int motion, bool relay1_state, bool relay2_state, float current1, float current2) {
  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    http.begin(serverUrl);
    http.addHeader("Content-Type", "application/json");

    // Calculate light ON duration in minutes
    unsigned long currentTime = millis();
    unsigned long light1Duration = !relay1_state ? (currentTime - light1OnTime) / 60000 : 0;
    unsigned long light2Duration = !relay2_state ? (currentTime - light2OnTime) / 60000 : 0;

  StaticJsonDocument<400> doc;
  doc["temperature"] = temp;
  doc["humidity"] = humidity;
  // Ensure 'motion' is set ONLY by the physical PIR sensor, not by relay or occupancy logic
  doc["motion"] = motion == HIGH;  // Only PIR motion state
  doc["relay1"] = !relay1_state;   // Invert because relays are active LOW
  doc["relay2"] = !relay2_state;   // Invert because relays are active LOW
  doc["light1_duration"] = light1Duration;  // Duration in minutes
  doc["light2_duration"] = light2Duration;  // Duration in minutes
  doc["current1"] = current1;
  doc["current2"] = current2;
  doc["current_total"] = current1 + current2;

    String jsonString;
    serializeJson(doc, jsonString);

    int httpResponseCode = http.POST(jsonString);

    if (httpResponseCode > 0) {
      String response = http.getString();
      Serial.println("\U0001F4E4 Data sent successfully");
    } else {
      Serial.print("❌ Error sending data: ");
      Serial.println(httpResponseCode);
    }

    http.end();
  }
}

void handleMotionLighting() {
  // Only handle PIR motion if no human is detected by camera in Zone 1
  if (!zone1_occupied) {
    int motion = digitalRead(PIR_PIN);
    unsigned long currentTime = millis();

    // New motion detected (transition from no motion to motion)
    if (motion == HIGH && !lastMotionState) {
      Serial.println("💡 New PIR Motion detected → Zone 1 Light ON");
      motionActive = true;
      lastMotionTime = currentTime;
      digitalWrite(RELAY1_PIN, LOW);  // Turn ON light
    }
    
    // If light is on, check for timeout
    if (motionActive && (currentTime - lastMotionTime >= MOTION_TIMEOUT)) {
      digitalWrite(RELAY1_PIN, HIGH);  // Turn OFF light
      Serial.println("💡 Motion timeout → Zone 1 Light OFF");
      motionActive = false;
    }

    lastMotionState = (motion == HIGH);  // Update last motion state
  }
}

void loop() {
  // ===== Sensor Data =====
  float h = dht.readHumidity();
  float t = dht.readTemperature();
  int motion = digitalRead(PIR_PIN);
  bool relay1_state = digitalRead(RELAY1_PIN);
  bool relay2_state = digitalRead(RELAY2_PIN);

  // Read current sensors with enhanced calibration
  float current1 = currentSensors.readCalibratedCurrent1();
  float current2 = currentSensors.readCalibratedCurrent2();

  // Only handle PIR motion if no human is detected by camera in Zone 1
  if (!zone1_occupied) {
    handleMotionLighting();
  }

  // Update light timers
  updateLightTimers(relay1_state, relay2_state);

  // Print debug info
  Serial.printf("Temp: %.2f°C, Humidity: %.2f%%, Motion: %d\n", t, h, motion);
  Serial.printf("Zone1: %s, Zone2: %s\n", 
                !relay1_state ? "ON" : "OFF",
                !relay2_state ? "ON" : "OFF");
  Serial.printf("Current1: %.3f A, Current2: %.3f A, Total: %.3f A\n", current1, current2, current1 + current2);

  // Send sensor data every 5 seconds
  unsigned long currentTime = millis();
  if (currentTime - lastSendTime >= SEND_INTERVAL) {
    sendSensorData(t, h, motion, relay1_state, relay2_state, current1, current2);
    lastSendTime = currentTime;
  }

  // ===== Handle Web Requests (Zone occupancy from camera or manual control) =====
  WiFiClient client = server.available();
  if (client) {
    String req = client.readStringUntil('\r');
    client.flush();

    if (req.indexOf("/light?zone=") > 0) {
      int z_start = req.indexOf("zone=") + 5;
      int z_end = req.indexOf("&", z_start);
      int zone = req.substring(z_start, z_end).toInt();

      int s_start = req.indexOf("state=") + 6;
      int s_end = req.indexOf(" ", s_start);
      String state = req.substring(s_start, s_end);

      // Handle camera detection or manual control for each zone separately
      if (zone == 1) {
        zone1_occupied = (state == "ON");
        digitalWrite(RELAY1_PIN, (state == "ON") ? LOW : HIGH);
        Serial.printf("\U0001F465 Zone 1: %s - Light %s\n", 
                     zone1_occupied ? "Occupied" : "Empty",
                     zone1_occupied ? "ON" : "OFF");
      }
      else if (zone == 2) {
        zone2_occupied = (state == "ON");
        digitalWrite(RELAY2_PIN, (state == "ON") ? LOW : HIGH);
        Serial.printf("\U0001F465 Zone 2: %s - Light %s\n", 
                     zone2_occupied ? "Occupied" : "Empty",
                     zone2_occupied ? "ON" : "OFF");
      }
    }
    
    // ===== Calibration Web Endpoint =====
    else if (req.indexOf("/calibrate") > 0) {
      Serial.println("🌐 Web calibration request received");
      currentSensors.recalibrate();
      
      client.println("HTTP/1.1 200 OK");
      client.println("Content-Type: application/json");
      client.println("Connection: close");
      client.println();
      client.println("{\"status\":\"success\",\"message\":\"ACS712-15A sensors recalibrated\"}");
      client.stop();
      return;
    }

    client.println("HTTP/1.1 200 OK");
    client.println("Content-Type: text/plain");
    client.println("Connection: close");
    client.println();
    client.println("Command Received");
    client.stop();
  }

  delay(100);  // Quick loop for responsive motion detection
}







