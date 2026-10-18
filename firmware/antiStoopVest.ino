/*
  ============================================================
  POSTURE T-SHIRT — MAIN FIRMWARE v1.0.0
  ESP32, Arduino core 3.x, ArduinoJson 6.x
  ============================================================

  PIN CONNECTIONS
    I2C bus (MPU6050, ADXL345, MAX30102) : SDA = GPIO21, SCL = GPIO22, 3V3, GND
    Flex sensors (voltage dividers)      : upper = GPIO34, lower = GPIO35  (USE_FLEX)
    DHT11 data                           : GPIO4
    Calibration / mute button            : GPIO16 to GND (internal pull-up)
    Vibration motor (via NPN transistor) : GPIO25
    Buzzer, ACTIVE (via NPN transistor)  : GPIO26
    LED red / yellow / green (+resistor) : GPIO27 / GPIO14 / GPIO13

  BOARD ORIENTATION
    MPU6050: flat on the upper back, chip side facing outward,
             Y arrow up toward the head, X arrow toward the wearer's right.
    ADXL345: strapped on the thigh. Any orientation works, because the
             standing pose is captured during calibration.

  BEHAVIOUR
    - After boot the vest is NOT armed. The yellow LED blinks slowly.
      Stand tall and press the button (or send the 'calibrate' command
      from the website). Keep still for about 2 s; all LEDs blink fast.
    - Confirmed bend = MPU pitch >= bend-on angle AND standing
      (AND flex agrees, when USE_FLEX is true).
    - Bend for 5 s : yellow LED + vibration pulses (300 ms on / 700 ms off)
    - Bend for 15 s: red LED + buzzer beeps (200 ms on / 200 ms off) + vibration
    - Sitting or lying: timers reset, no alerts.
    - Short button press = calibrate. Long press (1.5 s) = mute for 60 s
      (long press again to un-mute). Mute silences the motor and buzzer only.
    - Alerts run locally. Wi-Fi is only used for the website.

  LED PATTERNS
    green steady = posture OK        yellow steady = early warning
    red steady   = alert             yellow slow blink = not calibrated
    all blinking fast = calibrating  red/yellow alternating = MPU fault

  WEBSITE PROTOCOL (HTTP POST every UPLOAD_INTERVAL_MS)
    Request : JSON telemetry to SERVER_URL, header X-Device-Token
    Response: any 2xx JSON. Optional one-shot commands:
      {
        "status": "ok",
        "commands": {
          "calibrate": true,
          "mute_s": 60,                       (0 = un-mute)
          "test": "buzzer" | "vibration" | "leds",
          "config": { "bend_on_deg": 20, "bend_off_deg": 15,
                      "vibrate_delay_s": 5, "buzzer_delay_s": 15 }
        }
      }
    The backend must send each command only once.

  SERIAL (115200 baud):  c = calibrate | m = mute toggle | d = debug print
                         f = heart-rate finger-threshold wizard | h = help

  STATUS: written but not yet compiled or tested on hardware.
  ============================================================
*/

#include <Wire.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <DHT.h>
#include <Preferences.h>
#include "MAX30105.h"
#include "heartRate.h"
#include <math.h>

// ============================================================
// USER SETTINGS — edit these
// ============================================================

const char* WIFI_SSID = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const char* SERVER_URL = "http://YOUR_LAPTOP_IP:5000/api/data";
const char* DEVICE_ID = "vest-01";
const char* DEVICE_TOKEN = "change-me";
const uint32_t UPLOAD_INTERVAL_MS = 1000;

// Flex sensors are not connected yet. Set true after wiring them.
const bool USE_FLEX = false;

// MPU gyro axis signs. Copy the values confirmed by the MPU test sketch ('t' test).
const float PITCH_GYRO_SIGN = -1.0f;
const float ROLL_GYRO_SIGN = -1.0f;

// ============================================================
// PINS
// ============================================================

const int SDA_PIN = 21;
const int SCL_PIN = 22;
const int FLEX_PIN_UPPER = 34;
const int FLEX_PIN_LOWER = 35;
const int DHT_PIN = 4;
const int BUTTON_PIN = 16;
const int MOTOR_PIN = 25;
const int BUZZER_PIN = 26;
const int LED_RED_PIN = 27;
const int LED_YELLOW_PIN = 14;
const int LED_GREEN_PIN = 13;

// ============================================================
// DEFAULT THRESHOLDS (the website can change the first four)
// ============================================================

const float DEF_BEND_ON_DEG = 20.0f;
const float DEF_BEND_OFF_DEG = 15.0f;
const uint32_t DEF_VIBRATE_DELAY_MS = 5000;
const uint32_t DEF_BUZZER_DELAY_MS = 15000;

const uint32_t BEND_DEBOUNCE_MS = 300;

const float STAND_BELOW_DEG = 35.0f;         // thigh tilt below this = standing
const float SIT_ABOVE_DEG = 55.0f;           // thigh tilt above this = sitting / lying
const uint32_t POSTURE_CONFIRM_MS = 1000;    // new standing/sitting state must hold this long

const float FLEX_ON = 60.0f;                 // ADC units from baseline
const float FLEX_OFF = 40.0f;

const int MOTOR_PWM = 200;                   // 0-255
const uint32_t VIB_ON_MS = 300, VIB_PERIOD_MS = 1000;
const uint32_t BUZ_ON_MS = 200, BUZ_PERIOD_MS = 400;
const uint32_t MUTE_DURATION_MS = 60000;
const uint32_t LONG_PRESS_MS = 1500;
const uint32_t BUTTON_DEBOUNCE_MS = 40;

const uint32_t CAL_SETTLE_MS = 700;
const uint32_t CAL_MEASURE_MS = 1300;
const uint32_t CAL_TIMEOUT_MS = 10000;

// Sensor scaling and motion detection
const uint32_t MPU_SAMPLE_US = 10000;        // 100 Hz
const float MPU_ACCEL_LSB_PER_G = 8192.0f;   // +/-4 g
const float MPU_GYRO_LSB_PER_DPS = 65.5f;    // +/-500 dps
const float ALPHA_STILL = 0.98f;
const float ALPHA_MOVING = 0.995f;
const float MPU_MOTION_G = 0.15f;
const float MPU_MOTION_DPS = 80.0f;
const float ADXL_MOTION_G = 0.25f;
const uint32_t MOTION_HOLD_MS = 500;

// Heart rate
const long DEF_FINGER_THRESHOLD = 50000;
const byte DEF_LED_AMPLITUDE = 0x1F;
const int FINGER_ON_SAMPLES = 20;
const int FINGER_OFF_SAMPLES = 30;
const float FINGER_OFF_RATIO = 0.90f;
const uint32_t HR_WARMUP_MS = 2000;
const uint32_t HR_MIN_INTERVAL_MS = 300;
const uint32_t HR_MAX_INTERVAL_MS = 1500;
const float HR_JUMP_MIN_BPM = 15.0f;
const float HR_JUMP_FRACTION = 0.25f;
const int HR_RELOCK_REJECTS = 6;

#define FW_VERSION "1.0.0"

// ============================================================
// TYPES (kept above all functions)
// ============================================================

enum PostureState : uint8_t {
  ST_UNCALIBRATED = 0,
  ST_CALIBRATING,
  ST_FAULT,
  ST_UPRIGHT,
  ST_WARNING,
  ST_ALERT
};

struct PendingCommands {
  bool calibrate;
  bool muteSet;
  int muteSeconds;
  uint8_t testKind;        // 0 none, 1 buzzer, 2 vibration, 3 leds
  bool configSet;
  float bendOn;            // <= 0 means unchanged
  float bendOff;
  uint32_t vibrateMs;      // 0 means unchanged
  uint32_t buzzerMs;
};

struct Telemetry {
  uint32_t uptimeS;
  uint8_t state;
  bool armed, muted, standing, moving;
  bool bent, possible, imuBent, flexBent;
  bool vib, buz, ledR, ledY, ledG;
  bool finger;
  float pitch, roll, tilt, flexU, flexL;
  uint32_t bendMs;
  int hr;
  bool mpuOK, adxlOK, maxOK;
  float bendOn, bendOff;
  uint32_t vibMs, buzMs;
};

const char* stateName(uint8_t s) {
  switch (s) {
    case ST_UNCALIBRATED: return "UNCALIBRATED";
    case ST_CALIBRATING:  return "CALIBRATING";
    case ST_FAULT:        return "FAULT";
    case ST_UPRIGHT:      return "UPRIGHT";
    case ST_WARNING:      return "WARNING";
    case ST_ALERT:        return "ALERT";
  }
  return "UNKNOWN";
}

// ============================================================
// GLOBALS
// ============================================================

Preferences prefs;
DHT dht(DHT_PIN, DHT11);
MAX30105 pulseOx;

SemaphoreHandle_t dataMutex;
Telemetry telem;
PendingCommands pendingCmd;

// Runtime thresholds
float bendOnDeg = DEF_BEND_ON_DEG;
float bendOffDeg = DEF_BEND_OFF_DEG;
uint32_t vibrateDelayMs = DEF_VIBRATE_DELAY_MS;
uint32_t buzzerDelayMs = DEF_BUZZER_DELAY_MS;

// ---- MPU ----
uint8_t mpuAddr = 0x68;
bool mpuOK = false;
uint8_t mpuFail = 0;
float ax_g = 0, ay_g = 0, az_g = 0, gx_dps = 0, gy_dps = 0, gz_dps = 0;
float accMagG = 1.0f;
float gyroBiasX = 0, gyroBiasY = 0, gyroBiasZ = 0;
float pitchDeg = 0, rollDeg = 0;
float pitchOffset = 0, rollOffset = 0;
float pitchRel = 0, rollRel = 0;
bool mpuMoving = false;
uint32_t mpuMovingUntil = 0;
uint32_t lastMpuUs = 0;
bool imuBent = false;
uint32_t bendCandSince = 0;

// ---- ADXL345 ----
uint8_t adxlAddr = 0x53;
bool adxlOK = false;
uint8_t adxlFail = 0;
float rawAx = 0, rawAy = 0, rawAz = 1;
float fAx = 0, fAy = 0, fAz = 1;
bool adxlFilterInit = false;
float standX = 0, standY = 0, standZ = 1;
bool haveStandRef = false;
float adxlTilt = NAN;
bool adxlMoving = false;
uint32_t adxlMovingUntil = 0;
bool standing = true;
uint32_t standCandSince = 0;

// ---- Flex ----
float flexRawU = 0, flexRawL = 0;
bool flexInit = false;
float flexBaseU = 0, flexBaseL = 0;
float flexDeltaU = NAN, flexDeltaL = NAN;
bool flexBent = false;

// ---- Heart rate ----
bool maxOK = false;
long fingerThreshold = DEF_FINGER_THRESHOLD;
byte ledAmplitude = DEF_LED_AMPLITUDE;
long lastIR = 0;
bool fingerPresent = false;
int aboveCount = 0, belowCount = 0;
uint32_t fingerSince = 0;
uint32_t lastBeat = 0;
float hrInstBpm = 0;
int hrAvgBpm = 0;
const int HR_BUF = 5;
float bpmBuf[HR_BUF];
int bpmCount = 0, bpmIndex = 0, hrRejects = 0;

// ---- Posture state ----
uint8_t postureState = ST_UNCALIBRATED;
bool armed = false;
bool confirmedBent = false;
bool possibleBend = false;
uint32_t bendStartMs = 0;
uint32_t bendDurationMs = 0;

// ---- Calibration ----
bool calibrating = false;
uint32_t calStartMs = 0, calWindowStartMs = 0;
double calSumP = 0, calSumR = 0, calSumAx = 0, calSumAy = 0, calSumAz = 0, calSumFU = 0, calSumFL = 0;
int calN = 0;

// ---- Outputs / UI ----
uint32_t muteUntilMs = 0;
uint8_t testKind = 0;
uint32_t testUntilMs = 0;
bool vibrationActive = false, buzzerActive = false;
bool ledR = false, ledY = false, ledG = false;
bool debugOn = true;

// ---- Button ----
bool btnRaw = HIGH, btnStable = HIGH;
uint32_t btnChange = 0, pressStart = 0;
bool longDone = false;

// ---- Timing ----
uint32_t lastTickMs = 0, lastPublishMs = 0, lastPrintMs = 0, lastRetryMs = 0;

// ============================================================
// SMALL HELPERS
// ============================================================

static inline float clampf(float v, float lo, float hi) {
  return v < lo ? lo : (v > hi ? hi : v);
}

static inline uint32_t clampu(uint32_t v, uint32_t lo, uint32_t hi) {
  return v < lo ? lo : (v > hi ? hi : v);
}

bool isMuted(uint32_t now) {
  return muteUntilMs != 0 && (int32_t)(muteUntilMs - now) > 0;
}

// ============================================================
// I2C HELPERS
// ============================================================

bool i2cPresent(uint8_t addr) {
  Wire.beginTransmission(addr);
  return Wire.endTransmission() == 0;
}

bool i2cWrite(uint8_t addr, uint8_t reg, uint8_t val) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  Wire.write(val);
  return Wire.endTransmission() == 0;
}

bool i2cRead(uint8_t addr, uint8_t reg, uint8_t* buf, uint8_t n) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  uint8_t got = Wire.requestFrom(addr, n, (uint8_t)true);
  if (got != n) return false;
  for (uint8_t i = 0; i < n; i++) buf[i] = Wire.read();
  return true;
}

// ============================================================
// SETTINGS STORAGE
// ============================================================

void loadSettings() {
  prefs.begin("vest", false);
  bendOnDeg = prefs.getFloat("bon", DEF_BEND_ON_DEG);
  bendOffDeg = prefs.getFloat("boff", DEF_BEND_OFF_DEG);
  vibrateDelayMs = prefs.getUInt("vms", DEF_VIBRATE_DELAY_MS);
  buzzerDelayMs = prefs.getUInt("bms", DEF_BUZZER_DELAY_MS);
  pitchOffset = prefs.getFloat("pOff", 0.0f);
  rollOffset = prefs.getFloat("rOff", 0.0f);
  flexBaseU = prefs.getFloat("fbu", 0.0f);
  flexBaseL = prefs.getFloat("fbl", 0.0f);
  haveStandRef = prefs.getBool("hsr", false);
  standX = prefs.getFloat("sx", 0.0f);
  standY = prefs.getFloat("sy", 0.0f);
  standZ = prefs.getFloat("sz", 1.0f);
  fingerThreshold = prefs.getLong("fthr", DEF_FINGER_THRESHOLD);
  ledAmplitude = prefs.getUChar("led", DEF_LED_AMPLITUDE);
}

void saveThresholds() {
  prefs.putFloat("bon", bendOnDeg);
  prefs.putFloat("boff", bendOffDeg);
  prefs.putUInt("vms", vibrateDelayMs);
  prefs.putUInt("bms", buzzerDelayMs);
}

// ============================================================
// MPU6050 / MPU6500 — TRUNK PITCH
// ============================================================

bool mpuBegin() {
  if (i2cPresent(0x68)) mpuAddr = 0x68;
  else if (i2cPresent(0x69)) mpuAddr = 0x69;
  else {
    Serial.println("MPU: not found at 0x68/0x69.");
    return false;
  }

  uint8_t who = 0;
  if (!i2cRead(mpuAddr, 0x75, &who, 1)) {
    Serial.println("MPU: cannot read WHO_AM_I.");
    return false;
  }
  Serial.printf("MPU address 0x%02X, WHO_AM_I = 0x%02X\n", mpuAddr, who);

  if (who != 0x68 && who != 0x70 && who != 0x71 && who != 0x73) {
    Serial.println("MPU: unexpected WHO_AM_I.");
    return false;
  }

  i2cWrite(mpuAddr, 0x6B, 0x80);     // reset
  delay(100);
  if (!i2cWrite(mpuAddr, 0x6B, 0x01)) return false;   // wake, gyro PLL clock
  delay(50);
  i2cWrite(mpuAddr, 0x19, 9);        // sample-rate divider
  i2cWrite(mpuAddr, 0x1A, 0x03);     // gyro low-pass ~44 Hz
  i2cWrite(mpuAddr, 0x1B, 0x08);     // gyro +/-500 dps
  i2cWrite(mpuAddr, 0x1C, 0x08);     // accel +/-4 g
  i2cWrite(mpuAddr, 0x1D, 0x03);     // accel low-pass (6500; harmless on 6050)
  delay(50);
  return true;
}

bool mpuReadRaw() {
  uint8_t d[14];
  if (!i2cRead(mpuAddr, 0x3B, d, 14)) return false;

  int16_t rax = (int16_t)((d[0] << 8) | d[1]);
  int16_t ray = (int16_t)((d[2] << 8) | d[3]);
  int16_t raz = (int16_t)((d[4] << 8) | d[5]);
  int16_t rgx = (int16_t)((d[8] << 8) | d[9]);
  int16_t rgy = (int16_t)((d[10] << 8) | d[11]);
  int16_t rgz = (int16_t)((d[12] << 8) | d[13]);

  ax_g = rax / MPU_ACCEL_LSB_PER_G;
  ay_g = ray / MPU_ACCEL_LSB_PER_G;
  az_g = raz / MPU_ACCEL_LSB_PER_G;
  gx_dps = rgx / MPU_GYRO_LSB_PER_DPS - gyroBiasX;
  gy_dps = rgy / MPU_GYRO_LSB_PER_DPS - gyroBiasY;
  gz_dps = rgz / MPU_GYRO_LSB_PER_DPS - gyroBiasZ;
  accMagG = sqrtf(ax_g * ax_g + ay_g * ay_g + az_g * az_g);
  return true;
}

void mpuAccelAngles(float& pitch, float& roll) {
  pitch = atan2f(az_g, sqrtf(ax_g * ax_g + ay_g * ay_g)) * 180.0f / PI;
  roll = atan2f(-ax_g, sqrtf(ay_g * ay_g + az_g * az_g)) * 180.0f / PI;
}

bool mpuCalibrateGyro() {
  Serial.println("Measuring gyro bias... keep the shirt still.");
  gyroBiasX = gyroBiasY = gyroBiasZ = 0;
  float sx = 0, sy = 0, sz = 0;
  int got = 0;

  for (int i = 0; i < 200; i++) {
    if (mpuReadRaw()) {
      sx += gx_dps; sy += gy_dps; sz += gz_dps;
      got++;
    }
    delay(5);
  }
  if (got < 100) {
    Serial.println("Gyro bias failed.");
    return false;
  }
  gyroBiasX = sx / got;
  gyroBiasY = sy / got;
  gyroBiasZ = sz / got;
  Serial.printf("Gyro bias: %.2f %.2f %.2f dps\n", gyroBiasX, gyroBiasY, gyroBiasZ);
  return true;
}

void mpuInitAngles() {
  if (mpuReadRaw()) mpuAccelAngles(pitchDeg, rollDeg);
  lastMpuUs = micros();
}

void mpuStep(uint32_t now) {
  if (!mpuReadRaw()) {
    if (mpuFail < 255) mpuFail++;
    if (mpuFail >= 20) mpuOK = false;
    return;
  }
  mpuFail = 0;

  static uint32_t lastUs = 0;
  uint32_t nowUs = micros();
  float dt = (nowUs - lastUs) / 1e6f;
  lastUs = nowUs;
  if (dt <= 0.0f || dt > 0.1f) dt = MPU_SAMPLE_US / 1e6f;

  float gyroMag = sqrtf(gx_dps * gx_dps + gy_dps * gy_dps + gz_dps * gz_dps);
  if (fabsf(accMagG - 1.0f) > MPU_MOTION_G || gyroMag > MPU_MOTION_DPS) {
    mpuMovingUntil = now + MOTION_HOLD_MS;
  }
  mpuMoving = (int32_t)(mpuMovingUntil - now) > 0;

  float accP, accR;
  mpuAccelAngles(accP, accR);
  float a = mpuMoving ? ALPHA_MOVING : ALPHA_STILL;
  pitchDeg = a * (pitchDeg + PITCH_GYRO_SIGN * gx_dps * dt) + (1.0f - a) * accP;
  rollDeg = a * (rollDeg + ROLL_GYRO_SIGN * gz_dps * dt) + (1.0f - a) * accR;

  pitchRel = pitchDeg - pitchOffset;
  rollRel = rollDeg - rollOffset;
}

// Bend decision with hysteresis and debounce
void updateBendState(uint32_t now) {
  bool want = imuBent ? (pitchRel >= bendOffDeg) : (pitchRel >= bendOnDeg);
  if (want == imuBent) {
    bendCandSince = 0;
    return;
  }
  if (bendCandSince == 0) bendCandSince = now;
  if (now - bendCandSince >= BEND_DEBOUNCE_MS) {
    imuBent = want;
    bendCandSince = 0;
  }
}

// ============================================================
// ADXL345 — STANDING vs SITTING (raw I2C, any orientation)
// ============================================================

bool adxlBegin() {
  if (i2cPresent(0x53)) adxlAddr = 0x53;
  else if (i2cPresent(0x1D)) adxlAddr = 0x1D;
  else {
    Serial.println("ADXL345: not found at 0x53/0x1D.");
    return false;
  }

  uint8_t id = 0;
  if (!i2cRead(adxlAddr, 0x00, &id, 1) || id != 0xE5) {
    Serial.printf("ADXL345: unexpected device ID 0x%02X.\n", id);
    return false;
  }

  i2cWrite(adxlAddr, 0x2D, 0x00);    // standby
  i2cWrite(adxlAddr, 0x31, 0x08);    // full resolution, +/-2 g (256 LSB/g)
  i2cWrite(adxlAddr, 0x2C, 0x0A);    // 100 Hz output rate
  i2cWrite(adxlAddr, 0x2D, 0x08);    // measurement mode
  delay(20);
  return true;
}

bool adxlReadRaw(float& x, float& y, float& z) {
  uint8_t b[6];
  if (!i2cRead(adxlAddr, 0x32, b, 6)) return false;
  int16_t rx = (int16_t)((b[1] << 8) | b[0]);
  int16_t ry = (int16_t)((b[3] << 8) | b[2]);
  int16_t rz = (int16_t)((b[5] << 8) | b[4]);
  x = rx / 256.0f;
  y = ry / 256.0f;
  z = rz / 256.0f;
  return true;
}

void adxlStep(uint32_t now) {
  if (!adxlOK) return;

  float x, y, z;
  if (!adxlReadRaw(x, y, z)) {
    if (adxlFail < 255) adxlFail++;
    if (adxlFail >= 25) adxlOK = false;
    return;
  }
  adxlFail = 0;
  rawAx = x; rawAy = y; rawAz = z;

  float mag = sqrtf(x * x + y * y + z * z);
  if (fabsf(mag - 1.0f) > ADXL_MOTION_G) adxlMovingUntil = now + MOTION_HOLD_MS;
  adxlMoving = (int32_t)(adxlMovingUntil - now) > 0;

  if (!adxlFilterInit) {
    fAx = x; fAy = y; fAz = z;
    adxlFilterInit = true;
  } else {
    fAx += 0.2f * (x - fAx);
    fAy += 0.2f * (y - fAy);
    fAz += 0.2f * (z - fAz);
  }

  if (!haveStandRef) {
    adxlTilt = NAN;
    return;
  }

  // Tilt = angle between the current gravity vector and the standing one
  float fm = sqrtf(fAx * fAx + fAy * fAy + fAz * fAz);
  if (fm > 0.1f) {
    float dotp = (fAx * standX + fAy * standY + fAz * standZ) / fm;
    adxlTilt = acosf(clampf(dotp, -1.0f, 1.0f)) * 180.0f / PI;
  }

  // Standing / sitting with hysteresis and a hold time; frozen while moving
  bool candidate = standing;
  if (adxlTilt < STAND_BELOW_DEG) candidate = true;
  else if (adxlTilt > SIT_ABOVE_DEG) candidate = false;

  if (adxlMoving || candidate == standing) {
    standCandSince = 0;
  } else {
    if (standCandSince == 0) standCandSince = now;
    else if (now - standCandSince >= POSTURE_CONFIRM_MS) {
      standing = candidate;
      standCandSince = 0;
      Serial.println(standing ? ">>> STANDING" : ">>> SITTING/LYING");
    }
  }
}

// ============================================================
// FLEX SENSORS (only used when USE_FLEX = true)
// ============================================================

void flexStep() {
  if (!USE_FLEX) return;

  float u = (float)analogRead(FLEX_PIN_UPPER);
  float l = (float)analogRead(FLEX_PIN_LOWER);
  if (!flexInit) {
    flexRawU = u; flexRawL = l;
    flexInit = true;
  } else {
    flexRawU += 0.2f * (u - flexRawU);
    flexRawL += 0.2f * (l - flexRawL);
  }

  flexDeltaU = flexRawU - flexBaseU;
  flexDeltaL = flexRawL - flexBaseL;
  float avg = fabsf((flexDeltaU + flexDeltaL) / 2.0f);   // direction-agnostic
  flexBent = flexBent ? (avg >= FLEX_OFF) : (avg >= FLEX_ON);
}

// ============================================================
// HEART RATE — MAX30102
// ============================================================

void maxApplyAmplitude() {
  pulseOx.setPulseAmplitudeIR(ledAmplitude);
  pulseOx.setPulseAmplitudeRed(0x0A);
}

bool maxBegin() {
  if (!pulseOx.begin(Wire, I2C_SPEED_STANDARD)) {
    Serial.println("MAX30102: not found.");
    return false;
  }
  pulseOx.setup(ledAmplitude, 4, 2, 400, 411, 4096);   // 100 samples/s, red + IR
  maxApplyAmplitude();
  pulseOx.clearFIFO();
  return true;
}

void hrResetBeats() {
  lastBeat = 0;
  hrInstBpm = 0;
  hrAvgBpm = 0;
  bpmCount = 0;
  bpmIndex = 0;
  hrRejects = 0;
}

void hrRecomputeAverage() {
  if (bpmCount == 0) { hrAvgBpm = 0; return; }
  float tmp[HR_BUF];
  for (int i = 0; i < bpmCount; i++) tmp[i] = bpmBuf[i];
  for (int i = 0; i < bpmCount - 1; i++)
    for (int j = i + 1; j < bpmCount; j++)
      if (tmp[j] < tmp[i]) { float t = tmp[i]; tmp[i] = tmp[j]; tmp[j] = t; }

  int from = 0, to = bpmCount;
  if (bpmCount >= HR_BUF) { from = 1; to = bpmCount - 1; }   // drop min and max
  float sum = 0;
  for (int i = from; i < to; i++) sum += tmp[i];
  hrAvgBpm = (int)(sum / (to - from) + 0.5f);
}

void hrReject() {
  hrRejects++;
  if (hrRejects >= HR_RELOCK_REJECTS) {
    bpmCount = 0;
    bpmIndex = 0;
    hrAvgBpm = 0;
    hrRejects = 0;
  }
}

void hrHandleBeat(uint32_t now) {
  if (lastBeat == 0) { lastBeat = now; return; }

  uint32_t delta = now - lastBeat;
  if (delta < HR_MIN_INTERVAL_MS) { hrReject(); return; }              // false extra beat
  if (delta > HR_MAX_INTERVAL_MS) { lastBeat = now; hrReject(); return; }   // missed beats

  float bpm = 60000.0f / (float)delta;

  if (bpmCount >= 3 && hrAvgBpm > 0) {
    float tol = HR_JUMP_FRACTION * hrAvgBpm;
    if (tol < HR_JUMP_MIN_BPM) tol = HR_JUMP_MIN_BPM;
    if (bpm > hrAvgBpm + tol) { hrReject(); return; }
    if (bpm < hrAvgBpm - tol) { lastBeat = now; hrReject(); return; }
  }

  hrInstBpm = bpm;
  bpmBuf[bpmIndex] = bpm;
  bpmIndex = (bpmIndex + 1) % HR_BUF;
  if (bpmCount < HR_BUF) bpmCount++;
  hrRejects = 0;
  lastBeat = now;
  hrRecomputeAverage();
}

void hrProcessSample(long ir) {
  lastIR = ir;

  if (!fingerPresent) {
    if (ir > fingerThreshold) {
      if (++aboveCount >= FINGER_ON_SAMPLES) {
        fingerPresent = true;
        fingerSince = millis();
        aboveCount = belowCount = 0;
        hrResetBeats();
      }
    } else {
      aboveCount = 0;
    }
  } else {
    if (ir < (long)(fingerThreshold * FINGER_OFF_RATIO)) {
      if (++belowCount >= FINGER_OFF_SAMPLES) {
        fingerPresent = false;
        aboveCount = belowCount = 0;
        hrResetBeats();
      }
    } else {
      belowCount = 0;
    }
  }

  if (!fingerPresent) return;

  bool beat = checkForBeat(ir);
  if (!beat) return;
  uint32_t now = millis();
  if (now - fingerSince < HR_WARMUP_MS) return;
  hrHandleBeat(now);
}

// Call on every pass of loop()
void maxUpdate() {
  if (!maxOK) return;
  pulseOx.check();
  while (pulseOx.available()) {
    long ir = pulseOx.getFIFOIR();
    pulseOx.nextSample();
    hrProcessSample(ir);
  }
}

long hrReadIRAverage(uint32_t durationMs) {
  pulseOx.clearFIFO();
  double sum = 0;
  uint32_t n = 0;
  uint32_t start = millis();
  while (millis() - start < durationMs) {
    pulseOx.check();
    while (pulseOx.available()) {
      sum += pulseOx.getFIFOIR();
      n++;
      pulseOx.nextSample();
    }
    yield();
  }
  return n ? (long)(sum / n) : 0;
}

void runFingerWizard() {
  if (!maxOK) { Serial.println("MAX30102 not ready."); return; }

  Serial.println("Step 1/2: keep the sensor UNCOVERED. Measuring 3 s...");
  long noContact = hrReadIRAverage(3000);
  Serial.printf("No-contact IR = %ld\n", noContact);

  Serial.println("Step 2/2: put the sensor on your wearing spot. Starting in 5 s...");
  delay(5000);
  Serial.println("Measuring 4 s - hold still...");
  long withContact = hrReadIRAverage(4000);
  Serial.printf("With-contact IR = %ld\n", withContact);

  if (withContact < noContact * 1.5f || (withContact - noContact) < 8000) {
    Serial.println("Contact signal too weak. Threshold NOT changed (improve contact or raise LED current).");
    return;
  }

  fingerThreshold = noContact + (long)((withContact - noContact) * 0.4f);
  prefs.putLong("fthr", fingerThreshold);
  Serial.printf("Finger threshold set to %ld and saved.\n", fingerThreshold);
  fingerPresent = false;
  aboveCount = belowCount = 0;
  hrResetBeats();
  pulseOx.clearFIFO();
}

// ============================================================
// CALIBRATION (non-blocking)
// ============================================================

void calResetSums() {
  calSumP = calSumR = calSumAx = calSumAy = calSumAz = calSumFU = calSumFL = 0;
  calN = 0;
}

void startCalibration() {
  if (calibrating) return;
  if (!mpuOK) {
    Serial.println("Cannot calibrate: MPU not ready.");
    return;
  }
  calibrating = true;
  calStartMs = millis();
  calWindowStartMs = calStartMs;
  calResetSums();
  Serial.println("Calibrating: stand tall and keep still for about 2 seconds...");
}

void finishCalibration() {
  pitchOffset = (float)(calSumP / calN);
  rollOffset = (float)(calSumR / calN);
  prefs.putFloat("pOff", pitchOffset);
  prefs.putFloat("rOff", rollOffset);

  if (adxlOK) {
    float sx = (float)(calSumAx / calN);
    float sy = (float)(calSumAy / calN);
    float sz = (float)(calSumAz / calN);
    float m = sqrtf(sx * sx + sy * sy + sz * sz);
    if (m > 0.5f) {
      standX = sx / m; standY = sy / m; standZ = sz / m;
      haveStandRef = true;
      prefs.putBool("hsr", true);
      prefs.putFloat("sx", standX);
      prefs.putFloat("sy", standY);
      prefs.putFloat("sz", standZ);
    }
  }

  if (USE_FLEX) {
    flexBaseU = (float)(calSumFU / calN);
    flexBaseL = (float)(calSumFL / calN);
    prefs.putFloat("fbu", flexBaseU);
    prefs.putFloat("fbl", flexBaseL);
    flexBent = false;
  }

  imuBent = false;
  bendCandSince = 0;
  standing = true;
  standCandSince = 0;
  bendStartMs = 0;
  armed = true;
  calibrating = false;

  Serial.printf("Calibration done: pitch offset %.2f, roll offset %.2f%s\n",
                pitchOffset, rollOffset, haveStandRef ? ", standing pose saved" : "");
}

void calibrationStep(uint32_t now) {
  if (!calibrating) return;

  bool still = !mpuMoving && !(adxlOK && adxlMoving);
  if (!still) {
    calWindowStartMs = now;       // restart the still window
    calResetSums();
  } else if (now - calWindowStartMs >= CAL_SETTLE_MS) {
    calSumP += pitchDeg;
    calSumR += rollDeg;
    if (adxlOK) { calSumAx += rawAx; calSumAy += rawAy; calSumAz += rawAz; }
    if (USE_FLEX) { calSumFU += flexRawU; calSumFL += flexRawL; }
    calN++;
  }

  if (calN >= 30 && now - calWindowStartMs >= CAL_SETTLE_MS + CAL_MEASURE_MS) {
    finishCalibration();
    return;
  }

  if (now - calStartMs > CAL_TIMEOUT_MS) {
    calibrating = false;
    Serial.println("Calibration failed: could not stay still. Try again.");
  }
}

// ============================================================
// POSTURE LOGIC
// ============================================================

void updatePosture(uint32_t now) {
  calibrationStep(now);

  bool standingEff = adxlOK ? standing : true;

  confirmedBent = false;
  possibleBend = false;

  if (calibrating) {
    postureState = ST_CALIBRATING;
  } else if (!mpuOK) {
    postureState = ST_FAULT;
  } else if (!armed) {
    postureState = ST_UNCALIBRATED;
  } else {
    bool flexAgrees = USE_FLEX ? flexBent : true;
    confirmedBent = standingEff && imuBent && flexAgrees;
    possibleBend = standingEff && USE_FLEX && (imuBent != flexBent);

    if (confirmedBent) {
      if (bendStartMs == 0) bendStartMs = now;
      bendDurationMs = now - bendStartMs;
    } else {
      bendStartMs = 0;
      bendDurationMs = 0;
    }

    if (confirmedBent && bendDurationMs >= buzzerDelayMs) postureState = ST_ALERT;
    else if (confirmedBent && bendDurationMs >= vibrateDelayMs) postureState = ST_WARNING;
    else postureState = ST_UPRIGHT;
    return;
  }

  bendStartMs = 0;
  bendDurationMs = 0;
}

// ============================================================
// OUTPUTS
// ============================================================

void updateOutputs(uint32_t now) {
  bool r = false, y = false, g = false;
  bool vibPulse = false, buzPulse = false;
  bool muted = isMuted(now);

  vibrationActive = false;
  buzzerActive = false;

  if (testKind != 0 && (int32_t)(testUntilMs - now) > 0) {
    // Test mode from the website (works even when muted)
    switch (testKind) {
      case 1: buzPulse = true; buzzerActive = true; g = true; break;
      case 2: vibPulse = true; vibrationActive = true; g = true; break;
      case 3: {
        uint32_t ph = (now / 300) % 3;
        g = (ph == 0); y = (ph == 1); r = (ph == 2);
        break;
      }
    }
  } else {
    testKind = 0;
    switch (postureState) {
      case ST_UNCALIBRATED:
        y = (now % 1000) < 500;
        break;
      case ST_CALIBRATING: {
        bool on = (now % 300) < 150;
        r = y = g = on;
        break;
      }
      case ST_FAULT: {
        uint32_t ph = (now / 300) % 2;
        y = (ph == 0);
        r = (ph == 1);
        break;
      }
      case ST_UPRIGHT:
        g = true;
        break;
      case ST_WARNING:
        y = true;
        vibrationActive = !muted;
        vibPulse = vibrationActive && (now % VIB_PERIOD_MS) < VIB_ON_MS;
        break;
      case ST_ALERT:
        r = true;
        vibrationActive = !muted;
        buzzerActive = !muted;
        vibPulse = vibrationActive && (now % VIB_PERIOD_MS) < VIB_ON_MS;
        buzPulse = buzzerActive && (now % BUZ_PERIOD_MS) < BUZ_ON_MS;
        break;
    }
  }

  ledR = r; ledY = y; ledG = g;
  digitalWrite(LED_RED_PIN, r ? HIGH : LOW);
  digitalWrite(LED_YELLOW_PIN, y ? HIGH : LOW);
  digitalWrite(LED_GREEN_PIN, g ? HIGH : LOW);
  ledcWrite(MOTOR_PIN, vibPulse ? MOTOR_PWM : 0);
  digitalWrite(BUZZER_PIN, buzPulse ? HIGH : LOW);
}

// ============================================================
// BUTTON
// ============================================================

void toggleMute(uint32_t now) {
  if (isMuted(now)) {
    muteUntilMs = 0;
    Serial.println("Mute OFF");
  } else {
    muteUntilMs = now + MUTE_DURATION_MS;
    Serial.println("Muted for 60 s");
  }
}

void handleButton(uint32_t now) {
  bool r = digitalRead(BUTTON_PIN);
  if (r != btnRaw) {
    btnRaw = r;
    btnChange = now;
  }

  if (now - btnChange >= BUTTON_DEBOUNCE_MS && r != btnStable) {
    btnStable = r;
    if (btnStable == LOW) {
      pressStart = now;
      longDone = false;
    } else if (!longDone) {
      startCalibration();            // short press, acted on at release
    }
  }

  if (btnStable == LOW && !longDone && now - pressStart >= LONG_PRESS_MS) {
    longDone = true;
    toggleMute(now);
  }
}

// ============================================================
// COMMANDS FROM THE WEBSITE
// ============================================================

void applyConfig(const PendingCommands& c) {
  float on = bendOnDeg, off = bendOffDeg;
  uint32_t vib = vibrateDelayMs, buz = buzzerDelayMs;

  if (c.bendOn > 0) on = clampf(c.bendOn, 5.0f, 60.0f);
  if (c.bendOff > 0) off = clampf(c.bendOff, 2.0f, 58.0f);
  if (off > on - 2.0f) off = on - 2.0f;
  if (off < 2.0f) off = 2.0f;

  if (c.vibrateMs > 0) vib = clampu(c.vibrateMs, 1000, 60000);
  if (c.buzzerMs > 0) buz = clampu(c.buzzerMs, 2000, 120000);
  if (buz <= vib) buz = vib + 1000;

  bendOnDeg = on;
  bendOffDeg = off;
  vibrateDelayMs = vib;
  buzzerDelayMs = buz;
  saveThresholds();

  Serial.printf("Config updated: bend %.0f/%.0f deg, vibrate %lu ms, buzzer %lu ms\n",
                bendOnDeg, bendOffDeg, (unsigned long)vibrateDelayMs, (unsigned long)buzzerDelayMs);
}

void applyPendingCommands(uint32_t now) {
  PendingCommands c;
  xSemaphoreTake(dataMutex, portMAX_DELAY);
  c = pendingCmd;
  memset(&pendingCmd, 0, sizeof(pendingCmd));
  xSemaphoreGive(dataMutex);

  if (c.calibrate) startCalibration();

  if (c.muteSet) {
    if (c.muteSeconds <= 0) {
      muteUntilMs = 0;
      Serial.println("Mute OFF (website)");
    } else {
      int s = c.muteSeconds > 3600 ? 3600 : c.muteSeconds;
      muteUntilMs = now + (uint32_t)s * 1000UL;
      Serial.printf("Muted for %d s (website)\n", s);
    }
  }

  if (c.testKind != 0) {
    testKind = c.testKind;
    testUntilMs = now + 2000;
    Serial.printf("Actuator test %d for 2 s\n", c.testKind);
  }

  if (c.configSet) applyConfig(c);
}

// ============================================================
// TELEMETRY SNAPSHOT
// ============================================================

void publishTelemetry(uint32_t now) {
  Telemetry t;
  t.uptimeS = now / 1000;
  t.state = postureState;
  t.armed = armed;
  t.muted = isMuted(now);
  t.standing = adxlOK ? standing : true;
  t.moving = mpuMoving || adxlMoving;
  t.bent = confirmedBent;
  t.possible = possibleBend;
  t.imuBent = imuBent;
  t.flexBent = flexBent;
  t.vib = vibrationActive;
  t.buz = buzzerActive;
  t.ledR = ledR; t.ledY = ledY; t.ledG = ledG;
  t.finger = fingerPresent;
  t.pitch = pitchRel;
  t.roll = rollRel;
  t.tilt = adxlTilt;
  t.flexU = USE_FLEX ? flexDeltaU : NAN;
  t.flexL = USE_FLEX ? flexDeltaL : NAN;
  t.bendMs = bendDurationMs;
  t.hr = hrAvgBpm;
  t.mpuOK = mpuOK;
  t.adxlOK = adxlOK;
  t.maxOK = maxOK;
  t.bendOn = bendOnDeg;
  t.bendOff = bendOffDeg;
  t.vibMs = vibrateDelayMs;
  t.buzMs = buzzerDelayMs;

  xSemaphoreTake(dataMutex, portMAX_DELAY);
  telem = t;
  xSemaphoreGive(dataMutex);
}

// ============================================================
// WI-FI + UPLOAD TASK (runs on core 0)
// ============================================================

void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  Serial.print("Connecting to Wi-Fi");
  for (int i = 0; i < 16 && WiFi.status() != WL_CONNECTED; i++) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("Wi-Fi connected. ESP32 IP: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("Wi-Fi not connected yet. Alerts still work; will keep retrying.");
  }
}

void putNum(JsonDocument& doc, const char* key, float v) {
  if (isnan(v)) doc[key] = nullptr;
  else doc[key] = roundf(v * 100.0f) / 100.0f;
}

void parseCommands(const String& body) {
  StaticJsonDocument<512> doc;
  if (deserializeJson(doc, body)) return;

  JsonObject cmd = doc["commands"];
  if (cmd.isNull()) return;

  PendingCommands c;
  memset(&c, 0, sizeof(c));

  c.calibrate = cmd["calibrate"] | false;

  if (cmd["mute_s"].is<int>()) {
    c.muteSet = true;
    c.muteSeconds = cmd["mute_s"].as<int>();
  }

  const char* test = cmd["test"] | "";
  if (strcmp(test, "buzzer") == 0) c.testKind = 1;
  else if (strcmp(test, "vibration") == 0) c.testKind = 2;
  else if (strcmp(test, "leds") == 0) c.testKind = 3;

  JsonObject cfg = cmd["config"];
  if (!cfg.isNull()) {
    c.configSet = true;
    c.bendOn = cfg["bend_on_deg"] | -1.0f;
    c.bendOff = cfg["bend_off_deg"] | -1.0f;
    float vs = cfg["vibrate_delay_s"] | -1.0f;
    float bs = cfg["buzzer_delay_s"] | -1.0f;
    c.vibrateMs = vs > 0 ? (uint32_t)(vs * 1000.0f) : 0;
    c.buzzerMs = bs > 0 ? (uint32_t)(bs * 1000.0f) : 0;
  }

  xSemaphoreTake(dataMutex, portMAX_DELAY);
  pendingCmd.calibrate = pendingCmd.calibrate || c.calibrate;
  if (c.muteSet) { pendingCmd.muteSet = true; pendingCmd.muteSeconds = c.muteSeconds; }
  if (c.testKind) pendingCmd.testKind = c.testKind;
  if (c.configSet) {
    pendingCmd.configSet = true;
    pendingCmd.bendOn = c.bendOn;
    pendingCmd.bendOff = c.bendOff;
    pendingCmd.vibrateMs = c.vibrateMs;
    pendingCmd.buzzerMs = c.buzzerMs;
  }
  xSemaphoreGive(dataMutex);
}

void networkTask(void* pvParameters) {
  float temp = NAN, hum = NAN;
  uint32_t lastDhtMs = 0;
  int dhtFails = 0;
  uint32_t lastReconnectMs = 0;
  int lastCode = 0;

  for (;;) {
    vTaskDelay(pdMS_TO_TICKS(UPLOAD_INTERVAL_MS));

    if (WiFi.status() != WL_CONNECTED) {
      if (millis() - lastReconnectMs > 5000) {
        lastReconnectMs = millis();
        WiFi.reconnect();
      }
      continue;
    }

    // DHT11: at most once every 5 s; three failures in a row = no data
    if (lastDhtMs == 0 || millis() - lastDhtMs >= 5000) {
      lastDhtMs = millis();
      float t = dht.readTemperature();
      float h = dht.readHumidity();
      if (isnan(t) || isnan(h)) {
        if (++dhtFails >= 3) { temp = NAN; hum = NAN; }
      } else {
        dhtFails = 0;
        temp = t;
        hum = h;
      }
    }

    Telemetry t;
    xSemaphoreTake(dataMutex, portMAX_DELAY);
    t = telem;
    xSemaphoreGive(dataMutex);

    StaticJsonDocument<1536> doc;
    doc["device_id"] = DEVICE_ID;
    doc["fw"] = FW_VERSION;
    doc["uptime_s"] = t.uptimeS;
    doc["state"] = stateName(t.state);
    doc["armed"] = t.armed;
    doc["muted"] = t.muted;
    doc["is_standing"] = t.standing;
    doc["moving"] = t.moving;
    doc["bend_detected"] = t.bent;
    doc["possible_bend"] = t.possible;
    doc["bend_duration_ms"] = t.bendMs;
    putNum(doc, "imu_pitch_deg", t.pitch);
    putNum(doc, "imu_roll_deg", t.roll);
    doc["imu_says_bent"] = t.imuBent;
    putNum(doc, "flex_upper", t.flexU);
    putNum(doc, "flex_lower", t.flexL);
    if (USE_FLEX) doc["flex_says_bent"] = t.flexBent;
    else doc["flex_says_bent"] = nullptr;
    putNum(doc, "adxl_tilt_deg", t.tilt);
    doc["vibration_active"] = t.vib;
    doc["buzzer_active"] = t.buz;
    doc["led_green"] = t.ledG;
    doc["led_yellow"] = t.ledY;
    doc["led_red"] = t.ledR;
    if (t.maxOK && t.finger && t.hr > 0) doc["heart_rate_bpm"] = t.hr;
    else doc["heart_rate_bpm"] = nullptr;
    doc["finger_present"] = t.finger;
    putNum(doc, "temperature_c", temp);
    putNum(doc, "humidity_pct", hum);
    doc["mpu_ok"] = t.mpuOK;
    doc["adxl_ok"] = t.adxlOK;
    doc["max_ok"] = t.maxOK;
    doc["flex_enabled"] = USE_FLEX;
    putNum(doc, "bend_on_deg", t.bendOn);
    putNum(doc, "bend_off_deg", t.bendOff);
    doc["vibrate_delay_s"] = t.vibMs / 1000.0f;
    doc["buzzer_delay_s"] = t.buzMs / 1000.0f;
    doc["wifi_rssi"] = WiFi.RSSI();

    String payload;
    serializeJson(doc, payload);

    HTTPClient http;
    http.setConnectTimeout(1500);
    http.setTimeout(1500);

    int code = -1;
    if (http.begin(SERVER_URL)) {
      http.addHeader("Content-Type", "application/json");
      http.addHeader("X-Device-Token", DEVICE_TOKEN);
      code = http.POST(payload);
      if (code >= 200 && code < 300) {
        parseCommands(http.getString());
      }
      http.end();
    }

    // Log only when the result changes, to keep the serial output readable
    if (code != lastCode) {
      lastCode = code;
      if (code >= 200 && code < 300) Serial.printf("Upload OK (HTTP %d)\n", code);
      else Serial.printf("Upload failed (code %d). Check SERVER_URL and that the backend is running.\n", code);
    }
  }
}

// ============================================================
// SERIAL
// ============================================================

void printHelp() {
  Serial.println("Commands: c = calibrate | m = mute toggle | d = debug print | f = HR finger wizard | h = help");
}

void handleSerial(uint32_t now) {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == 'c' || c == 'C') startCalibration();
    else if (c == 'm' || c == 'M') toggleMute(now);
    else if (c == 'd' || c == 'D') {
      debugOn = !debugOn;
      Serial.println(debugOn ? "Debug print ON" : "Debug print OFF");
    }
    else if (c == 'f' || c == 'F') runFingerWizard();
    else if (c == 'h' || c == 'H') printHelp();
  }
}

// ============================================================
// SETUP
// ============================================================

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println();
  Serial.println("Posture T-shirt firmware " FW_VERSION);

  // Outputs first, all off
  pinMode(LED_RED_PIN, OUTPUT);
  pinMode(LED_YELLOW_PIN, OUTPUT);
  pinMode(LED_GREEN_PIN, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  digitalWrite(LED_RED_PIN, LOW);
  digitalWrite(LED_YELLOW_PIN, LOW);
  digitalWrite(LED_GREEN_PIN, LOW);
  digitalWrite(BUZZER_PIN, LOW);
  ledcAttach(MOTOR_PIN, 5000, 8);
  ledcWrite(MOTOR_PIN, 0);

  // Quick LED self-test: green, yellow, red
  digitalWrite(LED_GREEN_PIN, HIGH);  delay(150); digitalWrite(LED_GREEN_PIN, LOW);
  digitalWrite(LED_YELLOW_PIN, HIGH); delay(150); digitalWrite(LED_YELLOW_PIN, LOW);
  digitalWrite(LED_RED_PIN, HIGH);    delay(150); digitalWrite(LED_RED_PIN, LOW);

  analogReadResolution(12);

  memset(&pendingCmd, 0, sizeof(pendingCmd));
  dataMutex = xSemaphoreCreateMutex();

  loadSettings();
  Serial.printf("Thresholds: bend %.0f/%.0f deg, vibrate %lu ms, buzzer %lu ms\n",
                bendOnDeg, bendOffDeg, (unsigned long)vibrateDelayMs, (unsigned long)buzzerDelayMs);

  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.setClock(100000);

  mpuOK = mpuBegin();
  if (mpuOK) {
    mpuCalibrateGyro();
    mpuInitAngles();
  }

  adxlOK = adxlBegin();
  Serial.println(adxlOK ? "ADXL345: OK" : "ADXL345: NOT READY (assuming standing)");

  maxOK = maxBegin();
  Serial.println(maxOK ? "MAX30102: OK" : "MAX30102: NOT READY");

  dht.begin();

  connectWiFi();

  xTaskCreatePinnedToCore(networkTask, "networkTask", 12288, NULL, 1, NULL, 0);

  printHelp();
  Serial.println("NOT ARMED: stand tall and press the button to calibrate.");
}

// ============================================================
// LOOP — never blocks; heart-rate sampling needs a fast loop
// ============================================================

void loop() {
  uint32_t now = millis();

  handleSerial(now);
  handleButton(now);
  maxUpdate();

  if (mpuOK && micros() - lastMpuUs >= MPU_SAMPLE_US) {
    lastMpuUs = micros();
    mpuStep(now);
  }

  if (now - lastTickMs >= 20) {            // 50 Hz
    lastTickMs = now;
    adxlStep(now);
    flexStep();
    updateBendState(now);
    updatePosture(now);
    applyPendingCommands(now);
  }

  updateOutputs(now);

  if (now - lastPublishMs >= 100) {
    lastPublishMs = now;
    publishTelemetry(now);
  }

  // Try to bring back a sensor that dropped off the bus
  if (now - lastRetryMs >= 3000) {
    lastRetryMs = now;
    if (!mpuOK && !calibrating) {
      mpuOK = mpuBegin();
      if (mpuOK) { mpuCalibrateGyro(); mpuInitAngles(); }
    }
    if (!adxlOK) adxlOK = adxlBegin();
    if (!maxOK) maxOK = maxBegin();
  }

  if (debugOn && now - lastPrintMs >= 1000) {
    lastPrintMs = now;
    Serial.printf("[%s] pitch=%.1f roll=%.1f tilt=%.1f stand=%d mov=%d imuBent=%d bent=%d dur=%lums hr=%d finger=%d wifi=%d%s\n",
                  stateName(postureState), pitchRel, rollRel,
                  isnan(adxlTilt) ? -1.0f : adxlTilt,
                  adxlOK ? standing : 1, (mpuMoving || adxlMoving) ? 1 : 0,
                  imuBent ? 1 : 0, confirmedBent ? 1 : 0,
                  (unsigned long)bendDurationMs, hrAvgBpm, fingerPresent ? 1 : 0,
                  WiFi.status() == WL_CONNECTED ? 1 : 0,
                  isMuted(now) ? " MUTED" : "");
  }

  delay(1);
}
