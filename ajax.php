<?php
require_once(__DIR__ . '/../../config.php');

require_sesskey();
require_login();

error_reporting(E_ALL);
ini_set('display_errors', 1);

$question = required_param('question', PARAM_TEXT);

$ragurl = 'http://host.docker.internal:8001/ask'; // Docker Desktop host alias.
$payload = json_encode([
    'question' => $question
]);

$ch = curl_init($ragurl);
curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
curl_setopt($ch, CURLOPT_HTTPHEADER, ['Content-Type: application/json']);
curl_setopt($ch, CURLOPT_POST, true);
curl_setopt($ch, CURLOPT_POSTFIELDS, $payload);
curl_setopt($ch, CURLOPT_TIMEOUT, 120);

$response = curl_exec($ch);

if ($response === false) {
    $err = curl_error($ch);
    curl_close($ch);
    header('Content-Type: application/json');
    echo json_encode(['error' => 'cURL error: ' . $err]);
    die();
}

$httpcode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
curl_close($ch);

if ($httpcode >= 400) {
    header('Content-Type: application/json');
    echo json_encode(['error' => 'Ollama HTTP error ' . $httpcode, 'raw' => $response]);
    die();
}

$data = json_decode($response, true);

header('Content-Type: application/json');

if (!is_array($data)) {
    echo json_encode(['error' => 'Invalid JSON from Ollama', 'raw' => $response]);
    die();
}

// Ollama /api/generate typically returns 'response' in JSON.
echo json_encode(['answer' => $data['response'] ?? '(no response field)', 'raw' => $data]);