<?php
defined('MOODLE_INTERNAL') || die();

if ($ADMIN->fulltree) {
    $settings->add(new admin_setting_configtext(
        'block_llmassistant/rag_api_url',
        get_string('rag_api_url', 'block_llmassistant'),
        get_string('rag_api_url_desc', 'block_llmassistant'),
        'http://127.0.0.1:8001/ask',
        PARAM_URL
    ));
}