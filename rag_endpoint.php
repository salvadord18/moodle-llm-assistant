<?php
require_once(__DIR__ . '/../../config.php');

require_sesskey();
require_login();

$question = required_param('question', PARAM_TEXT);
$courseid = required_param('courseid', PARAM_INT);

$userid = $USER->id;

// URL do teu servidor RAG (FastAPI)
$apiurl = "http://127.0.0.1:8001/ask"; 

$payload = json_encode([
    "question" => $question,
    "courseid" => $courseid,
    "userid" => $userid
]);

$ch = curl_init($apiurl);
curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
curl_setopt($ch, CURLOPT_HTTPHEADER, ["Content-Type: application/json"]);
curl_setopt($ch, CURLOPT_POST, true);
curl_setopt($ch, CURLOPT_POSTFIELDS, $payload);

$response = curl_exec($ch);
curl_close($ch);

header("Content-Type: application/json");
echo $response;