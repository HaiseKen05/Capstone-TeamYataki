#include <WiFi.h>
#include <HTTPClient.h>
#include <time.h>  // NTP time

// WiFi Credentials
const char* ssid = "ESP32-AP";           // WIFI SSID
const char* password = "ESP32-Connect";  // WIFI Password

// Server URLs
const char* serverBaseURL = "http://192.168.254.109:5000";
const char* pingRoute = "/ping";
const char* dataRoute = "/add-log";

const int buttonPin = 13;

// Data variables
String inputSteps;
String inputVoltage;
String inputCurrent;

bool readyToSend = false;
bool serverOnline = false; // Flag to track server status

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
  Serial.println("\nWiFi connected");

  // Initialize NTP
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

  // Handle serial input for steps, voltage, current
  if (Serial.available()) {
    String input = Serial.readStringUntil('\n');
    input.trim();

    if (stage == 0) {
      inputSteps = input;
      Serial.println("Enter raw voltage (e.g., 3.75):");
      stage++;
    } else if (stage == 1) {
      inputVoltage = input;
      Serial.println("Enter raw current (e.g., 1.2):");
      stage++;
    } else if (stage == 2) {
      inputCurrent = input;
      Serial.println("Data is ready. Press the button on pin 13 to send.");
      readyToSend = true;
      stage = 0;
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
      inputCurrent.toFloat()
    );

    readyToSend = false;
    Serial.println("Enter number of steps:");
  }
}

// =========================
// Helper Functions
// =========================

// Get current date and time
String getCurrentDateTime() {
  struct tm timeinfo;
  if (!getLocalTime(&timeinfo)) {
    Serial.println("Failed to obtain time");
    return "1970-01-01T00:00"; // fallback
  }

  char buf[20];
  strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M", &timeinfo);
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

// Send sensor data to server
void sendSensorData(int steps, String datetime, float voltage, float current) {
  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;

    String fullDataURL = String(serverBaseURL) + dataRoute;
    http.begin(fullDataURL);
    http.addHeader("Content-Type", "application/x-www-form-urlencoded");

    // Format POST payload
    String postData = "steps=" + String(steps) +
                      "&datetime=" + datetime +
                      "&raw_voltage=" + String(voltage) +
                      "&raw_current=" + String(current);

    int httpResponseCode = http.POST(postData);

    Serial.print("POST Response Code: ");
    Serial.println(httpResponseCode);

    if (httpResponseCode > 0) {
      String response = http.getString();
      Serial.println("Server Response:");
      Serial.println(response);
    } else {
      Serial.println("Error sending POST");
    }

    http.end();
  } else {
    Serial.println("WiFi not connected");
  }
}
