<?php
define('AJAX_SCRIPT', true);

require_once(__DIR__ . '/../../config.php');
require_once($CFG->dirroot . '/blocks/llmassistant/classes/local/history_manager.php');

@ini_set('display_errors', '0');
@ini_set('html_errors', '0');
header('Content-Type: application/json; charset=utf-8');

ob_start();

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
        ob_end_clean();

        echo json_encode([
            'answer'  => 'Error: cannot reach the RAG API. Make sure uvicorn is running on 127.0.0.1:8001.',
            'sources' => [],
            'debug'   => $err,
        ]);
        exit;
    }

    $httpcode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);

    if ($httpcode < 200 || $httpcode >= 300) {
        ob_end_clean();
        echo json_encode([
            'answer'  => 'Error: the RAG API returned HTTP ' . $httpcode . '. Check /tmp/rag_api.log.',
            'sources' => [],
            'debug'   => $response,
        ]);
        exit;
    }

    $data = json_decode($response, true);
    if (!is_array($data)) {
        ob_end_clean();
        echo json_encode([
            'answer'  => 'Error: invalid JSON from the RAG API.',
            'sources' => [],
            'debug'   => $response,
        ]);
        exit;
    }

    $answer = $data['answer'] ?? 'No answer returned.';
    $sources = $data['sources'] ?? [];

    // Persist history server-side.
    \block_llmassistant\local\history_manager::add_message($USER->id, $courseid, 'user', $question);
    \block_llmassistant\local\history_manager::add_message($USER->id, $courseid, 'assistant', $answer);

    ob_end_clean();
    echo json_encode([
        'answer'  => $answer,
        'sources' => $sources,
    ]);
    exit;

} catch (Throwable $e) {
    ob_end_clean();
    echo json_encode([
        'answer'  => 'Error: request failed (server-side).',
        'sources' => [],
        'debug'   => get_class($e) . ': ' . $e->getMessage(),
    ]);
    exit;
}