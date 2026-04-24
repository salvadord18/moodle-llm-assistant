<?php
require_once(__DIR__ . '/../../config.php');

/**
 * Start buffering early so that any accidental output
 * does not break send_stored_file() headers.
 */
ob_start();

$courseid = required_param('courseid', PARAM_INT);
$source = optional_param('source', '', PARAM_RAW_TRIMMED);

/**
 * Fallback: if source was not passed correctly as query param,
 * try PATH_INFO and decode it.
 */
if ($source === '' && !empty($_SERVER['PATH_INFO'])) {
    $source = rawurldecode(trim((string)$_SERVER['PATH_INFO'], '/'));
}

/**
 * Decode defensively in case source arrives URL-encoded.
 */
$source = rawurldecode(trim($source));

if ($source === '') {
    throw new moodle_exception('missingparam', 'error', '', 'source');
}

require_login();

function llmassistant_normalize_compare(string $text): string {
    $text = core_text::strtolower(trim($text));
    $text = iconv('UTF-8', 'ASCII//TRANSLIT//IGNORE', $text);
    $text = preg_replace('/\s+/', ' ', $text);
    return trim((string)$text);
}

function llmassistant_resolve_global_source_course_id(): int {
    global $DB;

    $patterns = [
        'serviços académicos',
        'servicos academicos',
        'academic services',
    ];

    $courses = $DB->get_records('course', null, 'id ASC', 'id, fullname, shortname');

    foreach ($courses as $course) {
        $fullname = llmassistant_normalize_compare((string)($course->fullname ?? ''));
        $shortname = llmassistant_normalize_compare((string)($course->shortname ?? ''));

        foreach ($patterns as $pattern) {
            $p = llmassistant_normalize_compare($pattern);
            if (strpos($fullname, $p) !== false || strpos($shortname, $p) !== false) {
                return (int)$course->id;
            }
        }
    }

    throw new moodle_exception('Could not resolve global source course');
}

$sourcecourseid = ($courseid === 0) ? llmassistant_resolve_global_source_course_id() : $courseid;

// If this is a normal course source, require course access.
if ($sourcecourseid > 0 && $courseid !== 0) {
    $course = get_course($sourcecourseid);
    require_login($course);
}

/**
 * First try: strict lookup for normal Moodle resource PDFs.
 */
$sqlstrict = "
    SELECT
        f.id,
        f.filename,
        f.component,
        f.filearea,
        f.timemodified
    FROM {files} f
    JOIN {context} c
      ON f.contextid = c.id
    LEFT JOIN {course_modules} cm
      ON c.contextlevel = 70
     AND c.instanceid = cm.id
    WHERE f.filename = :filename
      AND f.filesize > 0
      AND f.filename <> '.'
      AND f.mimetype = 'application/pdf'
      AND f.component = 'mod_resource'
      AND f.filearea = 'content'
      AND (
            (c.contextlevel = 50 AND c.instanceid = :courseid1)
            OR
            (c.contextlevel = 70 AND cm.course = :courseid2)
      )
    ORDER BY f.timemodified DESC, f.id DESC
";

/**
 * Fallback: broader lookup if the strict query finds nothing.
 */
$sqlfallback = "
    SELECT
        f.id,
        f.filename,
        f.component,
        f.filearea,
        f.timemodified
    FROM {files} f
    JOIN {context} c
      ON f.contextid = c.id
    LEFT JOIN {course_modules} cm
      ON c.contextlevel = 70
     AND c.instanceid = cm.id
    WHERE f.filename = :filename
      AND f.filesize > 0
      AND f.filename <> '.'
      AND f.mimetype = 'application/pdf'
      AND (
            (c.contextlevel = 50 AND c.instanceid = :courseid1)
            OR
            (c.contextlevel = 70 AND cm.course = :courseid2)
      )
    ORDER BY
      CASE
        WHEN f.component = 'mod_resource' AND f.filearea = 'content' THEN 0
        ELSE 1
      END,
      f.timemodified DESC,
      f.id DESC
";

$params = [
    'filename'  => $source,
    'courseid1' => $sourcecourseid,
    'courseid2' => $sourcecourseid,
];

$records = $DB->get_records_sql($sqlstrict, $params, 0, 50);

if (!$records) {
    $records = $DB->get_records_sql($sqlfallback, $params, 0, 50);
}

if (!$records) {
    throw new moodle_exception('filenotfound', 'error');
}

$fs = get_file_storage();
$file = null;

foreach ($records as $rec) {
    $candidate = $fs->get_file_by_id((int)$rec->id);
    if ($candidate && !$candidate->is_directory()) {
        $file = $candidate;
        break;
    }
}

if (!$file) {
    throw new moodle_exception('filenotfound', 'error');
}

/**
 * Clear any accidental output before sending the file,
 * otherwise Moodle/PHP may complain about headers already sent.
 */
while (ob_get_level()) {
    ob_end_clean();
}

// Serve inline so the browser PDF viewer can use #page=N.
send_stored_file($file, 0, 0, false, [
    'cacheability' => 'public',
]);