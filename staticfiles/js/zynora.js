/* ==========================================================================
   Zynora front-end behaviour.
   All interaction lives here — templates stay pure HTML.
   ========================================================================== */
(function () {
    "use strict";

    const Zynora = {
        csrf() {
            const meta = document.querySelector('meta[name="csrf-token"]');
            return meta ? meta.getAttribute("content") : "";
        },

        async post(url, data) {
            const body = data instanceof FormData ? data : new URLSearchParams(data);
            const response = await fetch(url, {
                method: "POST",
                headers: {
                    "X-CSRFToken": Zynora.csrf(),
                    "X-Requested-With": "XMLHttpRequest",
                },
                body,
                credentials: "same-origin",
            });
            let payload = {};
            try { payload = await response.json(); } catch (e) { /* non-JSON */ }
            return { ok: response.ok, status: response.status, data: payload };
        },

        async get(url) {
            const response = await fetch(url, {
                headers: { "X-Requested-With": "XMLHttpRequest" },
                credentials: "same-origin",
            });
            return response.json();
        },

        toast(message, tone) {
            let stack = document.querySelector(".flash-stack");
            if (!stack) {
                stack = document.createElement("div");
                stack.className = "flash-stack";
                stack.setAttribute("role", "status");
                document.body.appendChild(stack);
            }
            const node = document.createElement("div");
            node.className = "flash flash-" + (tone || "info");
            node.innerHTML =
                '<span></span><button type="button" class="flash-close" data-dismiss>&times;</button>';
            node.querySelector("span").textContent = message;
            stack.appendChild(node);
            setTimeout(() => node.remove(), 6000);
        },
    };

    window.Zynora = Zynora;

    /* ---- dismissible flashes -------------------------------------------- */
    document.addEventListener("click", (event) => {
        if (event.target.matches("[data-dismiss]")) {
            event.target.closest(".flash").remove();
        }
    });

    document.querySelectorAll(".flash").forEach((flash) => {
        setTimeout(() => flash.remove(), 7000);
    });

    /* ---- progress bars ---------------------------------------------------
       Widths come from a data attribute rather than an inline style, so the
       templates stay free of presentation logic and the CSP stays strict. */
    document.querySelectorAll("[data-progress]").forEach((bar) => {
        const percent = Math.max(0, Math.min(100, parseFloat(bar.dataset.progress) || 0));
        bar.style.width = percent + "%";
    });

    /* ---- mark the active sidebar link ----------------------------------- */
    const path = window.location.pathname;
    document.querySelectorAll(".sidebar-link, .tab").forEach((link) => {
        const href = link.getAttribute("href");
        if (!href || href === "/") return;
        if (path === href || (path.startsWith(href) && href.length > 1)) {
            link.classList.add("is-active");
        }
    });

    /* ---- swipe actions ----------------------------------------------------
       Shared by the plain like/pass/super buttons and by the message compose
       panel, which sends a super like carrying a note. */
    function markLiked(card, kind) {
        if (!card) return;

        const like = card.querySelector(".act-like");
        const superLike = card.querySelector(".act-super");

        like?.classList.add("is-active");
        if (like) {
            like.disabled = true;
            like.title = "Liked";
        }
        if (kind === "super_like") {
            superLike?.classList.add("is-active");
            if (superLike) {
                superLike.disabled = true;
                superLike.title = "Super liked";
            }
        }

        // Badge on the photo, matching what a server render would produce.
        let flag = card.querySelector("[data-liked-flag]");
        if (!flag) {
            flag = document.createElement("span");
            flag.className = "card-liked";
            flag.setAttribute("data-liked-flag", "");
            card.querySelector(".card-media")?.appendChild(flag);
        }
        flag.textContent = kind === "super_like" ? "Super liked" : "Liked";
    }

    async function swipe(card, userId, kind, message) {
        const payload = { user_id: userId, kind: kind };
        if (message) payload.message = message;

        const result = await Zynora.post("/discover/swipe/", payload);

        if (!result.ok) {
            Zynora.toast(result.data.message || "Something went wrong.", "error");
            if (result.status === 402) {
                setTimeout(() => (window.location.href = "/subscriptions/"), 1400);
            }
            return false;
        }

        if (result.data.matched && result.data.match) {
            // A match moves to the Matches tab, so the card does leave.
            Zynora.toast(result.data.match.message, "success");
            if (card) {
                card.classList.add("is-gone");
                setTimeout(() => card.remove(), 240);
            }
        } else {
            // A like keeps the person visible, now marked as liked.
            markLiked(card, kind);
            if (message) Zynora.toast("Message sent with your super like.", "success");
        }

        updateQuota(result.data.quota);
        return true;
    }

    document.addEventListener("click", async (event) => {
        const button = event.target.closest("[data-swipe]");
        if (!button || button.disabled) return;

        const card = button.closest(".card");
        button.disabled = true;

        const ok = await swipe(card, button.dataset.userId, button.dataset.swipe);
        if (!ok) button.disabled = false;
    });

    /* Chat is a normal section of the app: message links are ordinary links
       that navigate this window, so the session and history stay intact. No
       popup, nothing to intercept here. */

    /* ---- swipe to delete --------------------------------------------------
       A row is a surface over a delete action. Dragging moves only the
       surface. The action is a real form, so everything here is enhancement:
       with JS off the button still submits and the page reloads. */
    const SWIPE_ACTION_WIDTH = 88;
    const SWIPE_OPEN_AT = 40;   // px of travel that counts as "reveal it"
    const SWIPE_AXIS_LOCK = 8;  // px before we decide horizontal vs vertical

    let openRow = null;

    function closeRow(row) {
        if (!row) return;
        row.classList.remove("is-open");
        if (openRow === row) openRow = null;
    }

    function openRowNow(row) {
        if (openRow && openRow !== row) closeRow(openRow);
        row.classList.add("is-open");
        openRow = row;
    }

    function setNotificationCount(count) {
        document.querySelectorAll("[data-notif-count]").forEach((node) => {
            if (count > 0) node.textContent = count;
            else node.remove();
        });
    }

    document.querySelectorAll("[data-swipe-item]").forEach((row) => {
        const surface = row.querySelector(".swipe-surface");
        if (!surface) return;

        let startX = 0, startY = 0, dx = 0, axis = null, dragging = false;

        row.addEventListener("touchstart", (event) => {
            if (event.touches.length !== 1) return;
            startX = event.touches[0].clientX;
            startY = event.touches[0].clientY;
            dx = 0;
            axis = null;
            dragging = true;
        }, { passive: true });

        row.addEventListener("touchmove", (event) => {
            if (!dragging) return;
            const moveX = event.touches[0].clientX - startX;
            const moveY = event.touches[0].clientY - startY;

            if (!axis) {
                if (Math.abs(moveX) < SWIPE_AXIS_LOCK && Math.abs(moveY) < SWIPE_AXIS_LOCK) return;
                // Vertical wins ties, so the page never fights the finger.
                axis = Math.abs(moveX) > Math.abs(moveY) ? "x" : "y";
                if (axis === "x") row.classList.add("is-dragging");
            }
            if (axis !== "x") return;

            event.preventDefault();
            const base = row.classList.contains("is-open") ? -SWIPE_ACTION_WIDTH : 0;
            // Clamp: fully open at one end, shut at the other.
            dx = Math.max(-SWIPE_ACTION_WIDTH, Math.min(0, base + moveX));
            surface.style.transform = `translateX(${dx}px)`;
        }, { passive: false });

        row.addEventListener("touchend", () => {
            if (!dragging) return;
            dragging = false;
            row.classList.remove("is-dragging");
            if (axis !== "x") return;
            surface.style.transform = "";
            if (dx <= -SWIPE_OPEN_AT) openRowNow(row); else closeRow(row);
        });

        // A tap on an open row shuts it instead of following the link.
        surface.addEventListener("click", (event) => {
            if (row.classList.contains("is-open")) {
                event.preventDefault();
                closeRow(row);
            }
        });
    });

    // Anywhere else closes whatever is open.
    document.addEventListener("touchstart", (event) => {
        if (openRow && !event.target.closest("[data-swipe-item]")) closeRow(openRow);
    }, { passive: true });

    document.addEventListener("submit", async (event) => {
        const form = event.target.closest("[data-swipe-delete]");
        if (!form) return;
        event.preventDefault();

        const row = form.closest("[data-swipe-item]");
        const list = form.closest("[data-swipe-list]");
        const result = await Zynora.post(form.action, {});
        if (!result.ok) {
            Zynora.toast((result.data && result.data.message) || "Could not delete that.", "error");
            return;
        }

        setNotificationCount(result.data.unread_count || 0);
        closeRow(row);
        // Fix the height first so the collapse has something to animate from.
        row.style.maxHeight = `${row.offsetHeight}px`;
        requestAnimationFrame(() => row.classList.add("is-removing"));
        setTimeout(() => {
            row.remove();
            // Nothing left: reload so the empty state renders server-side.
            if (list && !list.querySelector("[data-swipe-item]")) window.location.reload();
        }, 240);
    });

    /* ---- mobile drawer ----------------------------------------------------
       The sidebar and the backdrop are always in the DOM; CSS decides whether
       they occupy space. This only flips classes, so nothing here runs any
       differently on desktop — the elements are simply never visible. */
    const drawer = document.querySelector("[data-drawer]");
    const backdrop = document.querySelector(".drawer-backdrop");
    const burger = document.querySelector("[data-drawer-toggle]");

    function setDrawer(open) {
        if (!drawer) return;
        drawer.classList.toggle("is-open", open);
        if (backdrop) backdrop.classList.toggle("is-open", open);
        document.body.classList.toggle("drawer-open", open);
        if (burger) burger.setAttribute("aria-expanded", open ? "true" : "false");
    }

    if (burger) {
        burger.addEventListener("click", () => {
            setDrawer(!drawer.classList.contains("is-open"));
        });
    }

    document.addEventListener("click", (event) => {
        if (event.target.closest("[data-drawer-close]")) setDrawer(false);
        // Following a link inside the drawer should close it behind you.
        else if (event.target.closest("[data-drawer] a")) setDrawer(false);
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") setDrawer(false);
    });

    // Resizing past the breakpoint must not leave a hidden drawer holding the
    // body scroll lock.
    window.matchMedia("(min-width: 901px)").addEventListener("change", (event) => {
        if (event.matches) setDrawer(false);
    });

    function updateQuota(quota) {
        if (!quota) return;
        const node = document.querySelector("[data-quota-message]");
        if (!node) return;
        if (quota.is_unlimited) {
            node.textContent = "Unlimited likes";
        } else if (quota.likes_remaining <= 0) {
            node.textContent = "You're out of likes for today — upgrade for unlimited";
        } else {
            node.textContent = quota.likes_remaining + " likes left today";
        }
    }

    function checkEmptyFeed() {
        const grid = document.querySelector("[data-feed]");
        if (grid && grid.querySelectorAll(".card").length === 0) {
            window.location.reload();
        }
    }

    /* ---- rewind ---------------------------------------------------------- */
    document.addEventListener("click", async (event) => {
        const button = event.target.closest("[data-rewind]");
        if (!button) return;
        const result = await Zynora.post("/discover/rewind/", {});
        if (result.ok) {
            Zynora.toast("Last swipe undone.", "success");
            window.location.reload();
        } else {
            Zynora.toast(result.data.message || "Nothing to undo.", "error");
        }
    });

    /* ---- search scope chips ----------------------------------------------
       Radio inputs are hidden; clicking a chip re-runs the search. */
    document.addEventListener("change", (event) => {
        if (event.target.matches('.search-scopes input[type="radio"], .search-strict input')) {
            event.target.closest("form")?.requestSubmit();
        }
    });

    /* ---- geolocation ----------------------------------------------------- */
    document.addEventListener("click", (event) => {
        if (!event.target.closest("[data-locate]")) return;
        const button = event.target.closest("[data-locate]");

        if (!navigator.geolocation) {
            Zynora.toast("Your browser doesn't support location sharing.", "warning");
            return;
        }
        // Browsers gate the geolocation API behind a secure context (https,
        // or localhost) and some just never call back at all on a plain-http
        // LAN address rather than erroring — so check this ourselves first,
        // instead of leaving the button stuck on "Locating…" with no message.
        if (!window.isSecureContext) {
            Zynora.toast(
                "Location needs a secure (https) connection — it won't work over plain http.",
                "warning"
            );
            return;
        }
        button.disabled = true;
        button.textContent = "Locating…";

        navigator.geolocation.getCurrentPosition(
            async (position) => {
                const result = await Zynora.post("/profile/location/", {
                    latitude: position.coords.latitude,
                    longitude: position.coords.longitude,
                });
                if (result.data.success) {
                    Zynora.toast("Location updated.", "success");
                    const latField = document.querySelector('[name="latitude"]');
                    const lonField = document.querySelector('[name="longitude"]');
                    if (latField) latField.value = position.coords.latitude;
                    if (lonField) lonField.value = position.coords.longitude;
                }
                button.disabled = false;
                button.textContent = "Use my location";
            },
            (error) => {
                const messages = {
                    1: "Location permission was denied. Allow it in your browser's site settings and try again.",
                    2: "Your device couldn't determine a location right now.",
                    3: "Location took too long to respond. Try again.",
                };
                Zynora.toast(messages[error.code] || "We couldn't get your location.", "warning");
                button.disabled = false;
                button.textContent = "Use my location";
            },
            { enableHighAccuracy: false, timeout: 8000 }
        );
    });

    /* ---- block / report shortcuts ---------------------------------------- */
    document.addEventListener("click", async (event) => {
        const button = event.target.closest("[data-block]");
        if (!button) return;
        if (!window.confirm("Block this person? They won't be able to see or contact you.")) {
            return;
        }
        const result = await Zynora.post(`/reports/user/${button.dataset.block}/block/`, {});
        if (result.ok) {
            Zynora.toast("Blocked.", "success");
            const card = button.closest(".card, .list-item");
            if (card) card.remove();
        }
    });

    /* ---- badge polling (fallback when the socket is unavailable) --------- */
    if (document.querySelector("[data-badge-poll]")) {
        setInterval(async () => {
            try {
                const payload = await Zynora.get("/api/v1/notifications/badges/");
                if (!payload.success) return;
                Object.entries(payload.data).forEach(([key, value]) => {
                    document.querySelectorAll(`[data-badge="${key}"]`).forEach((node) => {
                        node.textContent = value > 0 ? value : "";
                        node.style.display = value > 0 ? "" : "none";
                    });
                });
            } catch (e) { /* offline — try again next tick */ }
        }, 45000);
    }

    /* ---- mobile-money payment polling -------------------------------------
       Mobile money confirms out of band, so the pending page polls until the
       provider callback (or the reconciliation task) settles the payment. */
    const paymentHost = document.querySelector("[data-payment-poll]");
    if (paymentHost) {
        const statusNode = paymentHost.querySelector("[data-payment-status]");
        const pollUrl = paymentHost.dataset.paymentPoll;
        let attempts = 0;

        const timer = setInterval(async () => {
            attempts += 1;
            try {
                const payload = await Zynora.get(pollUrl);
                if (payload.is_settled) {
                    clearInterval(timer);
                    statusNode.textContent = "Payment confirmed. Redirecting…";
                    window.location.href = payload.redirect_url || "/subscriptions/mine/";
                } else if (!payload.is_open) {
                    clearInterval(timer);
                    statusNode.textContent = "That payment did not go through.";
                }
            } catch (e) { /* transient — keep polling */ }

            if (attempts >= 40) {          // ~3.5 minutes
                clearInterval(timer);
                statusNode.textContent =
                    "Still waiting. We'll email you as soon as it clears.";
            }
        }, 5000);
    }

    /* ---- presence socket -------------------------------------------------- */
    const presenceHost = document.querySelector("[data-presence]");
    if (presenceHost && window.WebSocket) {
        const scheme = window.location.protocol === "https:" ? "wss" : "ws";
        const socket = new WebSocket(`${scheme}://${window.location.host}/ws/presence/`);

        socket.addEventListener("message", (event) => {
            const payload = JSON.parse(event.data);
            if (payload.type === "conversation_bump") {
                Zynora.toast("New message", "info");
            } else if (payload.type === "match") {
                Zynora.toast("It's a match!", "success");
            }
        });

        setInterval(() => {
            if (socket.readyState === WebSocket.OPEN) {
                socket.send(JSON.stringify({ action: "ping" }));
            }
        }, 30000);
    }

    /* ---- PWA service worker ------------------------------------------------ */
    if ("serviceWorker" in navigator) {
        if (document.body.dataset.debug === "true") {
            // The cache-first /static/ strategy is only safe in production,
            // where filenames are content-hashed. In dev the same URL always
            // wins the cache, so a worker installed here would keep serving
            // stale JS/CSS forever — tear down any that already got in.
            navigator.serviceWorker.getRegistrations().then((regs) => {
                regs.forEach((reg) => reg.unregister());
            });
            if (window.caches) {
                caches.keys().then((names) => names.forEach((name) => caches.delete(name)));
            }
        } else {
            navigator.serviceWorker.register("/sw.js");
        }
    }
})();
