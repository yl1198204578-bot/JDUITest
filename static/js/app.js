/* ============================================================
   JD UI Automation - Frontend Application
   ============================================================ */

(function () {
    "use strict";

    const MODULES_URL = "/api/modules";
    const RUN_URL = "/api/run";
    const STOP_URL = "/api/stop";
    const LOGS_URL = "/api/logs";

    let currentRunId = null;
    let currentModule = null;
    let eventSource = null;

    // ---- DOM references ----
    const grid = document.getElementById("modulesGrid");
    const logPanel = document.getElementById("logPanel");
    const logBody = document.getElementById("logBody");
    const logTitle = document.getElementById("logTitle");
    const btnStop = document.getElementById("btnStop");
    const btnCloseLog = document.getElementById("btnCloseLog");
    const deviceStatus = document.getElementById("deviceStatus");

    // ---- Initialize ----
    document.addEventListener("DOMContentLoaded", function () {
        loadModules();
        checkDevice();
        // Refresh modules every 5 seconds while idle
        setInterval(function () {
            if (!currentRunId) loadModules();
        }, 5000);
    });

    // ---- Load modules from API ----
    function loadModules() {
        fetch(MODULES_URL)
            .then(function (r) {
                if (!r.ok) { throw new Error("HTTP " + r.status); }
                return r.json();
            })
            .then(function (modules) {
                if (!modules || !modules.length) {
                    showGridMessage("没有可用的任务模块", "请确认 Flask 已重启、modules/ 目录下的模块加载正常。");
                    return;
                }
                renderCards(modules);
            })
            .catch(function (err) {
                console.error("Failed to load modules:", err);
                showGridMessage("无法加载任务列表", "接口 /api/modules 请求失败：" + err.message +
                    "。请确认访问的是 http://127.0.0.1:5000/ ，并关闭浏览器代理后刷新。");
            });
    }

    // ---- Visible empty / error state (never leave a blank page) ----
    function showGridMessage(title, detail) {
        grid.innerHTML =
            '<div class="grid-message">' +
            '<div class="grid-message-title">' + escapeHtml(title) + "</div>" +
            '<div class="grid-message-detail">' + escapeHtml(detail) + "</div>" +
            "</div>";
    }

    // ---- Render module cards ----
    function renderCards(modules) {
        grid.innerHTML = "";
        modules.forEach(function (m) {
            var card = document.createElement("div");
            card.className = "module-card" + (m.status === "running" ? " running" : "");
            card.dataset.name = m.name;
            card.dataset.status = m.status;

            var statusLabel = getStatusLabel(m.status);

            card.innerHTML =
                '<span class="card-status ' + m.status + '">' + statusLabel + '</span>' +
                '<span class="card-icon">' + m.icon + '</span>' +
                '<div class="card-title">' + m.name + "</div>" +
                '<div class="card-desc">' + m.description + "</div>" +
                '<button type="button" class="card-run-btn">▶ 运行</button>';

            var runBtn = card.querySelector(".card-run-btn");
            if (m.status === "running") {
                runBtn.disabled = true;
                runBtn.textContent = "运行中…";
            } else {
                runBtn.addEventListener("click", function (ev) {
                    ev.stopPropagation();
                    onCardClick(m);
                });
            }

            card.addEventListener("click", function () {
                onCardClick(m);
            });

            grid.appendChild(card);
        });
    }

    function getStatusLabel(status) {
        var labels = {
            idle: "空闲",
            running: "运行中",
            done: "已完成",
            error: "出错",
        };
        return labels[status] || status;
    }

    // ---- Card click handler ----
    function onCardClick(module) {
        if (module.status === "running") {
            return; // ignore click on running card
        }
        currentModule = module;
        startModule(module.name);
    }

    // ---- Start a module ----
    function startModule(moduleName) {
        btnStop.style.display = "inline-block";
        showLogPanel(moduleName + " 运行中...");
        clearLog();
        addLogEntry({ type: "log", level: "INFO", message: "正在启动模块: " + moduleName + "...", time: Date.now() / 1000 });

        fetch(RUN_URL + "/" + moduleName, { method: "POST" })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.error) {
                    addLogEntry({ type: "error", message: data.error });
                    btnStop.style.display = "none";
                    return;
                }
                currentRunId = data.run_id;
                connectSSE(data.run_id);
                updateCardStatus(moduleName, "running");
            })
            .catch(function (err) {
                addLogEntry({ type: "error", message: "启动失败: " + err.message });
                btnStop.style.display = "none";
            });
    }

    // ---- SSE: connect to log stream ----
    function connectSSE(runId) {
        if (eventSource) {
            eventSource.close();
        }

        eventSource = new EventSource(LOGS_URL + "/" + runId);

        eventSource.onmessage = function (e) {
            try {
                var data = JSON.parse(e.data);
                handleLogEntry(data);
            } catch (err) {
                // keepalive or parse error
            }
        };

        eventSource.onerror = function () {
            // SSE will auto-reconnect; if we already got done, clean up
        };
    }

    // ---- Handle incoming log entries ----
    function handleLogEntry(data) {
        addLogEntry(data);

        if (data.type === "done" || data.type === "error") {
            if (eventSource) {
                eventSource.close();
                eventSource = null;
            }
            currentRunId = null;
            btnStop.style.display = "none";
            if (currentModule) {
                updateCardStatus(currentModule.name, data.type === "done" ? "done" : "error");
            }
            // Refresh modules to update status
            setTimeout(loadModules, 1000);
        }
    }

    // ---- Add a log entry to the panel ----
    function addLogEntry(data) {
        var el;

        if (data.type === "log") {
            el = document.createElement("div");
            el.className = "log-entry";

            var timeStr = formatTime(data.time);
            var level = data.level || "INFO";

            el.innerHTML =
                '<span class="log-time">' + timeStr + '</span>' +
                '<span class="log-level ' + level + '">' + level + '</span>' +
                '<span class="log-msg">' + escapeHtml(data.message) + '</span>';
        } else if (data.type === "step") {
            el = document.createElement("div");
            el.className = "log-step";
            el.textContent = "[" + data.current + "/" + data.total + "] " + data.label;
        } else if (data.type === "done") {
            el = document.createElement("div");
            el.className = "log-done";
            el.textContent = "✓ " + (data.message || "完成");
        } else if (data.type === "error") {
            el = document.createElement("div");
            el.className = "log-error";
            el.textContent = "✗ " + (data.message || "出错");
        }

        if (el) {
            logBody.appendChild(el);
            logBody.scrollTop = logBody.scrollHeight;
        }
    }

    // ---- Stop button ----
    btnStop.addEventListener("click", function () {
        if (!currentModule) return;
        addLogEntry({ type: "log", level: "WARN", message: "正在停止模块...", time: Date.now() / 1000 });

        fetch(STOP_URL + "/" + currentModule.name, { method: "POST" })
            .then(function (r) { return r.json(); })
            .then(function () {
                addLogEntry({ type: "log", level: "INFO", message: "停止信号已发送", time: Date.now() / 1000 });
            })
            .catch(function (err) {
                addLogEntry({ type: "error", message: "停止失败: " + err.message });
            });
    });

    // ---- Close log panel ----
    btnCloseLog.addEventListener("click", function () {
        logPanel.style.display = "none";
        if (eventSource) {
            eventSource.close();
            eventSource = null;
        }
        currentRunId = null;
        btnStop.style.display = "none";
    });

    // ---- Helpers ----
    function showLogPanel(title) {
        logTitle.textContent = title;
        logPanel.style.display = "block";
    }

    function clearLog() {
        logBody.innerHTML = "";
    }

    function updateCardStatus(moduleName, status) {
        var cards = grid.querySelectorAll(".module-card");
        cards.forEach(function (card) {
            if (card.dataset.name === moduleName) {
                card.dataset.status = status;
                card.className = "module-card" + (status === "running" ? " running" : "");
                var badge = card.querySelector(".card-status");
                if (badge) {
                    badge.className = "card-status " + status;
                    badge.textContent = getStatusLabel(status);
                }
            }
        });
    }

    function formatTime(ts) {
        if (!ts) return "";
        var d = new Date(ts * 1000);
        var pad = function (n) { return (n < 10 ? "0" : "") + n; };
        return pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds());
    }

    function escapeHtml(text) {
        var div = document.createElement("div");
        div.appendChild(document.createTextNode(text));
        return div.innerHTML;
    }

    // ---- Device check ----
    function checkDevice() {
        // Simple ping to check if server is alive
        fetch("/api/modules")
            .then(function () {
                deviceStatus.textContent = "📱 服务器运行中";
                deviceStatus.style.background = "rgba(255,255,255,0.15)";
            })
            .catch(function () {
                deviceStatus.textContent = "❌ 服务器未连接";
                deviceStatus.style.background = "rgba(255,0,0,0.2)";
            });
    }

})();
