<?php
defined('MOODLE_INTERNAL') || die();

use block_llmassistant\local\chat_ui;

class block_llmassistant extends block_base {

    public function init() {
        $this->title = '';
    }

    public function applicable_formats() {
        return [
            'all'         => false,
            'course-view' => true,
            'site-index'  => true,
            'my'          => true,
        ];
    }

    public function instance_allow_multiple() {
        return false;
    }

    /**
     * Detect if a course should behave as the GLOBAL regulations source
     * based on course fullname / shortname.
     */
    protected function is_global_source_course($course): bool {
        if (empty($course) || empty($course->id)) {
            return false;
        }

        $patterns = [
            'serviços académicos',
            'servicos academicos',
            'academic services',
        ];

        $fullname = core_text::strtolower((string)($course->fullname ?? ''));
        $shortname = core_text::strtolower((string)($course->shortname ?? ''));

        foreach ($patterns as $pattern) {
            if (mb_stripos($fullname, $pattern) !== false || mb_stripos($shortname, $pattern) !== false) {
                return true;
            }
        }

        return false;
    }

    public function get_content() {
        global $COURSE, $PAGE, $OUTPUT;

        $PAGE->requires->css('/blocks/llmassistant/styles.css');

        if ($this->content !== null) {
            return $this->content;
        }

        $this->content = new stdClass();

        $instanceid = $this->instance ? (int)$this->instance->id : 0;
        $uid = 'llm_' . $instanceid;

        $apiurl = (new moodle_url('/blocks/llmassistant/rag_endpoint.php'))->out(false);
        $historyurl = (new moodle_url('/blocks/llmassistant/history_endpoint.php'))->out(false);
        $sourcebaseurl = (new moodle_url('/blocks/llmassistant/source_file.php/'))->out(false);

        $iscourse = (
            !empty($COURSE->id) &&
            $COURSE->id != SITEID &&
            $PAGE->context->contextlevel == CONTEXT_COURSE
        );

        $isglobalsourcecourse = $iscourse && $this->is_global_source_course($COURSE);

        $scopecourseid = ($iscourse && !$isglobalsourcecourse) ? (int)$COURSE->id : 0;

        if ($iscourse && !$isglobalsourcecourse) {
            $openurl = (new moodle_url('/blocks/llmassistant/chat.php', [
                'courseid' => $COURSE->id
            ]))->out(false);
        } else {
            $openurl = (new moodle_url('/blocks/llmassistant/global.php'))->out(false);
        }

        $welcomemessage = ($iscourse && !$isglobalsourcecourse)
            ? 'Hi! Ask me something about this course.'
            : 'Hi! Ask me about academic regulations, deadlines and faculty rules.';

        $cfg = [
            'containerid'       => 'llm_chat_' . $uid,
            'containerclasses'  => 'llm-chat-container llm-chat-container--block',
            'title'             => 'LLM Assistant',
            'subtitle'          => '',
            'showopenbutton'    => true,
            'openbuttonid'      => 'llm_open_' . $uid,
            'clearbuttonid'     => 'llm_clear_' . $uid,
            'chatwindowid'      => 'llm_chat_window_' . $uid,
            'chatwindowclasses' => '',
            'inputwrapclass'    => 'llm-chat-inputwrap',
            'inputid'           => 'llm_input_' . $uid,
            'placeholder'       => 'Write your question...',
            'sendbuttonid'      => 'llm_send_' . $uid,

            'apiurl'            => $apiurl,
            'historyurl'        => $historyurl,
            'sourcebaseurl'     => $sourcebaseurl,
            'courseid'          => $scopecourseid,
            'welcomemessage'    => $welcomemessage,
            'labelsources'      => 'Sources:',
            'labelthinking'     => 'Thinking...',
            'labelclearconfirm' => 'Are you sure you want to clear this chat?',
            'openurl'           => $openurl,
        ];

        $this->content->text = $OUTPUT->render_from_template(
            'block_llmassistant/chat_ui',
            chat_ui::template_context($cfg)
        );

        $PAGE->requires->js_call_amd(
            'block_llmassistant/chat',
            'init',
            [chat_ui::js_config($cfg)]
        );

        $this->content->footer = '';
        return $this->content;
    }
}