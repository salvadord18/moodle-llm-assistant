<?php
namespace block_llmassistant\local;

defined('MOODLE_INTERNAL') || die();

final class history_manager {

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
        int $userid,
        int $courseid,
        string $role,
        string $message,
        array $sources = [],
        array $sourcesstructured = []
    ): void {
        global $DB;

        if (!in_array($role, ['user', 'assistant'], true)) {
            throw new \coding_exception('Invalid LLM Assistant message role.');
        }

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
    public static function load_history(int $userid, int $courseid): array {
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
     * Load only the most recent messages and return them in chronological order.
     *
     * @param int $userid User ID.
     * @param int $courseid Course ID, or zero for global scope.
     * @param int $limit Maximum number of messages.
     * @return array
     */
    public static function load_recent_history(int $userid, int $courseid, int $limit): array {
        global $DB;

        if ($limit <= 0) {
            return [];
        }

        $records = $DB->get_records(
            'block_llmassistant_msg',
            ['userid' => $userid, 'courseid' => $courseid],
            'timecreated DESC, id DESC',
            '*',
            0,
            $limit
        );
        $records = array_reverse(array_values($records));
        return self::decode_sources($records);
    }

    /** Decode source payloads in history records. */
    private static function decode_sources(array $records): array {
        foreach ($records as $record) {
            $record->sources = [];
            $record->sources_structured = [];
            if (empty($record->sourcesjson)) {
                continue;
            }
            $decoded = json_decode($record->sourcesjson, true);
            if (!is_array($decoded)) {
                continue;
            }
            if (array_key_exists('sources', $decoded)) {
                $record->sources = is_array($decoded['sources']) ? $decoded['sources'] : [];
                $record->sources_structured = !empty($decoded['sources_structured']) &&
                        is_array($decoded['sources_structured']) ? $decoded['sources_structured'] : [];
            } else {
                $record->sources = $decoded;
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
    public static function clear_history(int $userid, int $courseid): void {
        global $DB;

        $DB->delete_records('block_llmassistant_msg', [
            'userid' => $userid,
            'courseid' => $courseid
        ]);
    }
}
