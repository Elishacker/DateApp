/* ==========================================================================
   Real-time chat client. Reads its configuration from data-* attributes so the
   template contains no JavaScript and no logic.
   ========================================================================== */
(function () {
    "use strict";

    const shell = document.querySelector("[data-conversation-id]");
    if (!shell) return;

    const conversationId = shell.dataset.conversationId;
    const currentUserId = shell.dataset.userId;
    const thread = document.querySelector("[data-thread]");
    const form = document.querySelector("[data-composer]");
    const input = form ? form.querySelector('[name="body"]') : null;
    const typingNode = document.querySelector("[data-typing]");

    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    let socket = null;
    let typingTimer = null;
    let reconnectDelay = 1000;

    const EMOJI = [
        "😀", "😁", "😂", "🤣", "😊", "😍", "😘", "😉", "😎", "🤔",
        "😅", "😇", "🙂", "😢", "😭", "😡", "😴", "🥳", "😮", "🙄",
        "👍", "👎", "👏", "🙌", "🙏", "💪", "🤝", "👋", "✌️", "🤞",
        "❤️", "🧡", "💛", "💚", "💙", "💜", "🖤", "💕", "💔", "🔥",
        "✨", "🎉", "😆", "🥰", "😏", "😳", "🤗", "😌", "🥺", "😋",
    ];

    function scrollToEnd() {
        if (thread) thread.scrollTop = thread.scrollHeight;
    }

    const SPRITE = shell.dataset.sprite || "/static/img/icons.svg";

    function icon(name, className) {
        // Built as a namespaced element because innerHTML-ing an <svg> string
        // does not bind the SVG namespace correctly in every browser.
        const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        svg.setAttribute("class", `icon ${className || ""}`.trim());
        svg.setAttribute("width", "13");
        svg.setAttribute("height", "13");
        svg.setAttribute("fill", "currentColor");
        svg.setAttribute("aria-hidden", "true");
        const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
        use.setAttribute("href", `${SPRITE}#i-${name}`);
        svg.appendChild(use);
        return svg;
    }

    function renderMessage(message) {
        const bubble = document.createElement("div");
        const isMine = String(message.sender_id) === String(currentUserId);
        bubble.className = "bubble" + (isMine ? " is-mine" : "");
        bubble.dataset.messageId = message.id;
        bubble.dataset.createdAt = message.created_at || "";

        if (message.is_deleted) {
            bubble.classList.add("is-deleted");
            const text = document.createElement("span");
            text.className = "bubble-text";
            text.textContent = "This message was deleted";
            bubble.appendChild(text);
            return bubble;
        }

        if (message.attachment_url) {
            const wrap = document.createElement("span");
            wrap.className = "bubble-image";
            const img = document.createElement("img");
            img.src = message.attachment_url;
            img.alt = "Shared photo";
            img.loading = "lazy";
            wrap.appendChild(img);
            bubble.appendChild(wrap);
        }

        if (message.voice_url) {
            const audio = document.createElement("audio");
            audio.controls = true;
            audio.src = message.voice_url;
            bubble.appendChild(audio);
        }

        if (message.video_url) {
            const wrap = document.createElement("span");
            wrap.className = "bubble-video";
            const video = document.createElement("video");
            video.controls = true;
            video.src = message.video_url;
            wrap.appendChild(video);
            bubble.appendChild(wrap);
        }

        if (message.document_url) {
            const link = document.createElement("a");
            link.className = "bubble-document";
            link.href = message.document_url;
            link.target = "_blank";
            link.rel = "noopener";
            link.appendChild(icon("journal-text"));
            const name = document.createElement("span");
            name.className = "bubble-document-name";
            name.textContent = message.document_name || "Document";
            link.appendChild(name);
            bubble.appendChild(link);
        }

        if (message.body) {
            const text = document.createElement("span");
            text.className = "bubble-text";
            text.textContent = message.body;   // textContent, never innerHTML
            bubble.appendChild(text);
        }

        const foot = document.createElement("span");
        foot.className = "bubble-foot";

        const time = document.createElement("span");
        time.className = "bubble-time";
        time.textContent = message.time_label || "";
        foot.appendChild(time);

        if (isMine) {
            foot.appendChild(
                message.is_read ? icon("check2-all", "is-read") : icon("check2")
            );
        }

        bubble.appendChild(foot);
        return bubble;
    }

    function markMineRead() {
        thread.querySelectorAll(".bubble.is-mine .bubble-foot").forEach((foot) => {
            const existing = foot.querySelector(".icon");
            if (existing && !existing.classList.contains("is-read")) {
                existing.replaceWith(icon("check2-all", "is-read"));
            }
        });
    }

    function connect() {
        socket = new WebSocket(`${scheme}://${window.location.host}/ws/chat/${conversationId}/`);

        socket.addEventListener("open", () => {
            reconnectDelay = 1000;
            socket.send(JSON.stringify({ action: "read" }));
        });

        socket.addEventListener("message", (event) => {
            const payload = JSON.parse(event.data);

            if (payload.type === "history") {
                if (thread) thread.innerHTML = "";
                payload.messages.forEach((m) => thread.appendChild(renderMessage(m)));
                scrollToEnd();
            } else if (payload.type === "message") {
                thread.querySelector(".chat-intro")?.remove();
                thread.appendChild(renderMessage(payload.message));
                scrollToEnd();
                if (String(payload.message.sender_id) !== String(currentUserId)) {
                    socket.send(JSON.stringify({ action: "read" }));
                }
            } else if (payload.type === "typing") {
                if (typingNode) {
                    typingNode.textContent = payload.is_typing ? "typing…" : "";
                }
            } else if (payload.type === "read") {
                // The peer opened the conversation: flip our ticks to double.
                markMineRead();
            } else if (payload.type === "deleted") {
                const node = thread.querySelector(`[data-message-id="${payload.message_id}"]`);
                if (node) {
                    node.classList.add("is-deleted");
                    node.textContent = "This message was deleted";
                }
            } else if (payload.type === "error") {
                window.Zynora.toast(payload.message, "error");
            }
        });

        socket.addEventListener("close", () => {
            // Exponential backoff, capped — a flaky mobile network is normal.
            setTimeout(connect, reconnectDelay);
            reconnectDelay = Math.min(reconnectDelay * 2, 20000);
        });
    }

    if (window.WebSocket) connect();

    /* ---- sending --------------------------------------------------------- */
    const ATTACH_KIND = { attachment: "image", video: "video", document: "document" };

    function fileInputWithContent() {
        return Array.from(form.querySelectorAll("[data-attach]"))
            .find((el) => el.files.length);
    }

    if (form) {
        form.addEventListener("submit", async (event) => {
            event.preventDefault();
            const body = input.value.trim();
            const fileInput = fileInputWithContent();
            if (!body && !fileInput) return;

            if (body && !fileInput && socket && socket.readyState === WebSocket.OPEN) {
                socket.send(JSON.stringify({ action: "send", body: body }));
                input.value = "";
            } else {
                // Fallback to the HTTP endpoint when the socket is down.
                const data = new FormData(form);
                if (fileInput) data.set("kind", ATTACH_KIND[fileInput.dataset.attach]);
                const result = await window.Zynora.post(form.action, data);
                if (result.ok) {
                    thread.querySelector(".chat-intro")?.remove();
                    thread.appendChild(renderMessage(result.data.message));
                    form.reset();
                    scrollToEnd();
                    input.value = "";
                } else {
                    window.Zynora.toast(result.data.message || "Could not send.", "error");
                }
            }
        });

        form.querySelectorAll("[data-attach]").forEach((attach) => {
            attach.addEventListener("change", () => {
                if (attach.files.length) form.requestSubmit();
            });
        });

        const attachToggle = form.querySelector("[data-attach-toggle]");
        const attachMenu = document.querySelector("[data-attach-menu]");
        if (attachToggle && attachMenu) {
            attachToggle.addEventListener("click", (event) => {
                event.stopPropagation();
                emojiPanel?.setAttribute("hidden", "");
                attachMenu.toggleAttribute("hidden");
            });
            attachMenu.querySelectorAll("[data-attach-trigger]").forEach((btn) => {
                btn.addEventListener("click", () => {
                    form.querySelector(`[data-attach="${btn.dataset.attachTrigger}"]`)?.click();
                    attachMenu.setAttribute("hidden", "");
                });
            });
        }

        const emojiToggle = form.querySelector("[data-emoji-toggle]");
        const emojiPanel = document.querySelector("[data-emoji-panel]");
        if (emojiToggle && emojiPanel && !emojiPanel.childElementCount) {
            EMOJI.forEach((glyph) => {
                const btn = document.createElement("button");
                btn.type = "button";
                btn.className = "emoji-option";
                btn.textContent = glyph;
                btn.addEventListener("click", () => {
                    const start = input.selectionStart ?? input.value.length;
                    const end = input.selectionEnd ?? input.value.length;
                    input.value = input.value.slice(0, start) + glyph + input.value.slice(end);
                    input.focus();
                    input.selectionStart = input.selectionEnd = start + glyph.length;
                });
                emojiPanel.appendChild(btn);
            });
        }
        if (emojiToggle && emojiPanel) {
            emojiToggle.addEventListener("click", (event) => {
                event.stopPropagation();
                attachMenu?.setAttribute("hidden", "");
                emojiPanel.toggleAttribute("hidden");
            });
        }
        document.addEventListener("click", (event) => {
            if (attachMenu && !attachMenu.contains(event.target) && event.target !== attachToggle) {
                attachMenu.setAttribute("hidden", "");
            }
            if (emojiPanel && !emojiPanel.contains(event.target) && event.target !== emojiToggle) {
                emojiPanel.setAttribute("hidden", "");
            }
        });

        input.addEventListener("input", () => {
            if (!socket || socket.readyState !== WebSocket.OPEN) return;
            socket.send(JSON.stringify({ action: "typing", is_typing: true }));
            clearTimeout(typingTimer);
            typingTimer = setTimeout(() => {
                socket.send(JSON.stringify({ action: "typing", is_typing: false }));
            }, 2500);
        });
    }

    /* ---- load older messages when scrolled to the top -------------------- */
    if (thread) {
        thread.addEventListener("scroll", () => {
            if (thread.scrollTop > 0) return;
            const oldest = thread.querySelector(".bubble");
            if (!oldest || !socket || socket.readyState !== WebSocket.OPEN) return;
            socket.send(JSON.stringify({
                action: "load_more",
                before: oldest.dataset.createdAt || null,
            }));
        });
        scrollToEnd();
    }
})();
