<?php
define('AJAX_SCRIPT', true);

/**
 * Start output buffering as early as possible so that
 * any accidental output (BOM/whitespace/notices) does not corrupt JSON.
 */
ob_start();

require_once(__DIR__ . '/../../config.php');
require_once($CFG->dirroot . '/blocks/llmassistant/classes/local/history_manager.php');

@ini_set('display_errors', '0');
@ini_set('html_errors', '0');
header('Content-Type: application/json; charset=utf-8');

try {
    require_login();
    require_sesskey();

    $question = required_param('question', PARAM_TEXT);
    $courseid = required_param('courseid', PARAM_INT);

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

        if (ob_get_length()) {
            ob_clean();
        }

        echo json_encode([
            'answer'  => 'Error: cannot reach the RAG API. Make sure uvicorn is running on 127.0.0.1:8001.',
            'sources' => [],
            'debug'   => $err,
        ], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
        exit;
    }

    $httpcode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);

    if ($httpcode < 200 || $httpcode >= 300) {
        if (ob_get_length()) {
            ob_clean();
        }

        echo json_encode([
            'answer'  => 'Error: the RAG API returned HTTP ' . $httpcode . '. Check /tmp/rag_api.log.',
            'sources' => [],
            'debug'   => $response,
        ], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
        exit;
    }

    $data = json_decode($response, true);

    if (!is_array($data)) {
        if (ob_get_length()) {
            ob_clean();
        }

        echo json_encode([
            'answer'  => 'Error: invalid JSON from the RAG API.',
            'sources' => [],
            'debug'   => $response,
        ], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
        exit;
    }

    $answer = trim((string)($data['answer'] ?? ''));
    if ($answer === '') {
        $answer = 'Error: empty answer returned by RAG backend.';
    }

    $sources = $data['sources'] ?? [];

    // Persist history server-side.
    \block_llmassistant\local\history_manager::save_message($USER->id, $courseid, 'user', $question);
    \block_llmassistant\local\history_manager::save_message($USER->id, $courseid, 'assistant', $answer);

    if (ob_get_length()) {
        ob_clean();
    }

    echo json_encode([
        'answer'  => $answer,
        'sources' => $sources,
    ], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;

} catch (Throwable $e) {
    if (ob_get_length()) {
        ob_clean();
    }

    echo json_encode([
        'answer'  => 'Error: request failed (server-side).',
        'sources' => [],
        'debug'   => get_class($e) . ': ' . $e->getMessage(),
    ], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}
