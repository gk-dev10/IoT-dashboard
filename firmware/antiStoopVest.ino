/*
  ============================================================
  SMART ANTI-STOOP VEST — FINAL FIRMWARE
  ============================================================
  Course: Embedded Systems & IoT
  Board: ESP32 DevKit

  SENSORS (5 types):
    1. Flex Sensor x2 (Upper + Lower Back)  -> Analog (GPIO34, GPIO35)
    2. MPU6050 IMU (Back)                    -> I2C   (GPIO21 SDA, GPIO22 SCL)
    3. ADXL335 Accelerometer (Thigh/Shank)   -> Analog (GPIO32 X, GPIO33 Y, GPIO36 Z)
    4. DHT11 (Temp/Humidity)                 -> Digital (GPIO4)
    5. MAX3010x Pulse Oximeter (HR + SpO2)   -> I2C   (shares bus with MPU6050)

  ACTUATORS (3 types):
    1. Vibration Motor -> GPIO25 (PWM, via NPN transistor)  [Tier 1]
    2. Buzzer           -> GPIO26 (PWM, via NPN transistor)  [Tier 2]
    3. Status RGB LED    -> GPIO27 (R), GPIO14 (G), GPIO12 (B)

  Calibration Button -> GPIO2 (INPUT_PULLUP)

  NETWORK:
    Wi-Fi -> HTTP POST (JSON) -> Flask server /api/data endpoint

  LIBRARIES REQUIRED (install via Arduino Library Manager):
    - Adafruit MPU6050
    - Adafruit Unified Sensor
    - DHT sensor library (Adafruit)
    - SparkFun MAX3010x Pulse and Proximity Sensor Library
    - ArduinoJson (by Benoit Blanchon)
    - WiFi (built-in for ESP32)
    - HTTPClient (built-in for ESP32)
  ============================================================
*/

#include <Wire.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include <DHT.h>
#include "MAX30105.h"
#include "heartRate.h"

// ---------------- Wi-Fi & Server Config ----------------
const char* WIFI_SSID     = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const char* SERVER_URL    = "http://192.168.1.100:5000/api/data"; // Flask server IP:port

// ---------------- Pin Definitions ----------------
const int FLEX_PIN_UPPER   = 34;   // ADC1_CH6
const int FLEX_PIN_LOWER   = 35;   // ADC1_CH7
const int ADXL_PIN_X       = 32;   // ADC1_CH4
const int ADXL_PIN_Y       = 33;   // ADC1_CH5
const int ADXL_PIN_Z       = 36;   // ADC1_CH0 (VP)
const int DHT_PIN          = 4;
const int CAL_BUTTON_PIN   = 2;

const int MOTOR_PIN        = 25;
const int BUZZER_PIN       = 26;
const int LED_R_PIN        = 27;
const int LED_G_PIN        = 14;
const int LED_B_PIN        = 12;

// ---------------- Sensor Objects ----------------
Adafruit_MPU6050 mpu;
DHT dht(DHT_PIN, DHT11);
MAX30105 pulseOx;

// ---------------- Tunable Parameters ----------------
const int   BEND_THRESHOLD_FLEX   = 60;      // analog units above baseline
const float BEND_THRESHOLD_IMU    = 20.0;    // degrees pitch considered "bent"
const float UPRIGHT_ANGLE_TOL     = 25.0;    // degrees from vertical considered "standing/walking"
const unsigned long HOLD_TIME_VIBRATE_MS = 5000;
const unsigned long HOLD_TIME_BUZZER_MS  = 15000;
const int   MOTOR_PWM  = 200;
const int   BUZZER_PWM = 180;
const unsigned long SENSOR_LOG_INTERVAL_MS = 5000;   // DHT11 + pulse ox log interval
const unsigned long SERVER_PUSH_INTERVAL_MS = 5000;  // how often we POST to Flask

// ---------------- PWM Channels (LEDC) ----------------
const int MOTOR_CH = 0;
const int BUZZER_CH = 1;
const int LED_R_CH  = 2;
const int LED_G_CH  = 3;
const int LED_B_CH  = 4;

// ---------------- State Variables ----------------
int baselineUpper = 0;
int baselineLower = 0;
unsigned long bendStartTime = 0;
bool isBending = false;
bool vibrateOn = false;
bool buzzerOn = false;
unsigned long lastSensorLog = 0;
unsigned long lastServerPush = 0;

// Buffer for heart-rate beat detection
const byte RATE_SIZE = 4;
byte rates[RATE_SIZE];
byte rateSpot = 0;
long lastBeat = 0;
float beatsPerMinute = 0;
int beatAvg = 0;

// Last known sensor readings (for server push)
float g_flexUpper, g_flexLower, g_imuPitch, g_adxlTilt, g_temp, g_hum;
bool g_isStanding = false, g_bendDetected = false, g_vibration = false, g_buzzer = false;
int g_heartRate = 0;

void setup() {
  Serial.begin(115200);
  pinMode(CAL_BUTTON_PIN, INPUT_PULLUP);

  // LEDC PWM setup (ESP32 requires ledcAttach/ledcWrite for PWM, not analogWrite)
  ledcSetup(MOTOR_CH, 5000, 8);
  ledcAttachPin(MOTOR_PIN, MOTOR_CH);
  ledcSetup(BUZZER_CH, 5000, 8);
  ledcAttachPin(BUZZER_PIN, BUZZER_CH);
  ledcSetup(LED_R_CH, 5000, 8);
  ledcAttachPin(LED_R_PIN, LED_R_CH);
  ledcSetup(LED_G_CH, 5000, 8);
  ledcAttachPin(LED_G_PIN, LED_G_CH);
  ledcSetup(LED_B_CH, 5000, 8);
  ledcAttachPin(LED_B_PIN, LED_B_CH);

  Wire.begin(21, 22); // SDA, SCL

  // --- MPU6050 init ---
  if (!mpu.begin()) {
    Serial.println("MPU6050 not found! Check wiring.");
  } else {
    mpu.setAccelerometerRange(MPU6050_RANGE_8_G);
    mpu.setGyroRange(MPU6050_RANGE_500_DEG);
    Serial.println("MPU6050 initialized.");
  }

  // --- DHT init ---
  dht.begin();

  // --- MAX3010x init ---
  if (!pulseOx.begin(Wire, I2C_SPEED_FAST)) {
    Serial.println("MAX3010x not found! Check wiring.");
  } else {
    pulseOx.setup();                    // default settings
    pulseOx.setPulseAmplitudeRed(0x0A);
    pulseOx.setPulseAmplitudeGreen(0);
    Serial.println("MAX3010x initialized.");
  }

  // --- Wi-Fi connect ---
  connectWiFi();

  Serial.println("Smart Anti-Stoop Vest — Final Firmware booting...");
  calibrate();
}

void loop() {
  // ---- Re-calibrate on button press ----
  if (digitalRead(CAL_BUTTON_PIN) == LOW) {
    delay(50);
    if (digitalRead(CAL_BUTTON_PIN) == LOW) {
      calibrate();
      delay(300);
    }
  }

  // ---- Core posture sensors ----
  int rawUpper = analogRead(FLEX_PIN_UPPER);
  int rawLower = analogRead(FLEX_PIN_LOWER);
  int deltaUpper = rawUpper - baselineUpper;
  int deltaLower = rawLower - baselineLower;
  int avgFlexDelta = (deltaUpper + deltaLower) / 2;

  float pitchAngle = getIMUPitch();
  float adxlTilt = getADXLTilt();
  bool isStanding = (adxlTilt < UPRIGHT_ANGLE_TOL); // leg sensor near-vertical = standing/walking

  bool flexSaysBent = (avgFlexDelta > BEND_THRESHOLD_FLEX);
  bool imuSaysBent  = (pitchAngle > BEND_THRESHOLD_IMU);
  bool currentlyBent = flexSaysBent && imuSaysBent && isStanding;

  Serial.print("FlexDelta: "); Serial.print(avgFlexDelta);
  Serial.print(" | IMU Pitch: "); Serial.print(pitchAngle);
  Serial.print(" | ADXL Tilt: "); Serial.print(adxlTilt);
  Serial.print(" (Standing: "); Serial.print(isStanding ? "Y" : "N");
  Serial.print(") | Bent: "); Serial.println(currentlyBent ? "YES" : "no");

  if (currentlyBent) {
    if (!isBending) {
      isBending = true;
      bendStartTime = millis();
    } else {
      unsigned long bentDuration = millis() - bendStartTime;
      if (bentDuration >= HOLD_TIME_VIBRATE_MS) {
        activateVibration();
        setStatusLED(255, 0, 0); // red = alert
      }
      if (bentDuration >= HOLD_TIME_BUZZER_MS) {
        activateBuzzer();
      }
    }
  } else {
    isBending = false;
    deactivateVibration();
    deactivateBuzzer();
    setStatusLED(0, 255, 0); // green = ok
  }

  // ---- Heart rate sampling (must be polled frequently) ----
  updateHeartRate();

  // ---- Slow sensor logging (DHT11) ----
  float temperature = g_temp, humidity = g_hum;
  if (millis() - lastSensorLog > SENSOR_LOG_INTERVAL_MS) {
    temperature = dht.readTemperature();
    humidity = dht.readHumidity();
    lastSensorLog = millis();
  }

  // ---- Store latest state for server push ----
  g_flexUpper = deltaUpper; g_flexLower = deltaLower; g_imuPitch = pitchAngle;
  g_adxlTilt = adxlTilt; g_isStanding = isStanding; g_bendDetected = currentlyBent;
  g_vibration = vibrateOn; g_buzzer = buzzerOn; g_heartRate = beatAvg;
  if (!isnan(temperature)) g_temp = temperature;
  if (!isnan(humidity)) g_hum = humidity;

  // ---- Push to Flask server periodically ----
  if (millis() - lastServerPush > SERVER_PUSH_INTERVAL_MS) {
    pushDataToServer();
    lastServerPush = millis();
  }

  delay(100);
}

// ---------------- Wi-Fi ----------------
void connectWiFi() {
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Connecting to Wi-Fi");
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 30) {
    delay(500);
    Serial.print(".");
    attempts++;
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nWi-Fi connected. IP: " + WiFi.localIP().toString());
  } else {
    Serial.println("\nWi-Fi connection FAILED — continuing offline (local loop still works).");
  }
}

// ---------------- Calibration ----------------
void calibrate() {
  Serial.println("Calibrating... stand up straight NOW.");
  delay(1000);

  long sumUpper = 0, sumLower = 0;
  const int samples = 10;
  for (int i = 0; i < samples; i++) {
    sumUpper += analogRead(FLEX_PIN_UPPER);
    sumLower += analogRead(FLEX_PIN_LOWER);
    delay(50);
  }
  baselineUpper = sumUpper / samples;
  baselineLower = sumLower / samples;

  Serial.print("Baseline set. Upper: "); Serial.print(baselineUpper);
  Serial.print(" Lower: "); Serial.println(baselineLower);

  isBending = false;
  deactivateVibration();
  deactivateBuzzer();
  setStatusLED(0, 255, 0);
}

// ---------------- IMU Pitch (Back) ----------------
float getIMUPitch() {
  sensors_event_t a, g, temp;
  mpu.getEvent(&a, &g, &temp);
  float pitch = atan2(a.acceleration.y,
                       sqrt(a.acceleration.x * a.acceleration.x +
                            a.acceleration.z * a.acceleration.z)) * 180.0 / PI;
  return abs(pitch);
}

// ---------------- ADXL335 Tilt (Thigh/Shank) ----------------
// Returns angle (degrees) of the sensor's primary axis from true vertical.
// Near 0 degrees  = leg vertical = standing/walking.
// Near 90 degrees = leg horizontal = sitting/lying.
float getADXLTilt() {
  int rawX = analogRead(ADXL_PIN_X);
  int rawY = analogRead(ADXL_PIN_Y);
  int rawZ = analogRead(ADXL_PIN_Z);

  // Convert raw ADC (0-4095, 3.3V ref) to approximate g-force
  // ADXL335: 1.65V = 0g, sensitivity ~330mV/g @3.3V supply
  float x_g = ((rawX / 4095.0) * 3.3 - 1.65) / 0.330;
  float y_g = ((rawY / 4095.0) * 3.3 - 1.65) / 0.330;
  float z_g = ((rawZ / 4095.0) * 3.3 - 1.65) / 0.330;

  // Angle of Z-axis (assumed mounted along leg length) from vertical gravity vector
  float tilt = acos(z_g / sqrt(x_g*x_g + y_g*y_g + z_g*z_g)) * 180.0 / PI;
  return tilt;
}

// ---------------- Heart Rate (MAX3010x) ----------------
void updateHeartRate() {
  long irValue = pulseOx.getIR();

  if (checkForBeat(irValue)) {
    long delta = millis() - lastBeat;
    lastBeat = millis();
    beatsPerMinute = 60 / (delta / 1000.0);

    if (beatsPerMinute > 20 && beatsPerMinute < 255) {
      rates[rateSpot++] = (byte)beatsPerMinute;
      rateSpot %= RATE_SIZE;
      int total = 0;
      for (byte i = 0; i < RATE_SIZE; i++) total += rates[i];
      beatAvg = total / RATE_SIZE;
    }
  }
}

// ---------------- Status LED ----------------
void setStatusLED(int r, int g, int b) {
  ledcWrite(LED_R_CH, r);
  ledcWrite(LED_G_CH, g);
  ledcWrite(LED_B_CH, b);
}

// ---------------- Actuator Control ----------------
void activateVibration() {
  if (!vibrateOn) { vibrateOn = true; Serial.println(">>> VIBRATION ON (Tier 1)"); }
  ledcWrite(MOTOR_CH, MOTOR_PWM);
}
void deactivateVibration() {
  if (vibrateOn) { vibrateOn = false; Serial.println(">>> Vibration OFF"); }
  ledcWrite(MOTOR_CH, 0);
}
void activateBuzzer() {
  if (!buzzerOn) { buzzerOn = true; Serial.println(">>> BUZZER ON (Tier 2)"); }
  ledcWrite(BUZZER_CH, BUZZER_PWM);
}
void deactivateBuzzer() {
  if (buzzerOn) { buzzerOn = false; Serial.println(">>> Buzzer OFF"); }
  ledcWrite(BUZZER_CH, 0);
}

// ---------------- Push JSON to Flask Server ----------------
void pushDataToServer() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("Wi-Fi not connected — skipping server push.");
    return;
  }

  HTTPClient http;
  http.begin(SERVER_URL);
  http.addHeader("Content-Type", "application/json");

  StaticJsonDocument<512> doc;
  doc["flex_upper"]       = g_flexUpper;
  doc["flex_lower"]       = g_flexLower;
  doc["imu_pitch_deg"]    = g_imuPitch;
  doc["adxl_tilt_deg"]    = g_adxlTilt;
  doc["is_standing"]      = g_isStanding;
  doc["bend_detected"]    = g_bendDetected;
  doc["vibration_active"] = g_vibration;
  doc["buzzer_active"]    = g_buzzer;
  doc["temperature_c"]    = g_temp;
  doc["humidity_pct"]     = g_hum;
  doc["heart_rate_bpm"]   = g_heartRate;

  String payload;
  serializeJson(doc, payload);

  int httpCode = http.POST(payload);
  Serial.print("POST /api/data -> HTTP "); Serial.println(httpCode);
  http.end();
}