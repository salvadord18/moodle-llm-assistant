<?php
require_once(__DIR__ . '/../../config.php');

ob_start();

$courseid    = required_param('courseid', PARAM_INT);
$source      = optional_param('source', '', PARAM_RAW_TRIMMED);
$doc_kind    = optional_param('doc_kind', '', PARAM_RAW_TRIMMED);
$source_type = optional_param('source_type', '', PARAM_RAW_TRIMMED);
$module_name = optional_param('module_name', '', PARAM_RAW_TRIMMED);
$cmid        = optional_param('cmid', 0, PARAM_INT);
$sectionnum  = optional_param('sectionnum', -1, PARAM_INT);
$page        = optional_param('page', -1, PARAM_INT);

if ($source === '' && !empty($_SERVER['PATH_INFO'])) {
    $source = rawurldecode(trim((string)$_SERVER['PATH_INFO'], '/'));
}

$source = rawurldecode(trim($source));
$doc_kind = trim($doc_kind);
$source_type = trim($source_type);
$module_name = trim($module_name);

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

if ($sourcecourseid > 0 && $courseid !== 0) {
    $course = get_course($sourcecourseid);
    require_login($course);
}

/**
 * ---------------------------------------------------------
 * 1) Moodle-native sources
 * ---------------------------------------------------------
 */
if ($doc_kind === 'moodle_text') {
    // If we have a Moodle module id, redirect directly to the module view.
    if ($cmid > 0 && $module_name !== '') {
        $allowedmods = [
            'assign', 'quiz', 'forum', 'page',
            'url', 'folder', 'resource', 'book'
        ];

        if (in_array($module_name, $allowedmods, true)) {
            while (ob_get_level()) {
                ob_end_clean();
            }
            redirect(new moodle_url("/mod/{$module_name}/view.php", ['id' => $cmid]));
        }

        // Label normally has no meaningful standalone page; fall through to course section.
    }

    // For labels / section summaries / course summaries, go to course page.
    $params = ['id' => $sourcecourseid];
    $url = new moodle_url('/course/view.php', $params);

    // Try section anchor if available
    if ($sectionnum >= 0) {
        $url->set_anchor('section-' . $sectionnum);
    }

    while (ob_get_level()) {
        ob_end_clean();
    }
    redirect($url);
}

/**
 * ---------------------------------------------------------
 * 2) PDF sources
 * ---------------------------------------------------------
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

while (ob_get_level()) {
    ob_end_clean();
}

send_stored_file($file, 0, 0, false, [
    'cacheability' => 'public',
]);