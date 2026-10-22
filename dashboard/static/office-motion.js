/* Ambient office walkers, original visualization. No broker/network APIs.
   No walking or animation implies the real AI model is working. */
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
  let occupied = false, scheduled = null;

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
  async function move(el, x, y, ms) {
    el.style.transitionDuration = ms + "ms";
    el.style.left = x + "px";
    el.style.top = y + "px";
    await wait(ms + 80);
  }
  async function visit() {
    if (occupied || !canWalk()) return;
    occupied = true;
    const i = Math.floor(Math.random() * pods.length);
    const from = pods[i];
    const to = pods[(i + 2 + Math.floor(Math.random() * 4)) % pods.length];
    const origin = point(from);
    const target = point(to);
    const walker = makeWalker(from);
    walker.style.left = origin.x + "px";
    walker.style.top = origin.y + "px";
    room.appendChild(walker);
    from.classList.add("is-wandering");
    try {
      await wait(100);
      const aisle = 443;
      await move(walker, origin.x, aisle, 950);
      await move(walker, target.x, aisle, Math.max(800, Math.abs(target.x - origin.x) * 2.5));
      await move(walker, target.x, target.y, 950);
      walker.classList.remove("is-walking");
      await wait(1300);
      walker.classList.add("is-walking");
      await move(walker, target.x, aisle, 950);
      await move(walker, origin.x, aisle, Math.max(800, Math.abs(origin.x - target.x) * 2.5));
      await move(walker, origin.x, origin.y, 950);
    } finally {
      walker.remove();
      from.classList.remove("is-wandering");
      occupied = false;
      queue();
    }
  }
  function queue() {
    if (scheduled !== null) window.clearTimeout(scheduled);
    scheduled = null;
    if (!canWalk()) return;
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
