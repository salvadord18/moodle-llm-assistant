<?php
require_once(__DIR__ . '/../../config.php');

$courseid = required_param('courseid', PARAM_INT);
$course = get_course($courseid);
require_login($course);

$context = context_course::instance($courseid);

$PAGE->set_url(new moodle_url('/blocks/llmassistant/chat.php', ['courseid' => $courseid]));
$PAGE->set_context($context);
$PAGE->set_pagelayout('course');
$PAGE->set_title('LLM Assistant');
$PAGE->set_heading($course->fullname);

$apiurl = (new moodle_url('/blocks/llmassistant/rag_endpoint.php'))->out(false);
$historyurl = (new moodle_url('/blocks/llmassistant/history_endpoint.php'))->out(false);

echo $OUTPUT->header();
?>

<style>
.llm-center-wrap { max-width: 980px; margin: 0 auto; }
.llm-card { background: #fff; border: 1px solid #d0d7de; border-radius: 14px; overflow: hidden; }
.llm-header { background: #0b5ed7; color: #fff; padding: 12px 14px; display: flex; justify-content: space-between; align-items: center; }
.llm-title { font-weight: 600; font-size: 16px; }
.llm-subtitle { opacity: 0.9; font-size: 12px; }
.llm-actions { display: flex; gap: 8px; }
.llm-btn { background: rgba(255,255,255,0.15); border: 1px solid rgba(255,255,255,0.25); color: #fff; border-radius: 10px; padding: 7px 10px; cursor: pointer; font-size: 12px; }
.llm-btn:hover { background: rgba(255,255,255,0.22); }
.llm-chat-window { height: min(72vh, 740px); overflow-y: auto; padding: 16px; background: #fafafa; }
.llm-msg-user { background: #d4edda; padding: 10px 12px; margin: 0 0 10px 0; border-radius: 14px; max-width: 80%; margin-left: auto; white-space: pre-wrap; }
.llm-msg-bot { background: #e9ecef; padding: 10px 12px; margin: 0 0 10px 0; border-radius: 14px; max-width: 80%; white-space: pre-wrap; }
.llm-sources { margin-top: 8px; font-size: 12px; opacity: 0.9; }
.llm-chip { display: inline-block; padding: 2px 8px; margin: 2px 6px 0 0; border-radius: 999px; background: #fff; border: 1px solid #d0d7de; }
.llm-input-row { display: flex; gap: 10px; padding: 12px; border-top: 1px solid #d0d7de; background: #fff; position: sticky; bottom: 0; }
.llm-input { flex: 1; border: 1px solid #c6cbd1; border-radius: 12px; padding: 10px; resize: none; outline: none; }
.llm-send { background: #0b5ed7; color: #fff; border: none; border-radius: 12px; padding: 10px 14px; cursor: pointer; }
.llm-send:hover { background: #0a53be; }
.llm-spinner { display:inline-block; width:12px; height:12px; border:2px solid #bbb; border-top-color:#333; border-radius:50%; margin-right:8px; animation: llmspin 0.8s linear infinite; }
@keyframes llmspin { to { transform: rotate(360deg); } }
</style>

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
        addMessage(m.message, m.role === "user" ? "user" : "bot");
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
        data = {answer: "Error: invalid JSON response."};
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