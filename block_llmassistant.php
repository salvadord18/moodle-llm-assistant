<?php
defined('MOODLE_INTERNAL') || die();

class block_llmassistant extends block_base {

    public function init() {
        $this->title = '';
    }

    public function applicable_formats() {
        return [
            'course-view' => true,
            'site' => true,
            'my' => true,
        ];
    }

    public function instance_allow_multiple() {
        return false;
    }

    public function get_content() {
        global $COURSE, $PAGE;

        $PAGE->requires->css('/blocks/llmassistant/styles.css');

        if ($this->content !== null) {
            return $this->content;
        }

        $this->content = new stdClass();

        $instanceid = $this->instance ? (int)$this->instance->id : 0;
        $uid = 'llm_' . $instanceid;

        $apiurl = (new moodle_url('/blocks/llmassistant/rag_endpoint.php'))->out(false);
        $historyurl = (new moodle_url('/blocks/llmassistant/history_endpoint.php'))->out(false);

        $iscourse = (!empty($COURSE->id) && $COURSE->id != SITEID && $PAGE->context->contextlevel == CONTEXT_COURSE);
        $scope_courseid = $iscourse ? (int)$COURSE->id : 0;

        if ($iscourse) {
            $openurl = (new moodle_url('/blocks/llmassistant/chat.php', ['courseid' => $COURSE->id]))->out(false);
        } else {
            $openurl = (new moodle_url('/blocks/llmassistant/global.php'))->out(false);
        }

        $labeltitle = 'LLM Assistant';
        $labelplaceholder = 'Write your question...';
        $labelthinking = 'Thinking...';
        $labelsources = 'Sources:';
        $labelwelcome_course = 'Hi! Ask me something about this course.';
        $labelwelcome_global = 'Hi! Ask me about faculty rules and general information.';

        $apiurl_js = json_encode($apiurl, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
        $historyurl_js = json_encode($historyurl, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
        $openurl_js = json_encode($openurl, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
        $welcome_js = json_encode($iscourse ? $labelwelcome_course : $labelwelcome_global, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
        $labelsources_js = json_encode($labelsources, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
        $labelthinking_js = json_encode($labelthinking, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);

        $this->content->text = <<<HTML
<div id="llm_chat_{$uid}" class="llm-chat-container">
  <div class="llm-header">
    <div class="llm-title">
      <span class="llm-ai-mark" aria-hidden="true">
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 8V4H8"/>
          <rect x="4" y="8" width="16" height="12" rx="2"/>
          <path d="M2 14h2"/>
          <path d="M20 14h2"/>
          <path d="M9 13h.01"/>
          <path d="M15 13h.01"/>
          <path d="M9 17h6"/>
        </svg>
      </span>
      <span>{$labeltitle}</span>
    </div>

    <div class="llm-actions">
      <button type="button"
              id="llm_open_{$uid}"
              class="llm-icon-btn"
              title="Expand chat"
              aria-label="Expand chat">
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="15 3 21 3 21 9"></polyline>
          <polyline points="9 21 3 21 3 15"></polyline>
          <line x1="21" y1="3" x2="14" y2="10"></line>
          <line x1="3" y1="21" x2="10" y2="14"></line>
        </svg>
      </button>

      <button type="button"
              id="llm_clear_{$uid}"
              class="llm-icon-btn"
              title="Clear conversation"
              aria-label="Clear conversation">
          <svg
            viewBox="0 0 24 24"
            width="18"
            height="18"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true">
            <path d="M20 20H7.5a2 2 0 0 1-1.4-.6l-3.5-3.5a2 2 0 0 1 0-2.8l8.6-8.6a2 2 0 0 1 2.8 0l5 5a2 2 0 0 1 0 2.8L12 20"/>
            <path d="M6 13l5 5"/>
          </svg>
      </button>
    </div>
  </div>

  <div id="llm_chat_window_{$uid}" class="llm-chat-window"></div>

  <div class="llm-chat-inputwrap">
    <textarea id="llm_input_{$uid}" class="llm-input" rows="2" placeholder="{$labelplaceholder}"></textarea>
    <button type="button"
            id="llm_send_{$uid}"
            class="llm-send-icon"
            title="Send message"
            aria-label="Send message">
      <svg viewBox="0 0 24 24" width="18" height="18">
        <path fill="currentColor" d="M2 21l21-9L2 3v7l15 2-15 2v7z"/>
      </svg>
    </button>
  </div>
</div>

<script>
(function() {
  const apiUrl = {$apiurl_js};
  const historyUrl = {$historyurl_js};
  const openUrl = {$openurl_js};
  const scopeCourseId = {$scope_courseid};
  const welcomeMsg = {$welcome_js};
  const labelSources = {$labelsources_js};
  const labelThinking = {$labelthinking_js};

  const chatWindow = document.getElementById("llm_chat_window_{$uid}");
  const sendBtn = document.getElementById("llm_send_{$uid}");
  const input = document.getElementById("llm_input_{$uid}");
  const openBtn = document.getElementById("llm_open_{$uid}");
  const clearBtn = document.getElementById("llm_clear_{$uid}");

  function addMessage(text, who) {
    const div = document.createElement("div");
    div.className = (who === "user") ? "llm-msg-user" : "llm-msg-bot";
    div.textContent = text;
    chatWindow.appendChild(div);
    chatWindow.scrollTop = chatWindow.scrollHeight;
  }

  function addAssistantMessage(answer, sources) {
    const wrap = document.createElement("div");
    wrap.className = "llm-msg-bot";

    const text = document.createElement("div");
    text.textContent = answer;
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
        formatted.forEach(function(t) {
          const chip = document.createElement("span");
          chip.className = "llm-chip";
          chip.textContent = t;
          chips.appendChild(chip);
        });

        src.appendChild(chips);
        wrap.appendChild(src);
      }
    }

    chatWindow.appendChild(wrap);
    chatWindow.scrollTop = chatWindow.scrollHeight;
  }

  function addThinking() {
    const div = document.createElement("div");
    div.className = "llm-msg-bot";
    div.innerHTML = '<span class="llm-spinner"></span>' + labelThinking;
    chatWindow.appendChild(div);
    chatWindow.scrollTop = chatWindow.scrollHeight;
    return div;
  }

  async function loadHistory() {
    try {
      const res = await fetch(historyUrl, {
        method: "POST",
        headers: {"Content-Type": "application/x-www-form-urlencoded"},
        body: new URLSearchParams({
          sesskey: M.cfg.sesskey,
          action: "load",
          courseid: scopeCourseId
        })
      });

      const data = await res.json();
      const msgs = data.messages || [];

      chatWindow.innerHTML = "";
      addMessage(welcomeMsg, "bot");

      msgs.forEach(function(m) {
        if (m.role === "assistant") {
          addAssistantMessage(m.message, m.sources || []);
        } else {
          addMessage(m.message, "user");
        }
      });
    } catch (e) {
      chatWindow.innerHTML = "";
      addMessage(welcomeMsg, "bot");
    }
  }

  async function clearHistory() {
    try {
      await fetch(historyUrl, {
        method: "POST",
        headers: {"Content-Type": "application/x-www-form-urlencoded"},
        body: new URLSearchParams({
          sesskey: M.cfg.sesskey,
          action: "clear",
          courseid: scopeCourseId
        })
      });
    } catch (e) {}

    chatWindow.innerHTML = "";
    addMessage(welcomeMsg, "bot");
  }

  async function sendMessage() {
    const q = (input.value || "").trim();
    if (!q) return;

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
          courseid: scopeCourseId
        })
      });

      const raw = await res.text();
      let data = {};
      try {
        data = JSON.parse(raw);
      } catch (e) {
        data = {
          answer: "Error: invalid JSON response from server.",
          sources: [],
          debug: raw
        };
      }

      if (data.debug) {
        console.warn("LLM debug:", data.debug);
      }

      thinkingEl.remove();

      const answer =
        (typeof data.answer === "string" && data.answer.trim() !== "")
          ? data.answer.trim()
          : "Error: empty or invalid assistant response.";

      addAssistantMessage(answer, Array.isArray(data.sources) ? data.sources : []);
    } catch (err) {
      thinkingEl.remove();
      addMessage("Error contacting the assistant. Please try again.", "bot");
    }
  }

  openBtn.addEventListener("click", function() { window.location.href = openUrl; });
  clearBtn.addEventListener("click", clearHistory);
  sendBtn.addEventListener("click", sendMessage);

  input.addEventListener("keydown", function(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  loadHistory();
})();
</script>
HTML;

        $this->content->footer = '';
        return $this->content;
    }
}
