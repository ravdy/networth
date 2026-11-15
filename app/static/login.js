"use strict";
const $ = (s) => document.querySelector(s);
let setupMode = false;

async function call(path, body) {
  const res = await fetch(path, {
    method: body ? "POST" : "GET",
    headers: { "Content-Type": "application/json", "X-NW": "1" },
    body: body ? JSON.stringify(body) : undefined,
    credentials: "same-origin",
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
}

function showError(msg) {
  const e = $("#error");
  e.textContent = msg;
  e.hidden = !msg;
}

(async function init() {
  const st = await call("/api/auth/status");
  if (st.authenticated) return location.replace("/");
  if (!st.configured) {
    setupMode = true;
    $("#title").textContent = "Create your account";
    $("#subtitle").textContent = "First time here: choose a username and a strong password. You'll need it every time you open the app.";
    $("#password").autocomplete = "new-password";
    $("#confirm-wrap").hidden = false;
    $("#confirm").required = true;
    $("#hint").hidden = false;
    $("#hint").textContent = `At least ${st.min_password} characters. A short sentence works well, e.g. "mango tree in Kadapa 1987".`;
    $("#submit").textContent = "Create account";
  }
})();

$("#form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  showError("");
  const username = $("#username").value.trim(), password = $("#password").value;
  if (setupMode && password !== $("#confirm").value) return showError("The two passwords don't match.");
  $("#submit").disabled = true;
  try {
    await call(setupMode ? "/api/auth/setup" : "/api/auth/login", { username, password });
    location.replace("/");
  } catch (e) {
    showError(e.message);
    $("#password").value = "";
    $("#password").focus();
  } finally {
    $("#submit").disabled = false;
  }
});
