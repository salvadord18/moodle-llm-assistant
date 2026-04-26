<?php
namespace block_llmassistant\local;

defined('MOODLE_INTERNAL') || die();

class history_manager {

    /**
     * Guarda uma mensagem no histórico
     *
     * @param int $userid
     * @param int $courseid
     * @param string $role 'user' ou 'assistant'
     * @param string $message
     */
    public static function save_message($userid, $courseid, $role, $message, $sourcesjson = null) {
        global $DB;

        $record = new \stdClass();
        $record->userid = $userid;
        $record->courseid = $courseid;
        $record->role = $role;
        $record->message = $message;
        $record->sourcesjson = $sourcesjson;
        $record->timecreated = time();

        $DB->insert_record('block_llmassistant_msg', $record);
    }

    /**
     * Carrega mensagens do histórico
     *
     * @param int $userid
     * @param int $courseid
     * @return array
     */
    public static function load_history($userid, $courseid) {
        global $DB;

        return $DB->get_records(
            'block_llmassistant_msg',
            ['userid' => $userid, 'courseid' => $courseid],
            'timecreated ASC, id ASC'
        );
    }

    /**
     * Limpa histórico do utilizador no curso
     *
     * @param int $userid
     * @param int $courseid
     */
    public static function clear_history($userid, $courseid) {
        global $DB;

        $DB->delete_records('block_llmassistant_msg', ['userid' => $userid, 'courseid' => $courseid]);
    }
}