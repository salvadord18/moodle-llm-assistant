<?php
require_once(__DIR__ . '/../../config.php');

use block_llmassistant\local\chat_ui;

require_login();

$PAGE->requires->css('/blocks/llmassistant/styles.css');
$PAGE->set_url(new moodle_url('/blocks/llmassistant/global.php'));
$PAGE->set_context(context_system::instance());
$PAGE->set_pagelayout('mydashboard');
$PAGE->set_title('LLM Academic Regulations Assistant');
$PAGE->set_heading('LLM Academic Regulations Assistant');

$apiurl = (new moodle_url('/blocks/llmassistant/rag_endpoint.php'))->out(false);
$historyurl = (new moodle_url('/blocks/llmassistant/history_endpoint.php'))->out(false);
$sourcebaseurl = $CFG->wwwroot . '/blocks/llmassistant/source_file.php/';

$cfg = [
    'containerid'       => 'llm_chat_global',
    'containerclasses'  => 'llm-center-wrap',
    'title'             => 'LLM Assistant',
    'subtitle'          => 'Academic services regulations, rules and deadlines',
    'showopenbutton'    => false,
    'openbuttonid'      => '',
    'clearbuttonid'     => 'llm_clear',
    'chatwindowid'      => 'llm_chat_window',
    'chatwindowclasses' => 'llm-chat-window--expanded',
    'inputwrapclass'    => 'llm-input-row',
    'inputid'           => 'llm_input',
    'placeholder'       => 'Ask about regulations, deadlines, enrollment, exams...',
    'sendbuttonid'      => 'llm_send',

    'apiurl'            => $apiurl,
    'historyurl'        => $historyurl,
    'sourcebaseurl'     => $sourcebaseurl,
    'courseid'          => 0,
    'welcomemessage'    => 'Hi! Ask me about faculty rules and general information.',
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