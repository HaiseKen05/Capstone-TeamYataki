#include <WiFi.h>
#include <HTTPClient.h>
#include <time.h>  // For NTP time sync
#include <ArduinoJson.h> // For creating JSON payload

// ========================
// WiFi Configuration
// ========================
const char* ssid = "ESP32-AP";           // WiFi SSID
const char* password = "ESP32-Connect";  // WiFi Password

// ========================
// Server Configuration
// ========================
const char* serverBaseURL = "http://192.168.254.109:5000";
const char* pingRoute = "/ping";
const char* dataRoute = "/api/v1/add-log";

// ========================
// Hardware Configuration
// ========================
const int buttonPin = 13; // Push button for sending data

// ========================
// Data Variables
// ========================
String inputSteps;
String inputVoltage;
String inputCurrent;
String inputTempVoltage; // For temp_data (battery health calculation only)

bool readyToSend = false;
bool serverOnline = false; // Track server availability

void setup() {
  Serial.begin(115200);
  pinMode(buttonPin, INPUT_PULLUP);

  // Connect to Wi-Fi
  Serial.print("Connecting to WiFi");
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi connected!");

  // Initialize NTP for accurate datetime
  Serial.println("Syncing time with NTP...");
  configTime(8 * 3600, 0, "pool.ntp.org", "time.nist.gov"); // UTC+8 timezone

  struct tm timeinfo;
  while (!getLocalTime(&timeinfo)) {
    Serial.print(".");
    delay(500);
  }
  Serial.println("\nTime synchronized!");

  // After time sync, immediately ping the server
  Serial.println("Checking server availability...");

  while (!serverOnline) {
    serverOnline = pingServer();
    if (!serverOnline) {
      Serial.println("Server offline, retrying in 5 seconds...");
      delay(5000);
    }
  }

  Serial.println("Server is online! Ready to collect data.");
  Serial.println("Enter number of steps:");
}

void loop() {
  static int stage = 0;

  // Handle serial input for steps, voltage, current, temp voltage
  if (Serial.available()) {
    String input = Serial.readStringUntil('\n');
    input.trim();

    if (stage == 0) {
      inputSteps = input;
      Serial.println("Enter raw voltage (e.g., 3.75):");
      stage++;
    } 
    else if (stage == 1) {
      inputVoltage = input;
      Serial.println("Enter raw current (e.g., 1.2):");
      stage++;
    } 
    else if (stage == 2) {
      inputCurrent = input;
      Serial.println("Enter temp voltage (for battery health, e.g., 4.05):");
      stage++;
    }
    else if (stage == 3) {
      inputTempVoltage = input;
      Serial.println("Data is ready. Press the button on pin 13 to send.");
      readyToSend = true;
      stage = 0; // Reset for next input cycle
    }
  }

  // When button is pressed, send the data
  if (readyToSend && digitalRead(buttonPin) == LOW) {
    delay(200); // debounce

    String datetime = getCurrentDateTime();

    sendSensorData(
      inputSteps.toInt(),
      datetime,
      inputVoltage.toFloat(),
      inputCurrent.toFloat(),
      inputTempVoltage.toFloat()
    );

    readyToSend = false;
    Serial.println("Enter number of steps:");
  }
}

// =========================
// Helper Functions
// =========================

// Get current date and time in ISO 8601 format
String getCurrentDateTime() {
  struct tm timeinfo;
  if (!getLocalTime(&timeinfo)) {
    Serial.println("Failed to obtain time");
    return "1970-01-01T00:00"; // fallback
  }

  char buf[25];
  strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%S", &timeinfo);
  return String(buf);
}

// Ping the server before sending data
bool pingServer() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi not connected");
    return false;
  }

  HTTPClient http;
  String fullPingURL = String(serverBaseURL) + pingRoute;

  Serial.print("Pinging server: ");
  Serial.println(fullPingURL);

  http.begin(fullPingURL);
  int httpResponseCode = http.GET();

  Serial.print("Ping response code: ");
  Serial.println(httpResponseCode);

  if (httpResponseCode == 200) {
    String response = http.getString();
    Serial.println("Ping response: " + response);
    http.end();
    return true;
  } else {
    Serial.println("Failed to ping server.");
    http.end();
    return false;
  }
}

// Send sensor data with temp_data containing ONLY temp voltage
void sendSensorData(int steps, String datetime, float voltage, float current, float tempVoltage) {
  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    String fullDataURL = String(serverBaseURL) + dataRoute;
    http.begin(fullDataURL);
    http.addHeader("Content-Type", "application/json");

    // Create JSON payload
    DynamicJsonDocument doc(1024);
    doc["steps"] = steps;
    doc["datetime"] = datetime;
    doc["raw_voltage"] = voltage;
    doc["raw_current"] = current;

    // temp_data now only contains temp_voltage
    JsonObject tempData = doc.createNestedObject("temp_data");
    tempData["temp_voltage"] = tempVoltage;

    // Convert JSON to string
    String jsonPayload;
    serializeJson(doc, jsonPayload);

    Serial.println("Sending JSON payload:");
    Serial.println(jsonPayload);

    // Send POST request
    int httpResponseCode = http.POST(jsonPayload);

    Serial.print("POST Response Code: ");
    Serial.println(httpResponseCode);

    if (httpResponseCode > 0) {
      String response = http.getString();
      Serial.println("Server Response:");
      Serial.println(response);
    } else {
      Serial.println("Error sending POST request");
    }

    http.end();
  } else {
    Serial.println("WiFi not connected");
  }
}
