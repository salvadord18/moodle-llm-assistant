<?php

defined('MOODLE_INTERNAL') || die();

function xmldb_block_llmassistant_upgrade($oldversion) {
    global $DB;

    $dbman = $DB->get_manager();

    // 2026032300: add chat history table
    if ($oldversion < 2026032300) {

        $table = new xmldb_table('block_llmassistant_msg');

        // Fields
        $table->add_field('id', XMLDB_TYPE_INTEGER, '10', null, XMLDB_NOTNULL, XMLDB_SEQUENCE, null);
        $table->add_field('userid', XMLDB_TYPE_INTEGER, '10', null, XMLDB_NOTNULL, null, null);
        $table->add_field('courseid', XMLDB_TYPE_INTEGER, '10', null, XMLDB_NOTNULL, null, '0');
        $table->add_field('role', XMLDB_TYPE_CHAR, '10', null, XMLDB_NOTNULL, null, 'user'); // user|assistant
        $table->add_field('message', XMLDB_TYPE_TEXT, null, null, XMLDB_NOTNULL, null, null);
        $table->add_field('timecreated', XMLDB_TYPE_INTEGER, '10', null, XMLDB_NOTNULL, null, null);

        // Keys & indexes
        $table->add_key('primary', XMLDB_KEY_PRIMARY, ['id']);
        $table->add_index('idx_user_course_time', XMLDB_INDEX_NOTUNIQUE, ['userid', 'courseid', 'timecreated']);

        // Create if missing
        if (!$dbman->table_exists($table)) {
            $dbman->create_table($table);
        }

        // Savepoint
        upgrade_block_savepoint(true, 2026032300, 'llmassistant');
    }

    return true;
}
