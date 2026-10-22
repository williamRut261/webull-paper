/* Decorative office walks only: no broker, model, or network activity.
   An agent's verified working state comes exclusively from GitHub Checks. */
(() => {
  "use strict";
  const room = document.querySelector(".room");
  const motion = document.getElementById("motion");
  if (!room || !motion) return;
  const pods = Array.from(room.querySelectorAll(".pod"));
  if (pods.length !== 7) return;

  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  const active = room.getAttribute("data-workflow-active") === "true";
  const canWalk = () => motion.checked && !reduced.matches &&
    !active && document.visibilityState === "visible";
  let occupied = false, scheduled = null, generation = 0;
  let walker = null, wanderingPod = null;

  function point(pod) {
    return {x: pod.offsetLeft + 19, y: pod.offsetTop + 71};
  }
  function makeWalker(pod) {
    const el = document.createElement("div");
    el.className = "agent-walker is-walking";
    el.setAttribute("aria-hidden", "true");
    el.style.setProperty("--accent", pod.style.getPropertyValue("--accent"));
    el.style.setProperty("--hair", pod.style.getPropertyValue("--hair"));
    el.style.setProperty("--skin", getComputedStyle(pod).getPropertyValue("--skin"));
    el.innerHTML = '<div class="person"><div class="head"></div><div class="jacket"></div>' +
      '<span class="limb l"></span><span class="limb r"></span></div>';
    return el;
  }
  const wait = (ms) => new Promise(resolve => window.setTimeout(resolve, ms));
  const valid = (token) => token === generation && canWalk();

  // Stop immediately on pause, reduced-motion changes, or hidden tab.
  // Older async steps cannot resurrect a removed walker.
  function stop() {
    generation += 1;
    if (scheduled !== null) window.clearTimeout(scheduled);
    scheduled = null;
    if (walker) walker.remove();
    if (wanderingPod) wanderingPod.classList.remove("is-wandering");
    walker = null;
    wanderingPod = null;
    occupied = false;
  }
  async function move(el, x, y, ms, token) {
    if (!valid(token)) return false;
    el.style.transitionDuration = ms + "ms";
    el.style.left = x + "px";
    el.style.top = y + "px";
    await wait(ms + 80);
    return valid(token);
  }
  async function visit() {
    if (occupied || !canWalk()) return;
    occupied = true;
    const token = ++generation;
    const i = Math.floor(Math.random() * pods.length);
    const from = pods[i];
    const to = pods[(i + 2 + Math.floor(Math.random() * 4)) % pods.length];
    const origin = point(from);
    const target = point(to);
    const el = makeWalker(from);
    walker = el;
    wanderingPod = from;
    el.style.left = origin.x + "px";
    el.style.top = origin.y + "px";
    room.appendChild(el);
    from.classList.add("is-wandering");
    try {
      await wait(100);
      if (!await move(el, origin.x, 443, 950, token)) return;
      if (!await move(el, target.x, 443,
          Math.max(800, Math.abs(target.x - origin.x) * 2.5), token)) return;
      if (!await move(el, target.x, target.y, 950, token)) return;
      el.classList.remove("is-walking");
      await wait(1300);
      if (!valid(token)) return;
      el.classList.add("is-walking");
      if (!await move(el, target.x, 443, 950, token)) return;
      if (!await move(el, origin.x, 443,
          Math.max(800, Math.abs(origin.x - target.x) * 2.5), token)) return;
      await move(el, origin.x, origin.y, 950, token);
    } finally {
      if (generation === token) {
        stop();
        queue();
      }
    }
  }
  function queue() {
    if (!canWalk()) {
      stop();
      return;
    }
    if (occupied) return;
    if (scheduled !== null) window.clearTimeout(scheduled);
    scheduled = window.setTimeout(() => {
      scheduled = null;
      void visit();
    }, 4000 + Math.random() * 8500);
  }
  motion.addEventListener("change", queue);
  if (reduced.addEventListener) reduced.addEventListener("change", queue);
  document.addEventListener("visibilitychange", queue);
  queue();
})();