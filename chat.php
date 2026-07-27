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
$PAGE->set_title(get_string('courseassistanttitle', 'block_llmassistant'));
$PAGE->set_heading($course->fullname);
$PAGE->add_body_class('llm-page-coursechat');

$apiurl = (new moodle_url('/blocks/llmassistant/rag_endpoint.php'))->out(false);
$historyurl = (new moodle_url('/blocks/llmassistant/history_endpoint.php'))->out(false);
$sourcebaseurl = $CFG->wwwroot . '/blocks/llmassistant/source_file.php/';

$cfg = [
    'containerid'       => 'llm_chat_page',
    'containerclasses'  => 'llm-chat-container llm-chat-container--coursepage',
    'title'             => get_string('blocktitle', 'block_llmassistant'),
    'subtitle'          => get_string('courseassistantsubtitle', 'block_llmassistant', $course->fullname),
    'showopenbutton'    => false,
    'openbuttonid'      => '',
    'clearbuttonid'     => 'llm_clear',
    'chatwindowid'      => 'llm_chat_window',
    'chatwindowclasses' => 'llm-chat-window--expanded',
    'inputwrapclass'    => 'llm-input-row',
    'inputid'           => 'llm_input',
    'placeholder'       => get_string('placeholder', 'block_llmassistant'),
    'sendbuttonid'      => 'llm_send',

    'apiurl'            => $apiurl,
    'historyurl'        => $historyurl,
    'sourcebaseurl'     => $sourcebaseurl,
    'courseid'          => (int)$courseid,
    'welcomemessage'    => get_string('welcome_course', 'block_llmassistant'),
    'labelsources'      => get_string('sources', 'block_llmassistant'),
    'labelthinking'     => get_string('thinking', 'block_llmassistant'),
    'labelclearconfirm' => get_string('clearconfirm', 'block_llmassistant'),
    'openurl'           => '',
];

echo $OUTPUT->header();
?>

<div class="llm-page-shell">
  <?php
  echo $OUTPUT->render_from_template(
      'block_llmassistant/chat_ui',
      chat_ui::template_context($cfg)
  );
  ?>
</div>

<?php
$PAGE->requires->js_call_amd(
    'block_llmassistant/chat',
    'init',
    [chat_ui::js_config($cfg)]
);

echo $OUTPUT->footer();
