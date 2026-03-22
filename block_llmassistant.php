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

    $apiurl = new moodle_url('/blocks/llmassistant/rag_endpoint.php');

    $this->content->text = '
        <style>
            /* ---------- SIDEBAR CHAT UI ---------- */

            .llm-chat-container {
                position: relative;
                background: #f8f9fa;
                border: 1px solid #ccc;
                border-radius: 10px;
                display: flex;
                flex-direction: column;
                height: 450px;
                max-height: 80vh;
                transition: all 0.3s ease;
            }

            /* Fullscreen mode */
            .llm-chat-fullscreen {
                position: fixed !important;
                top: 0; left: 0;
                width: 100vw !important;
                height: 100vh !important;
                z-index: 9999 !important;
                border-radius: 0 !important;
            }

            .llm-chat-header {
                background: #0b5ed7;
                color: white;
                padding: 10px;
                border-radius: 10px 10px 0 0;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }

            .llm-chat-header button {
                background: transparent;
                border: none;
                color: white;
                cursor: pointer;
                font-size: 18px;
            }

            #llm_chat_window {
                flex: 1;
                overflow-y: auto;
                padding: 12px;
            }

            .msg-user {
                background: #d4edda;
                padding: 10px;
                margin-bottom: 8px;
                border-radius: 8px;
                max-width: 80%;
                margin-left: auto;
            }

            .msg-bot {
                background: #e2e3e5;
                padding: 10px;
                margin-bottom: 8px;
                border-radius: 8px;
                max-width: 80%;
            }

            .llm-chat-input {
                display: flex;
                padding: 10px;
                gap: 5px;
            }

            #llm_input {
                flex: 1;
                padding: 8px;
                border-radius: 6px;
                border: 1px solid #ccc;
                resize: none;
            }

            #llm_send {
                padding: 8px 12px;
                background: #0b5ed7;
                border: none;
                border-radius: 6px;
                color: white;
                cursor: pointer;
            }

            .llm-chat-fullscreen #llm_chat_window {
                font-size: 16px;
                padding: 18px;
            }

            .llm-chat-fullscreen .llm-chat-input {
                position: sticky;
                bottom: 0;
                background: #f8f9fa;
            }
        </style>

        <div id="llm_chat" class="llm-chat-container">
            <div class="llm-chat-header">
                <span>LLM Assistant</span>
                <button id="llm_expand">⤢</button>
            </div>

            <div id="llm_chat_window"></div>

            <div class="llm-chat-input">
                <textarea id="llm_input" rows="2" placeholder="Write your question..."></textarea>
                <button id="llm_send">Submit</button>
            </div>
        </div>

        <script>
        (function() {
            const chat = document.getElementById("llm_chat");
            const chatWindow = document.getElementById("llm_chat_window");
            const sendBtn = document.getElementById("llm_send");
            const input = document.getElementById("llm_input");
            const expandBtn = document.getElementById("llm_expand");

            function addMessage(text, type) {
                const div = document.createElement("div");
                div.className = type === "user" ? "msg-user" : "msg-bot";
                div.textContent = text;
                chatWindow.appendChild(div);
                chatWindow.scrollTop = chatWindow.scrollHeight;
            }

            expandBtn.addEventListener("click", () => {
                chat.classList.toggle("llm-chat-fullscreen");
                expandBtn.textContent = chat.classList.contains("llm-chat-fullscreen") ? "⤡" : "⤢";
            });

            async function sendMessage() {
                const q = input.value.trim();
                if (!q) return;
                addMessage(q, "user");
                input.value = "";
                addMessage("Thinking...", "bot");

                const res = await fetch("'.$apiurl.'", {
                    method: "POST",
                    headers: {"Content-Type": "application/x-www-form-urlencoded"},
                    body: new URLSearchParams({
                        sesskey: M.cfg.sesskey,
                        question: q,
                        courseid: '.$COURSE->id.'
                    })
                });

                const data = await res.json();
                chatWindow.lastChild.remove();
                addMessage(data.answer, "bot");
                
                if (data.sources && data.sources.length) {
                addMessage("Sources: " + [...new Set(data.sources)].join(", "), "bot");
                }
            }

            sendBtn.addEventListener("click", sendMessage);
            input.addEventListener("keypress", e => {
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