import { useState, useSyncExternalStore } from "react";

type Prompt = { code: string; submit: (email: string | null) => void };
let prompts: Prompt[] = [];
const listeners = new Set<() => void>();
const notify = () => listeners.forEach((listener) => listener());
let sessionEmail = "";
export function requestSimurgAccess(
  code: string,
  signal: AbortSignal,
): Promise<string> {
  signal.throwIfAborted();
  return new Promise((resolve, reject) => {
    const finish = (email: string | null) => {
      signal.removeEventListener("abort", abort);
      prompts = prompts.filter((item) => item !== prompt);
      notify();
      if (email === null)
        reject(new DOMException("Stopped waiting", "AbortError"));
      else {
        sessionEmail = email;
        resolve(email);
      }
    };
    const abort = () => finish(null);
    const prompt = { code, submit: finish };
    prompts = [...prompts, prompt];
    signal.addEventListener("abort", abort, { once: true });
    notify();
  });
}
export function SimurgAccess() {
  const prompt = useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    () => prompts[0],
  );
  return prompt ? <AccessForm key={prompt.code} prompt={prompt} /> : null;
}
function AccessForm({ prompt }: { prompt: Prompt }) {
  const [email, setEmail] = useState(sessionEmail);
  const [emailError, setEmailError] = useState("");
  const normalized = email.trim().toLowerCase();
  const limit = prompt.code === "SIMURG_LIMIT_REACHED";
  return (
    <div
      className="simurg-access"
      role="dialog"
      aria-modal="true"
      aria-labelledby="simurg-title"
    >
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (
            !/^[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,63}$/.test(
              normalized,
            ) ||
            normalized.includes("..")
          ) {
            setEmailError("Enter a valid SIMuRG email address.");
            return;
          }
          prompt.submit(normalized);
        }}
      >
        <h2 id="simurg-title">
          {limit ? "SIMuRG limit reached" : "SIMuRG email required"}
        </h2>
        <p>
          {limit
            ? "SIMuRG permits 10 existing requests per email, including completed requests. Manually delete unnecessary requests, then check again."
            : "Missing data requires remote SIMuRG access. Enter your email to find reusable requests or create a request. Your chart settings and cached data are preserved."}
        </p>
        <label>
          Email{" "}
          <input
            autoFocus
            type="email"
            required
            maxLength={254}
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </label>
        {emailError && <p role="alert">{emailError}</p>}
        {limit && normalized && (
          <p>
            <a
              href={`https://simurg.iszf.irk.ru/queries?email=${encodeURIComponent(normalized)}`}
              target="_blank"
              rel="noreferrer"
            >
              Manage SIMuRG queries
            </a>
          </p>
        )}
        <button type="submit">{limit ? "Check again" : "Continue"}</button>
        <button type="button" onClick={() => prompt.submit(null)}>
          Stop waiting
        </button>
      </form>
    </div>
  );
}
