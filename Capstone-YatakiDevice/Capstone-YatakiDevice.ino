#include <WiFi.h>
#include <HTTPClient.h>
#include <time.h>  // NTP time

const char* ssid = ""; // WIFI SSID
const char* password = ""; // WIFI Password

const char* serverURL = "http://0.0.0.1:5000/add-log"; // Change this to the appropriate Flask route

const int buttonPin = 13;

String inputSteps;
String inputVoltage;
String inputCurrent;

bool readyToSend = false;

void setup() {
  Serial.begin(115200);
  pinMode(buttonPin, INPUT_PULLUP);

  // Connect to Wi-Fi
  WiFi.begin(ssid, password);
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi connected");

  // Initialize NTP
  configTime(8 * 3600, 0, "pool.ntp.org", "time.nist.gov"); // UTC timezone

  Serial.println("Waiting for NTP time...");
  struct tm timeinfo;
  while (!getLocalTime(&timeinfo)) {
    Serial.print(".");
    delay(500);
  }
  Serial.println("\nTime synchronized!");

  Serial.println("Enter number of steps:");
}

void loop() {
  static int stage = 0;

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
