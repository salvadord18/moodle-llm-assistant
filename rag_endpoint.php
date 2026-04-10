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
    $userid = $USER->id;

    $apiurl = 'http://127.0.0.1:8001/ask';

    /**
     * Load recent conversation history so the Python backend
     * can resolve follow-up questions like "his email", "that deadline", etc.
     *
     * history_endpoint.php already shows that history_manager::load_history($userid, $courseid)
     * exists and returns role/message/timecreated records. [1](https://liveeduisegiunl-my.sharepoint.com/personal/20240597_novaims_unl_pt/Documents/Microsoft%20Copilot%20Chat%20Files/rag_endpoint.php)
     */
    $historyrows = \block_llmassistant\local\history_manager::load_history($userid, $courseid);

    // Keep only the last few turns to avoid making the payload too large.
    $historyrows = array_slice($historyrows, -6);

    $history = [];
    foreach ($historyrows as $row) {
        $history[] = [
            'role' => $row->role ?? 'user',
            'message' => $row->message ?? '',
        ];
    }

    $payload = json_encode([
        'question' => $question,
        'courseid' => $courseid,
        'userid'   => $userid,
        'history'  => $history,
    ], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);

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

    // Persist the new user turn + assistant turn.
    \block_llmassistant\local\history_manager::save_message($userid, $courseid, 'user', $question);
    $sourcesjson = json_encode($sources, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);

    \block_llmassistant\local\history_manager::save_message(
        $userid,
        $courseid,
        'assistant',
        $answer,
        $sourcesjson
    );

    if (ob_get_length()) {
        ob_clean();
    }

    $out = [
        'answer'  => $answer,
        'sources' => $sources,
    ];

    // During development, forward backend debug info if present.
    if (!empty($data['debug'])) {
        $out['debug'] = $data['debug'];
    }

    echo json_encode($out, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
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
