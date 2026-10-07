/* ============================================================
   GLOBAL INCOMING CALL LISTENER
   Loaded on every logged-in page except the chat page (which has
   its own call engine). Rings for incoming video calls and, on
   Accept, opens the caller's chat page which answers the call.
   ============================================================ */
(function () {
    const script = document.currentScript;
    const myStudentId = script ? parseInt(script.dataset.studentId, 10) : NaN;
    if (!myStudentId || typeof io === "undefined") return;

    const socket = io({
        transports: ['websocket', 'polling'],
        reconnection: true,
        reconnectionAttempts: 10,
        reconnectionDelay: 1000
    });

    socket.on("connect", function () {
        socket.emit("register_student", { student_id: myStudentId });
    });

    let currentCall = null;

    /* ---------- Popup ---------- */
    const overlay = document.createElement("div");
    overlay.style.cssText =
        "display:none;position:fixed;inset:0;z-index:99999;background:rgba(15,10,40,0.65);" +
        "align-items:center;justify-content:center;font-family:'Poppins',sans-serif;";
    overlay.innerHTML =
        '<div style="background:#fff;border-radius:20px;padding:32px 36px;text-align:center;' +
        'box-shadow:0 20px 50px rgba(0,0,0,0.35);max-width:90vw;width:340px;">' +
        '<div style="font-size:44px;margin-bottom:10px;">📞</div>' +
        '<h2 style="color:#24135F;margin:0 0 6px;font-size:22px;">Incoming Video Call</h2>' +
        '<p data-role="caller-text" style="color:#555;margin:0 0 22px;">Someone is calling you...</p>' +
        '<div style="display:flex;gap:12px;justify-content:center;">' +
        '<button type="button" data-role="accept" style="background:#16A34A;color:#fff;border:none;' +
        'padding:12px 22px;border-radius:10px;font-size:15px;cursor:pointer;">Accept</button>' +
        '<button type="button" data-role="decline" style="background:#DC2626;color:#fff;border:none;' +
        'padding:12px 22px;border-radius:10px;font-size:15px;cursor:pointer;">Decline</button>' +
        '</div></div>';
    if (document.body) {
        document.body.appendChild(overlay);
    } else {
        document.addEventListener("DOMContentLoaded", function () {
            document.body.appendChild(overlay);
        });
    }

    const callerText = overlay.querySelector('[data-role="caller-text"]');

    function showPopup(name) {
        callerText.innerText = name + " is video calling you...";
        overlay.style.display = "flex";
    }

    function hidePopup() {
        overlay.style.display = "none";
    }

    /* ---------- Ringtone ---------- */
    let audioCtx = null;
    let ringtoneInterval = null;
    let activeOscillators = [];

    function getAudioContext() {
        try {
            if (!audioCtx) {
                const Ctx = window.AudioContext || window.webkitAudioContext;
                if (!Ctx) return null;
                audioCtx = new Ctx();
            }
            if (audioCtx.state === "suspended") audioCtx.resume();
            return audioCtx;
        } catch (e) {
            return null;
        }
    }

    function startRingtone() {
        stopRingtone();
        const ctx = getAudioContext();
        if (!ctx) return;
        const phrase = [
            { freq: 659.25, dur: 0.18, delay: 0.00 },
            { freq: 830.61, dur: 0.18, delay: 0.22 },
            { freq: 739.99, dur: 0.22, delay: 0.44 },
            { freq: 493.88, dur: 0.28, delay: 0.72 },
            { freq: 659.25, dur: 0.18, delay: 1.05 },
            { freq: 830.61, dur: 0.18, delay: 1.28 },
            { freq: 987.77, dur: 0.25, delay: 1.50 },
            { freq: 880.00, dur: 0.35, delay: 1.80 }
        ];
        function play() {
            const now = ctx.currentTime;
            phrase.forEach(function (note) {
                try {
                    const osc = ctx.createOscillator();
                    const gain = ctx.createGain();
                    osc.type = "triangle";
                    osc.frequency.setValueAtTime(note.freq, now + note.delay);
                    gain.gain.setValueAtTime(0.001, now + note.delay);
                    gain.gain.linearRampToValueAtTime(0.30, now + note.delay + 0.03);
                    gain.gain.exponentialRampToValueAtTime(0.001, now + note.delay + note.dur);
                    osc.connect(gain);
                    gain.connect(ctx.destination);
                    osc.start(now + note.delay);
                    osc.stop(now + note.delay + note.dur + 0.05);
                    activeOscillators.push(osc);
                } catch (e) {}
            });
        }
        play();
        ringtoneInterval = setInterval(play, 2600);
    }

    function stopRingtone() {
        if (ringtoneInterval) {
            clearInterval(ringtoneInterval);
            ringtoneInterval = null;
        }
        activeOscillators.forEach(function (osc) {
            try { osc.stop(); } catch (e) {}
        });
        activeOscillators = [];
    }

    // Browsers only allow sound/notifications after a user interaction.
    document.addEventListener("click", function () {
        getAudioContext();
        if ("Notification" in window && Notification.permission === "default") {
            Notification.requestPermission();
        }
    }, { once: true });

    function showDesktopNotification(title, body) {
        if ("Notification" in window && Notification.permission === "granted") {
            try {
                new Notification(title, {
                    body: body,
                    icon: "https://cdn-icons-png.flaticon.com/512/3135/3135789.png"
                });
            } catch (e) {}
        }
    }

    /* ---------- Call events ---------- */
    socket.on("incoming_call", function (data) {
        currentCall = data;
        const name = data.caller_name || "A student";
        showPopup(name);
        startRingtone();
        showDesktopNotification("📞 Incoming Video Call", name + " is video calling you on Skill Exchange...");
    });

    socket.on("call_cancelled", function () {
        stopRingtone();
        hidePopup();
        currentCall = null;
    });

    socket.on("call_ended", function () {
        stopRingtone();
        hidePopup();
        currentCall = null;
    });

    overlay.querySelector('[data-role="accept"]').addEventListener("click", function () {
        if (!currentCall) return;
        stopRingtone();
        const call = currentCall;
        const target = "/chat/" + encodeURIComponent(call.caller_id) +
            "?answer=" + encodeURIComponent(call.call_id);
        let navigated = false;
        function go() {
            if (navigated) return;
            navigated = true;
            window.location.href = target;
        }
        // Tell the server we are answering so the page change does not drop the call.
        socket.emit("answering_call", { call_id: call.call_id }, go);
        setTimeout(go, 1500);
    });

    overlay.querySelector('[data-role="decline"]').addEventListener("click", function () {
        stopRingtone();
        hidePopup();
        if (currentCall) {
            socket.emit("reject_call", {
                call_id: currentCall.call_id,
                receiver_id: myStudentId
            });
        }
        currentCall = null;
    });
})();
