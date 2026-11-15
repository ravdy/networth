"use strict";
const $ = (s) => document.querySelector(s);
let mode = "login";          // "login" | "register"
let status = {};

async function call(path, body) {
  const res = await fetch(path, {
    method: body ? "POST" : "GET",
    headers: { "Content-Type": "application/json", "X-NW": "1" },
    body: body ? JSON.stringify(body) : undefined,
    credentials: "same-origin",
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Please check the fields and try again.");
  return data;
}

function showError(msg) {
  const e = $("#error");
  e.textContent = msg;
  e.hidden = !msg;
}

function setMode(m) {
  mode = m;
  const reg = m === "register";
  const first = !status.configured;
  $("#title").textContent = reg ? (first ? "Create your account" : "Create an account") : "Sign in";
  $("#subtitle").textContent = reg
    ? (first ? "First time here: choose a username and a strong password. You'll need it every time you open the app."
             : status.demo ? "You'll get your own private copy of the sample portfolio to explore and edit."
                           : "You'll get your own private, empty portfolio. Nobody else can see your data.")
    : "Your financial data is locked. Sign in to continue.";
  $("#password").autocomplete = reg ? "new-password" : "current-password";
  $("#confirm-wrap").hidden = !reg;
  $("#confirm").required = reg;
  $("#hint").hidden = !reg;
  $("#hint").textContent = `Username: 3–60 characters (an email address works). Password: at least ${status.min_password} characters. A short sentence works well, e.g. "mango tree in Kadapa 1987".`;
  $("#submit").textContent = reg ? "Create account" : "Sign in";
  const sw = $("#switch");
  sw.hidden = first || !status.signup;
  sw.innerHTML = "";
  const a = document.createElement("a");
  a.href = "#";
  a.textContent = reg ? "Sign in" : "Create an account";
  a.addEventListener("click", (ev) => { ev.preventDefault(); showError(""); setMode(reg ? "login" : "register"); $("#username").focus(); });
  sw.append(reg ? "Already have an account? " : "New here? ", a);
  $("#demo-hint").hidden = !(status.demo && !reg);
  $("#demo-hint").textContent = "Demo: sign in with demo / demo-2026-show, or create your own account.";
  showError("");
}

(async function init() {
  status = await call("/api/auth/status");
  if (status.authenticated) return location.replace("/");
  const wantRegister = location.hash === "#register" && status.signup;
  setMode(!status.configured || wantRegister ? "register" : "login");
})();

$("#form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  showError("");
  const username = $("#username").value.trim(), password = $("#password").value;
  if (mode === "register" && password !== $("#confirm").value) return showError("The two passwords don't match.");
  $("#submit").disabled = true;
  try {
    await call(mode === "register" ? "/api/auth/register" : "/api/auth/login", { username, password });
    location.replace("/");
  } catch (e) {
    showError(e.message);
    $("#password").value = "";
    $("#confirm").value = "";
    $("#password").focus();
  } finally {
    $("#submit").disabled = false;
  }
});
