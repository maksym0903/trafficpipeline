(function () {
  if (window.__TRIAL_POPUP_LOADED__) return;
  window.__TRIAL_POPUP_LOADED__ = true;
  if (sessionStorage.getItem('trial_popup_dismissed')) return;

  var cfg = JSON.parse('{{config_json}}');

  function el(tag, text) {
    var node = document.createElement(tag);
    if (text) node.textContent = text;
    return node;
  }

  var overlay = el('div');
  overlay.id = 'trial-popup-overlay';
  overlay.style.cssText =
    'position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:2147483646;' +
    'display:flex;align-items:center;justify-content:center;padding:16px;';

  var box = el('div');
  box.style.cssText =
    'background:#fff;color:#111;max-width:380px;width:100%;padding:20px;' +
    'border:2px solid #111;font:14px/1.4 sans-serif;';

  var title = el('h2', cfg.headline || 'Offer');
  title.style.cssText = 'margin:0 0 10px;font-size:18px;';

  var body = el('p', cfg.body || '');
  body.style.cssText = 'margin:0 0 16px;';

  var actions = el('div');
  actions.style.cssText = 'display:flex;gap:8px;flex-wrap:wrap;';

  var cta = document.createElement('a');
  cta.href = cfg.ctaUrl || '#';
  cta.textContent = cfg.ctaText || 'Claim Bonus';
  cta.rel = 'nofollow sponsored';
  cta.style.cssText =
    'display:inline-block;padding:8px 14px;background:#111;color:#fff;text-decoration:none;';

  var close = el('button', 'Close');
  close.type = 'button';
  close.style.cssText = 'padding:8px 14px;border:1px solid #111;background:#fff;cursor:pointer;';
  close.onclick = function () {
    sessionStorage.setItem('trial_popup_dismissed', '1');
    overlay.remove();
  };

  actions.appendChild(cta);
  actions.appendChild(close);
  box.appendChild(title);
  box.appendChild(body);
  box.appendChild(actions);
  overlay.appendChild(box);

  function mount() {
    if (!document.body) return;
    document.body.appendChild(overlay);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount);
  } else {
    mount();
  }
})();
