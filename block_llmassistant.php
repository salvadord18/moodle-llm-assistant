<?php
/**
 * ==============================================
 * FILE: block_llmassistant.php
 * PURPOSE: Moodle block sidebar UI (chat preview + open center chat)
 * ==============================================
 *
 * Features:
 * - Sidebar chat UI (compact)
 * - Loads server-side history so sidebar matches center chat content
 * - "Open" navigates to center-panel chat page:
 *     - Course pages -> chat.php?courseid=<id>
 *     - Dashboard/site -> global.php (courseid=0)
 * - "Clear" clears history in DB for this conversation scope
 *
 * Notes:
 * - History is persisted server-side via history_endpoint.php
 * - Messages are persisted server-side via rag_endpoint.php
 */

defined('MOODLE_INTERNAL') || die();

class block_llmassistant extends block_base {

    /**
     * ----------------------------------------------
     * 1) Block title
     * ----------------------------------------------
     */
    public function init() {
        $this->title = get_string('pluginname', 'block_llmassistant');
    }

    /**
     * ----------------------------------------------
     * 2) Where the block can be shown
     * ----------------------------------------------
     */
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

    /**
     * ----------------------------------------------
     * 3) Main block rendering (HTML/CSS/JS)
     * ----------------------------------------------
     */
    public function get_content() {
        global $COURSE, $PAGE;

        if ($this->content !== null) {
            return $this->content;
        }

        $this->content = new stdClass();

        // Unique IDs per block instance (avoid DOM collisions).
        $instanceid = $this->instance ? (int)$this->instance->id : 0;
        $uid = 'llm_' . $instanceid;

        // Proxy endpoint (Moodle -> FastAPI).
        $apiurl = (new moodle_url('/blocks/llmassistant/rag_endpoint.php'))->out(false);

        // History endpoint (load/clear).
        $historyurl = (new moodle_url('/blocks/llmassistant/history_endpoint.php'))->out(false);

        // Decide scope:
        // - Course pages: use course id
        // - Dashboard/site: use 0 (global)
        $iscourse = (!empty($COURSE->id) && $COURSE->id != SITEID && $PAGE->context->contextlevel == CONTEXT_COURSE);
        $scope_courseid = $iscourse ? (int)$COURSE->id : 0;

        // Decide where "Open" should go:
        // - Course pages -> center panel course chat
        // - Dashboard/site -> center panel global chat
        if ($iscourse) {
            $openurl = (new moodle_url('/blocks/llmassistant/chat.php', ['courseid' => $COURSE->id]))->out(false);
        } else {
            $openurl = (new moodle_url('/blocks/llmassistant/global.php'))->out(false);
        }

        // English UI strings (as requested).
        $labeltitle = 'LLM Assistant';
        $labelopen = 'Open';
        $labelclear = 'Clear';
        $labelsend = 'Send';
        $labelplaceholder = 'Write your question...';
        $labelthinking = 'Thinking...';
        $labelsources = 'Sources:';
        $labelwelcome_course = 'Hi! Ask me something about this course.';
        $labelwelcome_global = 'Hi! Ask me about faculty rules and general information.';

        // Safe JS injection.
        $apiurl_js = json_encode($apiurl, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
        $historyurl_js = json_encode($historyurl, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
        $openurl_js = json_encode($openurl, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
        $welcome_js = json_encode($iscourse ? $labelwelcome_course : $labelwelcome_global, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);

        $this->content->text = <<<HTML
<style>
/* ==============================================
   LLM Assistant Sidebar UI
   ============================================== */

.llm-chat-container-{$uid}{background:#f8f9fa;border:1px solid #d0d7de;border-radius:12px;display:flex;flex-direction:column;height:460px;max-height:80vh;overflow:hidden;font-size:14px}
.llm-chat-header-{$uid}{background:#0b5ed7;color:#fff;padding:10px 12px;display:flex;justify-content:space-between;align-items:center}
.llm-chat-title-{$uid}{font-weight:600}
.llm-chat-actions-{$uid}{display:flex;gap:8px;align-items:center}
.llm-btn-{$uid}{background:rgba(255,255,255,.15);border:1px solid rgba(255,255,255,.25);color:#fff;border-radius:10px;padding:6px 10px;cursor:pointer;font-size:12px}
.llm-btn-{$uid}:hover{background:rgba(255,255,255,.22)}
.llm-chat-window-{$uid}{flex:1;overflow-y:auto;padding:12px;background:#fff}
.llm-msg-user-{$uid}{background:#d4edda;padding:10px;margin-bottom:8px;border-radius:12px;max-width:85%;margin-left:auto;white-space:pre-wrap}
.llm-msg-bot-{$uid}{background:#e9ecef;padding:10px;margin-bottom:8px;border-radius:12px;max-width:85%;white-space:pre-wrap}
.llm-sources-{$uid}{margin-top:6px;font-size:12px;opacity:.9}
.llm-chip-{$uid}{display:inline-block;padding:2px 8px;margin:2px 6px 0 0;border-radius:999px;background:#fff;border:1px solid #d0d7de}
.llm-chat-inputwrap-{$uid}{display:flex;gap:8px;padding:10px;background:#f8f9fa;border-top:1px solid #d0d7de}
.llm-input-{$uid}{flex:1;padding:8px;border-radius:10px;border:1px solid #c6cbd1;resize:none;outline:none}
.llm-send-{$uid}{padding:8px 14px;background:#0b5ed7;border:none;border-radius:10px;color:#fff;cursor:pointer}
.llm-send-{$uid}:hover{background:#0a53be}

.llm-spinner-{$uid}{display:inline-block;width:12px;height:12px;border:2px solid #bbb;border-top-color:#333;border-radius:50%;margin-right:8px;animation:llmspin-{$uid} .8s linear infinite}
@keyframes llmspin-{$uid}{to{transform:rotate(360deg)}}
</style>

<div id="llm_chat_{$uid}" class="llm-chat-container-{$uid}">
  <div class="llm-chat-header-{$uid}">
    <div class="llm-chat-title-{$uid}">{$labeltitle}</div>
    <div class="llm-chat-actions-{$uid}">
      <button type="button" id="llm_open_{$uid}" class="llm-btn-{$uid}">{$labelopen}</button>
      <button type="button" id="llm_clear_{$uid}" class="llm-btn-{$uid}">{$labelclear}</button>
    </div>
  </div>

  <div id="llm_chat_window_{$uid}" class="llm-chat-window-{$uid}"></div>

  <div class="llm-chat-inputwrap-{$uid}">
    <textarea id="llm_input_{$uid}" class="llm-input-{$uid}" rows="2" placeholder="{$labelplaceholder}"></textarea>
    <button type="button" id="llm_send_{$uid}" class="llm-send-{$uid}">{$labelsend}</button>
  </div>
</div>

<script>
/* ==============================================
   JS: Sidebar chat logic + history sync
   ============================================== */
(function() {
  const apiUrl = {$apiurl_js};
  const historyUrl = {$historyurl_js};
  const openUrl = {$openurl_js};
  const scopeCourseId = {$scope_courseid};
  const welcomeMsg = {$welcome_js};

  const chatWindow = document.getElementById("llm_chat_window_{$uid}");
  const sendBtn = document.getElementById("llm_send_{$uid}");
  const input = document.getElementById("llm_input_{$uid}");
  const openBtn = document.getElementById("llm_open_{$uid}");
  const clearBtn = document.getElementById("llm_clear_{$uid}");

  function addMessage(text, who) {
    const div = document.createElement("div");
    div.className = (who === "user") ? "llm-msg-user-{$uid}" : "llm-msg-bot-{$uid}";
    div.textContent = text;
    chatWindow.appendChild(div);
    chatWindow.scrollTop = chatWindow.scrollHeight;
  }

  function addThinking() {
    const div = document.createElement("div");
    div.className = "llm-msg-bot-{$uid}";
    div.innerHTML = '<span class="llm-spinner-{$uid}"></span>{$labelthinking}';
    chatWindow.appendChild(div);
    chatWindow.scrollTop = chatWindow.scrollHeight;
    return div;
  }

  function addSources(sources) {
    const uniq = [...new Set((sources || []).filter(Boolean))];
    if (!uniq.length) return;

    const wrap = document.createElement("div");
    wrap.className = "llm-msg-bot-{$uid}";

    const label = document.createElement("div");
    label.className = "llm-sources-{$uid}";
    label.textContent = "{$labelsources}";
    wrap.appendChild(label);

    const chips = document.createElement("div");
    uniq.forEach(s => {
      const chip = document.createElement("span");
      chip.className = "llm-chip-{$uid}";
      chip.textContent = s;
      chips.appendChild(chip);
    });
    wrap.appendChild(chips);

    chatWindow.appendChild(wrap);
    chatWindow.scrollTop = chatWindow.scrollHeight;
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
      if (!msgs.length) {
        addMessage(welcomeMsg, "bot");
        return;
      }

      msgs.forEach(m => addMessage(m.message, m.role === "user" ? "user" : "bot"));
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
      try { data = JSON.parse(raw); } catch (e) { data = {answer: "Error: invalid JSON response."}; }

      thinkingEl.remove();

      addMessage(data.answer || "No answer returned.", "bot");
      addSources(data.sources || []);

      // IMPORTANT: history is saved server-side by rag_endpoint.php,
      // so reloading history will show the same conversation here and in chat.php.
    } catch (err) {
      thinkingEl.remove();
      addMessage("Error contacting the assistant. Please try again.", "bot");
    }
  }

  openBtn.addEventListener("click", () => { window.location.href = openUrl; });
  clearBtn.addEventListener("click", clearHistory);
  sendBtn.addEventListener("click", sendMessage);

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  // Init: load persisted history so sidebar matches center panel chat.
  loadHistory();
})();
</script>
HTML;

        $this->content->footer = '';
        return $this->content;
    }
}
