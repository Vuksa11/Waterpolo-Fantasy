import { request, clearPublicCache } from "./api.js";

export function showAccountLink() {
  const verify = location.pathname === "/verify-email";
  const token = new URL(location.href).searchParams.get("token");
  // Keep credentials out of subsequent URLs and referrers; no persistence.
  history.replaceState(null, "", location.pathname);
  document.title = `${verify ? "Potvrda emaila" : "Nova lozinka"} · VRL Fantasy`;
  document.querySelector("#app").innerHTML =
    `<main class="account-link"><a class="text-link" href="/">← VRL Fantasy</a><section class="card"><div class="card-head"><h1>${verify ? "Potvrdi email" : "Postavi novu lozinku"}</h1></div><div class="account-link-body"><p>${verify ? "Potvrdi da želiš da aktiviraš email adresu svog naloga." : "Unesi novu lozinku za svoj nalog."}</p><form id="account-link-form">${verify ? "" : '<label>Nova lozinka<input name="password" type="password" autocomplete="new-password" minlength="8" required></label><label>Ponovi novu lozinku<input name="confirm" type="password" autocomplete="new-password" minlength="8" required></label>'}<p id="account-link-message" role="status" aria-live="polite"></p><button class="primary" ${token ? "" : "disabled"}>${verify ? "Potvrdi email" : "Promeni lozinku"}</button></form></div></section></main>`;
  const form = document.querySelector("#account-link-form");
  const message = document.querySelector("#account-link-message");
  const button = form.querySelector("button");
  if (!token)
    message.textContent =
      "Link nije potpun. Otvori originalni link koji sadrži token.";
  form.onsubmit = async (event) => {
    event.preventDefault();
    if (button.disabled || !token) return;
    const values = new FormData(form);
    const password = values.get("password");
    if (
      !verify &&
      (password !== values.get("confirm") ||
        new TextEncoder().encode(password).length > 72)
    ) {
      message.textContent =
        password !== values.get("confirm")
          ? "Lozinke se ne podudaraju."
          : "Lozinka može imati najviše 72 UTF-8 bajta.";
      return;
    }
    button.disabled = true;
    message.textContent = "Obrađujem zahtev…";
    try {
      await request(
        verify
          ? "/auth/verify-email?token=" + encodeURIComponent(token)
          : "/auth/reset-password",
        verify
          ? {}
          : { method: "POST", body: { token, new_password: password } },
      );
      if (!verify) {
        sessionStorage.removeItem("vrl-token");
        clearPublicCache();
      }
      form.reset();
      message.textContent = verify
        ? "Email je potvrđen."
        : "Lozinka je promenjena. Prijavi se novom lozinkom.";
      const link = document.createElement("a");
      link.href = "/";
      link.className = "secondary";
      link.textContent = "Nazad u aplikaciju";
      form.append(link);
      button.hidden = true;
    } catch (error) {
      message.textContent =
        error.status === 422
          ? "Link je nevažeći, iskorišćen ili istekao. Potreban je novi link."
          : error.message;
      button.disabled = false;
    }
  };
}
