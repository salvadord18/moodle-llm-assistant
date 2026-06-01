<?php
namespace block_llmassistant\local;

defined('MOODLE_INTERNAL') || die();

class history_manager {

    /**
     * Saves a message in the history for a given user and course, with role (user/assistant) and optional sources.
     *
     * For assistant messages, also saves the sources and structured sources as JSON in the database.
     * {
     *   "sources": [...],
     *   "sources_structured": [...]
     * }
     *
     * @param int $userid
     * @param int $courseid
     * @param string $role 'user' ou 'assistant'
     * @param string $message
     * @param array $sources Lista simples de sources (texto)
     * @param array $sourcesstructured Lista estruturada de sources
     */
    public static function save_message(
        $userid,
        $courseid,
        $role,
        $message,
        $sources = [],
        $sourcesstructured = []
    ) {
        global $DB;

        $record = new \stdClass();
        $record->userid = $userid;
        $record->courseid = $courseid;
        $record->role = $role;
        $record->message = $message;
        $record->timecreated = time();

        // Default: no sources.
        $record->sourcesjson = null;

        if ($role === 'assistant') {
            $payload = [
                'sources' => is_array($sources) ? array_values($sources) : [],
                'sources_structured' => is_array($sourcesstructured) ? array_values($sourcesstructured) : [],
            ];

            $record->sourcesjson = json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
        }

        $DB->insert_record('block_llmassistant_msg', $record);
    }

    /**
     * Loads the message history for a given user and course, ordered by creation time.:
     * - sources
     * - sources_structured
     *
     * Backward compatible:
     * - if sourcesjson is a simple array, it's treated as sources with empty sources_structured.
     *
     * @param int $userid
     * @param int $courseid
     * @return array
     */
    public static function load_history($userid, $courseid) {
        global $DB;

        $records = $DB->get_records(
            'block_llmassistant_msg',
            ['userid' => $userid, 'courseid' => $courseid],
            'timecreated ASC, id ASC'
        );

        foreach ($records as $record) {
            $record->sources = [];
            $record->sources_structured = [];

            if (!empty($record->sourcesjson)) {
                $decoded = json_decode($record->sourcesjson, true);

                if (json_last_error() === JSON_ERROR_NONE) {
                    // New format:
                    // { "sources": [...], "sources_structured": [...] }
                    if (is_array($decoded) && array_key_exists('sources', $decoded)) {
                        $record->sources = is_array($decoded['sources']) ? $decoded['sources'] : [];
                        $record->sources_structured = (
                            isset($decoded['sources_structured']) && is_array($decoded['sources_structured'])
                        ) ? $decoded['sources_structured'] : [];
                    }
                    // Old format:
                    // [...]
                    else if (is_array($decoded)) {
                        $record->sources = $decoded;
                        $record->sources_structured = [];
                    }
                }
            }
        }

        return $records;
    }

    /**
     * Clears the history for a given user and course.
     *
     * @param int $userid
     * @param int $courseid
     */
    public static function clear_history($userid, $courseid) {
        global $DB;

        $DB->delete_records('block_llmassistant_msg', [
            'userid' => $userid,
            'courseid' => $courseid
        ]);
    }
}