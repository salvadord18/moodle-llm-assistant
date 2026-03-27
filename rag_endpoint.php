<?php
// rag_endpoint.php
// Always return JSON (even on errors). English-only comments/messages.

require_once(__DIR__ . '/../../config.php');

require_login();
require_sesskey();

header('Content-Type: application/json; charset=utf-8');

$question = required_param('question', PARAM_TEXT);
$courseid = required_param('courseid', PARAM_INT);

// IMPORTANT: FastAPI runs inside the SAME webserver container.
// Use 127.0.0.1:8001, not localhost on host, not host.docker.internal.
$apiurl = 'http://127.0.0.1:8001/ask';

$payload = json_encode([
    'question' => $question,
    'courseid' => $courseid,
    'userid'   => $USER->id,
]);

$ch = curl_init($apiurl);
curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
curl_setopt($ch, CURLOPT_HTTPHEADER, ['Content-Type: application/json']);
curl_setopt($ch, CURLOPT_POST, true);
curl_setopt($ch, CURLOPT_POSTFIELDS, $payload);
curl_setopt($ch, CURLOPT_CONNECTTIMEOUT, 5);
curl_setopt($ch, CURLOPT_TIMEOUT, 60);

$response = curl_exec($ch);

if ($response === false) {
    $err = curl_error($ch);
    curl_close($ch);
    echo json_encode([
        'answer'  => 'Error: cannot reach the RAG API. Make sure uvicorn is running on 127.0.0.1:8001.',
        'sources' => [],
        'debug'   => 'cURL error: ' . $err,
    ]);
    exit;
}

$httpcode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
curl_close($ch);

// If FastAPI returned an error, still respond with valid JSON to the browser.
if ($httpcode < 200 || $httpcode >= 300) {
    echo json_encode([
        'answer'  => 'Error: the RAG API returned HTTP ' . $httpcode . '. Check /tmp/rag_api.log.',
        'sources' => [],
        'debug'   => 'Raw response: ' . $response,
    ]);
    exit;
}

// Validate JSON from FastAPI
$data = json_decode($response, true);
if (!is_array($data)) {
    echo json_encode([
        'answer'  => 'Error: invalid JSON from the RAG API.',
        'sources' => [],
        'debug'   => 'Raw response: ' . $response,
    ]);
    exit;
}

// Ensure stable output shape
echo json_encode([
    'answer'  => $data['answer'] ?? 'No answer returned.',
    'sources' => $data['sources'] ?? [],
]);
