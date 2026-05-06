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
 * Lightweight language detection from the user question.
 * Returns 'pt' or 'en'.
 */
function llmassistant_detect_language(string $text): string {
    $text = core_text::strtolower(trim($text));

    if ($text === '') {
        return 'en';
    }

    // Strong Portuguese diacritic cues.
    if (preg_match('/[áàâãéêíóôõúç]/u', $text)) {
        return 'pt';
    }

    // Strong Portuguese lexical cues.
    if (preg_match('/\b(quem|quais?|qual|como|quando|onde|porque|porquê|prazo|prazos|inscri[cç][aã]o|inscrever|exame|exames|época|epoca|recurso|melhoria|avalia[cç][aã]o|regulamento|regulamentos|docente|docentes|professor|professores|contacto|contactos|correio|estatuto|servi[cç]os acad[eé]micos)\b/u', $text)) {
        return 'pt';
    }

    return 'en';
}

/**
 * Localized user-facing messages for rag_endpoint.php.
 */
function llmassistant_localized_text(string $key, string $lang, array $vars = []): string {
    $messages = [
        'timeout' => [
            'pt' => 'O pedido ao assistente demorou demasiado tempo. Tente novamente dentro de instantes.',
            'en' => 'The request to the assistant took too long. Please try again in a moment.',
        ],
        'unreachable' => [
            'pt' => 'Não foi possível contactar o serviço do assistente neste momento.',
            'en' => 'The assistant service could not be reached at the moment.',
        ],
        'http_error' => [
            'pt' => 'O serviço do assistente devolveu um erro interno (HTTP {{code}}).',
            'en' => 'The assistant service returned an internal error (HTTP {{code}}).',
        ],
        'invalid_json' => [
            'pt' => 'O serviço do assistente devolveu uma resposta inválida.',
            'en' => 'The assistant service returned an invalid response.',
        ],
        'empty_answer' => [
            'pt' => 'O assistente devolveu uma resposta vazia.',
            'en' => 'The assistant returned an empty response.',
        ],
        'server_failed' => [
            'pt' => 'O pedido falhou no servidor.',
            'en' => 'The request failed on the server.',
        ],
    ];

    $text = $messages[$key][$lang] ?? $messages[$key]['en'] ?? 'Error.';

    foreach ($vars as $k => $v) {
        $text = str_replace('{{' . $k . '}}', (string)$v, $text);
    }

    return $text;
}

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
 * Base directory where all result folders and summary files are stored.
 */
function llmassistant_results_base_dir(): string {
    global $CFG;

    $base = $CFG->dataroot . '/llmassistant_results';
    check_dir_exists($base, true, true);
    return $base;
}

/**
 * Resolves the folder where to save the files
 */
function llmassistant_results_dir(int $courseid): string {
    global $CFG, $DB;

    $base = llmassistant_results_base_dir();

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

/**
 * Detects whether the assistant answer is a "no information found" fallback.
 */
function llmassistant_is_no_info_answer(string $answer): bool {
    $a = core_text::strtolower(trim($answer));

    if ($a === '') {
        return false;
    }

    return (
        strpos($a, "não encontrei") !== false ||
        strpos($a, "nao encontrei") !== false ||
        strpos($a, "i couldn't find") !== false ||
        strpos($a, "the provided pdfs do not contain this information") !== false ||
        strpos($a, "the provided course pdfs do not contain this information") !== false ||
        strpos($a, "the provided global documents do not contain this information") !== false
    );
}

/**
 * Converts source entries to one CSV-friendly string.
 *
 * @param mixed $sources
 * @return string
 */
function llmassistant_sources_to_csv_text($sources): string {
    if (!is_array($sources) || empty($sources)) {
        return '';
    }

    $labels = [];

    foreach ($sources as $s) {
        if (is_string($s)) {
            $label = trim($s);
            if ($label !== '') {
                $labels[] = $label;
            }
            continue;
        }

        if (is_array($s)) {
            $source = trim((string)($s['source'] ?? ''));
            $page = isset($s['page']) && $s['page'] !== null && $s['page'] !== ''
                ? ' (p. ' . $s['page'] . ')'
                : '';

            $label = trim($source . $page);
            if ($label !== '') {
                $labels[] = $label;
            }
        }
    }

    return implode(' | ', $labels);
}

/**
 * Converts debug fields into CSV-friendly columns.
 */
function llmassistant_debug_to_csv_fields(array $debug): array {
    $candidatecounts = (isset($debug['candidate_counts']) && is_array($debug['candidate_counts']))
        ? $debug['candidate_counts']
        : [];

    $rejectreasons = '';
    if (!empty($debug['reject_reasons'])) {
        if (is_array($debug['reject_reasons'])) {
            $rejectreasons = implode(' | ', $debug['reject_reasons']);
        } else {
            $rejectreasons = (string)$debug['reject_reasons'];
        }
    }

    $queries = '';
    if (!empty($debug['queries'])) {
        if (is_array($debug['queries'])) {
            $queries = implode(' || ', $debug['queries']);
        } else {
            $queries = (string)$debug['queries'];
        }
    }

    $topsources = '';
    if (!empty($debug['top_sources'])) {
        if (is_array($debug['top_sources'])) {
            $topsources = implode(' | ', $debug['top_sources']);
        } else {
            $topsources = (string)$debug['top_sources'];
        }
    }

    return [
        'debug_return_stage' => $debug['return_stage'] ?? '',
        'debug_no_info_reason' => $debug['no_info_reason'] ?? '',
        'debug_reject_reasons' => $rejectreasons,
        'debug_collection_name' => $debug['collection_name'] ?? '',
        'debug_source_courseid' => $debug['source_courseid'] ?? '',
        'debug_q_for_retrieval' => $debug['q_for_retrieval'] ?? '',
        'debug_queries' => $queries,

        'debug_want_definition' => !empty($debug['want_definition']) ? 'True' : 'False',
        'debug_want_policy' => !empty($debug['want_policy']) ? 'True' : 'False',
        'debug_want_contacts' => !empty($debug['want_contacts']) ? 'True' : 'False',
        'debug_want_eligibility' => !empty($debug['want_eligibility']) ? 'True' : 'False',

        'debug_candidate_merged_total' => $candidatecounts['merged_total'] ?? '',
        'debug_candidate_after_regulatory' => $candidatecounts['after_regulatory_filter'] ?? '',
        'debug_candidate_after_policy' => $candidatecounts['after_policy_filter'] ?? '',
        'debug_candidate_after_eligibility' => $candidatecounts['after_eligibility_filter'] ?? '',
        'debug_candidate_after_contact' => $candidatecounts['after_contact_filter'] ?? '',

        'debug_min_dist' => $debug['min_dist'] ?? '',
        'debug_threshold' => $debug['threshold'] ?? '',
        'debug_top_score' => $debug['top_score'] ?? '',
        'debug_top_lex' => $debug['top_lex'] ?? '',
        'debug_top_policy_quality' => $debug['top_policy_quality'] ?? '',

        'debug_top_sources' => $topsources,
    ];
}

/**
 * Rebuilds the summary CSV from all saved JSON result snapshots.
 */
function llmassistant_rebuild_result_summary_csv(): ?string {
    $base = llmassistant_results_base_dir();
    $csvpath = $base . '/all_results_summary.csv';

    $rows = [];

    $iterator = new RecursiveIteratorIterator(
        new RecursiveDirectoryIterator($base, FilesystemIterator::SKIP_DOTS)
    );

    foreach ($iterator as $fileinfo) {
        if (!$fileinfo->isFile()) {
            continue;
        }

        if (core_text::strtolower($fileinfo->getExtension()) !== 'json') {
            continue;
        }

        $filepath = $fileinfo->getPathname();

        $content = @file_get_contents($filepath);
        if ($content === false || trim($content) === '') {
            continue;
        }

        $data = json_decode($content, true);
        if (!is_array($data)) {
            continue;
        }

        $final = $data['final_response'] ?? [];
        $debug = $final['debug'] ?? [];
        $debugcsv = llmassistant_debug_to_csv_fields(is_array($debug) ? $debug : []);

        $timingphp = (is_array($debug) && !empty($debug['timing_php_ms']) && is_array($debug['timing_php_ms']))
            ? $debug['timing_php_ms']
            : [];

        $timingrag = (is_array($debug) && !empty($debug['timing_ms']) && is_array($debug['timing_ms']))
            ? $debug['timing_ms']
            : [];

        $answer = trim((string)($final['answer'] ?? ''));
        $sources = $final['sources'] ?? [];

        $rows[] = array_merge([
            'file' => ltrim(str_replace($base, '', $filepath), DIRECTORY_SEPARATOR),
            'saved_at' => $data['saved_at'] ?? '',
            'courseid' => $data['courseid'] ?? '',
            'userid' => $data['userid'] ?? '',
            'question' => $data['question'] ?? '',
            'answer' => $answer,
            'sources' => llmassistant_sources_to_csv_text($sources),
            'timing_php_total_ms' => $timingphp['total'] ?? '',
            'timing_rag_total_ms' => $timingrag['total'] ?? '',
            'timing_generation_ms' => $timingrag['generation'] ?? '',
            'no_info' => llmassistant_is_no_info_answer($answer) ? 'True' : 'False',
        ], $debugcsv);
    }

    // Sort by saved_at ascending, then by file path for stability.
    usort($rows, function($a, $b) {
        $ta = $a['saved_at'] ?? '';
        $tb = $b['saved_at'] ?? '';

        if ($ta === $tb) {
            return strcmp((string)$a['file'], (string)$b['file']);
        }

        return strcmp((string)$ta, (string)$tb);
    });

    $fh = fopen($csvpath, 'w');
    if (!$fh) {
        throw new \RuntimeException('Could not open summary CSV for rebuilding: ' . $csvpath);
    }

    try {
        if (!flock($fh, LOCK_EX)) {
            throw new \RuntimeException('Could not lock summary CSV for rebuilding: ' . $csvpath);
        }

        $header = [
            'file',
            'saved_at',
            'courseid',
            'userid',
            'question',
            'answer',
            'sources',
            'timing_php_total_ms',
            'timing_rag_total_ms',
            'timing_generation_ms',
            'no_info',

            'debug_return_stage',
            'debug_no_info_reason',
            'debug_reject_reasons',
            'debug_collection_name',
            'debug_source_courseid',
            'debug_q_for_retrieval',
            'debug_queries',

            'debug_want_definition',
            'debug_want_policy',
            'debug_want_contacts',
            'debug_want_eligibility',

            'debug_candidate_merged_total',
            'debug_candidate_after_regulatory',
            'debug_candidate_after_policy',
            'debug_candidate_after_eligibility',
            'debug_candidate_after_contact',

            'debug_min_dist',
            'debug_threshold',
            'debug_top_score',
            'debug_top_lex',
            'debug_top_policy_quality',

            'debug_top_sources',
        ];

        fputcsv($fh, $header);

        foreach ($rows as $row) {
            fputcsv($fh, $row);
        }

        fflush($fh);
        flock($fh, LOCK_UN);
    } finally {
        fclose($fh);
    }

    return $csvpath;
}

/**
 * Appends one evaluation row to the summary CSV.
 */
function llmassistant_append_result_summary_csv(
    ?string $savedfile,
    int $userid,
    int $courseid,
    string $question,
    array $finaloutput
): ?string {
    $base = llmassistant_results_base_dir();
    $csvpath = $base . '/all_results_summary.csv';

    $answer = trim((string)($finaloutput['answer'] ?? ''));
    $sources = $finaloutput['sources'] ?? [];
    $debug = $finaloutput['debug'] ?? [];
    $debugcsv = llmassistant_debug_to_csv_fields(is_array($debug) ? $debug : []);

    $timingphp = (is_array($debug) && !empty($debug['timing_php_ms']) && is_array($debug['timing_php_ms']))
        ? $debug['timing_php_ms']
        : [];

    $timingrag = (is_array($debug) && !empty($debug['timing_ms']) && is_array($debug['timing_ms']))
        ? $debug['timing_ms']
        : [];

    $row = array_merge([
        'file' => $savedfile ? ltrim(str_replace($base, '', $savedfile), DIRECTORY_SEPARATOR) : '',
        'saved_at' => date('c'),
        'courseid' => $courseid,
        'userid' => $userid,
        'question' => $question,
        'answer' => $answer,
        'sources' => llmassistant_sources_to_csv_text($sources),
        'timing_php_total_ms' => $timingphp['total'] ?? '',
        'timing_rag_total_ms' => $timingrag['total'] ?? '',
        'timing_generation_ms' => $timingrag['generation'] ?? '',
        'no_info' => llmassistant_is_no_info_answer($answer) ? 'True' : 'False',
    ], $debugcsv);

    $fh = fopen($csvpath, 'a+');
    if (!$fh) {
        throw new \RuntimeException('Could not open summary CSV for writing: ' . $csvpath);
    }

    try {
        if (!flock($fh, LOCK_EX)) {
            throw new \RuntimeException('Could not lock summary CSV: ' . $csvpath);
        }

        $stat = fstat($fh);
        $writeheader = ($stat['size'] === 0);

        if ($writeheader) {
            fputcsv($fh, array_keys($row));
        }

        fputcsv($fh, array_values($row));

        fflush($fh);
        flock($fh, LOCK_UN);
    } finally {
        fclose($fh);
    }

    return $csvpath;
}

/**
 * Saves one assistant message to history.
 */
function llmassistant_save_assistant_message(
    int $userid,
    int $courseid,
    string $answer,
    array $sources = []
): void {
    try {
        $sourcesjson = json_encode($sources, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);

        \block_llmassistant\local\history_manager::save_message(
            $userid,
            $courseid,
            'assistant',
            $answer,
            $sourcesjson
        );
    } catch (Throwable $e) {
        // Do not break the endpoint if history persistence fails.
    }
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
    $userlang = llmassistant_detect_language($question);

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

    // Save user message immediately so it is never lost.
    \block_llmassistant\local\history_manager::save_message($userid, $courseid, 'user', $question);

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
    curl_setopt($ch, CURLOPT_CONNECTTIMEOUT, 10);
    curl_setopt($ch, CURLOPT_TIMEOUT, 180);

    $response = curl_exec($ch);

    $apims = round((microtime(true) - $t0api) * 1000, 1);

    if ($response === false) {
        $err = curl_error($ch);
        $errno = curl_errno($ch);
        curl_close($ch);

        if (ob_get_length()) {
            ob_clean();
        }

        $isTimeout = in_array($errno, [CURLE_OPERATION_TIMEDOUT], true);

        $answer = $isTimeout
            ? llmassistant_localized_text('timeout', $userlang)
            : llmassistant_localized_text('unreachable', $userlang);

        $out = [
            'answer'  => $answer,
            'sources' => [],
            'debug'   => [
                'curl_errno' => $errno,
                'curl_error' => $err,
                'transport_error_kind' => $isTimeout ? 'timeout' : 'unreachable',
                'rag_api_url' => $apiurl,
            ],
        ];

        llmassistant_save_assistant_message($userid, $courseid, $answer, []);

        echo json_encode($out, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
        exit;
    }

    $httpcode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);

    if ($httpcode < 200 || $httpcode >= 300) {
        if (ob_get_length()) {
            ob_clean();
        }

        $answer = llmassistant_localized_text('http_error', $userlang, ['code' => $httpcode]);

        $out = [
            'answer'  => $answer,
            'sources' => [],
            'debug'   => [
                'http_code' => $httpcode,
                'rag_response' => $response,
            ],
        ];

        llmassistant_save_assistant_message($userid, $courseid, $answer, []);

        echo json_encode($out, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
        exit;
    }

    $data = json_decode($response, true);

    if (!is_array($data)) {
        if (ob_get_length()) {
            ob_clean();
        }

        $answer = llmassistant_localized_text('invalid_json', $userlang);

        $out = [
            'answer'  => $answer,
            'sources' => [],
            'debug'   => [
                'rag_response' => $response,
            ],
        ];

        llmassistant_save_assistant_message($userid, $courseid, $answer, []);

        echo json_encode($out, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
        exit;
    }

    // Save result snapshots only when backend debug is enabled.
    $saveresults = !empty($data['debug']);

    $answer = trim((string)($data['answer'] ?? ''));
    if ($answer === '') {
        $answer = llmassistant_localized_text('empty_answer', $userlang);
    }

    $sources = $data['sources'] ?? [];

    llmassistant_save_assistant_message(
        $userid,
        $courseid,
        $answer,
        is_array($sources) ? $sources : []
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

            $csvpath = llmassistant_results_base_dir() . '/all_results_summary.csv';

            if (!file_exists($csvpath) || filesize($csvpath) === 0) {
                $csvfile = llmassistant_rebuild_result_summary_csv();
            } else {
                $csvfile = llmassistant_append_result_summary_csv(
                    $savedfile,
                    $userid,
                    $courseid,
                    $question,
                    $out
                );
            }

            if (!isset($out['debug']) || !is_array($out['debug'])) {
                $out['debug'] = [];
            }

            $out['debug']['saved_result_file'] = $savedfile;
            $out['debug']['saved_summary_csv'] = $csvfile;
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

    $answer = llmassistant_localized_text('server_failed', isset($userlang) ? $userlang : 'en');

    $out = [
        'answer'  => $answer,
        'sources' => [],
        'debug'   => get_class($e) . ': ' . $e->getMessage(),
    ];

    if (isset($userid, $courseid, $question) && $question !== '') {
        llmassistant_save_assistant_message($userid, $courseid, $answer, []);
    }

    echo json_encode($out, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}
