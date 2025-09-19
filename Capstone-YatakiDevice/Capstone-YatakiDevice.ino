#include <WiFi.h>
#include <HTTPClient.h>
#include <time.h>  // NTP time

// ====== Wi-Fi Credentials ======
const char* ssid = "ESP32-AP";
const char* password = "ESP32-Connect";

// ====== API Endpoint ======
const char* serverURL = "http://192.168.254.107:5000/add-log";
const char* pingURL   = "http://192.168.254.107:5000/ping";

// ====== Hardware Config ======
const int buttonPin = 13; // Button to trigger data sending

// ====== User Inputs ======
String inputSteps;
String inputVoltage;
String inputCurrent;
String inputBatteryHealth;

bool readyToSend = false;

void setup() {
  Serial.begin(115200);
  pinMode(buttonPin, INPUT_PULLUP);
  delay(1000);

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
  Serial.println("Enter number of steps:");
}

void loop() {
  // Monitor Wi-Fi connection
  checkWiFiConnection();

  static int stage = 0;

  // Handle serial input step-by-step
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
      Serial.println("Enter battery health (e.g., 87.5):");
      stage++;
    } else if (stage == 3) {
      inputBatteryHealth = input;
      Serial.println("Data ready. Press the button on pin 13 to send.");
      readyToSend = true;
      stage = 0;
    }
  }

  // When button is pressed, send data to unified endpoint
  if (readyToSend && digitalRead(buttonPin) == LOW) {
    delay(200); // Debounce

    String datetime = getCurrentDateTime();

    // Send all data in a single request
    sendAllData(
      inputSteps.toInt(),
      datetime,
      inputVoltage.toFloat(),
      inputCurrent.toFloat(),
      inputBatteryHealth.toFloat()
    );

    readyToSend = false;
    Serial.println("Enter number of steps:");
  }
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
