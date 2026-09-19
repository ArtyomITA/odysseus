// static/js/shadowbrokerBoot.js
//
// Wires up the ShadowBroker workspace once the rail buttons exist.
// Kept separate from shadowbroker.js so that module stays a pure API surface
// (open/close/toggle) that other code — and eventually the agent — can call
// without the side effect of binding DOM handlers on import.

import shadowbroker from './shadowbroker.js?v=20260826sbpicker1';

function boot() {
  try {
    shadowbroker.init();
  } catch (e) {
    console.warn('ShadowBroker panel init failed:', e);
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot, { once: true });
} else {
  boot();
}
