<?php
// This file is part of Moodle - http://moodle.org/
//
// Language strings for the LLM Assistant block.

defined('MOODLE_INTERNAL') || die();

$string['pluginname'] = 'LLM Assistant';

// Capabilities.
$string['llmassistant:addinstance'] = 'Add a new LLM Assistant block';
$string['llmassistant:myaddinstance'] = 'Add a new LLM Assistant block to Dashboard';

// General UI labels.
$string['blocktitle'] = 'LLM Assistant';
$string['ask'] = 'Ask';
$string['send'] = 'Send';
$string['placeholder'] = 'Write your question...';
$string['sources'] = 'Sources:';
$string['thinking'] = 'Thinking...';
$string['clearconfirm'] = 'Are you sure you want to clear this chat?';

// Welcome messages.
$string['welcome_course'] = 'Hi! Ask me something about this course.';
$string['welcome_global'] = 'Hi! Ask me about academic regulations, deadlines and faculty rules.';

// RAG API configuration.
$string['rag_api_url'] = 'RAG API URL';
$string['rag_api_url_desc'] = 'URL of the Python RAG API endpoint used by the LLM Assistant. Example: http://127.0.0.1:8001/ask';

// Optional labels for chat pages.
$string['coursechat'] = 'Course chat';
$string['globalchat'] = 'Global chat';
$string['openchat'] = 'Open';
$string['clearchat'] = 'Clear chat';

// Error / fallback labels, if needed by the frontend or future PHP handlers.
$string['error_unavailable'] = 'The assistant service is currently unavailable.';
$string['error_emptyresponse'] = 'The assistant returned an empty response.';
$string['error_invalidresponse'] = 'The assistant returned an invalid response.';