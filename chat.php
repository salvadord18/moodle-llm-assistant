<?php
/**
 * Course Chat Page (Center Panel)
 * --------------------------------
 * This page renders a full-size chat experience inside Moodle's main content area.
 *
 * Key features:
 * - Uses the current course context (course-specific chat)
 * - Loads chat history (one conversation per course per user)
 * - Clears chat history from DB (course-specific)
 * - Sends questions to rag_endpoint.php (Moodle -> FastAPI proxy)
 *
 * Notes:
 * - This file assumes you have:
 *   - /blocks/llmassistant/rag_endpoint.php (returns JSON: {answer, sources})
 *   - /blocks/llmassistant/history_endpoint.php (supports actions: load, clear)
 *
 * All UI text is intentionally in English (as requested).
 */

require_once(__DIR__ . '/../../config.php');

// -------------------------
// 1) Input / Permissions
// -------------------------
$courseid = required_param('courseid', PARAM_INT);
$course = get_course($courseid);
require_login($course);

$context = context_course::instance($courseid);

// -------------------------
// 2) Page Setup (Center Panel)
// -------------------------
$PAGE->set_url(new moodle_url('/blocks/llmassistant/chat.php', ['courseid' => $courseid]));
$PAGE->set_context($context);
$PAGE->set_pagelayout('course');
$PAGE->set_title('LLM Assistant');
$PAGE->set_heading($course->fullname);

// -------------------------
// 3) Endpoint URLs
// -------------------------
$apiurl = (new moodle_url('/blocks/llmassistant/rag_endpoint.php'))->out(false);
$historyurl = (new moodle_url('/blocks/llmassistant/history_endpoint.php'))->out(false);

echo $OUTPUT->header();
?>

<!-- =========================
     4) Styles (Chat UI)
     ========================= -->
<style>
/* --------------------------------
   Center Panel Layout
--------------------------------- */
.llm-center-wrap {
  max-width: 980px;
  margin: 0 auto;
}
.llm-card {
  background: #fff;
  border: 1px solid #d0d7de;
  border-radius: 14px;
  overflow: hidden;
}
.llm-header {
  background: #0b5ed7;
  color: #fff;
  padding: 12px 14px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.llm-title {
  font-weight: 600;
  font-size: 16px;
}
.llm-subtitle {
  opacity: 0.9;
  font-size: 12px;
}
.llm-actions {
  display: flex;
  gap: 8px;
}
.llm-btn {
  background: rgba(255,255,255,0.15);
  border: 1px solid rgba(255,255,255,0.25);
  color: #fff;
  border-radius: 10px;
  padding: 7px 10px;
  cursor: pointer;
  font-size: 12px;
}
.llm-btn:hover { background: rgba(255,255,255,0.22); }

/* --------------------------------
   Chat Window / Bubbles
--------------------------------- */
.llm-chat-window {
  height: min(72vh, 740px);
  overflow-y: auto;
  padding: 16px;
  background: #fafafa;
}

.llm-msg-user {
  background: #d4edda;
  padding: 10px 12px;
  margin: 0 0 10px 0;
  border-radius: 14px;
  max-width: 80%;
  margin-left: auto;
  white-space: pre-wrap;
}

.llm-msg-bot {
  background: #e9ecef;
  padding: 10px 12px;
  margin: 0 0 10px 0;
  border-radius: 14px;
  max-width: 80%;
  white-space: pre-wrap;
}

/* Sources */
.llm-sources {
  margin-top: 8px;
  font-size: 12px;
  opacity: 0.9;
}
.llm-chip {
  display: inline-block;
  padding: 2px 8px;
  margin: 2px 6px 0 0;
  border-radius: 999px;
  background: #fff;
  border: 1px solid #d0d7de;
}

/* --------------------------------
   Input Bar (Sticky)
--------------------------------- */
.llm-input-row {
  display: flex;
  gap: 10px;
  padding: 12px;
  border-top: 1px solid #d0d7de;
  background: #fff;
  position: sticky;
  bottom: 0;
}
.llm-input {
  flex: 1;
  border: 1px solid #c6cbd1;
  border-radius: 12px;
  padding: 10px;
  resize: none;
  outline: none;
}
.llm-send {
  background: #0b5ed7;
  color: #fff;
  border: none;
  border-radius: 12px;
  padding: 10px 14px;
  cursor: pointer;
}
.llm-send:hover { background: #0a53be; }

/* --------------------------------
   Spinner
--------------------------------- */
.llm-spinner {
  display:inline-block;
  width:12px; height:12px;
  border:2px solid #bbb; border-top-color:#333;
  border-radius:50%;
  margin-right:8px;
  animation: llmspin 0.8s linear infinite;
}
@keyframes llmspin { to { transform: rotate(360deg); } }
</style>

<!-- =========================
     5) HTML Structure
     ========================= -->
<div class="llm-center-wrap">
  <div class="llm-card">
    <div class="llm-header">
      <div>
        <div class="llm-title">LLM Assistant</div>
        <div class="llm-subtitle">Course chat (this course only)</div>
      </div>
      <div class="llm-actions">
        <button type="button" class="llm-btn" id="llm_clear">Clear</button>
      </div>
    </div>

    <div id="llm_chat_window" class="llm-chat-window"></div>

    <div class="llm-input-row">
      <textarea id="llm_input" class="llm-input" rows="2" placeholder="Write your question..."></textarea>
      <button type="button" id="llm_send" class="llm-send">Send</button>
    </div>
  </div>
</div>

<!-- =========================
     6) JavaScript Logic
     ========================= -->
<script>
(function() {
  // -------------------------
  // A) Configuration
  // -------------------------
  const apiUrl = <?php echo json_encode($apiurl); ?>;
  const historyUrl = <?php echo json_encode($historyurl); ?>;
  const courseId = <?php echo (int)$courseid; ?>;

  // -------------------------
  // B) DOM References
  // -------------------------
  const chatWindow = document.getElementById("llm_chat_window");
  const sendBtn = document.getElementById("llm_send");
  const input = document.getElementById("llm_input");
  const clearBtn = document.getElementById("llm_clear");

  // -------------------------
  // C) UI Helpers
  // -------------------------
  function scrollToBottom() {
    chatWindow.scrollTop = chatWindow.scrollHeight;
  }

  function addMessage(text, who) {
    const div = document.createElement("div");
    div.className = (who === "user") ? "llm-msg-user" : "llm-msg-bot";
    div.textContent = text;
    chatWindow.appendChild(div);
    scrollToBottom();
    return div;
  }

  function addThinking() {
    const div = document.createElement("div");
    div.className = "llm-msg-bot";
    div.innerHTML = `<span class="llm-spinner"></span>Thinking...`;
    chatWindow.appendChild(div);
    scrollToBottom();
    return div;
  }

  function addSources(sources) {
    const uniq = [...new Set((sources || []).filter(Boolean))];
    if (!uniq.length) return;

    const wrap = document.createElement("div");
    wrap.className = "llm-msg-bot";

    const label = document.createElement("div");
    label.className = "llm-sources";
    label.textContent = "Sources:";
    wrap.appendChild(label);

    const chips = document.createElement("div");
    uniq.forEach(s => {
      const chip = document.createElement("span");
      chip.className = "llm-chip";
      chip.textContent = s;
      chips.appendChild(chip);
    });
    wrap.appendChild(chips);

    chatWindow.appendChild(wrap);
    scrollToBottom();
  }

  // -------------------------
  // D) History: Load / Clear
  // -------------------------
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
        const who = (m.role === "user") ? "user" : "bot";
        addMessage(m.message, who);
      }
    } catch (e) {
      // If history fails, still allow chat.
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
    } catch (e) {
      // Ignore errors; we still clear UI.
    }
    chatWindow.innerHTML = "";
    addMessage("Hi! Ask me something about this course.", "bot");
  }

  // -------------------------
  // E) Send Message (RAG)
  // -------------------------
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
      try { data = JSON.parse(raw); }
      catch (e) { data = {answer: "Error: invalid JSON response."}; }

      thinkingEl.remove();
      addMessage(data.answer || "No answer returned.", "bot");
      addSources(data.sources || []);

      // History saving:
      // Recommended approach: save in rag_endpoint.php (server-side),
      // so both sidebar and center chat share the same persisted history.
      // If you do server-side saving, reloading history will show everything.
      //
      // If you prefer client-side saving, add an action='save' to history_endpoint.php.
      // (Not implemented here to keep server-side as source of truth.)
    } catch (err) {
      thinkingEl.remove();
      addMessage("Error contacting the assistant. Please try again.", "bot");
    }
  }

  // -------------------------
  // F) Event wiring
  // -------------------------
  clearBtn.addEventListener("click", clearHistory);
  sendBtn.addEventListener("click", sendMessage);

  // Enter sends, Shift+Enter newline.
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  // -------------------------
  // G) Init
  // -------------------------
  loadHistory();
})();
</script>

<?php
echo $OUTPUT->footer();
