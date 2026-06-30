/* AppKit Glass — glass surface system + adaptive glass (FR-UIKIT F1).
   Merged from upstream liquidGlass.js + adaptiveGlass.js per FR-UIKIT-4.
   Provides the --ow-glass-* token infrastructure and adaptive backdrop blur. */

"use strict";

const REDUCED = window.matchMedia
  ? window.matchMedia("(prefers-reduced-motion: reduce)")
  : { matches: false };

/**
 * Apply glass effect to a target element based on intensity.
 * @param {HTMLElement} el - Target element
 * @param {'light'|'medium'|'heavy'} intensity - Glass intensity level
 */
export function applyGlass(el, intensity) {
  if (!el) return;
  const level = intensity || "medium";
  el.dataset.glassIntensity = level;
  if (!REDUCED.matches) {
    el.style.transition = "backdrop-filter 0.4s ease, background 0.4s ease";
  }
}

/**
 * Remove glass effect from a target element.
 */
export function removeGlass(el) {
  if (!el) return;
  delete el.dataset.glassIntensity;
  el.style.backdropFilter = "";
  el.style.background = "";
  el.style.transition = "";
}

/**
 * Toggle the frosted theme class on the document body.
 */
export function toggleFrosted(enable) {
  document.body.classList.toggle("theme-frosted", enable);
}

/**
 * Set glass-full mode on the document body.
 */
export function setGlassFull(enable) {
  document.body.classList.toggle("glass-full", enable);
  document.body.classList.toggle("theme-frosted", !enable);
}

/**
 * Get current glass intensity from a target element.
 * @returns {'light'|'medium'|'heavy'}
 */
export function getGlassIntensity(el) {
  return (el && el.dataset.glassIntensity) || "medium";
}

window.AppKitGlass = {
  applyGlass,
  removeGlass,
  toggleFrosted,
  setGlassFull,
  getGlassIntensity,
};
