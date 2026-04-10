<?php
require_once(__DIR__ . '/../../config.php');

$courseid = required_param('courseid', PARAM_INT);
$course = get_course($courseid);
require_login($course);

$context = context_course::instance($courseid);

$PAGE->requires->css('/blocks/llmassistant/styles.css');
$PAGE->set_url(new moodle_url('/blocks/llmassistant/chat.php', ['courseid' => $courseid]));
$PAGE->set_context($context);
$PAGE->set_pagelayout('course');
$PAGE->set_title('LLM Course Assistant');
$PAGE->set_heading($course->fullname);

$apiurl = (new moodle_url('/blocks/llmassistant/rag_endpoint.php'))->out(false);
$historyurl = (new moodle_url('/blocks/llmassistant/history_endpoint.php'))->out(false);

echo $OUTPUT->header();
?>

<div class="llm-center-wrap">
  <div class="llm-card">
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
        <span>LLM Assistant</span>
      </div>

      <div class="llm-actions">
        <button type="button"
                class="llm-icon-btn"
                id="llm_clear"
                title="Clear conversation"
                aria-label="Clear conversation">
          <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M20 20H7L3 16l9-9a2.8 2.8 0 0 1 4 0l5 5a2.8 2.8 0 0 1 0 4l-4 4Z"/>
            <path d="M6 13l5 5"/>
          </svg>
        </button>
      </div>
    </div>

    <div id="llm_chat_window" class="llm-chat-window llm-chat-window--expanded"></div>

    <div class="llm-input-row">
      <textarea id="llm_input" class="llm-input" rows="2" placeholder="Write your question..."></textarea>
      <button type="button"
              id="llm_send"
              class="llm-send-icon"
              title="Send message"
              aria-label="Send message">
        <svg viewBox="0 0 24 24" width="18" height="18">
          <path fill="currentColor" d="M2 21l21-9L2 3v7l15 2-15 2v7z"/>
        </svg>
      </button>
    </div>
  </div>
</div>

<script>
(function() {
  const apiUrl = <?php echo json_encode($apiurl); ?>;
  const historyUrl = <?php echo json_encode($historyurl); ?>;
  const courseId = <?php echo (int)$courseid; ?>;
  const labelSources = "Sources:";

  const chatWindow = document.getElementById("llm_chat_window");
  const sendBtn = document.getElementById("llm_send");
  const input = document.getElementById("llm_input");
  const clearBtn = document.getElementById("llm_clear");

  function scrollToBottom() {
    chatWindow.scrollTop = chatWindow.scrollHeight;
  }

  function addMessage(text, who) {
    const div = document.createElement("div");
    div.className = (who === "user") ? "llm-msg-user" : "llm-msg-bot";
    div.textContent = text;
    chatWindow.appendChild(div);
    scrollToBottom();
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
    scrollToBottom();
  }

  function addThinking() {
    const div = document.createElement("div");
    div.className = "llm-msg-bot";
    div.innerHTML = '<span class="llm-spinner"></span>Thinking...';
    chatWindow.appendChild(div);
    scrollToBottom();
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
          courseid: courseId
        })
      });

      const data = await res.json();
      const messages = data.messages || [];

      chatWindow.innerHTML = "";
      if (!messages.length) {
        addMessage("Hi! Ask me something about this course.", "bot");
        return;
      }

      for (const m of messages) {
        if (m.role === "assistant") {
          addAssistantMessage(m.message, m.sources || []);
        } else {
          addMessage(m.message, "user");
        }
      }
    } catch (e) {
      chatWindow.innerHTML = "";
      addMessage("Hi! Ask me something about this course.", "bot");
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
          courseid: courseId
        })
      });
    } catch (e) {}

    chatWindow.innerHTML = "";
    addMessage("Hi! Ask me something about this course.", "bot");
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
          courseid: courseId
        })
      });

      const raw = await res.text();
      let data = {};
      try {
        data = JSON.parse(raw);
      } catch (e) {
        data = {answer: "Error: invalid JSON response.", sources: []};
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

<?php
echo $OUTPUT->footer();