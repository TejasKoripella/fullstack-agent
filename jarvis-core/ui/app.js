    const form = document.getElementById("chat-form");
    const messageInput = document.getElementById("message");
    const saveInput = document.getElementById("save");
    const speakInput = document.getElementById("speak");
    const sendButton = document.getElementById("send");
    const micButton = document.getElementById("mic");
    const micStatus = document.getElementById("mic-status");
    const imagePreview = document.getElementById("image-preview");
    const captureStatus = document.getElementById("capture-status");
    const conversation = document.getElementById("conversation");
    const recalledLabel = document.getElementById("recalled");
    const statusDot = document.getElementById("status-dot");
    const statusText = document.getElementById("status-text");
    const homeTab = document.getElementById("home-tab");
    const controlTab = document.getElementById("control-tab");
    const wakeEnabled = document.getElementById("wake-enabled");
    const microphoneSelect = document.getElementById("microphone-select");
    const wakeStatus = document.getElementById("wake-status");
    const sidebarToggle = document.getElementById("sidebar-toggle");
    const sidebarClose = document.getElementById("sidebar-close");
    const sidebarScrim = document.getElementById("sidebar-scrim");
    const chatList = document.getElementById("chat-list");
    const chatMenu = document.createElement("div");
    chatMenu.className = "chat-row-menu";
    chatMenu.setAttribute("role", "menu");
    chatMenu.setAttribute("aria-label", "Chat actions");
    chatMenu.hidden = true;
    const chatMenuRename = document.createElement("button");
    chatMenuRename.type = "button";
    chatMenuRename.setAttribute("role", "menuitem");
    chatMenuRename.textContent = "Rename";
    const chatMenuDelete = document.createElement("button");
    chatMenuDelete.type = "button";
    chatMenuDelete.className = "chat-row-menu-delete";
    chatMenuDelete.setAttribute("role", "menuitem");
    chatMenuDelete.textContent = "Delete";
    chatMenu.append(chatMenuRename, chatMenuDelete);
    document.body.append(chatMenu);
    let openChatMenuSession = null;
    let openChatMenuTrigger = null;
    let openChatMenuRowButton = null;
    let sending = false;
    let openingSide = false;
    let sessionTurns = [];
    let activeSession = null;
    const activePreviews = new Map();
    function cancelTargetPreviews() {
      for (const [reference, workspace_scope] of activePreviews) {
        safeFetch("/tools/preview-cancel", { ...jsonRequest("POST", {reference, workspace_scope}), keepalive: true }).catch(() => {});
      }
      activePreviews.clear();
    }
    window.addEventListener("pagehide", cancelTargetPreviews);
    let sideSession = null;
    let masterSession = null;
    let conversationType = "master";
    const chatSessions = [];
    let chatPendingDeletion = null;
    let localVoice = null;
    let pendingImage = null;
    let pendingDocumentPath = null;
    let pendingWindowReference = null;
    let pendingDocumentScope = "documents";
    let lastReadDocumentPath = null;
    let lastReadProjectPath = null;
    let projectReadVersion = 0;
    let imageCaptureVersion = 0;
    let imageCaptureStream = null;
    let micRequested = false;
    let recordingVersion = 0;
    let conversationVersion = 0;
    let documentRequestVersion = 0;
    let spotifyStatusVersion = 0;
    let bluetoothStatusVersion = 0;
    let appListVersion = 0;
    let recorder = null;
    let releaseRecordingStream = () => {};
    let micTimer = null;
    let sendRecordedAudio = false;
    let wakeStream = null;
    let wakeRecorder = null;
    let wakeTimer = null;
    let wakeSession = 0;
    let wakeAudioContext = null;
    let wakeMeterTimer = null;
    let wakeVoiceSeen = false;
    let wakeVoiceHits = 0;
    let wakeNoiseFloor = 2;
    let wakeCheckBusy = false;
    let refreshVisuals = () => {};
    let currentAudio = null;
    let speechVersion = 0;
    let speechAbort = null;
    let currentAudioUrl = null;
    let safetyStopped = true;
    let safetyEpoch = null;
    let safetySyncBusy = false;
    let chatAbort = null;
    const requestControllers = new Set();
    const emergencyButton = document.getElementById("emergency-stop");
    const resumeButton = document.getElementById("resume-jarvis");
    const safetyStatus = document.getElementById("safety-status");
    const resourceSelect = document.getElementById("resource-select");
    const resourceButton = document.getElementById("open-resource");

    async function safeFetch(url, options = {}) {
      const active = (options.method || "GET") !== "GET" || /^\/(tools|voice)\//.test(url);
      if (active && safetyStopped) throw new Error("Jarvis is stopped. Resume manually first.");
      const controller = new AbortController();
      const abort = () => controller.abort();
      if (options.signal?.aborted) abort();
      options.signal?.addEventListener("abort", abort, { once: true });
      // Saved history and other read-only local views remain usable while stopped.
      if (active) requestControllers.add(controller);
      try {
        const response = await window.fetch(url, { ...options, signal: options.signal || controller.signal });
        if (response.status === 423) {
          localStorage.setItem("jarvis-emergency-stop", "1");
          stopLocalActivity();
        }
        if (active && safetyStopped) throw new Error("Jarvis stopped; request cancelled.");
        return response;
      } finally {
        requestControllers.delete(controller);
        options.signal?.removeEventListener("abort", abort);
      }
    }

    const stoppedActionControls = new Map();
    function setActionControlsStopped(stopped) {
      if (stopped) {
        document.querySelectorAll("#open-app, #close-app, #inspect-app, #app-select, #open-resource, #resource-select, #open-windows-documents, #list-documents, #find-documents-form button, #read-form button, #open-spotify-app, #spotify-play, #spotify-pause, #spotify-check, #open-bluetooth-settings, #open-sound-settings, #check-bluetooth").forEach(control => {
          if (!stoppedActionControls.has(control)) stoppedActionControls.set(control, control.disabled);
          control.disabled = true;
        });
      } else {
        for (const [control, wasDisabled] of stoppedActionControls) control.disabled = wasDisabled;
        stoppedActionControls.clear();
      }
    }

    function stopLocalActivity() {
      const firstStop = !safetyStopped;
      safetyStopped = true;
      if (firstStop) {
        cancelTargetPreviews();
        conversationVersion += 1;
      }
      chatAbort?.abort();
      for (const controller of requestControllers) controller.abort();
      requestControllers.clear();
      endRecording(false);
      stopWake();
      stopSpeech();
      clearImage();
      clearDocument();
      closeChatMenu();
      closeSideActions();
      document.querySelectorAll(".workflow-actions").forEach(actions => {
        if (!actions.querySelector("button")) return;
        actions.replaceChildren();
        actions.textContent = "Approval cancelled by Emergency Stop";
      });
      document.querySelectorAll(".target-preview button, .target-preview select").forEach(control => { control.disabled = true; });
      document.querySelectorAll(".reply-dots").forEach(dots => {
        dots.parentElement.replaceChildren(document.createTextNode("Stopped"));
      });
      sending = false;
      sendButton.disabled = true;
      sendButton.textContent = "↑";
      resumeButton.disabled = true;
      resourceButton.disabled = true;
      setActionControlsStopped(true);
      setAssistantState("stopped");
    }

    async function emergencyStop(source = "settings") {
      localStorage.setItem("jarvis-emergency-stop", "1");
      stopLocalActivity();
      safetyStatus.textContent = "STOPPED · confirming backend stop…";
      try {
        const response = await window.fetch("/safety/stop", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ approved: true, source, reason: "User Emergency Stop" })
        });
        if (!response.ok) throw new Error("Stop not confirmed");
        const result = await response.json();
        safetyEpoch = result.epoch;
        resumeButton.disabled = false;
        safetyStatus.textContent = "STOPPED · " + (result.cleanup_errors?.join("; ") || "All new activity blocked");
      } catch {
        safetyStatus.textContent = "STOPPED locally · backend confirmation failed. Press Emergency Stop to retry.";
      }
    }

    async function deviceReady() {
      if (safetyStopped) return false;
      try {
        const response = await window.fetch("/safety", { cache: "no-store" });
        if (!response.ok) throw new Error("Safety unavailable");
        const result = await response.json();
        if (result.state !== "RUNNING" || result.epoch !== safetyEpoch) {
          stopLocalActivity();
          return false;
        }
        return !safetyStopped;
      } catch {
        stopLocalActivity();
        return false;
      }
    }

    async function syncSafety() {
      if (safetySyncBusy) return;
      safetySyncBusy = true;
      try {
        const response = await window.fetch("/safety", { cache: "no-store" });
        if (!response.ok) throw new Error("Safety unavailable");
        const result = await response.json();
        safetyEpoch = result.epoch;
        if (result.state === "STOPPED") {
          localStorage.setItem("jarvis-emergency-stop", "1");
          if (!safetyStopped || document.body.dataset.assistantState !== "stopped") stopLocalActivity();
          resumeButton.disabled = false;
          safetyStatus.textContent = "STOPPED · manual resume required";
        } else if (localStorage.getItem("jarvis-emergency-stop") === "1") {
          // A lost stop response or reload must never silently clear the latch.
          await emergencyStop();
        } else {
          const wasStopped = safetyStopped;
          safetyStopped = false;
          setActionControlsStopped(false);
          sendButton.disabled = sending;
          resumeButton.disabled = true;
          safetyStatus.textContent = "RUNNING · Emergency Stop available";
          if (wasStopped) {
            setAssistantState(speakInput.checked ? "idle" : "muted");
            loadApps();
            loadResources();
            findLocalVoice();
            checkBluetooth();
            checkSpotifyStatus();
          }
        }
      } catch {
        stopLocalActivity();
        safetyStatus.textContent = "STOPPED · local safety service unavailable";
      } finally { safetySyncBusy = false; }
    }

    emergencyButton.addEventListener("click", () => emergencyStop());
    resumeButton.addEventListener("click", async () => {
      resumeButton.disabled = true;
      try {
        const response = await window.fetch("/safety/resume", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ approved: true, source: "settings" })
        });
        if (!response.ok) throw new Error("Resume not confirmed");
        const result = await response.json();
        safetyEpoch = result.epoch;
        localStorage.removeItem("jarvis-emergency-stop");
        safetyStopped = false;
        setActionControlsStopped(false);
        sending = false;
        sendButton.disabled = false;
        setAssistantState(speakInput.checked ? "idle" : "muted");
        safetyStatus.textContent = "RUNNING · cancelled activity stays cancelled";
        loadApps();
        loadResources();
        findLocalVoice();
        checkBluetooth();
        checkSpotifyStatus();
      } catch {
        safetyStatus.textContent = "STOPPED · could not confirm resume";
        resumeButton.disabled = false;
      }
    });
    window.addEventListener("keydown", event => {
      if (document.hasFocus() && event.ctrlKey && event.altKey && event.code === "KeyJ") {
        event.preventDefault();
        emergencyStop("keyboard");
      }
    });
    window.addEventListener("focus", syncSafety);

    function stopSpeech() {
      speechVersion += 1;
      speechAbort?.abort();
      speechAbort = null;
      if (window.speechSynthesis) speechSynthesis.cancel();
      if (currentAudio) {
        currentAudio.onended = null;
        currentAudio.onerror = null;
        currentAudio.onplaying = null;
        currentAudio.pause();
        currentAudio = null;
      }
      if (currentAudioUrl) URL.revokeObjectURL(currentAudioUrl);
      currentAudioUrl = null;
    }
    let assistantStateVersion = 0;
    const stateLabels = { idle: "READY", listening: "LISTENING", thinking: "THINKING", tool: "USING TOOL", approval: "AWAITING APPROVAL", speaking: "SPEAKING", muted: "MUTED", error: "ERROR", stopped: "STOPPED" };
    const stateLabel = document.getElementById("assistant-state");
    stateLabel.replaceChildren();
    for (const [state, label] of Object.entries(stateLabels)) {
      const layer = document.createElement("span");
      layer.className = "state-label-layer";
      layer.dataset.state = state;
      layer.setAttribute("aria-hidden", "true");
      [...label].forEach((letter, index) => {
        const span = document.createElement("span");
        span.className = "state-letter";
        span.textContent = letter === " " ? "\u00a0" : letter;
        span.style.setProperty("--letter", index);
        layer.append(span);
      });
      stateLabel.append(layer);
    }
    stateLabel.setAttribute("aria-label", "READY");
    function setAssistantState(state, preview = false) {
      if (safetyStopped) state = "stopped";
      else if (!preview && (state === "idle" || state === "muted") &&
               conversation.querySelector(".workflow-actions button:not(:disabled)")) state = "approval";
      if (!stateLabels[state]) return assistantStateVersion;
      if (document.body.dataset.assistantState === state) return assistantStateVersion;
      const version = ++assistantStateVersion;
      document.body.dataset.assistantState = state;
      stateLabel.setAttribute("aria-label", stateLabels[state]);
      window.dispatchEvent(new Event("jarvis-state-change"));
      document.getElementById("dev-state").textContent = state.toUpperCase();
      if (state === "error" && !preview) {
        setTimeout(() => {
          if (assistantStateVersion === version) setAssistantState(speakInput.checked ? "idle" : "muted");
        }, 3800);
      }
      return version;
    }
    function settleTool(version) {
      setTimeout(() => {
        if (assistantStateVersion === version) setAssistantState(speakInput.checked ? "idle" : "muted");
      }, 420);
    }
    document.getElementById("dev-mode").addEventListener("change", event => {
      document.getElementById("dev-diagnostics").hidden = !event.target.checked;
      if (!event.target.checked && !sending) setAssistantState(speakInput.checked ? "idle" : "muted");
    });
    document.getElementById("dev-state-preview").addEventListener("change", event => {
      if (sending || recorder || currentAudio) return;
      showView("home");
      setAssistantState(event.target.value, true);
    });

    function closeSidebar() {
      closeChatMenu();
      document.body.classList.remove("sidebar-open");
      sidebarToggle.setAttribute("aria-expanded", "false");
      sidebarScrim.hidden = true;
    }
    function openSidebar() {
      document.body.classList.add("sidebar-open");
      sidebarToggle.setAttribute("aria-expanded", "true");
      sidebarScrim.hidden = false;
    }
    sidebarToggle.addEventListener("click", () => document.body.classList.contains("sidebar-open") ? closeSidebar() : openSidebar());
    sidebarClose.addEventListener("click", closeSidebar);
    sidebarScrim.addEventListener("click", closeSidebar);

    async function apiJson(url, options = {}) {
      const response = await safeFetch(url, options);
      let result;
      try { result = await response.json(); }
      catch { throw new Error("The local service did not return a usable response."); }
      if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Request failed.");
      return result;
    }
    const jsonRequest = (method, body) => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

    function updateConversationLayout() {
      document.body.dataset.hasMessages = conversation.querySelector(".message") ? "true" : "false";
      requestAnimationFrame(refreshVisuals);
    }

    async function persistEntry(chatId, role, content) {
      if (!chatId) return;
      await apiJson("/conversations/" + chatId + "/messages", jsonRequest("POST", { role, content }));
    }

    function closeChatMenu() {
      openChatMenuTrigger?.setAttribute("aria-expanded", "false");
      openChatMenuSession = null;
      openChatMenuTrigger = null;
      openChatMenuRowButton = null;
      chatMenu.hidden = true;
    }

    function positionChatMenu() {
      if (!openChatMenuTrigger || chatMenu.hidden) return;
      const trigger = openChatMenuTrigger.getBoundingClientRect();
      const sidebar = document.querySelector(".app-sidebar").getBoundingClientRect();
      const list = chatList.getBoundingClientRect();
      const scrollArea = chatList.closest(".sidebar-section").getBoundingClientRect();
      const visibleTop = Math.max(list.top, scrollArea.top);
      const visibleBottom = Math.min(list.bottom, scrollArea.bottom);
      if (trigger.bottom < visibleTop || trigger.top > visibleBottom ||
          visibleBottom <= visibleTop || !openChatMenuTrigger.isConnected) {
        closeChatMenu();
        return;
      }
      const gap = 4;
      const width = chatMenu.offsetWidth;
      const height = chatMenu.offsetHeight;
      const lowerEdge = Math.min(window.innerHeight - 8, sidebar.bottom - 8);
      const upperEdge = Math.max(8, sidebar.top + 8);
      const below = trigger.bottom + gap;
      const above = trigger.top - height - gap;
      const top = below + height <= lowerEdge ? below : above >= upperEdge ? above : Math.max(upperEdge, lowerEdge - height);
      const leftEdge = Math.max(8, sidebar.left + 8);
      const rightEdge = Math.min(window.innerWidth - 8, sidebar.right - 8);
      const left = Math.max(leftEdge, Math.min(trigger.right - width, rightEdge - width));
      chatMenu.style.top = `${Math.round(top)}px`;
      chatMenu.style.left = `${Math.round(left)}px`;
    }

    function toggleChatMenu(session, trigger, rowButton) {
      if (openChatMenuTrigger === trigger) {
        closeChatMenu();
        return;
      }
      closeChatMenu();
      openChatMenuSession = session;
      openChatMenuTrigger = trigger;
      openChatMenuRowButton = rowButton;
      trigger.setAttribute("aria-expanded", "true");
      chatMenu.hidden = false;
      positionChatMenu();
    }

    function startChatRename(session, button) {
      const input = document.createElement("input");
      input.className = "chat-rename-input";
      input.maxLength = 100;
      input.value = session.title;
      button.replaceWith(input);
      input.focus();
      input.select();
      let finished = false;
      const commit = async () => {
        if (finished) return;
        finished = true;
        const title = input.value.trim();
        if (title && title !== session.title) {
          try {
            await apiJson("/conversations/" + session.id, jsonRequest("PATCH", { title }));
            session.title = title;
            if (session === activeSession) updateChatHeader();
          } catch { /* Keep the old title when storage is unavailable. */ }
        }
        renderChatList();
      };
      input.addEventListener("keydown", event => {
        if (event.key === "Enter") { event.preventDefault(); commit(); }
        if (event.key === "Escape") { event.preventDefault(); finished = true; renderChatList(); }
      });
      input.addEventListener("blur", commit, { once: true });
    }

    chatMenuRename.addEventListener("click", () => {
      const session = openChatMenuSession;
      const button = openChatMenuRowButton;
      closeChatMenu();
      if (session && button?.isConnected) startChatRename(session, button);
    });
    chatMenuDelete.addEventListener("click", () => {
      const session = openChatMenuSession;
      closeChatMenu();
      if (session) requestChatDeletion(session);
    });
    document.addEventListener("pointerdown", event => {
      if (!chatMenu.hidden && !chatMenu.contains(event.target) && !openChatMenuTrigger?.contains(event.target)) closeChatMenu();
    });
    document.addEventListener("keydown", event => {
      if (event.key === "Escape" && !chatMenu.hidden) {
        closeChatMenu();
        event.preventDefault();
      }
    });
    window.addEventListener("scroll", positionChatMenu, true);
    window.addEventListener("resize", positionChatMenu);

    function renderChatList() {
      closeChatMenu();
      chatList.replaceChildren();
      document.getElementById("side-chat-list-section").hidden = !chatSessions.length;
      for (const session of chatSessions) {
        const row = document.createElement("div");
        row.className = "chat-row" + (session.id === sideSession?.id ? " active" : "");
        const button = document.createElement("button");
        button.type = "button";
        button.className = "recent-chat";
        button.textContent = session.title;
        button.addEventListener("click", () => openSideChat(session).catch(error => addMessage("error", error.message)));
        const menuButton = document.createElement("button");
        menuButton.type = "button";
        menuButton.className = "chat-row-menu-button";
        menuButton.textContent = "⋯";
        menuButton.setAttribute("aria-label", "Actions for " + session.title);
        menuButton.setAttribute("aria-haspopup", "menu");
        menuButton.setAttribute("aria-expanded", "false");
        menuButton.addEventListener("click", () => toggleChatMenu(session, menuButton, button));
        row.append(button, menuButton);
        chatList.append(row);
      }
    }

    async function openConversation(session, navigate = true) {
      if (sending || openingSide || !session) return;
      if (activeSession?.id === session.id) { if (navigate) showView("home"); return; }
      openingSide = true;
      if (navigate) showView("home");
      messageInput.disabled = true;
      sendButton.disabled = true;
      cancelTargetPreviews();
      conversationVersion += 1;
      endRecording(false);
      stopSpeech();
      clearImage();
      clearDocument();
      try {
      const data = await apiJson("/conversations/" + session.id);
      messageInput.value = "";
      activeSession = session;
      conversationType = data.kind;
      sideSession = conversationType === "side" ? session : null;
      if (conversationType === "master") masterSession = session;
      sessionTurns = data.messages.map(item => ({ role: item.role, content: item.content }));
      conversation.replaceChildren();
      for (const item of data.messages) addMessage(item.role, item.content, "", conversation, false);
      updateChatHeader();
      localStorage.setItem("jarvis_active_chat", String(session.id));
      updateConversationLayout();
      renderChatList();
      } finally {
        openingSide = false;
        messageInput.disabled = false;
        sendButton.disabled = safetyStopped || sending;
      }
    }

    async function loadConversations() {
      sendButton.disabled = true;
      try {
        const list = await apiJson("/conversations?kind=master");
        await openConversation(list.conversations[0], false);
        const sides = await apiJson("/conversations?kind=side");
        chatSessions.splice(0, chatSessions.length, ...sides.conversations);
        sideSession = null;
        renderChatList();
      } catch (error) {
        addMessage("error", "Could not load saved conversations: " + error.message);
      } finally {
        sendButton.disabled = safetyStopped || sending;
      }
    }

    function requestChatDeletion(session) {
      if (sending) return;
      chatPendingDeletion = session;
      const dialog = document.getElementById("delete-chat-dialog");
      document.getElementById("delete-chat-error").textContent = "";
      document.getElementById("delete-chat-name").textContent = session.title;
      dialog.hidden = false;
      document.getElementById("cancel-delete-chat").focus();
    }
    function closeDeleteDialog() {
      document.getElementById("delete-chat-dialog").hidden = true;
      chatPendingDeletion = null;
    }
    document.getElementById("cancel-delete-chat").addEventListener("click", closeDeleteDialog);
    document.addEventListener("keydown", event => {
      if (event.key === "Escape" && !document.getElementById("delete-chat-dialog").hidden) closeDeleteDialog();
    });
    document.getElementById("delete-chat-dialog").addEventListener("click", event => {
      if (event.target.id === "delete-chat-dialog") closeDeleteDialog();
    });
    document.getElementById("confirm-delete-chat").addEventListener("click", async () => {
      const session = chatPendingDeletion;
      if (!session) return;
      const button = document.getElementById("confirm-delete-chat");
      button.disabled = true;
      try {
        await apiJson("/conversations/" + session.id, jsonRequest("DELETE", { confirm: true }));
        const index = chatSessions.findIndex(item => item.id === session.id);
        if (index >= 0) chatSessions.splice(index, 1);
        if (session === activeSession) await openConversation(masterSession);
        renderChatList();
        closeDeleteDialog();
      } catch (error) {
        document.getElementById("delete-chat-error").textContent = error.message;
      } finally { button.disabled = false; }
    });

    function updateChatHeader() {
      const isSide = conversationType === "side";
      document.body.dataset.conversationType = conversationType;
      document.getElementById("header-chat-title").textContent = isSide ? "Side Chat" + (activeSession ? " · " + activeSession.title : "") : "Master Chat";
      document.getElementById("side-actions-trigger").hidden = !isSide;
      document.getElementById("promote-side-chat").disabled = !activeSession;
      document.getElementById("commit-side-chat").disabled = !activeSession;
      homeTab.classList.toggle("active", !isSide && document.body.dataset.view === "home");
      homeTab.setAttribute("aria-current", !isSide && document.body.dataset.view === "home" ? "page" : "false");
      closeSideActions();
      if (document.body.dataset.assistantState === "approval") setAssistantState(speakInput.checked ? "idle" : "muted");
    }
    function openSideChat(session) { return openConversation(session); }
    const sideActions = document.getElementById("side-actions-menu");
    document.body.append(sideActions);
    const sideActionsTrigger = document.getElementById("side-actions-trigger");
    function closeSideActions() { sideActions.hidden = true; sideActionsTrigger.setAttribute("aria-expanded", "false"); }
    sideActionsTrigger.addEventListener("click", () => {
      const open = sideActions.hidden;
      closeChatMenu();
      closeSideActions();
      if (!open) return;
      sideActions.hidden = false;
      sideActionsTrigger.setAttribute("aria-expanded", "true");
      const box = sideActionsTrigger.getBoundingClientRect();
      sideActions.style.top = Math.max(8, Math.min(box.bottom + 5, window.innerHeight - sideActions.offsetHeight - 8)) + "px";
      sideActions.style.left = Math.max(8, Math.min(box.right - sideActions.offsetWidth, window.innerWidth - sideActions.offsetWidth - 8)) + "px";
    });
    document.addEventListener("pointerdown", event => { if (!sideActions.contains(event.target) && !sideActionsTrigger.contains(event.target)) closeSideActions(); });
    document.addEventListener("keydown", event => { if (event.key === "Escape") closeSideActions(); });
    window.addEventListener("resize", closeSideActions);
    window.addEventListener("scroll", closeSideActions, true);
    document.getElementById("discard-side-chat").addEventListener("click", () => {
      closeSideActions();
      if (activeSession) requestChatDeletion(activeSession);
      else openConversation(masterSession).catch(error => addMessage("error", error.message));
    });
    document.getElementById("promote-side-chat").addEventListener("click", async () => {
      if (!sideSession || sending || safetyStopped) return;
      const selected = sideSession, version = conversationVersion, epoch = safetyEpoch;
      const current = () => !safetyStopped && epoch === safetyEpoch && version === conversationVersion && sideSession?.id === selected.id;
      closeSideActions();
      try {
      const promoted = await apiJson("/conversations/" + selected.id + "/promote", { method: "POST" });
      if (safetyStopped || epoch !== safetyEpoch) return;
      const index = chatSessions.findIndex(item => item.id === selected.id);
      if (index >= 0) chatSessions.splice(index, 1);
      if (!current()) { renderChatList(); return; }
      sideSession = null;
      await openConversation(promoted);
      } catch (error) { if (current()) addMessage("error", error.message); }
    });
    document.getElementById("commit-side-chat").addEventListener("click", async () => {
      if (!sideSession || sending || safetyStopped) return;
      const selected = sideSession, version = conversationVersion, epoch = safetyEpoch;
      const current = () => !safetyStopped && epoch === safetyEpoch && version === conversationVersion && sideSession?.id === selected.id;
      closeSideActions();
      try {
        const result = await apiJson("/conversations/" + selected.id + "/commit-memory", { method: "POST" });
        if (!current()) return;
        addMessage("assistant", result.saved_entries || result.saved_facts ? result.saved_entries + " exchanges and " + result.saved_facts + " stated facts committed to memory." : "This chat's completed exchanges are already in memory.");
        loadFacts();
      } catch (error) { if (current()) addMessage("error", error.message); }
    });

    function openSideDraft() {
      if (sending || openingSide) return;
      cancelTargetPreviews();
      conversationVersion += 1;
      endRecording(false);
      stopSpeech();
      clearImage();
      clearDocument();
      activeSession = null;
      sideSession = null;
      conversationType = "side";
      messageInput.value = "";
      sessionTurns = [];
      conversation.replaceChildren();
      updateConversationLayout();
      renderChatList();
      showView("home");
      updateChatHeader();
    }
    document.getElementById("new-chat").addEventListener("click", openSideDraft);
    document.getElementById("tools-shortcut").addEventListener("click", () => showView("control"));

    function showView(view) {
      document.body.dataset.view = view;
      homeTab.classList.toggle("active", view === "home" && conversationType === "master");
      controlTab.classList.toggle("active", view === "control");
      homeTab.setAttribute("aria-current", view === "home" && conversationType === "master" ? "page" : "false");
      controlTab.setAttribute("aria-current", view === "control" ? "page" : "false");
      if (view === "home") {
        refreshVisuals();
        messageInput.focus();
      }
      closeSidebar();
      closeSideActions();
    }
    homeTab.addEventListener("click", () => openConversation(masterSession).catch(error => addMessage("error", error.message)));
    controlTab.addEventListener("click", () => showView("control"));
    loadConversations();

    async function auditBrowserAction(action) {
      const response = await safeFetch("/audit/event", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ event: action, approved: true })
      });
      if (!response.ok) throw new Error("Audit logging unavailable");
    }

    function setMicState(text, recording = false) {
      micStatus.textContent = text;
      micButton.classList.toggle("recording", recording);
      micButton.setAttribute("aria-pressed", String(recording));
    }

    function clearImage() {
      imageCaptureVersion += 1;
      imageCaptureStream?.getTracks().forEach(track => track.stop());
      imageCaptureStream = null;
      pendingImage = null;
      imagePreview.removeAttribute("src");
      imagePreview.style.display = "none";
      captureStatus.textContent = "OFF";
    }

    async function captureOnce(kind) {
      if (safetyStopped) return;
      let stream;
      clearImage();
      const version = imageCaptureVersion;
      const current = () => version === imageCaptureVersion;
      captureStatus.textContent = "REQUESTING";
      const captureAvailable = kind === "screen" ? typeof navigator.mediaDevices?.getDisplayMedia === "function" : typeof navigator.mediaDevices?.getUserMedia === "function";
      if (!captureAvailable) {
        captureStatus.textContent = "OFF · " + (kind === "screen" ? "Screen" : "Camera") + " capture is unavailable in this browser.";
        return;
      }
      try {
        if (!await deviceReady() || !current()) return;
        stream = kind === "screen"
          ? await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false })
          : await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" }, audio: false });
        if (!current()) return;
        imageCaptureStream = stream;
        const video = document.createElement("video");
        video.muted = true;
        video.playsInline = true;
        video.srcObject = stream;
        await video.play();
        if (!current()) return;
        if (!video.videoWidth || !video.videoHeight) throw new Error("No video frame available");
        const canvas = document.createElement("canvas");
        const scale = Math.min(1, 1280 / video.videoWidth, 1280 / video.videoHeight);
        canvas.width = Math.max(1, Math.round(video.videoWidth * scale));
        canvas.height = Math.max(1, Math.round(video.videoHeight * scale));
        canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
        const dataUrl = canvas.toDataURL("image/jpeg", 0.82);
        stream.getTracks().forEach(track => track.stop());
        imageCaptureStream = null;
        stream = null;
        video.srcObject = null;
        await auditBrowserAction(kind === "screen" ? "screen_capture" : "camera_capture");
        if (!current()) return;
        pendingImage = dataUrl.split(",", 2)[1];
        imagePreview.src = dataUrl;
        imagePreview.style.display = "block";
        captureStatus.textContent = "FRAME READY";
      } catch (error) {
        if (current()) captureStatus.textContent = error?.name === "NotFoundError" ? "OFF · No camera was found." :
          error?.name === "NotReadableError" ? "OFF · The camera or capture device is busy or unavailable." :
          error?.name === "NotAllowedError" || error?.name === "AbortError" ? "OFF · Capture cancelled or permission denied." :
          "OFF · Capture failed. No frame was attached.";
      } finally {
        stream?.getTracks().forEach(track => track.stop());
        if (imageCaptureStream === stream) imageCaptureStream = null;
      }
    }

    document.getElementById("camera").addEventListener("click", () => captureOnce("camera"));
    document.getElementById("screen").addEventListener("click", () => captureOnce("screen"));
    document.getElementById("clear-image").addEventListener("click", clearImage);

    function findLocalVoice() {
      if (!window.speechSynthesis) {
        speakInput.title = "Jarvis will use the local offline voice.";
        return;
      }
      const voices = speechSynthesis.getVoices().filter(voice => voice.localService === true);
      localVoice = voices.find(voice => voice.lang.toLowerCase().startsWith("en")) || voices[0] || null;
      speakInput.title = localVoice ? "Uses an installed local voice." : "Jarvis will use the local offline voice.";
    }

    if (window.speechSynthesis) {
      speechSynthesis.addEventListener("voiceschanged", findLocalVoice);
    }
    speakInput.addEventListener("change", () => {
      if (!speakInput.checked) stopSpeech();
      if (!speakInput.checked) setAssistantState("muted");
      else if (!sending) setAssistantState("idle");
    });

    async function beginRecording(durationMs = 20000) {
      if (safetyStopped) return;
      if (micRequested || recorder || !navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) return;
      if (wakeStream) stopWake();
      micRequested = true;
      const version = ++recordingVersion;
      const chatVersion = conversationVersion;
      const current = () => version === recordingVersion && chatVersion === conversationVersion;
      setMicState("REQUESTING");
      let stream;
      let release = () => {};
      try {
        const audio = microphoneSelect.value
          ? { deviceId: { exact: microphoneSelect.value } }
          : true;
        if (!await deviceReady() || !current() || !micRequested) return;
        stream = await navigator.mediaDevices.getUserMedia({ audio });
        let released = false;
        release = () => {
          if (released) return;
          released = true;
          stream.getTracks().forEach(track => track.stop());
          if (releaseRecordingStream === release) releaseRecordingStream = () => {};
        };
        if (!micRequested || !current()) {
          release();
          if (current()) setMicState("OFF");
          return;
        }
        releaseRecordingStream = release;
        setMicState("MIC LIVE");
        setAssistantState("listening");
        await auditBrowserAction("microphone_recording");
        refreshMicrophones().catch(() => {});
        if (!micRequested || !current()) {
          release();
          if (current()) setMicState("OFF");
          return;
        }
        const chunks = [];
        recorder = new MediaRecorder(stream);
        const activeRecorder = recorder;
        recorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
        recorder.onstop = async () => {
          release();
          if (!current()) { if (recorder === activeRecorder) recorder = null; return; }
          const shouldSend = sendRecordedAudio;
          sendRecordedAudio = false;
          const type = activeRecorder.mimeType || "audio/webm";
          recorder = null;
          if (!shouldSend || !chunks.length) {
            setMicState("OFF");
            return;
          }
          setMicState("OFF · TRANSCRIBING");
          setAssistantState("thinking");
          try {
            const response = await safeFetch("/transcribe", {
              method: "POST",
              headers: { "Content-Type": type },
              body: new Blob(chunks, { type })
            });
            if (!response.ok) throw new Error("Transcription failed (HTTP " + response.status + ").");
            const result = await response.json();
            if (!current()) return;
            if (result.text) {
              messageInput.value = [messageInput.value.trim(), result.text].filter(Boolean).join(" ");
              messageInput.focus();
              setMicState("OFF · TEXT READY");
              setAssistantState("idle");
            } else {
              setMicState("OFF · NO SPEECH");
              setAssistantState("idle");
            }
          } catch (error) {
            if (!current()) return;
            setMicState("OFF · TRANSCRIPTION ERROR");
            setAssistantState("error");
          }
        };
        recorder.onerror = () => {
          release();
          if (!current()) return;
          recordingVersion += 1;
          micRequested = false;
          recorder = null;
          clearTimeout(micTimer);
          setMicState("OFF · RECORDING ERROR");
          setAssistantState("error");
        };
        recorder.start();
        setMicState("RECORDING", true);
        micTimer = setTimeout(() => endRecording(true), durationMs);
      } catch (error) {
        if (!current()) { release(); return; }
        micRequested = false;
        release();
        recorder = null;
        setMicState(error?.name === "NotFoundError" ? "OFF · NO MICROPHONE" :
          error?.name === "NotAllowedError" ? "OFF · ACCESS DENIED" : "OFF · UNAVAILABLE");
        setAssistantState("error");
      }
    }

    function endRecording(sendAudio) {
      micRequested = false;
      if (!sendAudio) releaseRecordingStream();
      if (!sendAudio) recordingVersion += 1;
      clearTimeout(micTimer);
      if (recorder && recorder.state !== "inactive") {
        sendRecordedAudio = sendAudio;
        recorder.stop();
      }
      if (!sendAudio) setMicState("OFF");
    }

    async function refreshMicrophones() {
      if (!navigator.mediaDevices?.enumerateDevices) return;
      const selected = microphoneSelect.value || localStorage.getItem("jarvis_microphone") || "";
      const devices = await navigator.mediaDevices.enumerateDevices();
      microphoneSelect.replaceChildren();
      const defaultOption = document.createElement("option");
      defaultOption.value = "";
      defaultOption.textContent = "Default microphone";
      microphoneSelect.append(defaultOption);
      for (const device of devices.filter(item => item.kind === "audioinput" && item.deviceId)) {
        const option = document.createElement("option");
        option.value = device.deviceId;
        option.textContent = device.label || "Microphone " + microphoneSelect.options.length;
        microphoneSelect.append(option);
      }
      if ([...microphoneSelect.options].some(option => option.value === selected)) microphoneSelect.value = selected;
    }

    function stopWake() {
      wakeSession += 1;
      wakeCheckBusy = false;
      clearTimeout(wakeTimer);
      clearInterval(wakeMeterTimer);
      wakeRecorder?.state === "recording" && wakeRecorder.stop();
      wakeRecorder = null;
      wakeStream?.getTracks().forEach(track => track.stop());
      wakeStream = null;
      wakeAudioContext?.close().catch(() => {});
      wakeAudioContext = null;
      wakeEnabled.checked = false;
      wakeStatus.textContent = "OFF · microphone released";
      if (!recorder) setMicState("OFF");
      if (!sending) setAssistantState(speakInput.checked ? "idle" : "muted");
    }

    async function startWake() {
      if (safetyStopped) return;
      if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
        wakeStatus.textContent = "Wake listening unavailable in this browser.";
        wakeEnabled.checked = false;
        setAssistantState("error");
        return;
      }
      const session = ++wakeSession;
      wakeNoiseFloor = 2;
      wakeVoiceHits = 0;
      wakeStatus.textContent = "REQUESTING MICROPHONE";
      try {
        const audio = microphoneSelect.value
          ? { deviceId: { exact: microphoneSelect.value } }
          : true;
        if (!await deviceReady() || session !== wakeSession || !wakeEnabled.checked) return;
        const stream = await navigator.mediaDevices.getUserMedia({ audio });
        if (session !== wakeSession || !wakeEnabled.checked) {
          stream.getTracks().forEach(track => track.stop());
          return;
        }
        wakeStream = stream;
        await auditBrowserAction("wake_listening");
        if (session !== wakeSession || !wakeEnabled.checked) { stream.getTracks().forEach(track => track.stop()); return; }
        await refreshMicrophones();
        if (session !== wakeSession || !wakeEnabled.checked) { stream.getTracks().forEach(track => track.stop()); return; }
        wakeAudioContext = new AudioContext();
        const analyser = wakeAudioContext.createAnalyser();
        analyser.fftSize = 1024;
        wakeAudioContext.createMediaStreamSource(stream).connect(analyser);
        const levels = new Uint8Array(analyser.fftSize);
        wakeMeterTimer = setInterval(() => {
          analyser.getByteTimeDomainData(levels);
          let energy = 0;
          for (const level of levels) {
            const sample = level - 128;
            energy += sample * sample;
          }
          const rms = Math.sqrt(energy / levels.length);
          if (rms > Math.max(4, wakeNoiseFloor * 2.1)) {
            wakeVoiceHits += 1;
            if (wakeVoiceHits >= 2) wakeVoiceSeen = true;
          } else {
            wakeVoiceHits = 0;
            wakeNoiseFloor = wakeNoiseFloor * .94 + rms * .06;
          }
        }, 250);
        wakeStatus.textContent = "LISTENING · LOCAL · SAY HEY JARVIS";
        setMicState("WAKE LISTENING", true);
        setAssistantState("listening");
        const recordWindow = () => {
          if (session !== wakeSession || !wakeStream) return;
          const recorderForWindow = new MediaRecorder(wakeStream);
          wakeRecorder = recorderForWindow;
          wakeVoiceSeen = false;
          wakeVoiceHits = 0;
          const pieces = [];
          recorderForWindow.ondataavailable = event => { if (event.data.size) pieces.push(event.data); };
          recorderForWindow.onstop = async () => {
            if (session !== wakeSession) return;
            const heardVoice = wakeVoiceSeen;
            recordWindow();
            if (!heardVoice || !pieces.length || wakeCheckBusy) return;
            wakeCheckBusy = true;
            try {
              const type = recorderForWindow.mimeType || "audio/webm";
              const response = await safeFetch("/wake/check", {
                method: "POST",
                headers: { "Content-Type": type },
                body: new Blob(pieces, { type })
              });
              if (!response.ok) throw new Error("Wake check failed");
              const result = await response.json();
              if (session !== wakeSession || !result.detected) return;
              stopWake();
              showView("home");
              if (result.command) {
                messageInput.value = [messageInput.value.trim(), result.command].filter(Boolean).join(" ");
                messageInput.focus();
                setMicState("OFF · COMMAND READY");
              } else {
                setMicState("OFF · WAKE DETECTED");
                beginRecording(8000);
              }
            } catch {
              if (session === wakeSession) wakeStatus.textContent = "LISTENING · CHECK RETRYING";
            } finally { if (session === wakeSession) wakeCheckBusy = false; }
          };
          recorderForWindow.start();
          wakeTimer = setTimeout(() => {
            if (recorderForWindow.state === "recording") recorderForWindow.stop();
          }, 4000);
        };
        recordWindow();
      } catch (error) {
        if (session !== wakeSession) return;
        stopWake();
        wakeStatus.textContent = error?.name === "NotFoundError"
          ? "OFF · No usable microphone input. Connect or enable one in Windows"
          : error?.name === "NotAllowedError"
            ? "OFF · Microphone access was denied"
            : "OFF · Microphone unavailable";
        setAssistantState("error");
      }
    }

    wakeEnabled.addEventListener("change", () => wakeEnabled.checked ? startWake() : stopWake());
    microphoneSelect.addEventListener("change", () => {
      localStorage.setItem("jarvis_microphone", microphoneSelect.value);
      if (wakeEnabled.checked) {
        stopWake();
        wakeEnabled.checked = true;
        startWake();
      }
    });
    refreshMicrophones().catch(() => {});
    window.addEventListener("beforeunload", stopWake);

    micButton.addEventListener("pointerdown", event => {
      event.preventDefault();
      micButton.setPointerCapture(event.pointerId);
      beginRecording();
    });
    micButton.addEventListener("pointerup", () => endRecording(true));
    micButton.addEventListener("pointercancel", () => endRecording(false));
    micButton.addEventListener("keydown", event => {
      if ((event.key === " " || event.key === "Enter") && !event.repeat) {
        event.preventDefault();
        beginRecording();
      }
    });
    micButton.addEventListener("keyup", event => {
      if (event.key === " " || event.key === "Enter") {
        event.preventDefault();
        endRecording(true);
      }
    });
    window.addEventListener("blur", () => endRecording(false));
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) endRecording(false);
    });

    function renderMessageText(bubble, content) {
      bubble.replaceChildren();
      const pieces = content.split(/(\*\*[^*\n]+\*\*|`[^`\n]+`)/g);
      for (const piece of pieces) {
        if (piece.startsWith("**") && piece.endsWith("**")) {
          const strong = document.createElement("strong");
          strong.textContent = piece.slice(2, -2);
          bubble.append(strong);
        } else if (piece.startsWith("`") && piece.endsWith("`")) {
          const code = document.createElement("code");
          code.textContent = piece.slice(1, -1);
          bubble.append(code);
        } else bubble.append(document.createTextNode(piece));
      }
    }

    function addMessage(role, content, metadata = "", destination = conversation, update = true) {
      if (destination === conversation) document.getElementById("intro")?.remove();
      const item = document.createElement("div");
      item.className = "message " + role;
      const label = document.createElement("div");
      label.className = "label";
      label.textContent = role === "user" ? "You" : role === "error" ? "Error" : "Jarvis";
      const bubble = document.createElement("div");
      bubble.className = "bubble";
      renderMessageText(bubble, content);
      item.append(label, bubble);
      if (metadata) {
        const meta = document.createElement("div");
        meta.className = "meta";
        meta.textContent = metadata;
        item.append(meta);
      }
      destination.append(item);
      destination.scrollTop = destination.scrollHeight;
      if (destination === conversation && update) updateConversationLayout();
      return item;
    }

    function addPendingReply() {
      const item = addMessage("assistant", "");
      const bubble = item.querySelector(".bubble");
      bubble.setAttribute("aria-label", "Jarvis is thinking");
      const dots = document.createElement("span");
      dots.className = "reply-dots";
      dots.setAttribute("aria-hidden", "true");
      for (let index = 0; index < 3; index += 1) {
        const dot = document.createElement("span");
        dot.style.setProperty("--dot", index);
        dots.append(dot);
      }
      bubble.append(dots);
      return item;
    }

    function replyTokenWriter(bubble) {
      let started = false;
      let tail = null;
      return token => {
        if (!started) {
          bubble.replaceChildren();
          bubble.removeAttribute("aria-label");
          started = true;
        }
        // Keep at most one animating text fragment. Settled tokens become a
        // single text node, so long answers do not accumulate animated spans.
        if (tail) {
          const text = document.createTextNode(tail.textContent);
          tail.replaceWith(text);
          const previous = text.previousSibling;
          if (previous?.nodeType === Node.TEXT_NODE) { previous.appendData(text.data); text.remove(); }
        }
        tail = document.createElement("span");
        tail.className = "reply-fragment";
        tail.textContent = token;
        bubble.append(tail);
      };
    }

    async function checkHealth() {
      try {
        const response = await safeFetch("/health", { cache: "no-store" });
        if (!response.ok) throw new Error("Health check failed");
        const health = await response.json();
        statusText.textContent = health.model_ready
          ? health.model + " · " + (health.inference || "local")
          : "Local model unavailable";
        statusDot.className = health.model_ready ? "dot online" : "dot offline";
      } catch {
        statusText.textContent = "Local service unavailable";
        statusDot.className = "dot offline";
      }
    }

    messageInput.addEventListener("keydown", event => {
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        if (messageInput.value.trim()) form.requestSubmit();
      }
    });

    async function postApproved(url, body) {
      const response = await safeFetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...body, approved: true })
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || "Action failed (HTTP " + response.status + ").");
      return result;
    }

    async function loadPermissions() {
      const list = document.getElementById("permissions-list");
      try {
        const response = await safeFetch("/permissions", { cache: "no-store" });
        if (!response.ok) throw new Error("Permissions unavailable");
        const data = await response.json();
        list.replaceChildren();
        if (!data.permissions.length) {
          list.textContent = "No saved permissions";
          return;
        }
        for (const permission of data.permissions) {
          const row = document.createElement("div");
          row.className = "permission-row";
          const label = document.createElement("span");
          label.textContent = permission.target + " · " + permission.action_type.replaceAll("_", " ");
          const revoke = document.createElement("button");
          revoke.type = "button";
          revoke.textContent = "Revoke";
          revoke.addEventListener("click", async () => {
            const result = await safeFetch("/permissions/" + permission.id, { method: "DELETE" });
            if (result.ok) loadPermissions();
            else revoke.textContent = "Could not revoke";
          });
          row.append(label, revoke);
          list.append(row);
        }
      } catch { list.textContent = "Permissions unavailable"; }
    }

    async function requestTool(actionType, target, status, destination = conversation, initialResult = null) {
      if (safetyStopped) return null;
      let approvalEpoch = safetyEpoch;
      const chatVersion = conversationVersion;
      const workspaceScope = String(activeSession?.id || "draft") + ":" + chatVersion;
      const current = () => !safetyStopped && chatVersion === conversationVersion;
      const scopedScroll = actionType === "scroll_control";
      let toolVersion = setAssistantState("tool");
      const targetName = target === "Default playlist" ? "your playlist" : target === "Jarvis project" ? "your Jarvis project" : target;
      const actionName = scopedScroll ? "Scroll the selected " + targetName + " pane " + (initialResult?.action === "scroll_up" ? "up" : "down") + " (" + (initialResult?.control_label || "Unnamed scroll pane") + ")" : actionType === "focus_app" ? "Bring " + targetName + " forward" : actionType === "inspect_app" ? "Inspect " + targetName : actionType === "spotify_playback"
        ? (target === "Spotify Pause" ? "Pause Spotify" : target === "Spotify Play" ? "Play Spotify" : "Play " + targetName) : "Open " + targetName;
      status.textContent = "Getting that ready.";
      document.getElementById("dev-tool").textContent = actionType.replaceAll("_", " ") + " · " + target;
      const send = async decision => {
        if (scopedScroll && (!initialResult?.reference || !["allow_once","deny"].includes(decision))) throw new Error("Inspect and attach the window again before scrolling.");
        const scrollBody = scopedScroll ? {reference:initialResult.reference, workspace_scope:initialResult.workspace_scope,
          control_id:initialResult.control_id, action:initialResult.action, decision, safety_epoch:approvalEpoch} : null;
        if (scopedScroll && decision === "allow_once") activePreviews.set(initialResult.reference,initialResult.workspace_scope);
        let response;
        try { response = await safeFetch(scopedScroll ? decision === "deny" ? "/tools/preview-cancel" : "/tools/scroll-control" : "/tools/dispatch", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(scopedScroll ? scrollBody : { action_type: actionType, target, decision, safety_epoch: approvalEpoch, workspace_scope: workspaceScope })
        }); } finally { if (scopedScroll) activePreviews.delete(initialResult.reference); }
        let result;
        try { result = await response.json(); }
        catch { throw new Error("The local service did not return a usable response."); }
        if (!response.ok) throw new Error(result.detail || "Action failed");
        if (scopedScroll) result = {...result, action_type:actionType,target,
          status:decision === "deny" ? "denied" : "executed",
          ...(decision === "deny" ? {message:"Okay, I won’t scroll that pane."} : {})};
        if (!current()) return result;
        document.getElementById("dev-authorization").textContent = result.source || result.status;
        document.getElementById("dev-security").textContent = result.security_result || "unknown";
        document.getElementById("dev-execution").textContent = result.status;
        document.getElementById("dev-tool-latency").textContent = result.latency_ms == null ? "—" : result.latency_ms + " ms";
        return result;
      };
      try {
        const result = initialResult || await send(null);
        if (result.safety_epoch != null) approvalEpoch = result.safety_epoch;
        if (!current()) return result;
        if (result.status === "executed") {
          status.textContent = result.message || "I’ve started that for you.";
          settleTool(toolVersion);
          return result;
        }
        if (result.status !== "approval_required") return result;
        status.textContent = "Approval needed for " + actionName + ".";
        if (document.body.dataset.view !== "home") showView("home");
        const card = addMessage("assistant", actionName + "?", "Permission needed", destination);
        const actions = document.createElement("div");
        actions.className = "workflow-actions";
        const choices = result.persistent_eligible !== true
          ? [["Allow Once", "allow_once"], ["Deny", "deny"]]
          : [["Allow Once", "allow_once"], ["Always Allow", "always_allow"], ["Deny", "deny"]];
        for (const [label, choice] of choices) {
          const button = document.createElement("button");
          button.type = "button";
          button.textContent = label;
          button.addEventListener("click", async () => {
            if (!current()) return;
            for (const item of actions.querySelectorAll("button")) item.disabled = true;
            toolVersion = setAssistantState("tool");
            try {
              const approved = await send(choice);
              if (!current()) return;
              status.textContent = approved.message || (approved.status === "executed" ? "I’ve started that for you." : "Okay, I won’t do that.");
              card.querySelector(".meta").textContent = approved.message || (approved.status === "executed" ? "Started" : "Not allowed");
              actions.replaceChildren();
              if (approved.observation) {
                const details = document.createElement("details");
                const summary = document.createElement("summary");
                summary.textContent = "Observed controls (read only)";
                const text = document.createElement("pre");
                text.style.whiteSpace = "pre-wrap";
                text.textContent = approved.observation.controls.map(control => control.name).join("\n");
                details.append(summary, text);
                if (approved.window_context_reference) {
                  const use = document.createElement("button");
                  use.type = "button";
                  use.textContent = "Use snapshot in next message";
                  use.addEventListener("click", () => {
                    if (!current()) return;
                    clearDocument();
                    pendingWindowReference = {reference:approved.window_context_reference,scope:workspaceScope};
                    document.getElementById("document-attachment").hidden = false;
                    document.getElementById("document-attachment-name").textContent = "Next message: " + target + " window snapshot (one message)";
                    use.disabled = true;
                    showView("home"); messageInput.focus();
                  });
                  details.append(use);
                }
                if (approved.observation_reference) {
                  const targets = document.createElement("div");
                  targets.className = "target-preview";
                  const hint = document.createElement("p");
                  hint.textContent = "Preview highlights a control without input. Scrolling changes only one supported pane after a separate confirmation.";
                  targets.append(hint);
                  let used = false;
                  const controls = approved.observation.controls.filter(item => item.id && item.context_id && item.enabled && !item.offscreen && item.bounds[2] > item.bounds[0] && item.bounds[3] > item.bounds[1]);
                  const select = document.createElement("select");
                  select.setAttribute("aria-label", "Preview control");
                  controls.forEach((control, index) => {
                    const option = document.createElement("option");
                    option.value = String(index);
                    option.textContent = control.name ? control.name + (control.scrollable ? " (scroll pane)" : "") : "Unnamed scroll pane " + (index + 1);
                    select.append(option);
                  });
                  targets.append(select);
                  const actionSelect = document.createElement("select");
                  actionSelect.setAttribute("aria-label", "Control action");
                  for (const [value, title] of [["preview","Preview only"],["scroll_up","Scroll pane up"],["scroll_down","Scroll pane down"]]) {
                    const option = document.createElement("option");
                    option.value=value; option.textContent=title; actionSelect.append(option);
                  }
                  const updateActions = () => {
                    const canScroll = approved.control_reference && controls[Number(select.value)]?.scrollable;
                    for (const option of actionSelect.options) option.disabled = option.value !== "preview" && !canScroll;
                    if (!canScroll) actionSelect.value="preview";
                  };
                  select.addEventListener("change", updateActions);
                  updateActions(); targets.append(actionSelect);
                    const button = document.createElement("button");
                    button.type = "button";
                    button.textContent = "Show target";
                    button.disabled = !controls.length;
                    button.addEventListener("click", () => {
                      if (!current() || used) return;
                      const control = controls[Number(select.value)];
                      if (!control) return;
                      const action=actionSelect.value;
                      const scrolling=action!=="preview";
                      if (scrolling && (!control.scrollable || !approved.control_reference)) return;
                      const reference=scrolling ? approved.control_reference : approved.observation_reference;
                      const confirmation = document.createElement("div");
                      confirmation.className = "approval-actions workflow-actions";
                      const label = document.createElement("p");
                      const controlLabel = control.name || "Unnamed scroll pane " + (Number(select.value) + 1);
                      label.textContent = "Bring " + target + " forward and " + (scrolling ? "scroll “" + controlLabel + "” " + (action==="scroll_down" ? "down" : "up") + " once?" : "highlight “" + controlLabel + "”?");
                      const allow = document.createElement("button"), deny = document.createElement("button");
                      allow.type = deny.type = "button";
                      allow.textContent = scrolling ? "Scroll once" : "Preview once"; deny.textContent = scrolling ? "Cancel action" : "Cancel preview";
                      deny.addEventListener("click", async () => {
                        if (!used) { confirmation.remove(); settleTool(preparationVersion); return; }
                        deny.disabled = true;
                        try {
                          await apiJson("/tools/preview-cancel", jsonRequest("POST", {
                            reference, workspace_scope: workspaceScope
                          }));
                          if (current()) label.textContent = scrolling ? "Scroll action cancelled. Inspect the pane before retrying." : "Target preview cancelled.";
                        } catch (error) { if (current()) label.textContent = error.message; }
                      });
                      allow.addEventListener("click", async () => {
                        if (!current() || used) return;
                        used = true;
                        select.disabled = true;
                        actionSelect.disabled = true;
                        for (const item of targets.querySelectorAll("button")) item.disabled = true;
                        deny.disabled = false;
                        deny.textContent = scrolling ? "Cancel action" : "Cancel preview";
                        activePreviews.set(reference, workspaceScope);
                        const previewVersion = setAssistantState("tool");
                        try {
                          const result = await apiJson(scrolling ? "/tools/scroll-control" : "/tools/preview-control", jsonRequest("POST", {
                            reference, control_id: control.id,
                            ...(scrolling ? {action} : {}),
                            workspace_scope: workspaceScope, decision: "allow_once", safety_epoch: approvalEpoch
                          }));
                          if (current()) label.textContent = result.message;
                        } catch (error) {
                          if (current()) label.textContent = error.message;
                        } finally {
                          activePreviews.delete(reference);
                          allow.remove(); deny.remove();
                          if (current()) settleTool(previewVersion);
                        }
                      });
                      confirmation.append(label, allow, deny);
                      targets.querySelector(".approval-actions")?.remove();
                      targets.append(confirmation);
                      const preparationVersion = setAssistantState("approval");
                      destination.scrollTop = destination.scrollHeight;
                    });
                    targets.append(button);
                  details.append(targets);
                }
                card.append(details);
                destination.scrollTop = destination.scrollHeight;
              }
              if (choice === "always_allow") loadPermissions();
              settleTool(toolVersion);
            } catch (error) {
              if (!current()) return;
              status.textContent = error.message;
              card.querySelector(".meta").textContent = error.message;
              setAssistantState("error");
              for (const item of actions.querySelectorAll("button")) item.disabled = false;
            }
          });
          actions.append(button);
        }
        card.append(actions);
        destination.scrollTop = destination.scrollHeight;
        setAssistantState("approval");
        return result;
      } catch (error) {
        if (!current()) return null;
        status.textContent = error.message;
        setAssistantState("error");
        return null;
      }
    }

    async function streamReply(payload, onToken, onTools = () => {}) {
      const controller = new AbortController();
      chatAbort = controller;
      const response = await safeFetch("/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload), signal: controller.signal
      });
      if (!response.ok || !response.body) throw new Error("Chat request failed (HTTP " + response.status + ").");
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let done = null;
      try {
      while (true) {
        const chunk = await reader.read();
        if (chunk.done) break;
        buffer += decoder.decode(chunk.value, { stream: true });
        const events = buffer.split("\n\n");
        buffer = events.pop();
        for (const event of events) {
          if (!event.startsWith("data: ")) continue;
          const item = JSON.parse(event.slice(6));
          if (item.type === "token") onToken(item.text);
          if (item.type === "tools") await onTools(item.tool_results || []);
          if (item.type === "error") throw new Error(item.detail);
          if (item.type === "done") done = item;
        }
      }
      if (!done) throw new Error("The reply ended before completion.");
      return done;
      } finally {
        // Parsing errors and interrupted replies must release their connection.
        try { await reader.cancel(); } catch { /* Connection may already be closed. */ }
        reader.releaseLock();
        if (chatAbort === controller) chatAbort = null;
      }
    }

    async function showModelTools(result, destination) {
      for (const tool of result.tool_results || []) {
        if (tool.status === "clarification_required") continue;
        if (tool.action_type === "find_documents") continue;
        await requestTool(tool.action_type, tool.target, document.getElementById("workflow-status"), destination, tool);
      }
    }

    async function speakReply(text, preferPiper = false) {
      if (safetyStopped || !speakInput.checked) return;
      stopSpeech();
      const version = speechVersion;
      const active = () => version === speechVersion && speakInput.checked;
      try {
        if (!await deviceReady() || !active()) return;
        if (!preferPiper && localVoice && window.speechSynthesis) {
          const utterance = new SpeechSynthesisUtterance(text);
          utterance.voice = localVoice;
          utterance.onstart = () => { if (active()) setAssistantState("speaking"); };
          utterance.onend = () => { if (active()) setAssistantState("idle"); };
          utterance.onerror = () => {
            if (!active()) return;
            // A listed browser voice can still fail at playback. Retry through
            // the existing offline WAV path, respecting the same stop/version gate.
            return speakReply(text, true);
          };
          speechSynthesis.speak(utterance);
          document.getElementById("dev-tts").textContent = "Browser local voice";
          return;
        }
        document.getElementById("dev-tts").textContent = "Generating locally";
        speechAbort = new AbortController();
        const response = await safeFetch("/voice/speak", {
          method: "POST", headers: { "Content-Type": "application/json" },
          signal: speechAbort.signal,
          body: JSON.stringify({ text: text.slice(0, 3000) })
        });
        if (!response.ok) throw new Error("Local speech unavailable");
        const audio = await response.blob();
        if (!active()) return;
        speechAbort = null;
        const url = URL.createObjectURL(audio);
        currentAudioUrl = url;
        const player = new Audio(url);
        currentAudio = player;
        const finish = state => {
          URL.revokeObjectURL(url);
          if (!active()) return;
          currentAudioUrl = null;
          currentAudio = null;
          setAssistantState(state);
        };
        player.onended = () => finish("idle");
        player.onerror = () => finish("error");
        player.onplaying = () => { if (active()) setAssistantState("speaking"); };
        await player.play();
        if (!active()) return;
        document.getElementById("dev-tts").textContent = "Piper offline voice";
      } catch {
        if (!active()) return;
        stopSpeech();
        document.getElementById("dev-tts").textContent = "Unavailable";
        setAssistantState("error");
      }
    }

    function renderDocuments(folder, entries) {
      const list = document.getElementById("documents-list");
      list.replaceChildren();
      const heading = document.createElement("strong");
      heading.textContent = "Documents" + (folder ? " / " + folder : "") + " · " + entries.length + " shown";
      list.append(heading);
      if (folder) {
        const back = document.createElement("button");
        back.type = "button";
        back.textContent = "← Parent folder";
        back.addEventListener("click", () => listDocuments(folder.split("/").slice(0, -1).join("/")));
        list.append(back);
      }
      for (const entry of entries) {
        const row = document.createElement("button");
        row.className = "document-row";
        row.textContent = (entry.kind === "folder" ? "▸ " : "· ") + entry.name;
        row.type = "button";
        if (entry.kind === "folder") {
          row.addEventListener("click", () => listDocuments([folder, entry.name].filter(Boolean).join("/")));
        } else {
          row.addEventListener("click", () => readDocument([folder, entry.name].filter(Boolean).join("/")));
        }
        list.append(row);
      }
      if (!entries.length) list.append("This folder is empty.");
    }

    async function listDocuments(folder = "") {
      if (safetyStopped) return null;
      const version = ++documentRequestVersion;
      const epoch = safetyEpoch, chatVersion = conversationVersion;
      const current = () => !safetyStopped && epoch === safetyEpoch && chatVersion === conversationVersion && version === documentRequestVersion;
      const status = document.getElementById("workflow-status");
      try {
        const result = await postApproved("/tools/list-documents", { folder });
        if (!current()) return null;
        renderDocuments(folder, result.entries);
        status.textContent = "Document names listed and audit logged. File contents were not read.";
        return result;
      } catch (error) {
        if (!current()) return null;
        status.textContent = error.message;
        return null;
      }
    }

    async function readDocument(path) {
      if (safetyStopped) return;
      const version = ++documentRequestVersion;
      const epoch = safetyEpoch, chatVersion = conversationVersion;
      const current = () => !safetyStopped && epoch === safetyEpoch && chatVersion === conversationVersion && version === documentRequestVersion;
      const status = document.getElementById("workflow-status");
      const output = document.getElementById("document-output");
      const useButton = document.getElementById("use-document");
      useButton.hidden = true;
      lastReadDocumentPath = null;
      output.hidden = true;
      try {
        const result = await postApproved("/tools/read-document", { path });
        if (!current()) return;
        output.textContent = result.content || "(No extractable text)";
        output.hidden = false;
        lastReadDocumentPath = path;
        useButton.hidden = false;
        status.textContent = "Selected document read locally and audit logged.";
      } catch (error) {
        if (!current()) return;
        status.textContent = error.message;
      }
    }

    function clearDocument() {
      pendingDocumentPath = null;
      pendingWindowReference = null;
      pendingDocumentScope = "documents";
      document.getElementById("document-attachment").hidden = true;
      document.getElementById("document-attachment-name").textContent = "";
    }
    document.getElementById("clear-document").addEventListener("click", clearDocument);
    document.getElementById("use-document").addEventListener("click", () => {
      if (safetyStopped || !lastReadDocumentPath) return;
      pendingWindowReference = null;
      pendingDocumentPath = lastReadDocumentPath;
      pendingDocumentScope = "documents";
      document.getElementById("document-attachment").hidden = false;
      document.getElementById("document-attachment-name").textContent = "Next message: " + pendingDocumentPath + " (up to 6000 characters)";
      showView("home");
      messageInput.focus();
    });
    document.getElementById("use-project-file").addEventListener("click", () => {
      if (safetyStopped || !lastReadProjectPath) return;
      pendingWindowReference = null;
      pendingDocumentPath = lastReadProjectPath;
      pendingDocumentScope = "project";
      document.getElementById("document-attachment").hidden = false;
      document.getElementById("document-attachment-name").textContent = "Next message: Jarvis/" + pendingDocumentPath + " (up to 6000 characters)";
      showView("home");
      messageInput.focus();
    });

    async function loadResources() {
      const epoch = safetyEpoch;
      resourceButton.disabled = true;
      resourceSelect.disabled = true;
      const status = document.getElementById("resource-status");
      try {
        const result = await apiJson("/tools/resources");
        if (safetyStopped || epoch !== safetyEpoch) return;
        resourceSelect.replaceChildren();
        for (const item of result.resources) {
          const option = document.createElement("option");
          option.value = item.name;
          option.textContent = item.name + (item.available ? "" : " (unavailable)");
          option.disabled = !item.available;
          resourceSelect.append(option);
        }
        const available = [...resourceSelect.options].find(option => !option.disabled);
        if (available) resourceSelect.value = available.value;
        resourceButton.disabled = !available;
        resourceSelect.disabled = !available;
        status.textContent = available ? "Choose an item. Saved permissions apply only to that item." : "No saved items are available.";
      } catch {
        status.textContent = safetyStopped ? "Resume Jarvis to open saved items." : "Saved items are unavailable.";
      }
    }

    document.getElementById("find-documents-form").addEventListener("submit", async event => {
      event.preventDefault();
      if (safetyStopped) return;
      const version = ++documentRequestVersion;
      const epoch = safetyEpoch, chatVersion = conversationVersion;
      const current = () => !safetyStopped && epoch === safetyEpoch && chatVersion === conversationVersion && version === documentRequestVersion;
      const status = document.getElementById("workflow-status");
      try {
        const query = document.getElementById("document-query").value.trim();
        const result = await postApproved("/tools/find-documents", {query});
        if (!current()) return;
        const list = document.getElementById("documents-list");
        list.replaceChildren();
        for (const match of result.matches) {
          const row = document.createElement("button");
          row.type = "button";
          row.className = "document-row";
          row.textContent = match.path;
          row.addEventListener("click", () => readDocument(match.path));
          list.append(row);
        }
        status.textContent = result.matches.length + " matching filenames" + (result.partial
          ? ". Search was limited or some folders were unavailable; results are incomplete."
          : ". File contents were not read.");
      } catch (error) {
        if (current()) status.textContent = error.message;
      }
    });
    resourceButton.addEventListener("click", () => {
      if (safetyStopped || resourceButton.disabled) return;
      requestTool("open_resource", resourceSelect.value, document.getElementById("resource-status"));
    });

    async function openSite(name, destination = conversation) {
      const status = document.getElementById("workflow-status");
      return requestTool("open_site", name, status, destination);
    }

    async function openDocuments(destination = conversation) {
      return requestTool("open_documents", "Windows Documents", document.getElementById("workflow-status"), destination);
    }

    async function openSettings(name, destination = conversation) {
      const status = document.getElementById("workflow-status");
      return requestTool("open_settings", name, status, destination);
    }

    async function spotifyPlayback(target, destination = conversation) {
      return requestTool("spotify_playback", target, document.getElementById("spotify-status"), destination);
    }

    async function checkSpotifyStatus() {
      if (safetyStopped) return;
      const version = ++spotifyStatusVersion, epoch = safetyEpoch;
      const current = () => !safetyStopped && epoch === safetyEpoch && version === spotifyStatusVersion;
      const status = document.getElementById("spotify-status");
      try {
        const result = await apiJson("/tools/spotify-status");
        if (!current()) return;
        status.textContent = result.available
          ? result.playing ? "Windows reports Spotify is playing. Audio output has not been verified." : "Windows reports Spotify is paused."
          : "No Spotify media session yet. Open Spotify and start a track to enable playback control.";
      } catch { if (current()) status.textContent = "Spotify playback status is unavailable."; }
    }

    document.getElementById("open-windows-documents").addEventListener("click", () => openDocuments());
    document.getElementById("list-documents").addEventListener("click", () => listDocuments());
    document.getElementById("open-spotify-app").addEventListener("click", () => openAppByName("Spotify"));
    document.getElementById("spotify-play").addEventListener("click", () => spotifyPlayback("Spotify Play"));
    document.getElementById("spotify-pause").addEventListener("click", () => spotifyPlayback("Spotify Pause"));
    document.getElementById("spotify-check").addEventListener("click", checkSpotifyStatus);
    checkSpotifyStatus();
    document.getElementById("open-bluetooth-settings").addEventListener("click", () => openSettings("Bluetooth"));
    document.getElementById("open-sound-settings").addEventListener("click", () => openSettings("Sound"));
    async function checkBluetooth() {
      if (safetyStopped) return;
      const version = ++bluetoothStatusVersion, epoch = safetyEpoch;
      const current = () => !safetyStopped && epoch === safetyEpoch && version === bluetoothStatusVersion;
      const status = document.getElementById("bluetooth-status");
      try {
        const response = await safeFetch("/tools/bluetooth-status", { cache: "no-store" });
        if (!response.ok) throw new Error("Bluetooth check unavailable");
        const result = await response.json();
        if (!current()) return;
        status.textContent = result.radio_available
          ? "Bluetooth adapter detected. Put the speaker in pairing mode, then open Bluetooth settings."
          : "No Bluetooth adapter detected. Connect or enable one, then check again.";
      } catch { if (current()) status.textContent = "Bluetooth check unavailable."; }
    }
    document.getElementById("check-bluetooth").addEventListener("click", checkBluetooth);
    checkBluetooth();

    function workflowActions(message, destination = conversation) {
      const text = message.toLowerCase();
      // Resource aliases use the existing model/broker route, including mixed
      // Spotify + playlist requests. Never substitute generic media playback.
      if (/\bmy\s+(?:default\s+)?playlist\b|\bjarvis\s+(?:project|in\s+vs\s+code)\b/.test(text)) return [];
      // Filename searches, including mixed requests, use Qwen's scoped tool
      // pipeline. Opening/listing Documents is a different user action.
      if (/\bdocuments\b/.test(text) && /(?:^\s*(?:please\s+)?|\band\s+)(?:find|search for)\b/.test(text)) return [];
      if (!/^\s*(?:(?:please|hey jarvis|jarvis)[, ]+)?(?:(?:can|could|would) you\s+)?(?:open|launch|pull up|show|check|list|browse|play|resume|pause|stop|connect)\b/.test(text)) return [];
      if (/^(what|which|why|how|are you|do you|can you|could you|would you)\b/.test(text) &&
          /\b(apps|applications|tools|capabilities|able|possible)\b|\bnot do\b|\bcan['’]?t\b|\bcannot\b/.test(text)) return [];
      const actionVerb = /\b(open|launch|pull up|show|check|list|browse|play|resume|pause|stop|connect)\b/.test(text);
      if (!actionVerb) return [];
      const actions = [];
      if (/\bchrome\b/.test(text)) actions.push(["Open Chrome", () => openAppByName("Chrome", destination)]);
      if (/\bepic(?: games)?\b/.test(text)) actions.push(["Open Epic Games Launcher", () => openAppByName("Epic Games Launcher", destination)]);
      const localDocs = /\b(documents|document folder|my files)\b/.test(text) ||
        /\bdocs\b/.test(text) && !/\bgoogle docs\b/.test(text);
      if (localDocs) {
        if (/\b(open|launch|pull up|show)\b/.test(text)) actions.push(["Open Windows Documents", () => openDocuments(destination)]);
        actions.push(["List Windows Documents", () => listDocuments()]);
      }
      if (/\bspotify\b/.test(text)) {
        const webRequested = /\b(web|website|browser)\b/.test(text);
        if (/\b(open|launch|pull up|show)\b/.test(text)) {
          actions.push(webRequested
            ? ["Open Spotify Web", () => openSite("Spotify Web", destination)]
            : ["Open Spotify", () => openAppByName("Spotify", destination)]);
        }
        if (/\b(play|resume)\b/.test(text)) actions.push(["Play Spotify", () => spotifyPlayback("Spotify Play", destination)]);
        if (/\b(pause|stop)\b/.test(text)) actions.push(["Pause Spotify", () => spotifyPlayback("Spotify Pause", destination)]);
        if (!actions.some(([label]) => label.includes("Spotify"))) actions.push(["Open Spotify", () => openAppByName("Spotify", destination)]);
      }
      if (/\b(speaker|bluetooth)\b/.test(text)) {
        actions.push(["Bluetooth settings", () => openSettings("Bluetooth", destination)]);
        actions.push(["Sound output settings", () => openSettings("Sound", destination)]);
      }
      return actions;
    }

    async function showWorkflow(message, actions, destination = conversation, chatId = activeSession?.id) {
      const version = conversationVersion;
      if (safetyStopped) return;
      addMessage("user", message, "", destination);
      await persistEntry(chatId, "user", message);
      const card = addMessage("assistant", "Checking the requested actions…", "Workflow", destination);
      const outcomes = [];
      for (const [label, run] of actions) {
        if (safetyStopped || version !== conversationVersion) return;
        try {
          const result = await run();
          if (result?.status === "executed") outcomes.push(result.message || label + ": request accepted by Windows.");
          else if (result?.status === "approval_required") outcomes.push(label + ": approval needed.");
          else if (result?.status === "denied") outcomes.push(label + ": denied.");
          else if (result?.entries) outcomes.push(label + ": " + result.entries.length + " items listed.");
          else outcomes.push(label + ": could not confirm completion.");
        } catch (error) { outcomes.push(label + ": " + error.message); }
      }
      if (/\bupdate/.test(message.toLowerCase()) && /\bepic\b/.test(message.toLowerCase())) {
        outcomes.push("To check update status, capture one screen frame and send it here.");
      }
      if (/\b(speaker|music|connect|play)\b/.test(message.toLowerCase()) && /\bspotify\b/.test(message.toLowerCase())) {
        outcomes.push("Pair the Bluetooth speaker in Windows, select it as Sound output, then start music in Spotify. Playback is not confirmed yet.");
      }
      if (safetyStopped || version !== conversationVersion) return;
      const note = outcomes.join("\n");
      renderMessageText(card.querySelector(".bubble"), note);
      if (chatId == null && conversationType === "side") {
        const created = await apiJson("/conversations", jsonRequest("POST", {
          kind: "side", title: message.slice(0, 36), first_message: message, first_reply: note,
        }));
        registerSideConversation(created);
      } else await persistEntry(chatId, "assistant", note);
    }

    function registerSideConversation(session) {
      activeSession = session;
      sideSession = session;
      if (!chatSessions.some(item => item.id === session.id)) chatSessions.unshift(session);
      updateChatHeader();
      renderChatList();
    }

    form.addEventListener("submit", async event => {
      event.preventDefault();
      if (safetyStopped || sending) return;
      const turnVersion = conversationVersion;
      const message = messageInput.value.trim();
      if (!message) return;
      if (!activeSession && conversationType !== "side") return;
      // Chat/voice requests all go through Qwen intent understanding first.
      // Settings buttons continue to call the same deterministic broker.
      const actions = [];
      if (actions.length && !pendingImage && !pendingDocumentPath) {
        messageInput.value = "";
        sending = true;
        sendButton.disabled = true;
        try { await showWorkflow(message, actions); }
        catch (error) { if (turnVersion === conversationVersion && !safetyStopped) addMessage("error", error.message); }
        finally { if (turnVersion === conversationVersion) { sending = false; sendButton.disabled = safetyStopped; } }
        return;
      }
      const save = conversationType === "master" && saveInput.checked;
      const imageBase64 = pendingImage;
      const documentPath = pendingDocumentPath;
      const documentScope = pendingDocumentScope;
      const windowReference = pendingWindowReference;
      sending = true;
      sendButton.disabled = true;
      sendButton.textContent = "···";
      const userItem = addMessage("user", message);
      if (imageBase64) {
        const thumbnail = document.createElement("img");
        thumbnail.className = "message-image";
        thumbnail.alt = "One-shot image sent with this message";
        thumbnail.src = imagePreview.src;
        userItem.append(thumbnail);
      }
      messageInput.value = "";
      saveInput.checked = false;
      clearImage();
      clearDocument();
      const pending = addPendingReply();
      setAssistantState("thinking");
      try {
        const appendToken = replyTokenWriter(pending.querySelector(".bubble"));
        let toolsShown = false;
        const result = await streamReply(
          { message, save, conversation_id: activeSession?.id, new_side: conversationType === "side" && !activeSession, image_base64: imageBase64,
            document_path: documentScope === "documents" ? documentPath : null, project_path: documentScope === "project" ? documentPath : null,
            window_reference: windowReference?.reference || null, workspace_scope: windowReference?.scope || null },
          token => {
            if (turnVersion !== conversationVersion || safetyStopped) return;
            appendToken(token);
            conversation.scrollTop = conversation.scrollHeight;
          },
          async results => {
            if (turnVersion !== conversationVersion || safetyStopped) return;
            toolsShown = true;
            await showModelTools({tool_results: results}, conversation);
          }
        );
        if (turnVersion !== conversationVersion || safetyStopped) { pending.remove(); return; }
        if (conversationType === "side" && !activeSession) registerSideConversation({ id: result.conversation_id, kind: "side", title: message.slice(0, 36) });
        sessionTurns.push({ role: "user", content: message }, { role: "assistant", content: result.reply });
        const count = Number(result.recalled_memories) || 0;
        const factNote = result.saved_facts?.length ? " · " + result.saved_facts.length + " new fact saved" : "";
        const meta = document.createElement("div");
        meta.className = "meta";
        meta.textContent = (result.saved ? "Exchange saved · " : "") + count + (count === 1 ? " memory recalled" : " memories recalled") + factNote;
        pending.append(meta);
        renderMessageText(pending.querySelector(".bubble"), result.reply);
        pending.querySelector(".bubble").removeAttribute("aria-label");
        if (!toolsShown) await showModelTools(result, conversation);
        recalledLabel.textContent = count + " MATCHES";
        document.getElementById("dev-first-token").textContent = result.first_token_ms + " ms";
        document.getElementById("dev-total").textContent = result.total_ms + " ms";
        document.getElementById("dev-memory").textContent = String(count);
        if (result.saved_facts?.length) loadFacts();
        setAssistantState(speakInput.checked ? "idle" : "muted");
        speakReply(result.reply);
      } catch (error) {
        pending.remove();
        if (turnVersion !== conversationVersion || safetyStopped) return;
        addMessage("error", error.message || "Could not reach Jarvis. Please try again.");
        setAssistantState("error");
      } finally {
        if (turnVersion !== conversationVersion) return;
        sending = false;
        sendButton.disabled = safetyStopped;
        sendButton.textContent = "↑";
        messageInput.focus();
      }
    });

    async function loadFacts() {
      const list = document.getElementById("facts-list");
      try {
        const response = await safeFetch("/facts", { cache: "no-store" });
        if (!response.ok) throw new Error("Memory unavailable");
        const data = await response.json();
        list.replaceChildren();
        if (!data.facts.length) {
          list.textContent = "No structured facts saved yet.";
          return;
        }
        for (const fact of data.facts) {
          const row = document.createElement("div");
          row.className = "fact";
          const key = document.createElement("strong");
          key.textContent = fact.key;
          const value = document.createElement("span");
          value.textContent = fact.value;
          row.append(key, value);
          list.append(row);
        }
      } catch {
        list.textContent = "Memory unavailable.";
      }
    }

    document.getElementById("fact-form").addEventListener("submit", async event => {
      event.preventDefault();
      const key = document.getElementById("fact-key").value.trim();
      const value = document.getElementById("fact-value").value.trim();
      const status = document.getElementById("facts-status");
      if (!key || !value || !window.confirm("Save this fact to long-term memory?\n" + key + ": " + value)) return;
      try {
        const response = await safeFetch("/facts", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ key, value, approved: true })
        });
        if (!response.ok) throw new Error("Save failed (HTTP " + response.status + ").");
        status.textContent = "Fact saved.";
        document.getElementById("fact-form").reset();
        await loadFacts();
      } catch (error) {
        status.textContent = error.message;
      }
    });

    document.getElementById("read-form").addEventListener("submit", async event => {
      event.preventDefault();
      if (safetyStopped) return;
      const version = ++projectReadVersion, epoch = safetyEpoch, chatVersion = conversationVersion;
      const current = () => !safetyStopped && version === projectReadVersion && epoch === safetyEpoch && chatVersion === conversationVersion;
      const path = document.getElementById("file-path").value.trim();
      const status = document.getElementById("read-status");
      const output = document.getElementById("read-output");
      if (!path) return;
      const useButton = document.getElementById("use-project-file");
      lastReadProjectPath = null;
      useButton.hidden = true;
      output.hidden = true;
      try {
        const response = await safeFetch("/tools/read-file", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path, approved: true })
        });
        if (!response.ok) throw new Error("Read denied (HTTP " + response.status + ").");
        const result = await response.json();
        if (!current()) return;
        output.textContent = result.content;
        output.hidden = false;
        lastReadProjectPath = path;
        useButton.hidden = false;
        status.textContent = "Read confirmed and audit logged.";
      } catch (error) {
        if (!current()) return;
        status.textContent = error.message;
      }
    });

    async function loadApps() {
      if (safetyStopped) return;
      const version = ++appListVersion, epoch = safetyEpoch;
      const current = () => !safetyStopped && epoch === safetyEpoch && version === appListVersion;
      const select = document.getElementById("app-select");
      const button = document.getElementById("open-app");
      const closeButton = document.getElementById("close-app");
      try {
        const response = await safeFetch("/tools/apps", { cache: "no-store" });
        if (!response.ok) throw new Error("App list unavailable");
        const result = await response.json();
        if (!current()) return;
        const previousSelection = select.value;
        select.replaceChildren();
        for (const name of [...result.apps, ...result.packaged_apps]) {
          const option = document.createElement("option");
          option.value = name;
          option.textContent = name;
          select.append(option);
        }
        if ([...select.options].some(option => option.value === previousSelection)) select.value = previousSelection;
        select.disabled = button.disabled = !(result.apps.length || result.packaged_apps.length);
        closeButton.disabled = !result.closable.includes(select.value);
        select.onchange = () => {
          closeButton.disabled = safetyStopped || !result.closable.includes(select.value);
        };
        document.getElementById("app-status").textContent = result.apps.length || result.packaged_apps.length
          ? "First open asks once. Saved permissions open immediately. Closing asks first."
          : "No apps configured yet.";
      } catch {
        if (!current()) return;
        select.disabled = button.disabled = closeButton.disabled = true;
        document.getElementById("app-status").textContent = "App list unavailable.";
      }
    }

    async function openAppByName(name, destination = conversation) {
      const status = document.getElementById("app-status");
      if (!name) return;
      const result = await requestTool("open_app", name, status, destination);
      if (result?.status === "executed") await loadApps();
      return result;
    }

    document.getElementById("open-app").addEventListener("click", () => {
      openAppByName(document.getElementById("app-select").value);
    });
    document.getElementById("inspect-app").addEventListener("click", () => {
      requestTool("inspect_app", document.getElementById("app-select").value, document.getElementById("app-status"));
    });

    document.getElementById("close-app").addEventListener("click", async () => {
      const name = document.getElementById("app-select").value;
      const status = document.getElementById("app-status");
      if (!name || !window.confirm("Ask " + name + " to close? Unsaved work may need your attention in the app.")) return;
      try {
        const response = await safeFetch("/tools/close-app", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name, approved: true })
        });
        if (!response.ok) throw new Error("Close denied (HTTP " + response.status + ").");
        const result = await response.json();
        await loadApps();
        status.textContent = result.close_request_sent
          ? "Close request sent to " + name + ". The app may ask about unsaved work."
          : "Close not confirmed.";
      } catch (error) {
        status.textContent = error.message;
      }
    });

    syncSafety();
    setInterval(syncSafety, 750);
    checkHealth();
    loadFacts();
    loadApps();
    loadPermissions();
    findLocalVoice();
    if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
    messageInput.focus();

    function initVisuals() {
      const starsCanvas = document.getElementById("starfield");
      const coreCanvas = document.getElementById("neural-core");
      const starsCtx = starsCanvas?.getContext("2d");
      const coreCtx = coreCanvas?.getContext("2d");
      if (!starsCtx || !coreCtx) return;
      const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
      let stars = [];
      let starWidth = 0;
      let starHeight = 0;
      let coreSize = 340;
      let tiltX = 0;
      let tiltY = 0;
      let targetX = 0;
      let targetY = 0;
      let pulseAt = -10000;
      let frame = 0;
      let lastVisualTime = null;
      let spinPhase = .35;
      const motion = { speed: .00014, pulse: .008, energy: 1 };
      const stateMotion = {
        stopped: { speed: 0, pulse: 0, energy: 0 },
        idle: { speed: .00014, pulse: .008, energy: 1 },
        listening: { speed: .00018, pulse: .023, energy: 1.12 },
        thinking: { speed: .00025, pulse: .012, energy: 1.05 },
        tool: { speed: .00034, pulse: .014, energy: 1.1 },
        approval: { speed: .00009, pulse: .004, energy: .92 },
        speaking: { speed: .00019, pulse: .03, energy: 1.13 },
        muted: { speed: .00007, pulse: .003, energy: .78 },
        error: { speed: .00009, pulse: .008, energy: .86 }
      };
      let seed = 29291;
      const random = () => {
        seed = (seed * 1664525 + 1013904223) >>> 0;
        return seed / 4294967296;
      };
      // Dense points give the core the illuminated, granular surface in the reference.
      const particles = Array.from({ length: 3250 }, () => {
        const z = random() * 2 - 1;
        const angle = random() * Math.PI * 2;
        const shell = Math.sqrt(1 - z * z);
        const distance = .52 + .48 * Math.pow(random(), .27);
        return {
          x: Math.cos(angle) * shell * distance,
          y: Math.sin(angle) * shell * distance,
          z: z * distance,
          size: random() > .9 ? .85 + random() * .9 : .24 + random() * .75,
          phase: random() * Math.PI * 2
        };
      });
      const compactParticles = particles.slice(0, 950);

      function resizeVisuals() {
        const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
        starWidth = window.innerWidth;
        starHeight = window.innerHeight;
        starsCanvas.width = Math.round(starWidth * pixelRatio);
        starsCanvas.height = Math.round(starHeight * pixelRatio);
        starsCtx.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
        coreSize = Math.max(1, coreCanvas.getBoundingClientRect().width);
        coreCanvas.width = Math.round(coreSize * pixelRatio);
        coreCanvas.height = Math.round(coreSize * pixelRatio);
        coreCtx.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
        seed = 29291;
        stars = Array.from({ length: Math.min(310, Math.max(80, Math.round(starWidth * starHeight / 4200))) }, () => ({
          x: random() * starWidth,
          y: random() * starHeight,
          radius: random() > .96 ? 1.05 + random() * .7 : .24 + random() * .65,
          phase: random() * Math.PI * 2,
          speed: .65 + random() * .65,
          drift: 5 + random() * 8,
          blue: random() > .88
        }));
        drawVisuals(reducedMotion.matches ? 0 : lastVisualTime ?? 0);
      }
      refreshVisuals = resizeVisuals;

      function drawVisuals(time) {
        const delta = lastVisualTime === null ? 0 : Math.min(80, Math.max(0, time - lastVisualTime));
        lastVisualTime = time;
        const target = stateMotion[document.body.dataset.assistantState] || stateMotion.idle;
        const ease = reducedMotion.matches ? 1 : 1 - Math.exp(-delta / 480);
        for (const key of Object.keys(motion)) motion[key] += (target[key] - motion[key]) * ease;
        if (!reducedMotion.matches) spinPhase += motion.speed * delta;
        starsCtx.clearRect(0, 0, starWidth, starHeight);
        for (const star of stars) {
          const glow = reducedMotion.matches ? .4 : .22 + .32 * (1 + Math.sin(time * .00055 * star.speed + star.phase)) / 2;
          const offsetX = reducedMotion.matches ? 0 : Math.sin(time * .0001 * star.speed + star.phase) * star.drift;
          const offsetY = reducedMotion.matches ? 0 : Math.cos(time * .00008 * star.speed + star.phase) * star.drift * .7;
          starsCtx.fillStyle = star.blue ? `rgba(149,198,255,${glow})` : `rgba(229,235,248,${glow})`;
          starsCtx.beginPath();
          starsCtx.arc(star.x + offsetX, star.y + offsetY, star.radius, 0, Math.PI * 2);
          starsCtx.fill();
        }

        coreCtx.clearRect(0, 0, coreSize, coreSize);
        const center = coreSize / 2;
        const breath = reducedMotion.matches ? 1 : 1 + motion.pulse * Math.sin(time * .0024);
        const radius = coreSize * .32 * breath;
        tiltX += (targetX - tiltX) * .045;
        tiltY += (targetY - tiltY) * .045;
        const spin = spinPhase;
        coreCtx.globalAlpha = motion.energy / 1.13;
        const cx = Math.cos(tiltY), sx = Math.sin(tiltY);
        const cy = Math.cos(spin + tiltX), sy = Math.sin(spin + tiltX);
        const halo = coreCtx.createRadialGradient(center, center, radius * .12, center, center, radius * 1.5);
        halo.addColorStop(0, "rgba(154,220,255,.40)");
        halo.addColorStop(.42, "rgba(38,126,255,.29)");
        halo.addColorStop(.74, "rgba(10,77,219,.20)");
        halo.addColorStop(1, "rgba(0,0,0,0)");
        coreCtx.fillStyle = halo;
        coreCtx.beginPath();
        coreCtx.arc(center, center, radius * 1.5, 0, Math.PI * 2);
        coreCtx.fill();
        const surface = coreCtx.createRadialGradient(center - radius * .22, center - radius * .24, radius * .06, center, center, radius * 1.02);
        surface.addColorStop(0, "rgba(222,248,255,.85)");
        surface.addColorStop(.34, "rgba(93,185,255,.70)");
        surface.addColorStop(.78, "rgba(24,115,244,.42)");
        surface.addColorStop(1, "rgba(18,74,180,.05)");
        coreCtx.fillStyle = surface;
        coreCtx.beginPath();
        coreCtx.arc(center, center, radius, 0, Math.PI * 2);
        coreCtx.fill();

        // Rotate the point cloud gently, with the pointer controlling its tilt.
        const visibleParticles = coreSize < 120 ? compactParticles : particles;
        for (const point of visibleParticles) {
          const y1 = point.y * cx - point.z * sx;
          const z1 = point.y * sx + point.z * cx;
          const x2 = point.x * cy + z1 * sy;
          const z2 = -point.x * sy + z1 * cy;
          const perspective = 2.8 / (2.8 - z2 * .28);
          const x = center + x2 * radius * perspective;
          const y = center + y1 * radius * perspective;
          const depth = (z2 + 1) / 2;
          const shimmer = reducedMotion.matches ? 1 : .83 + .17 * Math.sin(time * .0012 + point.phase);
          coreCtx.fillStyle = `rgba(${depth > .58 ? "223,247,255" : "89,178,255"},${(.23 + depth * .7) * shimmer})`;
          coreCtx.beginPath();
          coreCtx.arc(x, y, point.size * (.7 + depth * .65), 0, Math.PI * 2);
          coreCtx.fill();
        }
        const rings = [1.12, 1.27, 1.4];
        for (let index = 0; index < rings.length; index += 1) {
          const ringRadius = radius * rings[index];
          coreCtx.strokeStyle = `rgba(69,165,255,${index === 0 ? .7 : .34})`;
          coreCtx.lineWidth = index === 0 ? 1.3 : .8;
          coreCtx.beginPath();
          coreCtx.arc(center, center, ringRadius, spin * (index % 2 ? -1 : 1), spin * (index % 2 ? -1 : 1) + Math.PI * 1.77);
          coreCtx.stroke();
        }
        for (let tick = 0; tick < 96; tick += 1) {
          const angle = tick * Math.PI * 2 / 96 + spin * .23;
          const inner = radius * 1.32;
          const outer = inner + (tick % 8 === 0 ? 7 : tick % 4 === 0 ? 4 : 2);
          coreCtx.strokeStyle = `rgba(98,191,255,${tick % 8 === 0 ? .65 : .32})`;
          coreCtx.lineWidth = tick % 8 === 0 ? 1.3 : .7;
          coreCtx.beginPath();
          coreCtx.moveTo(center + Math.cos(angle) * inner, center + Math.sin(angle) * inner);
          coreCtx.lineTo(center + Math.cos(angle) * outer, center + Math.sin(angle) * outer);
          coreCtx.stroke();
        }
        const age = time - pulseAt;
        if (age >= 0 && age < 900) {
          const progress = age / 900;
          coreCtx.strokeStyle = `rgba(167,255,248,${(1 - progress) * .72})`;
          coreCtx.lineWidth = 1.7;
          coreCtx.beginPath();
          coreCtx.arc(center, center, radius * (.35 + progress * .9), 0, Math.PI * 2);
          coreCtx.stroke();
        }
        coreCtx.globalAlpha = 1;
      }

      let lastFrame = 0;
      function animate(time) {
        const frameInterval = 32;
        if (!document.hidden && time - lastFrame >= frameInterval) {
          drawVisuals(time);
          lastFrame = time;
        }
        if (!reducedMotion.matches && !document.hidden) frame = requestAnimationFrame(animate);
      }
      coreCanvas.addEventListener("pointermove", event => {
        if (reducedMotion.matches) return;
        const box = coreCanvas.getBoundingClientRect();
        targetX = ((event.clientX - box.left) / box.width - .5) * .75;
        targetY = ((event.clientY - box.top) / box.height - .5) * -.75;
        if (reducedMotion.matches) drawVisuals(0);
      });
      coreCanvas.addEventListener("pointerleave", () => { targetX = 0; targetY = 0; });
      const pulse = () => {
        if (reducedMotion.matches) return;
        pulseAt = performance.now();
        if (reducedMotion.matches) drawVisuals(pulseAt);
      };
      coreCanvas.addEventListener("click", pulse);
      coreCanvas.addEventListener("keydown", event => {
        if (event.key === "Enter" || event.key === " ") { event.preventDefault(); pulse(); }
      });
      window.addEventListener("resize", resizeVisuals, { passive: true });
      reducedMotion.addEventListener("change", () => {
        cancelAnimationFrame(frame);
        lastVisualTime = null;
        if (reducedMotion.matches) drawVisuals(0);
        else frame = requestAnimationFrame(animate);
      });
      document.addEventListener("visibilitychange", () => {
        cancelAnimationFrame(frame);
        lastVisualTime = null;
        if (!document.hidden && !reducedMotion.matches) frame = requestAnimationFrame(animate);
      });
      window.addEventListener("jarvis-state-change", () => {
        if (reducedMotion.matches) drawVisuals(0);
      });
      resizeVisuals();
      if (!reducedMotion.matches) frame = requestAnimationFrame(animate);
    }

    initVisuals();
