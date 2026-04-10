<?php
defined('MOODLE_INTERNAL') || die();

function xmldb_block_llmassistant_upgrade($oldversion) {
    global $DB;

    $dbman = $DB->get_manager();

    // -----------------------------
    // 1) Create table block_llmassistant_msg (initial install/upgrade)
    // -----------------------------
    if ($oldversion < 2026040200) {

        $table = new xmldb_table('block_llmassistant_msg');

        if (!$dbman->table_exists($table)) {
            $table->add_field('id', XMLDB_TYPE_INTEGER, '10', null, XMLDB_NOTNULL, XMLDB_SEQUENCE);
            $table->add_field('userid', XMLDB_TYPE_INTEGER, '10', null, XMLDB_NOTNULL);
            $table->add_field('courseid', XMLDB_TYPE_INTEGER, '10', null, XMLDB_NOTNULL, null, '0');
            $table->add_field('role', XMLDB_TYPE_CHAR, '10', null, XMLDB_NOTNULL, null, 'user');
            $table->add_field('message', XMLDB_TYPE_TEXT, null, null, XMLDB_NOTNULL);
            $table->add_field('timecreated', XMLDB_TYPE_INTEGER, '10', null, XMLDB_NOTNULL);

            $table->add_key('primary', XMLDB_KEY_PRIMARY, ['id']);
            $table->add_index('idx_user_course_time', XMLDB_INDEX_NOTUNIQUE, ['userid', 'courseid', 'timecreated']);

            $dbman->create_table($table);
        }

        upgrade_block_savepoint(true, 2026040200, 'llmassistant');
    }

    // -----------------------------
    // 2) Add sourcesjson field to persist RAG sources in history
    // -----------------------------
    if ($oldversion < 2026040701) {

        $table = new xmldb_table('block_llmassistant_msg');
        $field = new xmldb_field('sourcesjson', XMLDB_TYPE_TEXT, null, null, null, null, null, 'message');

        if ($dbman->table_exists($table) && !$dbman->field_exists($table, $field)) {
            $dbman->add_field($table, $field);
        }

        upgrade_block_savepoint(true, 2026040701, 'llmassistant');
    }

    return true;
}