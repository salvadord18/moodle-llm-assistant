<?php
/**
 * ==============================================
 * FILE: history_endpoint.php
 * PURPOSE: AJAX endpoint to load/clear chat history
 * ==============================================
 */


define('AJAX_SCRIPT', true);

require_once(__DIR__ . '/../../config.php');
require_once($CFG->dirroot . '/blocks/llmassistant/classes/local/history_manager.php');

require_login();

$action = required_param('action', PARAM_ALPHA);
$courseid = required_param('courseid', PARAM_INT);

header('Content-Type: application/json');

$userid = $USER->id;

switch ($action) {
    case 'load':
        // Se quiseres máxima segurança, descomenta a linha seguinte
        // require_sesskey();

        $rows = \block_llmassistant\local\history_manager::get_history($userid, $courseid, 200);

        $out = [];
        foreach ($rows as $r) {
            $out[] = [
                'role' => $r->role,
                'message' => $r->message,
                'timecreated' => $r->timecreated,
            ];
        }

        echo json_encode(['messages' => $out]);
        break;

    case 'clear':
        require_sesskey();

        \block_llmassistant\local\history_manager::clear_history($userid, $courseid);
        echo json_encode(['ok' => true]);
        break;

    default:
        http_response_code(400);
        echo json_encode(['error' => 'Invalid action']);
        break;
}

exit;