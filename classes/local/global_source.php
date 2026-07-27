<?php
namespace block_llmassistant\local;

defined('MOODLE_INTERNAL') || die();

/**
 * Resolves and validates the course used as the global institutional source.
 *
 * @package    block_llmassistant
 * @copyright  2026 Salvador de Oliveira Carvalho Nunes Domingues
 * @license    http://www.gnu.org/copyleft/gpl.html GNU GPL v3 or later
 */
final class global_source {
    /** Resolve the configured global source course. */
    public static function course_id(): int {
        global $DB;

        $configuredid = config::global_source_course_id();
        if ($configuredid > 0 && $DB->record_exists('course', ['id' => $configuredid])) {
            return $configuredid;
        }

        $courses = $DB->get_records('course', null, 'id ASC', 'id, fullname, shortname');
        foreach ($courses as $course) {
            if (self::is_global_course($course)) {
                return (int) $course->id;
            }
        }

        throw new \moodle_exception('globalcoursenotconfigured', 'block_llmassistant');
    }

    /** Check whether a course is the configured global source. */
    public static function is_global_course($course): bool {
        if (empty($course) || empty($course->id)) {
            return false;
        }

        $configuredid = config::global_source_course_id();
        if ($configuredid > 0) {
            return (int) $course->id === $configuredid;
        }

        $fullname = self::normalise((string) ($course->fullname ?? ''));
        $shortname = self::normalise((string) ($course->shortname ?? ''));
        foreach (config::global_source_patterns() as $pattern) {
            $normalisedpattern = self::normalise($pattern);
            if ($normalisedpattern !== '' &&
                    (strpos($fullname, $normalisedpattern) !== false ||
                    strpos($shortname, $normalisedpattern) !== false)) {
                return true;
            }
        }
        return false;
    }

    /** Require authentication and access for a course or global scope. */
    public static function require_scope_access(int $courseid): void {
        if ($courseid === 0) {
            require_login();
            if (isguestuser()) {
                throw new \require_login_exception('Guests cannot use the LLM Assistant.');
            }
            return;
        }
        $course = get_course($courseid);
        require_login($course);
    }

    /** Accent-insensitive comparison form. */
    private static function normalise(string $text): string {
        $text = \core_text::strtolower(trim($text));
        $converted = iconv('UTF-8', 'ASCII//TRANSLIT//IGNORE', $text);
        return trim((string) ($converted === false ? $text : $converted));
    }
}
