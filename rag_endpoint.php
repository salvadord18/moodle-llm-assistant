<?php
define('AJAX_SCRIPT', true);

/**
 * Start output buffering as early as possible so that
 * any accidental output (BOM/whitespace/notices) does not corrupt JSON.
 */
ob_start();

require_once(__DIR__ . '/../../config.php');
require_once($CFG->dirroot . '/blocks/llmassistant/classes/local/history_manager.php');

/**
 * Normalizes text to use in the files/folders names.
 */
function llmassistant_slugify(string $text, int $maxlen = 40): string {
    $text = core_text::strtolower(trim($text));
    $text = iconv('UTF-8', 'ASCII//TRANSLIT//IGNORE', $text);
    $text = preg_replace('/[^a-z0-9]+/i', '_', $text);
    $text = trim($text, '_');

    if ($text === '') {
        $text = 'query';
    }

    if (core_text::strlen($text) > $maxlen) {
        $text = core_text::substr($text, 0, $maxlen);
        $text = rtrim($text, '_');
    }

    return $text;
}

/**
 * Tries to extract a short and idetificable keyword from the question.
 */
function llmassistant_question_keyword(string $question): string {
    $q = core_text::strtolower(trim($question));
    $q = iconv('UTF-8', 'ASCII//TRANSLIT//IGNORE', $q);
    $tokens = preg_split('/[^a-z0-9]+/i', $q);

    $stopwords = [
        // English
        'what','is','are','the','of','this','that','who','how','when','where','why',
        'can','could','should','would','do','does','did','a','an','and','or','to','in','on','for','with',
        'course',

        // Portuguese
        'qual','quais','o','a','os','as','de','do','da','dos','das','e','é','sao',
        'como','quando','onde','porque','por','para','com','um','uma','que'
    ];

    $useful = [];
    foreach ($tokens as $t) {
        $t = trim($t);
        if ($t === '' || in_array($t, $stopwords, true)) {
            continue;
        }

        // ignore very short tokens unless they are meaningful acronyms like dbms
        if (strlen($t) <= 2 && !in_array($t, ['db', 'ai', 'ml'], true)) {
            continue;
        }

        $useful[] = $t;

        if (count($useful) >= 4) {
            break;
        }
    }

    if (!$useful) {
        return 'query';
    }

    return llmassistant_slugify(implode('_', $useful), 50);
}

/**
 * Resolves the folder where to save the files
 */
function llmassistant_results_dir(int $courseid): string {
    global $CFG, $DB;

    $base = $CFG->dataroot . '/llmassistant_results';

    if ($courseid === 0) {
        $dir = $base . '/global';
        check_dir_exists($dir, true, true);
        return $dir;
    }

    $course = $DB->get_record('course', ['id' => $courseid], 'id, shortname, fullname', IGNORE_MISSING);

    if ($course) {
        $name = !empty($course->shortname) ? $course->shortname : $course->fullname;
        $slug = llmassistant_slugify($name, 50);
        $dir = $base . '/course_' . $courseid . '_' . $slug;
    } else {
        $dir = $base . '/course_' . $courseid;
    }

    check_dir_exists($dir, true, true);
    return $dir;
}

/**
 * Saves a JSON snapshot from the test.
 */
function llmassistant_save_result_snapshot(
    int $userid,
    int $courseid,
    string $question,
    array $requestpayload,
    array $backenddata,
    array $finaloutput
): ?string {
    $dir = llmassistant_results_dir($courseid);

    $keyword = llmassistant_question_keyword($question);
    $timestamp = date('Y-m-d_H\hi\ms\s');
    $filename = clean_filename($keyword . '_' . $timestamp . '.json');
    $filepath = $dir . '/' . $filename;

    $record = [
        'saved_at' => date('c'),
        'userid' => $userid,
        'courseid' => $courseid,
        'question' => $question,
        'request_payload' => $requestpayload,
        'backend_response' => $backenddata,
        'final_response' => $finaloutput,
    ];

    file_put_contents(
        $filepath,
        json_encode($record, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES)
    );

    return $filepath;
}

@ini_set('display_errors', '0');
@ini_set('html_errors', '0');
header('Content-Type: application/json; charset=utf-8');

try {
    $t0total = microtime(true);

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

    $requestpayload = [
        'question' => $question,
        'courseid' => $courseid,
        'userid'   => $userid,
        'history'  => $history,
    ];

    $payload = json_encode($requestpayload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);

    $t0api = microtime(true);

    $ch = curl_init($apiurl);
    curl_setopt($ch, CURLOPT_RETURNTRANSFER, true);
    curl_setopt($ch, CURLOPT_HTTPHEADER, ['Content-Type: application/json']);
    curl_setopt($ch, CURLOPT_POST, true);
    curl_setopt($ch, CURLOPT_POSTFIELDS, $payload);
    curl_setopt($ch, CURLOPT_CONNECTTIMEOUT, 5);
    curl_setopt($ch, CURLOPT_TIMEOUT, 60);

    $response = curl_exec($ch);

    $apims = round((microtime(true) - $t0api) * 1000, 1);

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

    // Save result snapshots only when backend debug is enabled.
    $saveresults = !empty($data['debug']);

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

    $totalms = round((microtime(true) - $t0total) * 1000, 1);

    $out = [
        'answer'  => $answer,
        'sources' => $sources,
    ];

    // During development, forward backend debug info if present.
    if (!empty($data['debug'])) {
        $out['debug'] = $data['debug'];
    }

    if (!isset($out['debug']) || !is_array($out['debug'])) {
        $out['debug'] = [];
    }

    $out['debug']['timing_php_ms'] = [
        'api_call' => $apims,
        'total' => $totalms,
    ];

    $out['debug']['result_snapshot_enabled'] = $saveresults;

    if ($saveresults) {
        try {
            $savedfile = llmassistant_save_result_snapshot(
                $userid,
                $courseid,
                $question,
                $requestpayload,
                $data,
                $out
            );

            if (!isset($out['debug']) || !is_array($out['debug'])) {
                $out['debug'] = [];
            }

            $out['debug']['saved_result_file'] = $savedfile;
        } catch (Throwable $savee) {
            if (!isset($out['debug']) || !is_array($out['debug'])) {
                $out['debug'] = [];
            }

            $out['debug']['saved_result_file_error'] = $savee->getMessage();
        }
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
