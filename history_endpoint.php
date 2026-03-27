<?php
require_once(__DIR__ . '/../../config.php');

require_login();
require_sesskey();

$action = required_param('action', PARAM_ALPHA);
$courseid = required_param('courseid', PARAM_INT);

require_once($CFG->dirroot . '/blocks/llmassistant/classes/local/history_manager.php');
use block_llmassistant\local\history_manager;

header('Content-Type: application/json');

$userid = $USER->id;

if ($action === 'load') {
    $rows = history_manager::get_history($userid, $courseid, 200);
    $out = [];
    foreach ($rows as $r) {
        $out[] = [
            'role' => $r->role,
            'message' => $r->message,
            'timecreated' => $r->timecreated,
        ];
    }
    echo json_encode(['messages' => $out]);
    exit;
}

if ($action === 'clear') {
    history_manager::clear_history($userid, $courseid);
    echo json_encode(['ok' => true]);
    exit;
}

echo json_encode(['error' => 'Invalid action']);