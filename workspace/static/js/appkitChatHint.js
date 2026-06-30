/* AppKit Chat Hint — above-composer guide tip (.ow-chat-hint).
   Renamed from upstream orwellChatHint.js per FR-UIKIT-4.
   One consistent above-composer guidance affordance for the Chat surface. */

"use strict";

let _cssInjected = false;

function injectCss() {
  if (_cssInjected) return;
  _cssInjected = true;
  const st = document.createElement("style");
  st.id = "appkit-chat-hint-css";
  st.textContent = `
    .ow-chat-hint {
      display: flex; align-items: center; gap: .4rem;
      padding: .3rem .5rem; margin-bottom: .3rem;
      border-radius: 6px;
      background: color-mix(in srgb, var(--accent, #e06c75) 8%, transparent);
      color: var(--fg, #9cdef2);
      font-size: .75rem; line-height: 1.3;
      border: 1px solid color-mix(in srgb, var(--accent, #e06c75) 20%, transparent);
    }
    .ow-chat-hint-icon { flex-shrink: 0; opacity: .7; width: 14px; height: 14px; }
    .ow-chat-hint-text { flex: 1; min-width: 0; }
    .ow-chat-hint-dismiss {
      flex-shrink: 0; background: none; border: none; color: inherit;
      cursor: pointer; opacity: .45; padding: 0 4px; font-size: .85rem; line-height: 1;
    }
    .ow-chat-hint-dismiss:hover { opacity: 1; }
    @media (prefers-reduced-motion: no-preference) {
      .ow-chat-hint { animation: ow-hint-in .2s ease-out; }
      @keyframes ow-hint-in { from { opacity: 0; transform: translateY(-4px); } to { opacity: 1; transform: none; } }
    }
  `;
  document.head.appendChild(st);
}

/**
 * Create a chat hint element placed above the composer.
 * @param {string} message - Hint text
 * @param {object} opts - { icon, dismissable, onClick, onDismiss }
 * @returns {HTMLElement}
 */
export function createChatHint(message, opts = {}) {
  injectCss();
  const el = document.createElement("div");
  el.className = "ow-chat-hint";

  if (opts.icon) {
    const icon = document.createElement("span");
    icon.className = "ow-chat-hint-icon";
    if (typeof opts.icon === "string") icon.innerHTML = opts.icon;
    else icon.appendChild(opts.icon);
    el.appendChild(icon);
  }

  const text = document.createElement("span");
  text.className = "ow-chat-hint-text";
  text.textContent = message;
  el.appendChild(text);

  if (opts.onClick) {
    el.style.cursor = "pointer";
    el.addEventListener("click", opts.onClick);
  }

  if (opts.dismissable !== false) {
    const dismiss = document.createElement("button");
    dismiss.className = "ow-chat-hint-dismiss";
    dismiss.type = "button";
    dismiss.setAttribute("aria-label", "Dismiss hint");
    dismiss.innerHTML = "&times;";
    dismiss.addEventListener("click", (e) => {
      e.stopPropagation();
      el.remove();
      if (opts.onDismiss) opts.onDismiss();
    });
    el.appendChild(dismiss);
  }

  return el;
}

export { injectCss as ensureChatHintCss };

window.AppKitChatHint = {
  createChatHint,
};
