<?php
/**
 * ==============================================
 * FILE: history_endpoint.php
 * PURPOSE: AJAX endpoint to load/clear chat history
 * ==============================================
 */


define('AJAX_SCRIPT', true);

require_once(__DIR__ . '/../../config.php');

@ini_set('display_errors', '0');
header('Content-Type: application/json; charset=utf-8');

require_login();
require_sesskey();

$action = required_param('action', PARAM_ALPHA);
$courseid = required_param('courseid', PARAM_INT);
$userid = $USER->id;

try {

    if ($action === 'load') {
        $messages = \block_llmassistant\local\history_manager::load_history($userid, $courseid);

        $result = [];
        foreach ($messages as $m) {
            $result[] = [
                'role' => $m->role,
                'message' => $m->message,
                'timecreated' => $m->timecreated,
            ];
        }

        echo json_encode(['messages' => $result]);
        exit;
    }

    if ($action === 'clear') {
        \block_llmassistant\local\history_manager::clear_history($userid, $courseid);

        echo json_encode(['success' => true]);
        exit;
    }

    echo json_encode(['error' => 'Invalid action']);
    exit;

} catch (Throwable $e) {
    echo json_encode([
        'error' => 'Server error',
        'debug' => $e->getMessage()
    ]);
    exit;
}