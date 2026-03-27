<?php
/**
 * ==============================================
 * FILE: rag_endpoint.php
 * PURPOSE: Moodle -> FastAPI proxy + history persistence
 * ==============================================
 *
 * Responsibilities:
 * - Require login + sesskey
 * - Receive question + courseid
 * - Call FastAPI /ask (running inside the same container on 127.0.0.1:8001)
 * - Always return valid JSON
 * - Always persist chat history (user + assistant) in Moodle DB
 */

require_once(__DIR__ . '/../../config.php');

require_login();
require_sesskey();

$question = required_param('question', PARAM_TEXT);
$courseid = required_param('courseid', PARAM_INT);
$userid = $USER->id;

// ----------------------------------------------
// History manager (server-side persistence)
// ----------------------------------------------
require_once($CFG->dirroot . '/blocks/llmassistant/classes/local/history_manager.php');
use block_llmassistant\local\history_manager;

// Save user message always
history_manager::save_message($userid, $courseid, 'user', $question);

// ----------------------------------------------
// Call FastAPI (inside same container)
// ----------------------------------------------
$apiurl = "http://127.0.0.1:8001/ask";

$payload = json_encode([
    "question" => $question,
    "courseid" => $courseid,
    "userid" => $userid,
]);

$ch = curl_init($apiurl);
curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
curl_setopt($ch, CURLOPT_HTTPHEADER, ["Content-Type: application/json"]);
curl_setopt($ch, CURLOPT_POST, true);
curl_setopt($ch, CURLOPT_POSTFIELDS, $payload);
curl_setopt($ch, CURLOPT_TIMEOUT, 120);

$response = curl_exec($ch);
$httpcode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
$curlerr = curl_error($ch);
curl_close($ch);

header("Content-Type: application/json");

// ----------------------------------------------
// Error handling: always return valid JSON
// ----------------------------------------------
if ($response === false || $httpcode >= 400) {
    $msg = "Error: the RAG API returned HTTP $httpcode.";
    if (!empty($curlerr)) {
        $msg .= " Curl error: $curlerr";
    }
    $out = ["answer" => $msg . " Check /tmp/rag_api.log.", "sources" => []];

    // Save assistant message even on error (so history reflects what happened)
    history_manager::save_message($userid, $courseid, 'assistant', $out["answer"]);

    echo json_encode($out);
    exit;
}

// ----------------------------------------------
// Save assistant message (happy path)
// ----------------------------------------------
$decoded = json_decode($response, true);
$answer = is_array($decoded) ? ($decoded["answer"] ?? "") : "";
history_manager::save_message($userid, $courseid, 'assistant', $answer);

echo $response;