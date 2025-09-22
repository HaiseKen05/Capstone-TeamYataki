#include <WiFi.h>
#include <HTTPClient.h>
#include <time.h>  // NTP time

// ====== Wi-Fi Credentials ======
const char* ssid = "ESP32-AP";
const char* password = "ESP32-Connect";

// ====== API Endpoint ======
const char* serverURL = "http://192.168.254.113:5000/add-log";
const char* pingURL   = "http://192.168.254.113:5000/ping";

// ====== Hardware Config ======
const int buttonPin = 13; // Button to trigger data sending

// ====== From WIP CODE 1: Pin Assignments ===
const int voltagePin = 36; // VT pin connected to GPIO36 (VP)
const int currentPin = 34; // AT pin connected to GPIO34

// ====== From WIP CODE 1: ESP32 ADC Specifications ===
const float ADC_REF_VOLTAGE = 3.3;   // Max ADC voltage
const int ADC_RESOLUTION = 4095;     // 12-bit ADC (0 - 4095)

// ====== From WIP CODE 1: MAX471 Specifications ===
const float CURRENT_SENSITIVITY = 1.0; // 1V per 1A

// ====== From WIP CODE 1: Voltage Divider Settings (VT) ===
const float VOLTAGE_DIVIDER_RATIO = 4.0;

// ====== From WIP CODE 1: Detection Settings ===
const float VOLTAGE_THRESHOLD = 0.1; // Minimum voltage to trigger detection (V)
const float VOLTAGE_CHANGE_TOLERANCE = 0.05; // Prevents duplicate triggers (V)

// ====== From WIP CODE 1: Session Management ===
const unsigned long SESSION_TIMEOUT = 10000; // 10 seconds in ms

// ====== From WIP CODE 1: Tracking Variables ===
float lastVoltage = 0.0;
unsigned long lastDetectionTime = 0;
int eventCounter = 0;
float totalVoltage = 0.0;
float totalCurrent = 0.0;
bool sessionActive = false;

// ====== Data to Send ======
int steps;
float voltage;
float current;
float batteryHealth;
bool readyToSend = false;

void setup() {
  Serial.begin(115200);
  pinMode(buttonPin, INPUT_PULLUP);
  delay(1000);

  Serial.println("MAX471 + ESP32 Voltage Session Tracker with WiFi Sending");
  Serial.println("Waiting for voltage events...");
  Serial.println("--------------------------------------");

  // Connect to Wi-Fi
  connectToWiFi();

  // Initialize NTP for accurate timestamps
  configTime(8 * 3600, 0, "pool.ntp.org", "time.nist.gov");

  Serial.println("Waiting for NTP time...");
  struct tm timeinfo;
  while (!getLocalTime(&timeinfo)) {
    Serial.print(".");
    delay(500);
  }
  Serial.println("\nTime synchronized!");

  // Check server availability
  Serial.println("Checking server availability...");
  while (!pingServer()) {
    Serial.println("Server is not reachable. Retrying in 10 seconds...");
    delay(10000);
  }

  Serial.println("Server is reachable.");
}

void loop() {
  // Monitor Wi-Fi connection
  checkWiFiConnection();

  // --- Read ADC Values ---
  int rawVoltage = analogRead(voltagePin);
  int rawCurrent = analogRead(currentPin);

  // --- Convert ADC to real-world values ---
  float voltageMeasured = (rawVoltage * ADC_REF_VOLTAGE) / ADC_RESOLUTION;
  float actualVoltage = voltageMeasured * VOLTAGE_DIVIDER_RATIO;

  float currentVoltage = (rawCurrent * ADC_REF_VOLTAGE) / ADC_RESOLUTION;
  float currentAmps = currentVoltage / CURRENT_SENSITIVITY;

  unsigned long currentTime = millis();

  // --- Detect voltage event ---
  if (actualVoltage > VOLTAGE_THRESHOLD &&
      fabs(actualVoltage - lastVoltage) > VOLTAGE_CHANGE_TOLERANCE) {

    if (!sessionActive) {
      // Start a new session
      Serial.println("\n--- Voltage Event Session Started ---");
      sessionActive = true;
      eventCounter = 0;
      totalVoltage = 0.0;
      totalCurrent = 0.0;
    }

    // Update session data
    eventCounter++;
    totalVoltage += actualVoltage;
    totalCurrent += currentAmps;
    lastDetectionTime = currentTime;

    Serial.print("Event #");
    Serial.print(eventCounter);
    Serial.print(" | Voltage: ");
    Serial.print(actualVoltage, 3);
    Serial.print(" V | Current: ");
    Serial.print(currentAmps, 3);
    Serial.println(" A");

    // Update last voltage reading
    lastVoltage = actualVoltage;
  }

  // --- Check if session should end ---
  if (sessionActive && (currentTime - lastDetectionTime > SESSION_TIMEOUT)) {
    // Session has ended, prepare data
    Serial.println("\n--- Session Summary ---");
    Serial.print("Total Events: ");
    Serial.println(eventCounter);
    Serial.print("Total Voltage (sum): ");
    Serial.print(totalVoltage, 3);
    Serial.println(" V");
    Serial.print("Total Current (sum): ");
    Serial.print(totalCurrent, 3);
    Serial.println(" A");
    Serial.println("-----------------------\n");

    // Prepare data for sending (using totals for voltage and current)
    steps = eventCounter;
    voltage = totalVoltage;
    current = totalCurrent;
    batteryHealth = 0.0; // Placeholder, to be fixed later

    readyToSend = true;
    Serial.println("Data ready. Press the button on pin 13 to send.");

    // Reset for next session
    sessionActive = false;
    lastVoltage = 0.0;
  }

  // When button is pressed, send data to unified endpoint
  if (readyToSend && digitalRead(buttonPin) == LOW) {
    delay(200); // Debounce

    String datetime = getCurrentDateTime();

    // Send all data in a single request
    sendAllData(
      steps,
      datetime,
      voltage,
      current,
      batteryHealth
    );

    readyToSend = false;
    Serial.println("Waiting for next session...");
  }

  delay(50); // Reduce CPU usage slightly
}

// ====== Helper Functions ======

// Get current datetime as ISO 8601 string
String getCurrentDateTime() {
  struct tm timeinfo;
  if (!getLocalTime(&timeinfo)) {
    Serial.println("Failed to obtain time");
    return "1970-01-01T00:00";
  }

  char buf[20];
  strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M", &timeinfo);
  return String(buf);
}

// Connect to Wi-Fi
void connectToWiFi() {
  Serial.print("Connecting to WiFi");
  WiFi.begin(ssid, password);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
    attempts++;

    if (attempts >= 60) { // 30 seconds timeout
      Serial.println("\nFailed to connect to Wi-Fi. Restarting...");
      ESP.restart();
    }
  }

  Serial.println("\nWiFi connected successfully!");
  Serial.print("IP Address: ");
  Serial.println(WiFi.localIP());
}

// Monitor and auto-reconnect Wi-Fi
void checkWiFiConnection() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("Wi-Fi disconnected! Attempting to reconnect...");

    WiFi.disconnect();
    WiFi.begin(ssid, password);

    int retryCount = 0;
    while (WiFi.status() != WL_CONNECTED && retryCount < 10) {
      delay(500);
      Serial.print(".");
      retryCount++;
    }

    if (WiFi.status() == WL_CONNECTED) {
      Serial.println("\nReconnected to Wi-Fi!");
    } else {
      Serial.println("\nFailed to reconnect to Wi-Fi. Retrying later...");
    }
  }
}

// Ping the server to check connectivity
bool pingServer() {
  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    http.begin(pingURL);
    int httpResponseCode = http.GET();

    if (httpResponseCode == 200) {
      String response = http.getString();
      Serial.print("Ping response: ");
      Serial.println(response);
      http.end();
      return true;
    } else {
      Serial.print("Ping failed, code: ");
      Serial.println(httpResponseCode);
    }
    http.end();
  } else {
    Serial.println("WiFi not connected");
  }
  return false;
}

// Send all data to the unified /add-log endpoint
void sendAllData(int steps, String datetime, float voltage, float current, float batteryHealth) {
  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    http.begin(serverURL);
    http.addHeader("Content-Type", "application/x-www-form-urlencoded");

    // Combine everything into one payload
    String postData = "steps=" + String(steps) +
                      "&datetime=" + datetime +
                      "&raw_voltage=" + String(voltage, 2) +
                      "&raw_current=" + String(current, 2) +
                      "&battery_health=" + String(batteryHealth, 2);

    Serial.println("Sending data to server:");
    Serial.println(postData);

    int httpResponseCode = http.POST(postData);

    Serial.print("POST /add-log Response Code: ");
    Serial.println(httpResponseCode);

    if (httpResponseCode > 0) {
      Serial.println("Server Response:");
      Serial.println(http.getString());
    } else {
      Serial.println("Error sending POST to /add-log");
    }

    http.end();
  } else {
    Serial.println("WiFi not connected");
  }
}