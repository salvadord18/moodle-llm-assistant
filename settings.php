<?php
defined('MOODLE_INTERNAL') || die();

if ($ADMIN->fulltree) {
    $settings->add(new admin_setting_heading(
        'block_llmassistant/backendsettings',
        get_string('backendsettings', 'block_llmassistant'),
        get_string('backendsettings_desc', 'block_llmassistant')
    ));

    $settings->add(new admin_setting_configtext(
        'block_llmassistant/rag_api_url',
        get_string('rag_api_url', 'block_llmassistant'),
        get_string('rag_api_url_desc', 'block_llmassistant'),
        'http://127.0.0.1:8001/ask',
        PARAM_URL
    ));

    $settings->add(new admin_setting_configtext(
        'block_llmassistant/connect_timeout',
        get_string('connect_timeout', 'block_llmassistant'),
        get_string('connect_timeout_desc', 'block_llmassistant'),
        10,
        PARAM_INT
    ));

    $settings->add(new admin_setting_configtext(
        'block_llmassistant/request_timeout',
        get_string('request_timeout', 'block_llmassistant'),
        get_string('request_timeout_desc', 'block_llmassistant'),
        180,
        PARAM_INT
    ));

    $settings->add(new admin_setting_heading(
        'block_llmassistant/globalsourcesettings',
        get_string('globalsourcesettings', 'block_llmassistant'),
        get_string('globalsourcesettings_desc', 'block_llmassistant')
    ));

    $settings->add(new admin_setting_configtext(
        'block_llmassistant/global_source_course_id',
        get_string('global_source_course_id', 'block_llmassistant'),
        get_string('global_source_course_id_desc', 'block_llmassistant'),
        0,
        PARAM_INT
    ));

    $settings->add(new admin_setting_configtext(
        'block_llmassistant/global_source_patterns',
        get_string('global_source_patterns', 'block_llmassistant'),
        get_string('global_source_patterns_desc', 'block_llmassistant'),
        'serviços académicos,servicos academicos,academic services',
        PARAM_TEXT
    ));

    $settings->add(new admin_setting_heading(
        'block_llmassistant/conversationsettings',
        get_string('conversationsettings', 'block_llmassistant'),
        get_string('conversationsettings_desc', 'block_llmassistant')
    ));

    $settings->add(new admin_setting_configtext(
        'block_llmassistant/history_message_limit',
        get_string('history_message_limit', 'block_llmassistant'),
        get_string('history_message_limit_desc', 'block_llmassistant'),
        6,
        PARAM_INT
    ));

    $settings->add(new admin_setting_configcheckbox(
        'block_llmassistant/enable_result_logging',
        get_string('enable_result_logging', 'block_llmassistant'),
        get_string('enable_result_logging_desc', 'block_llmassistant'),
        0
    ));
}
