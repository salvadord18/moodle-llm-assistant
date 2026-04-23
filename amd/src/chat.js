/* global DOMPurify, marked */

define(['core/log'], function(Log) {
    /**
     * Initialize chat.
     *
     * @param {Object} config Chat config.
     */
    function init(config) {
        const apiUrl = config.apiUrl;
        const historyUrl = config.historyUrl;
        const sourceBaseUrl = config.sourceBaseUrl;
        const courseId = config.courseId;
        const welcomeMessage = config.welcomeMessage;
        const labelSources = config.labelSources || "Sources:";
        const labelThinking = config.labelThinking || "Thinking...";
        const labelClearConfirm = config.labelClearConfirm || "Are you sure you want to clear this chat?";
        const openUrl = config.openUrl || "";

        const chatWindow = document.getElementById(config.chatWindowId);
        const sendBtn = document.getElementById(config.sendButtonId);
        const input = document.getElementById(config.inputId);
        const clearBtn = document.getElementById(config.clearButtonId);
        const openBtn = config.openButtonId ? document.getElementById(config.openButtonId) : null;

        if (!chatWindow || !sendBtn || !input || !clearBtn) {
            return;
        }

        /**
         * Scroll to the bottom of the chat window.
         */
        function scrollToBottom() {
            chatWindow.scrollTop = chatWindow.scrollHeight;
        }

        /**
         * Add a simple message to the chat.
         *
         * @param {string} text Text of the message.
         * @param {string} who "user" or "bot".
         */
        function addMessage(text, who) {
            const div = document.createElement("div");
            div.className = (who === "user") ? "llm-msg-user" : "llm-msg-bot";
            div.textContent = text;
            chatWindow.appendChild(div);
            scrollToBottom();
        }

        /**
         * Build the link of the source.
         *
         * @param {string} label Source visible label.
         * @returns {string} Source URL.
         */
        function buildSourceHref(label) {
            const m = label.match(/^(.*?)(?:\s+\(p\.\s*([0-9]+)(?:-[0-9]+)?(?:,\s*.*)?\))?$/i);
            const filename = m ? m[1].trim() : label.trim();
            const page = (m && m[2]) ? parseInt(m[2], 10) : null;

            let href = sourceBaseUrl
                + encodeURIComponent(filename)
                + "?courseid=" + encodeURIComponent(courseId)
                + "&source=" + encodeURIComponent(filename);

            if (page) {
                href += "#page=" + page;
            }

            return href;
        }

        /**
         * Add a message from the assistant with sources.
         *
         * @param {string} answer Assistant's answer.
         * @param {Array} sources List of sources.
         */
        function addAssistantMessage(answer, sources) {
            const wrap = document.createElement("div");
            wrap.className = "llm-msg-bot";

            const text = document.createElement("div");
            text.innerHTML = DOMPurify.sanitize(marked.parse(answer));
            wrap.appendChild(text);

            if (Array.isArray(sources) && sources.length) {
                const src = document.createElement("div");
                src.className = "llm-sources";

                const formatted = [];
                const seen = new Set();

                sources.forEach(function(s) {
                    let label = "";

                    if (typeof s === "string") {
                        label = s.trim();
                    } else if (s && typeof s === "object") {
                        const source = (typeof s.source === "string") ? s.source.trim() : "Unknown source";
                        const page = (s.page !== undefined && s.page !== null) ? " (p. " + s.page + ")" : "";
                        label = source + page;
                    }

                    if (label && !seen.has(label)) {
                        seen.add(label);
                        formatted.push(label);
                    }
                });

                if (formatted.length) {
                    const title = document.createElement("div");
                    title.style.marginTop = "8px";
                    title.style.fontWeight = "600";
                    title.textContent = labelSources;
                    src.appendChild(title);

                    const chips = document.createElement("div");

                    formatted.forEach(function(label) {
                        const chip = document.createElement("a");
                        chip.className = "llm-chip llm-chip--link";
                        chip.textContent = label;
                        chip.target = "_blank";
                        chip.rel = "noopener noreferrer";
                        chip.href = buildSourceHref(label);
                        chips.appendChild(chip);
                    });

                    src.appendChild(chips);
                    wrap.appendChild(src);
                }
            }

            chatWindow.appendChild(wrap);
            scrollToBottom();
        }

        /**
         * Add "Thinking..." message.
         *
         * @returns {HTMLElement} Teemporary message element.
         */
        function addThinking() {
            const div = document.createElement("div");
            div.className = "llm-msg-bot";
            div.innerHTML = '<span class="llm-spinner"></span>' + labelThinking;
            chatWindow.appendChild(div);
            scrollToBottom();
            return div;
        }

        /**
         * Load user history.
         *
         * @returns {Promise<void>}
         */
        async function loadHistory() {
            try {
                const res = await fetch(historyUrl, {
                    method: "POST",
                    headers: {"Content-Type": "application/x-www-form-urlencoded"},
                    body: new URLSearchParams({
                        sesskey: M.cfg.sesskey,
                        action: "load",
                        courseid: courseId
                    })
                });

                const data = await res.json();
                const messages = data.messages || [];

                chatWindow.innerHTML = "";
                addMessage(welcomeMessage, "bot");

                for (const m of messages) {
                    if (m.role === "assistant") {
                        addAssistantMessage(m.message, m.sources || []);
                    } else {
                        addMessage(m.message, "user");
                    }
                }
            } catch (e) {
                chatWindow.innerHTML = "";
                addMessage(welcomeMessage, "bot");
            }
        }

        /**
         * Clears user history.
         *
         * @returns {Promise<void>}
         */
        async function clearHistory() {
            try {
                await fetch(historyUrl, {
                    method: "POST",
                    headers: {"Content-Type": "application/x-www-form-urlencoded"},
                    body: new URLSearchParams({
                        sesskey: M.cfg.sesskey,
                        action: "clear",
                        courseid: courseId
                    })
                });
            } catch (e) {
                // Ignore cleaning error.
            }

            chatWindow.innerHTML = "";
            addMessage(welcomeMessage, "bot");
        }

        /**
         * Sends a question to the backend.
         *
         * @returns {Promise<void>}
         */
        async function sendMessage() {
            const q = (input.value || "").trim();
            if (!q) {
                return;
            }

            addMessage(q, "user");
            input.value = "";

            const thinkingEl = addThinking();

            try {
                const res = await fetch(apiUrl, {
                    method: "POST",
                    headers: {"Content-Type": "application/x-www-form-urlencoded"},
                    body: new URLSearchParams({
                        sesskey: M.cfg.sesskey,
                        question: q,
                        courseid: courseId
                    })
                });

                const raw = await res.text();
                let data = {};

                try {
                    data = JSON.parse(raw);
                } catch (e) {
                    data = {
                        answer: "Error: invalid JSON response.",
                        sources: [],
                        debug: raw
                    };
                }

                if (data.debug) {
                    try {
                        Log.debug("LLM debug: " + JSON.stringify(data.debug));
                    } catch (e) {
                        Log.debug("LLM debug available.");
                    }
                }

                thinkingEl.remove();

                const answer =
                    (typeof data.answer === "string" && data.answer.trim() !== "")
                        ? data.answer.trim()
                        : "No answer returned.";

                addAssistantMessage(answer, Array.isArray(data.sources) ? data.sources : []);
            } catch (err) {
                thinkingEl.remove();
                addMessage("Error contacting the assistant. Please try again.", "bot");
            }
        }

        /**
         * Confirms and cleans the history.
         *
         * @returns {Promise<void>}
         */
        async function confirmClearHistory() {
            const ok = window.confirm(labelClearConfirm);
            if (!ok) {
                return;
            }

            clearBtn.disabled = true;
            try {
                await clearHistory();
            } finally {
                clearBtn.disabled = false;
            }
        }

        clearBtn.addEventListener("click", confirmClearHistory);
        sendBtn.addEventListener("click", sendMessage);

        if (openBtn && openUrl) {
            openBtn.addEventListener("click", function() {
                window.location.href = openUrl;
            });
        }

        input.addEventListener("keydown", function(e) {
            if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });

        loadHistory();
    }

    return {
        init: init
    };
});
