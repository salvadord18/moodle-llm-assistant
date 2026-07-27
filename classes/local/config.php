<?php
namespace block_llmassistant\local;

defined('MOODLE_INTERNAL') || die();

/**
 * Central access to LLM Assistant plugin settings.
 *
 * @package    block_llmassistant
 * @copyright  2026 Salvador de Oliveira Carvalho Nunes Domingues
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */
final class config {
    /** @return string Configured RAG endpoint URL. */
    public static function rag_api_url(): string {
        $value = trim((string) get_config('block_llmassistant', 'rag_api_url'));
        return $value !== '' ? $value : 'http://127.0.0.1:8001/ask';
    }

    /** @return int Connection timeout in seconds. */
    public static function connect_timeout(): int {
        return self::bounded_int('connect_timeout', 10, 1, 60);
    }

    /** @return int Total request timeout in seconds. */
    public static function request_timeout(): int {
        return self::bounded_int('request_timeout', 180, 10, 600);
    }

    /** @return int Explicit global source course ID, or zero to use pattern matching. */
    public static function global_source_course_id(): int {
        return max(0, (int) get_config('block_llmassistant', 'global_source_course_id'));
    }

    /** @return string[] Course-name patterns used as a fallback. */
    public static function global_source_patterns(): array {
        $value = trim((string) get_config('block_llmassistant', 'global_source_patterns'));
        if ($value === '') {
            $value = 'serviços académicos,servicos academicos,academic services';
        }
        $patterns = array_map('trim', explode(',', $value));
        return array_values(array_filter($patterns, static fn(string $pattern): bool => $pattern !== ''));
    }

    /** @return int Maximum number of recent messages sent to the RAG API. */
    public static function history_message_limit(): int {
        return self::bounded_int('history_message_limit', 6, 0, 40);
    }

    /** @return bool Whether evaluation snapshots and CSV summaries may be written. */
    public static function result_logging_enabled(): bool {
        return (bool) get_config('block_llmassistant', 'enable_result_logging');
    }

    /** Read an integer setting and constrain it to a safe range. */
    private static function bounded_int(string $name, int $default, int $minimum, int $maximum): int {
        $raw = get_config('block_llmassistant', $name);
        $value = ($raw === false || $raw === '') ? $default : (int) $raw;
        return max($minimum, min($maximum, $value));
    }
}
