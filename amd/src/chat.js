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

        let isBusy = false;

        let currentController = null;
        let currentThinkingEl = null;

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
         * Checks whether the chat window is currently near the bottom.
         *
         * @param {number} threshold Allowed distance from the bottom in pixels.
         * @returns {boolean} True if the user is near the bottom.
         */
        function isNearBottom(threshold) {
            const t = threshold || 80;
            const distance = chatWindow.scrollHeight - chatWindow.scrollTop - chatWindow.clientHeight;
            return distance <= t;
        }

        /**
         * Resizes the input automatically up to a maximum height.
         */
        function autoResizeInput() {
            const maxHeight = 160;
            const shouldStickToBottom = isNearBottom();

            input.style.height = "auto";
            input.style.height = Math.min(input.scrollHeight, maxHeight) + "px";
            input.style.overflowY = input.scrollHeight > maxHeight ? "auto" : "hidden";

            if (shouldStickToBottom) {
                window.requestAnimationFrame(scrollToBottom);
            }
        }

        /**
         * Resets the input to its initial single-line height.
         */
        function resetInputHeight() {
            const shouldStickToBottom = isNearBottom();

            input.style.height = "48px";
            input.style.overflowY = "hidden";

            if (shouldStickToBottom) {
                window.requestAnimationFrame(scrollToBottom);
            }
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
            text.className = "llm-msg-body";
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
         * Updates chat loading status.
         *
         * @param {boolean} busy If true, locks input and turns send into stop.
         */
        function setBusy(busy) {
            isBusy = !!busy;

            input.disabled = isBusy;

            // Optional: lock clear/expand while answering.
            if (clearBtn) {
                clearBtn.disabled = isBusy;
            }

            if (openBtn) {
                openBtn.disabled = isBusy;
            }

            if (isBusy) {
                input.setAttribute("aria-disabled", "true");
            } else {
                input.removeAttribute("aria-disabled");
            }

            updateSendButtonState();
        }

        /**
         * Sends a question to the backend, or stops the current request if already busy.
         *
         * @returns {Promise<void>}
         */
        async function sendMessage() {
            // If already generating, clicking the same button stops the request.
            if (isBusy) {
                if (currentController) {
                    currentController.abort();
                }
                return;
            }

            const q = (input.value || "").trim();
            if (!q) {
                return;
            }

            currentController = new AbortController();
            setBusy(true);

            addMessage(q, "user");
            input.value = "";
            resetInputHeight();

            currentThinkingEl = addThinking();

            try {
                const res = await fetch(apiUrl, {
                    method: "POST",
                    headers: {"Content-Type": "application/x-www-form-urlencoded"},
                    body: new URLSearchParams({
                        sesskey: M.cfg.sesskey,
                        question: q,
                        courseid: courseId
                    }),
                    signal: currentController.signal
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

                if (currentThinkingEl) {
                    currentThinkingEl.remove();
                    currentThinkingEl = null;
                }

                const answer =
                    (typeof data.answer === "string" && data.answer.trim() !== "")
                        ? data.answer.trim()
                        : "No answer returned.";

                addAssistantMessage(answer, Array.isArray(data.sources) ? data.sources : []);
            } catch (err) {
                if (currentThinkingEl) {
                    currentThinkingEl.remove();
                    currentThinkingEl = null;
                }

                // Abort is intentional stop by user; do not show error bubble.
                if (err && err.name === "AbortError") {
                    addMessage("Generation stopped.", "bot");
                } else {
                    addMessage("Error contacting the assistant. Please try again.", "bot");
                }
            } finally {
                currentController = null;
                setBusy(false);
                input.focus();
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
            if (isBusy) {
                return;
            }

            if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });

        input.addEventListener("input", autoResizeInput);

        /**
         * Updates send button appearance/meaning depending on busy state.
         */
        function updateSendButtonState() {
            if (isBusy) {
                sendBtn.disabled = false; // keep clickable so it can stop
                sendBtn.setAttribute("aria-label", "Stop generating");
                sendBtn.setAttribute("title", "Stop generating");
                sendBtn.classList.add("llm-send-icon--stop");
            } else {
                sendBtn.disabled = false;
                sendBtn.setAttribute("aria-label", "Send message");
                sendBtn.setAttribute("title", "Send message");
                sendBtn.classList.remove("llm-send-icon--stop");
            }
        }

        updateSendButtonState();

        resetInputHeight();

        loadHistory();
    }

    return {
        init: init
    };
});
