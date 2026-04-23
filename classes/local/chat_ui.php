<?php
namespace block_llmassistant\local;

defined('MOODLE_INTERNAL') || die();

class chat_ui {

    public static function template_context(array $cfg): array {
        return [
            'containerid'      => $cfg['containerid'],
            'containerclasses' => $cfg['containerclasses'] ?? '',
            'title'            => $cfg['title'] ?? 'LLM Assistant',
            'subtitle'         => $cfg['subtitle'] ?? '',
            'showopenbutton'   => !empty($cfg['showopenbutton']),
            'openbuttonid'     => $cfg['openbuttonid'] ?? '',
            'clearbuttonid'    => $cfg['clearbuttonid'],
            'chatwindowid'     => $cfg['chatwindowid'],
            'chatwindowclasses'=> $cfg['chatwindowclasses'] ?? '',
            'inputwrapclass'   => $cfg['inputwrapclass'] ?? 'llm-input-row',
            'inputid'          => $cfg['inputid'],
            'placeholder'      => $cfg['placeholder'] ?? '',
            'sendbuttonid'     => $cfg['sendbuttonid'],
        ];
    }

    public static function js_config(array $cfg): array {
        return [
            'apiUrl'            => $cfg['apiurl'],
            'historyUrl'        => $cfg['historyurl'],
            'sourceBaseUrl'     => $cfg['sourcebaseurl'],
            'courseId'          => (int)$cfg['courseid'],
            'welcomeMessage'    => $cfg['welcomemessage'],
            'labelSources'      => $cfg['labelsources'] ?? 'Sources:',
            'labelThinking'     => $cfg['labelthinking'] ?? 'Thinking...',
            'labelClearConfirm' => $cfg['labelclearconfirm'] ?? 'Are you sure you want to clear this chat?',
            'openUrl'           => $cfg['openurl'] ?? '',
            'chatWindowId'      => $cfg['chatwindowid'],
            'sendButtonId'      => $cfg['sendbuttonid'],
            'inputId'           => $cfg['inputid'],
            'clearButtonId'     => $cfg['clearbuttonid'],
            'openButtonId'      => $cfg['openbuttonid'] ?? '',
        ];
    }
}