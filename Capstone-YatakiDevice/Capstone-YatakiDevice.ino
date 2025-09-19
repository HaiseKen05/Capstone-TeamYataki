#include <WiFi.h>
#include <HTTPClient.h>
#include <time.h>  // NTP time

// Wi-Fi Credentials
const char* ssid = "ESP32-AP";
const char* password = "ESP32-Connect";

// API Endpoints
const char* serverURL        = "http://192.168.254.107:5000/add-log";
const char* pingURL          = "http://192.168.254.107:5000/ping";
const char* batteryHealthURL = "http://192.168.254.107:5000/api/v1/add-battery-health";

// Button
const int buttonPin = 13;

// User inputs
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

  // Initialize NTP
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
      Serial.println("Data is ready. Press the button on pin 13 to send.");
      readyToSend = true;
      stage = 0;
    }
  }

  // When button is pressed, send all data to both endpoints
  if (readyToSend && digitalRead(buttonPin) == LOW) {
    delay(200); // debounce

    String datetime = getCurrentDateTime();

    // Send base log data to /add-log
    sendSensorData(
      inputSteps.toInt(),
      datetime,
      inputVoltage.toFloat(),
      inputCurrent.toFloat()
    );

    // Send battery health data to /api/v1/add-battery-health
    sendBatteryHealth(inputBatteryHealth.toFloat(), datetime);

    readyToSend = false;
    Serial.println("Enter number of steps:");
  }
}

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

// Connect to Wi-Fi initially
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

// Continuously check if Wi-Fi is still connected
void checkWiFiConnection() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("Wi-Fi disconnected! Attempting to reconnect...");

    WiFi.disconnect();
    WiFi.begin(ssid, password);

    int retryCount = 0;
    while (WiFi.status() != WL_CONNECTED && retryCount < 10) { // 5 seconds max
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

// Function: Ping the server
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

// Send data to /add-log
void sendSensorData(int steps, String datetime, float voltage, float current) {
  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    http.begin(serverURL);
    http.addHeader("Content-Type", "application/x-www-form-urlencoded");

    String postData = "steps=" + String(steps) +
                      "&datetime=" + datetime +
                      "&raw_voltage=" + String(voltage) +
                      "&raw_current=" + String(current);

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

// Send data to /api/v1/add-battery-health
void sendBatteryHealth(float batteryHealth, String datetime) {
  if (WiFi.status() == WL_CONNECTED) {
    HTTPClient http;
    http.begin(batteryHealthURL);
    http.addHeader("Content-Type", "application/json");

    // Create JSON payload
    String jsonPayload = "{\"datetime\": \"" + datetime + "\", \"battery_health\": " + String(batteryHealth, 2) + "}";

    int httpResponseCode = http.POST(jsonPayload);

    Serial.print("POST /api/v1/add-battery-health Response Code: ");
    Serial.println(httpResponseCode);

    if (httpResponseCode > 0) {
      Serial.println("Server Response:");
      Serial.println(http.getString());
    } else {
      Serial.println("Error sending POST to /api/v1/add-battery-health");
    }

    http.end();
  } else {
    Serial.println("WiFi not connected");
  }
}
