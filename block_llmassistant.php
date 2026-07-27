<?php
defined('MOODLE_INTERNAL') || die();

use block_llmassistant\local\chat_ui;
use block_llmassistant\local\global_source;

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
     * Indicates that this block has global plugin settings.
     *
     * @return bool
     */
    public function has_config() {
        return true;
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
        $sourcebaseurl = (new moodle_url('/blocks/llmassistant/source_file.php'))->out(false);

        $iscourse = (
            !empty($COURSE->id) &&
            $COURSE->id != SITEID &&
            $PAGE->context->contextlevel == CONTEXT_COURSE
        );

        $isglobalsourcecourse = $iscourse && global_source::is_global_course($COURSE);

        $scopecourseid = ($iscourse && !$isglobalsourcecourse) ? (int)$COURSE->id : 0;

        if ($iscourse && !$isglobalsourcecourse) {
            $openurl = (new moodle_url('/blocks/llmassistant/chat.php', [
                'courseid' => $COURSE->id
            ]))->out(false);
        } else {
            $openurl = (new moodle_url('/blocks/llmassistant/global.php'))->out(false);
        }

        $welcomemessage = ($iscourse && !$isglobalsourcecourse)
            ? get_string('welcome_course', 'block_llmassistant')
            : get_string('welcome_global', 'block_llmassistant');

        $cfg = [
            'containerid'       => 'llm_chat_' . $uid,
            'containerclasses'  => 'llm-chat-container llm-chat-container--block',
            'title'             => get_string('blocktitle', 'block_llmassistant'),
            'subtitle'          => '',
            'showopenbutton'    => true,
            'openbuttonid'      => 'llm_open_' . $uid,
            'clearbuttonid'     => 'llm_clear_' . $uid,
            'chatwindowid'      => 'llm_chat_window_' . $uid,
            'chatwindowclasses' => '',
            'inputwrapclass'    => 'llm-chat-inputwrap',
            'inputid'           => 'llm_input_' . $uid,
            'placeholder'       => get_string('placeholder', 'block_llmassistant'),
            'sendbuttonid'      => 'llm_send_' . $uid,

            'apiurl'            => $apiurl,
            'historyurl'        => $historyurl,
            'sourcebaseurl'     => $sourcebaseurl,
            'courseid'          => $scopecourseid,
            'welcomemessage'    => $welcomemessage,
            'labelsources'      => get_string('sources', 'block_llmassistant'),
            'labelthinking'     => get_string('thinking', 'block_llmassistant'),
            'labelclearconfirm' => get_string('clearconfirm', 'block_llmassistant'),
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
