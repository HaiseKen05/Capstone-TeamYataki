<?php
// insert_data.php

// --- 1. Get the POST data ---
$steps = isset($_POST['steps']) ? intval($_POST['steps']) : null;
$datetime = isset($_POST['datetime']) ? $_POST['datetime'] : null;
$raw_voltage = isset($_POST['raw_voltage']) ? floatval($_POST['raw_voltage']) : null;
$raw_current = isset($_POST['raw_current']) ? floatval($_POST['raw_current']) : null;

// --- 2. Simple validation ---
if ($steps === null || !$datetime || $raw_voltage === null || $raw_current === null) {
    http_response_code(400); // Bad Request
    echo "Missing required fields.";
    exit;
}

// --- 3. Connect to the database ---
$servername = "localhost";
$username = "your_db_username";  // 🔁 Replace this
$password = "your_db_password";  // 🔁 Replace this
$dbname = "Capstone";

$conn = new mysqli($servername, $username, $password, $dbname);

// Check for connection error
if ($conn->connect_error) {
    http_response_code(500); // Internal Server Error
    echo "Database connection failed: " . $conn->connect_error;
    exit;
}

// --- 4. Insert data using prepared statements ---
$stmt = $conn->prepare("INSERT INTO sensor_data (steps, datetime, raw_voltage, raw_current) VALUES (?, ?, ?, ?)");
$stmt->bind_param("issd", $steps, $datetime, $raw_voltage, $raw_current);

if ($stmt->execute()) {
    echo "Data inserted successfully.";
} else {
    http_response_code(500);
    echo "Failed to insert data: " . $stmt->error;
}

// --- 5. Close connections ---
$stmt->close();
$conn->close();
?>
