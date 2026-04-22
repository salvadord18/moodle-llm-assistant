<?php
require_once(__DIR__ . '/../../config.php');

$courseid = required_param('courseid', PARAM_INT);
$source = required_param('source', PARAM_FILE);

require_login();

$dbprefix = $CFG->prefix;

function llmassistant_normalize_compare(string $text): string {
    $text = core_text::strtolower(trim($text));
    $text = \core_text::substr($text, 0); // ensure utf8-safe
    $text = iconv('UTF-8', 'ASCII//TRANSLIT//IGNORE', $text);
    $text = preg_replace('/\s+/', ' ', $text);
    return trim($text ?? '');
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

$sql = "
    SELECT f.id
      FROM {files} f
      JOIN {context} c
        ON f.contextid = c.id
 LEFT JOIN {course_modules} cm
        ON c.contextlevel = 70
       AND c.instanceid = cm.id
     WHERE f.filename = :filename
       AND f.filesize > 0
       AND (
            (c.contextlevel = 50 AND c.instanceid = :courseid1)
            OR
            (c.contextlevel = 70 AND cm.course = :courseid2)
       )
  ORDER BY f.timemodified DESC, f.id DESC
";

$params = [
    'filename' => $source,
    'courseid1' => $sourcecourseid,
    'courseid2' => $sourcecourseid,
];

$fileid = $DB->get_field_sql($sql, $params);

if (!$fileid) {
    throw new moodle_exception('filenotfound', 'error');
}

$fs = get_file_storage();
$file = $fs->get_file_by_id($fileid);

if (!$file || $file->is_directory()) {
    throw new moodle_exception('filenotfound', 'error');
}

// Serve inline so the browser PDF viewer can use #page=N.
send_stored_file($file, 0, 0, false, [
    'cacheability' => 'public',
]);