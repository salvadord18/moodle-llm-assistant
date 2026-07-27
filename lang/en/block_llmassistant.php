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

// Administration settings.
$string['backendsettings'] = 'Backend connection';
$string['backendsettings_desc'] = 'Configure the connection from Moodle to the Python RAG API.';
$string['connect_timeout'] = 'Connection timeout';
$string['connect_timeout_desc'] = 'Maximum number of seconds allowed to establish a connection to the RAG API (1–60).';
$string['request_timeout'] = 'Request timeout';
$string['request_timeout_desc'] = 'Maximum total duration in seconds for a RAG request (10–600).';
$string['globalsourcesettings'] = 'Global assistant source';
$string['globalsourcesettings_desc'] = 'Configure the Moodle course that contains institutional or global source material.';
$string['global_source_course_id'] = 'Global source course ID';
$string['global_source_course_id_desc'] = 'Numeric Moodle course ID used by the global assistant. Leave as 0 to use the fallback name patterns below.';
$string['global_source_patterns'] = 'Global source course name patterns';
$string['global_source_patterns_desc'] = 'Comma-separated fullname or shortname patterns used only when the course ID is 0.';
$string['conversationsettings'] = 'Conversation and evaluation';
$string['conversationsettings_desc'] = 'Configure recent conversation context and optional evaluation logging.';
$string['history_message_limit'] = 'Recent history messages';
$string['history_message_limit_desc'] = 'Maximum number of recent user and assistant messages sent to the RAG API (0–40).';
$string['enable_result_logging'] = 'Enable evaluation result logging';
$string['enable_result_logging_desc'] = 'Store JSON snapshots and a CSV summary in moodledata/llmassistant_results when backend debug data is available. Keep disabled for normal use.';
$string['globalcoursenotconfigured'] = 'The global source course is not configured or could not be found.';
$string['invalidaction'] = 'Invalid action.';
$string['servererror'] = 'The request could not be completed.';
$string['courseassistanttitle'] = 'LLM Course Assistant';
$string['courseassistantsubtitle'] = 'Course materials, assessment and questions for {$a}';
$string['globalassistanttitle'] = 'LLM Academic Regulations Assistant';
$string['globalassistantsubtitle'] = 'Academic services regulations, rules and deadlines';
$string['globalplaceholder'] = 'Ask about regulations, deadlines, enrolment or exams...';
$string['generationstopped'] = 'Generation stopped.';
$string['errorcontacting'] = 'Error contacting the assistant. Please try again.';
$string['noanswer'] = 'No answer returned.';
$string['stopgenerating'] = 'Stop generating';
$string['sendmessage'] = 'Send message';
$string['expandchat'] = 'Expand chat';
