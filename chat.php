<?php
require_once(__DIR__ . '/../../config.php');

use block_llmassistant\local\chat_ui;

$courseid = required_param('courseid', PARAM_INT);
$course = get_course($courseid);
require_login($course);

$context = context_course::instance($courseid);

$PAGE->requires->css('/blocks/llmassistant/styles.css');
$PAGE->set_url(new moodle_url('/blocks/llmassistant/chat.php', ['courseid' => $courseid]));
$PAGE->set_context($context);
$PAGE->set_pagelayout('course');
$PAGE->set_title('LLM Course Assistant');
$PAGE->set_heading($course->fullname);

$apiurl = (new moodle_url('/blocks/llmassistant/rag_endpoint.php'))->out(false);
$historyurl = (new moodle_url('/blocks/llmassistant/history_endpoint.php'))->out(false);
$sourcebaseurl = $CFG->wwwroot . '/blocks/llmassistant/source_file.php/';

$cfg = [
    'containerid'       => 'llm_chat_page',
    'containerclasses'  => 'llm-center-wrap',
    'title'             => 'LLM Assistant',
    'subtitle'          => '',
    'showopenbutton'    => false,
    'openbuttonid'      => '',
    'clearbuttonid'     => 'llm_clear',
    'chatwindowid'      => 'llm_chat_window',
    'chatwindowclasses' => 'llm-chat-window--expanded',
    'inputwrapclass'    => 'llm-input-row',
    'inputid'           => 'llm_input',
    'placeholder'       => 'Write your question...',
    'sendbuttonid'      => 'llm_send',

    'apiurl'            => $apiurl,
    'historyurl'        => $historyurl,
    'sourcebaseurl'     => $sourcebaseurl,
    'courseid'          => (int)$courseid,
    'welcomemessage'    => 'Hi! Ask me something about this course.',
    'labelsources'      => 'Sources:',
    'labelthinking'     => 'Thinking...',
    'labelclearconfirm' => 'Are you sure you want to clear this chat?',
    'openurl'           => '',
];

echo $OUTPUT->header();
?>

<div class="llm-center-wrap">
  <div class="llm-card">
    <?php
    echo $OUTPUT->render_from_template(
        'block_llmassistant/chat_ui',
        chat_ui::template_context($cfg)
    );
    ?>
  </div>
</div>

<?php
$PAGE->requires->js_call_amd(
    'block_llmassistant/chat',
    'init',
    [chat_ui::js_config($cfg)]
);

echo $OUTPUT->footer();
