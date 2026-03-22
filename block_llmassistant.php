<?php
defined('MOODLE_INTERNAL') || die();

class block_llmassistant extends block_base
{

    public function init()
    {
        $this->title = get_string('pluginname', 'block_llmassistant');
    }

    public function applicable_formats()
    {
        return [
            'course-view' => true,
            'site' => true,
            'my' => true
        ];
    }

    public function instance_allow_multiple()
    {
        return false;
    }

public function get_content() {
    global $OUTPUT, $USER, $COURSE;

    if ($this->content !== null) {
        return $this->content;
    }

    $this->content = new stdClass();

    // API endpoint (FastAPI RAG)
    $apiurl = new moodle_url('/blocks/llmassistant/rag_endpoint.php');

    // HTML structure of the chat interface
    $this->content->text = '
        <style>
            /* Chat container */
            #llm_chat_window {
                height: 350px;
                overflow-y: auto;
                padding: 12px;
                border-radius: 10px;
                background: #f5f5f5;
                border: 1px solid #ddd;
                margin-bottom: 10px;
                font-size: 14px;
            }

            /* Message bubbles */
            .msg-user {
                background: #dcf8c6;
                padding: 10px;
                border-radius: 10px;
                margin-bottom: 8px;
                width: fit-content;
                max-width: 80%;
                margin-left: auto;
            }

            .msg-bot {
                background: #ededed;
                padding: 10px;
                border-radius: 10px;
                margin-bottom: 8px;
                width: fit-content;
                max-width: 80%;
            }

            #llm_input {
                width: 100%;
                padding: 8px;
                border-radius: 6px;
                border: 1px solid #ccc;
                margin-bottom: 6px;
            }

            #llm_send {
                width: 100%;
                padding: 8px;
                background: #0b5ed7;
                color: white;
                border: none;
                border-radius: 6px;
                cursor: pointer;
            }

            #llm_send:hover {
                background: #0a53be;
            }
        </style>

        <div id="llm_chat_window"></div>

        <textarea id="llm_input" rows="2" placeholder="Write your question..."></textarea>
        <button id="llm_send">Submit</button>

        <script>
        (function() {
            const sendBtn = document.getElementById("llm_send");
            const input = document.getElementById("llm_input");
            const chat = document.getElementById("llm_chat_window");

            function addMessage(text, type) {
                const div = document.createElement("div");
                div.className = (type === "user" ? "msg-user" : "msg-bot");
                div.textContent = text;
                chat.appendChild(div);
                chat.scrollTop = chat.scrollHeight;
            }

            async function sendMessage() {
                const question = input.value.trim();
                if (!question) return;

                addMessage(question, "user");
                input.value = "";
                addMessage("Thinking...", "bot");

                const res = await fetch("'.$apiurl.'", {
                    method: "POST",
                    headers: { "Content-Type": "application/x-www-form-urlencoded" },
                    body: new URLSearchParams({
                        sesskey: M.cfg.sesskey,
                        question: question,
                        courseid: '.$COURSE->id.'
                    })
                });
                
                const data = await res.json();

                // Remove temporary "Thinking..."
                chat.lastChild.remove();

                addMessage(data.answer || "Error answering.", "bot");
            }

            sendBtn.addEventListener("click", sendMessage);
            input.addEventListener("keypress", function(e) {
                if (e.key === "Enter") {
                    e.preventDefault();
                    sendMessage();
                }
            });
        })();
        </script>
    ';

    return $this->content;
}
}