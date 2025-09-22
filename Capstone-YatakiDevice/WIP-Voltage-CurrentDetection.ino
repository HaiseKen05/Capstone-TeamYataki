// ============================================
// MAX471 + ESP32
// Voltage Event Session Tracker
// ============================================

// --- Pin Assignments ---
const int voltagePin = 36; // VT pin connected to GPIO36 (VP)
const int currentPin = 34; // AT pin connected to GPIO34

// --- ESP32 ADC Specifications ---
const float ADC_REF_VOLTAGE = 3.3;   // Max ADC voltage
const int ADC_RESOLUTION = 4095;     // 12-bit ADC (0 - 4095)

// --- MAX471 Specifications ---
const float CURRENT_SENSITIVITY = 1.0; // 1V per 1A

// --- Voltage Divider Settings (VT) ---
// Example: R1 = 30kΩ, R2 = 10kΩ → scale factor = 4.0
const float VOLTAGE_DIVIDER_RATIO = 4.0;

// --- Detection Settings ---
const float VOLTAGE_THRESHOLD = 0.1; // Minimum voltage to trigger detection (V)
const float VOLTAGE_CHANGE_TOLERANCE = 0.05; // Prevents duplicate triggers (V)

// --- Session Management ---
const unsigned long SESSION_TIMEOUT = 10000; // 10 seconds in ms

// --- Tracking Variables ---
float lastVoltage = 0.0;
unsigned long lastDetectionTime = 0;
int eventCounter = 0;
float totalVoltage = 0.0;
float totalCurrent = 0.0;
bool sessionActive = false;

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("MAX471 + ESP32 Voltage Session Tracker");
  Serial.println("Waiting for voltage events...");
  Serial.println("--------------------------------------");
}

void loop() {
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
    // Session has ended, print summary
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

    // Reset for next session
    sessionActive = false;
    lastVoltage = 0.0;
  }

  delay(50); // Reduce CPU usage slightly
}
